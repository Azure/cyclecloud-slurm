import logging
import logging.config
import os
import subprocess
import sys

LOGGING_CONFIG = "/opt/cycle/slurm/healthcheck.logging.conf"


if os.path.exists(LOGGING_CONFIG):
    logging.config.fileConfig(LOGGING_CONFIG)
else:
    logging.basicConfig(
        format="HealthCheck: %(asctime)s %(message)s", level=logging.INFO
    )


def _check_output(cmd):
    logging.debug("Running cmd: %s", cmd)
    return subprocess.check_output(cmd, stderr=subprocess.PIPE).decode()


def _safe_healthcheck(argv):
    cyclecloud_home = os.getenv("CYCLECLOUD_HOME") or "/opt/cycle/jetpack"
    jetpack_path = os.path.join(cyclecloud_home, "bin", "jetpack")
    nodename = _check_output([jetpack_path, "config", "cyclecloud.node.name"]).strip()

    sinfo_output = _check_output(
        ["sinfo", "-n", nodename, "-N", "-t", "idle,down,drain", "-O", "nodelist", "-h"]
    ).strip()
    if not sinfo_output:
        logging.info("Node is busy. Exiting")
        return

    _check_output(
        [
            "scontrol",
            "update",
            "nodename=%s" % nodename,
            "state=drain",
            "reason=cyclecloud_drain_command",
        ]
    )
    sinfo_output = _check_output(
        ["sinfo", "-n", nodename, "-N", "-t", "drained", "-O", "nodelist", "-h"]
    ).strip()

    if not sinfo_output:
        logging.info("Node is now busy, undraining")
        _check_output(
            [
                "scontrol",
                "update",
                "nodename=%s" % nodename,
                "state=undrain",
                "reason=cyclecloud_drain_command",
            ]
        )

    try:
        _check_output(argv)
        logging.info("Health check passed, undraining")
        _check_output(
            [
                "scontrol",
                "update",
                "nodename=%s" % nodename,
                "state=undrain",
                "reason=cyclecloud_drain_command",
            ]
        )
    except subprocess.CalledProcessError as e:
        logging.error(
            "HealthCheck script exited with %d. Leaving node in drained state due to failure.",
            e.returncode,
        )
        logging.error("stdout: '%s'", (e.stdout or bytes()).decode())
        logging.error("stderr: '%s'", (e.stderr or bytes()).decode())
    except Exception:
        logging.exception("Leaving node in drained state due to failure.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage:", __file__, "path/to/script.sh", file=sys.stderr)
        sys.exit(1)
    _safe_healthcheck(sys.argv[1:])
