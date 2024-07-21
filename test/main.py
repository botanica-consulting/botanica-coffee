import os
import email_validator
from dataclasses import dataclass, asdict
from flask import Flask, redirect, url_for, session, request, abort, g, jsonify
import json
import logging
from oauthlib.oauth2 import WebApplicationClient
import requests

from typing import Dict

from dataclasses import dataclass, asdict
from lmcloud.client_cloud import LaMarzoccoCloudClient
from lmcloud.lm_machine import LaMarzoccoMachine
from lmcloud.const import MachineModel, BoilerType
from lmcloud.exceptions import AuthFail, RequestNotSuccessful
from lmcloud.models import LaMarzoccoMachineConfig

from google.cloud import secretmanager_v1 as secretmanager
secretmanager.SecretManagerServiceAsyncClient


USERNAME = os.getenv("USERNAME")
GOOGLE_SECRET_RESOURCE_NAME = os.getenv("GOOGLE_SECRET_RESOURCE_NAME")
SERIAL_NUMBER = os.getenv("SERIAL_NUMBER")
NAME = os.getenv("NAME")

app = Flask(__name__)
app.secret_key = bytes.fromhex(os.environ['SECRET_KEY'])

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI')

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
PORT = int(os.getenv('PORT', 5000))
FLASK_ENV = os.getenv('FLASK_ENV', 'production')

ALLOWED_DOMAINS = [
            domain.lower() for domain in os.getenv('ALLOWED_DOMAINS', '').split(',')
        ]

# Log environment variables for debugging
logger = app.logger
logger.debug(f"GOOGLE_CLIENT_ID: {GOOGLE_CLIENT_ID}")
logger.debug(f"GOOGLE_CLIENT_SECRET: {GOOGLE_CLIENT_SECRET}")
logger.debug(f"GOOGLE_REDIRECT_URI: {GOOGLE_REDIRECT_URI}")

client = WebApplicationClient(GOOGLE_CLIENT_ID)

def get_google_provider_cfg():
    return requests.get(GOOGLE_DISCOVERY_URL).json()

@app.before_request
async def before_request():
    if 'email' not in session and request.endpoint not in ['login', 'callback']:
        return redirect(url_for('login'))

@app.route("/whoami")
async def index():
    return f'Hello, {session["email"]}!'

@app.route("/status")
async def status():
    cloud_client = await get_lamarzocco_cloud_client()
    machine = await get_machine(cloud_client)
    config = machine.config
    status = LaMarzoccoMachineStatus.from_la_marzocco_machine_config(config)
    return jsonify(status.to_dict()), 200

@app.route("/turn_on")
async def turn_on():
    cloud_client = await get_lamarzocco_cloud_client()
    machine = await get_machine(cloud_client)
    try:
        if not await machine.set_power(True):
            return jsonify(
                    {
                        "message": f"failed to turn on machine {machine.name}"
                    }), 400
        return jsonify({"message": f"turned on machine {machine.name}"}), 200
    except RequestNotSuccessful as e:
        return jsonify({"message": "failed to turn on machine", "e": str(e)}), 400

@app.route("/turn_off")
async def turn_off():
    cloud_client = await get_lamarzocco_cloud_client()
    machine = await get_machine(cloud_client)
    try:
        if not await machine.set_power(False):
            return jsonify(
                    {
                        "message": f"failed to turn off machine {machine.name}"
                    }), 400
        return jsonify({"message": f"turned on machine {machine.name}"}), 200
    except RequestNotSuccessful as e:
        return jsonify({"message": "failed to turn off machine", "e": str(e)}), 400

@app.route("/login")
async def login():
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=GOOGLE_REDIRECT_URI,
        scope=["openid", "email", "profile"],
    )
    return redirect(request_uri)

@app.route("/login/callback")
async def callback():
    code = request.args.get("code")

    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=GOOGLE_REDIRECT_URI,
        code=code
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
    )

    client.parse_request_body_response(token_response.text)

    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)

    userinfo = userinfo_response.json()
    email = userinfo['email']

    emailinfo = email_validator.validate_email(email)
    if emailinfo.domain.lower() not in ALLOWED_DOMAINS:
        return abort(403)

    return redirect(url_for("status"))

@app.route("/logout")
async def logout():
    session.clear()
    return redirect(url_for("login"))


async def get_lamarzocco_cloud_client() -> LaMarzoccoCloudClient:
    if 'cloud_client' not in g:
        g.cloud_client = await la_marzocco_login()

    return g.cloud_client

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
    steam_boiler_temp: float
    steam_boiler_target_temp: float

    main_boiler_on: bool
    main_boiler_temp: float
    main_boiler_target_temp: float

    @staticmethod
    def from_la_marzocco_machine_config(config: LaMarzoccoMachineConfig) -> "LaMarzoccoMachineStatus":
        steam_boiler = config.boilers[BoilerType.STEAM]
        main_boiler = config.boilers[BoilerType.COFFEE]
        return LaMarzoccoMachineStatus(
            turned_on=config.turned_on,
            steam_boiler_on=steam_boiler.enabled,
            steam_boiler_temp=steam_boiler.current_temperature,
            steam_boiler_target_temp=steam_boiler.target_temperature,
            main_boiler_on=main_boiler.enabled,
            main_boiler_temp=main_boiler.current_temperature,
            main_boiler_target_temp=main_boiler.target_temperature
        )
    def to_dict(self):
        return asdict(self)

async def get_google_secret() -> str:
    # Create a client
    client = secretmanager.SecretManagerServiceAsyncClient()

    # Initialize request argument(s)
    request = secretmanager.AccessSecretVersionRequest(
        name="name_value",
    )

    # Make the request
    response = await client.access_secret_version(request=request)

    return response.payload.data.decode("UTF-8")

async def la_marzocco_login() -> LaMarzoccoCloudClient:
    logger.info("accessing google secret manager")
    password = await get_google_secret()
    logger.info("creating LaMarzoccoCloudClient object")
    cloud_client = LaMarzoccoCloudClient(USERNAME, password)
    return cloud_client

async def get_machine(cloud_client: LaMarzoccoCloudClient) -> LaMarzoccoMachine:
    try:
        logger.info("getting machine...")
        machine = await LaMarzoccoMachine.create(MachineModel.LINEA_MICRA, SERIAL_NUMBER, NAME, cloud_client)
        logger.info("got machine successfully")
    except AuthFail as e:
        logger.error(f"failed to login to La Marzocco Cloud: {e}")
        raise LaMarzoccoLambdaError("failed to login to La Marzocco Cloud")
    except RequestNotSuccessful as e:
        logger.error(f"failed to get machine: {e}")
        raise LaMarzoccoLambdaError("failed to get machine")
    return machine


if __name__ == "__main__":
    match FLASK_ENV.lower():
        case 'development':
            logging.basicConfig(level=logging.DEBUG)
            app.run(host='localhost', port=PORT, debug=True, ssl_context='adhoc')
        case 'production':
            logging.basicConfig(level=logging.INFO)
            app.run(host='0.0.0.0', port=PORT, debug=False)
        case _:
            raise ValueError(f"Invalid FLASK_ENV value: {FLASK_ENV}")


