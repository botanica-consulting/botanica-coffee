import asyncio
import os
import logging
from typing import Dict
from urllib.parse import parse_qs
import json
import boto3
import copy
import urllib.request

from dataclasses import dataclass, asdict
from lmcloud.client_cloud import LaMarzoccoCloudClient
from lmcloud.lm_machine import LaMarzoccoMachine
from lmcloud.const import MachineModel, BoilerType
from lmcloud.exceptions import AuthFail, RequestNotSuccessful
from lmcloud.models import LaMarzoccoMachineConfig

USERNAME = os.environ["USERNAME"]
PASSWORD = os.environ["PASSWORD"]
SERIAL_NUMBER = os.environ["SERIAL_NUMBER"]
NAME = os.environ["NAME"]
DEBUG = os.environ.get("DEBUG", False)

logger = logging.getLogger()
if DEBUG:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class LaMarzoccoLambdaError(Exception):
    pass


@dataclass
class Response:
    statusCode: int
    body: str

    def __init__(self, statusCode: int, body: Dict):
        self.statusCode = statusCode
        self.body = json.dumps(body)

    def to_dict(self):
        return asdict(self)


@dataclass
class LaMarzoccoMachineWrapper:
    name: str
    serial_number: str
    model: str

    def to_dict(self):
        return asdict(self)


@dataclass
class LaMarzoccoMachineStatus:
    turned_on: bool

    steam_boiler_on: bool
    steam_boiler_temp: int
    steam_boiler_target_temp: int

    main_boiler_on: bool
    main_boiler_temp: int
    main_boiler_target_temp: int

    @staticmethod
    def from_la_marzocco_machine_config(
        config: LaMarzoccoMachineConfig,
    ) -> "LaMarzoccoMachineStatus":
        steam_boiler = config.boilers[BoilerType.STEAM]
        main_boiler = config.boilers[BoilerType.COFFEE]
        return LaMarzoccoMachineStatus(
            turned_on=config.turned_on,
            steam_boiler_on=steam_boiler.enabled,
            steam_boiler_temp=steam_boiler.current_temperature,
            steam_boiler_target_temp=steam_boiler.target_temperature,
            main_boiler_on=main_boiler.enabled,
            main_boiler_temp=main_boiler.current_temperature,
            main_boiler_target_temp=main_boiler.target_temperature,
        )

    def to_dict(self):
        return asdict(self)


async def login() -> LaMarzoccoCloudClient:
    logger.info("creating LaMarzoccoCloudClient object")
    cloud_client = LaMarzoccoCloudClient(USERNAME, PASSWORD)
    return cloud_client


async def get_machine(cloud_client: LaMarzoccoCloudClient) -> LaMarzoccoMachine:
    try:
        logger.info("getting machine...")
        machine = await LaMarzoccoMachine.create(
            MachineModel.LINEA_MICRA, SERIAL_NUMBER, NAME, cloud_client
        )
        logger.info("got machine successfully")
    except AuthFail as e:
        logger.error(f"failed to login to La Marzocco Cloud: {e}")
        raise LaMarzoccoLambdaError("failed to login to La Marzocco Cloud")
    except RequestNotSuccessful as e:
        logger.error(f"failed to get machine: {e}")
        raise LaMarzoccoLambdaError("failed to get machine")
    return machine


async def list_machines(
    cloud_client: LaMarzoccoCloudClient,
) -> Dict[str, LaMarzoccoMachineWrapper]:
    machines: Dict[str, LaMarzoccoMachineWrapper] = {}
    try:
        logger.info("getting customer fleet...")
        fleet = await cloud_client.get_customer_fleet()
        logger.info("got customer fleet successfully")
    except AuthFail as e:
        logger.error(f"failed to login to La Marzocco Cloud: {e}")
        raise LaMarzoccoLambdaError("failed to login to La Marzocco Cloud")
    except RequestNotSuccessful as e:
        logger.error(f"failed to get customer fleet: {e}")
        raise LaMarzoccoLambdaError("failed to get customer fleet")

    for machine_name, lmdi in fleet.items():
        wrapper = LaMarzoccoMachineWrapper(machine_name, lmdi.serial_number, lmdi.model)
        machines[machine_name] = wrapper

    return machines


def parse_event(event: Dict) -> Dict:
    logger.info(str(event))
    content_type = event.get("headers", {}).get(
        "content-type", "application/x-www-form-urlencoded"
    )
    logger.debug(f"Got event with Content-Type {content_type}")
    match content_type.lower():
        case "application/json":
            if "body" in event:
                return json.loads(event["body"])
            raise LaMarzoccoLambdaError("Invalid event: " + str(event))
        case "application/x-www-form-urlencoded":
            parsed_data = parse_qs(event["body"])
            return {k: v[0] for k, v in parsed_data.items()}
        case _:
            raise LaMarzoccoLambdaError(f"Unsupported Content-Type: {content_type}")


async def turn_on() -> Response:
    cloud_client = await login()
    logger.info("Logged in")
    machine = await get_machine(cloud_client)
    logger.info("Got machine")
    try:
        if not await machine.set_power(True):
            logger.info("Set power failed")
            return Response(401, {"message": "failed to turn on machine"})
        logger.info("Set power success")
        return Response(200, {})
    except RequestNotSuccessful as e:
        return Response(400, {"message": "failed to turn on machine", "e": str(e)})


async def async_slack_handler(event, parsed_event, context, is_background) -> Response:
    if ["/tired"] == parsed_event["command"] or "/tired" == parsed_event["command"]:
        if is_background:
            t = await turn_on()
            response_message = {
                "text": "The machine has been turned on."
            }
            data = json.dumps(response_message).encode('utf-8')
            req = urllib.request.Request(parsed_event['response_url'], 
                                         data=data, 
                                         headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req)

            return t
        else:
            # Invoke the background processing asynchronously
            lambda_client = boto3.client("lambda")
            lambda_client.invoke(
                FunctionName=context.function_name,
                InvocationType="Event",  # Asynchronous invocation
                Payload=json.dumps({"background": True, **event}),
            )

            return Response(202, 'Hmm... wait a sec!')

    raise ValueError(f"IDK what to do, {event}")


async def async_handler(event, context) -> Response:
    is_background = "background" in event
    original_event = copy.copy(event)
    event = parse_event(event)
    if "action" not in event:
        return await async_slack_handler(original_event, event, context, is_background)

    logger.info(f'Got action: {event["action"]}')
    try:
        match event["action"]:
            case "list_machines":
                cloud_client = await login()
                machines = await list_machines(cloud_client)
                return Response(200, machines)
            case "turn_on":
                return await turn_on()
            case "turn_off":
                cloud_client = await login()
                machine = await get_machine(cloud_client)
                try:
                    if not await machine.set_power(False):
                        return Response(400, {"message": "failed to turn off machine"})
                    return Response(200, {})
                except RequestNotSuccessful as e:
                    return Response(
                        400, {"message": "failed to turn off machine", "e": str(e)}
                    )
            case "get_status":
                cloud_client = await login()
                machine = await get_machine(cloud_client)
                config = machine.config
                status = LaMarzoccoMachineStatus.from_la_marzocco_machine_config(config)
                return Response(200, status.to_dict())
            case _:
                return Response(400, {"message": f"unknown action {event['action']}"})
    except RequestNotSuccessful as e:
        return Response(400, {"message": "request not successful", "e": str(e)})
    except LaMarzoccoLambdaError as e:
        return Response(400, {"message": str(e)})


def handler(event, context):
    logger.debug(f"event: {event}")
    response = asyncio.run(async_handler(event, context))
    return response.to_dict()
