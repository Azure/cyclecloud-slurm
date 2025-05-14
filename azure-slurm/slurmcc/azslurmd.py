import os
import time

from hpc.autoscale.util import load_config
from hpc.autoscale import hpclogging as logging


def azslurmd() -> None:
    """Run the main loop of the azslurm daemon. Writes log to azslurmd.log under /opt/azurehpc/slurm/logs"""
    logging.info("azslurmd is running with PID=%s", os.getpid())
    while True:
        logging.info("azslurmd is running")
        time.sleep(5)


def run(config_path: str) -> None:
    config = load_config(config_path)
    logging.set_context(f"[azslurmd]")
    logging.initialize_logging(config)
    logging.info("RDH line 54")
    azslurmd()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logging.info("Starting azslurmd in the foreground")
    azslurmd()


if __name__ == "__main__":
    main()
