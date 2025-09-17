import asyncio
import os
import logging
from typing import Dict, Any, Coroutine
from urllib.parse import parse_qs
import json
import boto3
import copy
import urllib.request
import uuid
from botocore.exceptions import ClientError

from dataclasses import dataclass, asdict
# from lmcloud.lm_machine import LaMarzoccoMachine
# from lmcloud.const import MachineModel
# from lmcloud.models import LaMarzoccoMachineConfig
from pylamarzocco import LaMarzoccoCloudClient
from pylamarzocco.util import InstallationKey, generate_installation_key
from pylamarzocco.const import BoilerType
from pylamarzocco.exceptions import RequestNotSuccessful, AuthFail

USERNAME = os.environ["USERNAME"]
PASSWORD = os.environ["PASSWORD"]
SERIAL_NUMBER = os.environ["SERIAL_NUMBER"]
NAME = os.environ["NAME"]
DEBUG = os.environ.get("DEBUG", False)
S3_BUCKET = os.environ.get("S3_BUCKET")
INSTALLATION_KEY_FILE = "installation_key.json"

logger = logging.getLogger()
if DEBUG:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


class LaMarzoccoLambdaError(Exception):
    pass


async def get_or_create_installation_key() -> tuple[InstallationKey, bool]:
    """Get installation key from S3 or create a new one if it doesn't exist."""
    s3_client = boto3.client('s3')

    try:
        # Try to get existing key from S3
        logger.info(f"Attempting to retrieve installation key from S3: {S3_BUCKET}/{INSTALLATION_KEY_FILE}")
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=INSTALLATION_KEY_FILE)
        key_json = response['Body'].read().decode('utf-8')
        logger.info("Installation key found in S3, loading existing key")
        return InstallationKey.from_json(key_json), False

    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            # Key doesn't exist, create a new one
            logger.info("Installation key not found in S3, generating new key")
            installation_key = generate_installation_key(str(uuid.uuid4()).lower())

            # Store the new key in S3
            key_json = installation_key.to_json()
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=INSTALLATION_KEY_FILE,
                Body=key_json,
                ContentType='application/json'
            )
            logger.info("New installation key generated and stored in S3")
            return installation_key, True
        else:
            logger.error(f"Error retrieving installation key from S3: {e}")
            raise


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


async def login() -> LaMarzoccoCloudClient:
    logger.info("creating LaMarzoccoCloudClient object")
    installation_key, new_key = await get_or_create_installation_key()
    cloud_client = LaMarzoccoCloudClient(USERNAME, PASSWORD, installation_key)
    if new_key:
        await cloud_client.async_register_client()
    return cloud_client


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


async def turn_on() -> tuple[bool, str]:
    return await set_power(True)


async def turn_off() -> tuple[bool, str]:
    return await set_power(True)


async def set_power(power):
    cloud_client = await login()
    logger.info("Logged in")
    try:
        if not await cloud_client.set_power(SERIAL_NUMBER, power):
            logger.info("Set power failed")
            return False, "failed to turn on machine"
        logger.info("Set power success!")
        return True, "Great success"
    except RequestNotSuccessful as e:
        return False, "failed to turn on machine: " + str(e)


async def async_slack_handler(event, parsed_event, context, is_background) -> Response | None:
    if ["/tired"] == parsed_event["command"] or "/tired" == parsed_event["command"]:
        if is_background:
            t, message = await turn_on()
            response_message = {
                "text": "The machine has been turned on." if t else "Unable to turn on." + message,
            }
            data = json.dumps(response_message).encode('utf-8')
            req = urllib.request.Request(parsed_event['response_url'],
                                         data=data,
                                         headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req)

            return
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

    return Response(400, "Missing action")


def handler(event, context):
    logger.debug(f"event: {event}")
    response = asyncio.run(async_handler(event, context))
    return response.to_dict()
