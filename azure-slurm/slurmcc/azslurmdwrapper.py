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
    args = parser.parse_args()

    with daemon.DaemonContext(stdout=sys.stdout, stderr=sys.stderr, pidfile=daemon.pidfile.PIDLockFile(PID_FILE)):
        azslurmd.run(args.config)


if __name__ == "__main__":
    main()
