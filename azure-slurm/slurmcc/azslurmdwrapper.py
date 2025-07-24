import argparse
import daemon
import daemon.pidfile
import lockfile
import os
import sys
from slurmcc import azslurmd

PID_FILE = os.environ.get("AZSLURM_PID_FILE", "/opt/azurehpc/slurm/azslurm.pid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", default="/opt/azurehpc/slurm/autoscale.json", help="Path to the configuration file")
    parser.add_argument("--foreground", "-f", action="store_true", default=False, help="Run in the foreground")
    args = parser.parse_args()

    if args.foreground:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
        )
        logging.info("Starting azslurmd in the foreground")
        return azslurmd.run(args.config)

    with daemon.DaemonContext(stdout=sys.stdout, stderr=sys.stderr, pidfile=daemon.pidfile.PIDLockFile(PID_FILE)):
        azslurmd.run(args.config)


if __name__ == "__main__":
    main()
