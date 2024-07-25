import os
import asyncio
import logging
import sys

from prometheus_client import start_http_server, Gauge
from lmcloud.client_cloud import LaMarzoccoCloudClient
from lmcloud.lm_machine import LaMarzoccoMachine
from lmcloud.const import MachineModel, BoilerType
from lmcloud.exceptions import AuthFail, RequestNotSuccessful
from lmcloud.models import LaMarzoccoMachineConfig

USERNAME = os.environ["USERNAME"]
PASSWORD = os.environ["PASSWORD"]
SERIAL_NUMBER = os.environ["SERIAL_NUMBER"]
NAME = os.environ["NAME"]
REPORT_INTERVAL = int(os.environ.get("REPORT_INTERVAL", "60"))

DEBUG = os.environ.get("DEBUG", False)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
if DEBUG:
    logger.setLevel(logging.DEBUG)

ON_OFF_GAUGE = Gauge('coffee_machine_on_off', 'Coffee Machine ON/OFF status')
STEAM_TEMP_GAUGE = Gauge('coffee_machine_steam_temp', 'Coffee Machine Steam Temperature')
COFFEE_TEMP_GAUGE = Gauge('coffee_machine_coffee_temp', 'Coffee Machine Coffee Temperature')

async def fetch_metrics_forever(machine: LaMarzoccoMachine):
    while True:
        logger.info("fetching current metrics")
        await machine.get_config() # Not strictly sure we need to call this
        config = machine.config
        logger.debug(f'fetched config: {config}')
        steam_boiler = config.boilers[BoilerType.STEAM]
        main_boiler = config.boilers[BoilerType.COFFEE]

        # Report the status of the machine
        ON_OFF_GAUGE.set(1 if config.turned_on else 0)
        STEAM_TEMP_GAUGE.set(steam_boiler.current_temperature)
        COFFEE_TEMP_GAUGE.set(main_boiler.current_temperature)
        
        await asyncio.sleep(REPORT_INTERVAL)

async def main():
    # Start the Prometheus HTTP server to expose the metrics
    logger.info("creating LaMarzoccoCloudClient object")
    cloud_client = LaMarzoccoCloudClient(USERNAME, PASSWORD)

    logger.info("getting machine...")
    machine = await LaMarzoccoMachine.create(MachineModel.LINEA_MICRA, SERIAL_NUMBER, NAME, cloud_client)
    logger.info("got machine successfully")

    logger.info("starting prometheus endpoint")
    start_http_server(8000)
    # Start fetching metrics
    logger.info("starting monitor")
    await fetch_metrics_forever(machine)


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
