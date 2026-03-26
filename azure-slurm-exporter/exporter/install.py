import yaml
import os
import logging
import logging.config
import sys
import subprocess
import signal
from importlib import resources

log = logging.getLogger("installer")

class PrometheusNotFoundException(Exception):
    pass

class SystemdSetupException(Exception):
    pass

def add_azslurm_exporter_scraper(prom_config: str, port: int = 9101) -> None:
    """
    Add azslurm_exporter scrape config to prometheus.yml so Prometheus can scrape the azslurm_exporter server at
    a given interval and ingest the metrics.
    """

    if not os.path.isfile(prom_config):
        log.error("Prometheus configuration file not found, exiting azslurm_exporter configuration.")
        raise PrometheusNotFoundException

    # Merge YAML files
    with open(prom_config, "r") as f:
        prom_yaml = yaml.safe_load(f) or {}

    hostname = os.uname().nodename

    new_scrape = {
        "job_name": "azslurm_exporter",
        "static_configs": [
            {"targets": [f"{hostname}:{port}"]}
        ],
        "relabel_configs": [
            {
                "source_labels": ["__address__"],
                "target_label": "instance",
                "regex": "([^:]+)(:[0-9]+)?",
                "replacement": "${1}",
            }
        ],
    }

    scrape_configs = prom_yaml.get("scrape_configs", [])

    # Remove any existing azslurm_exporter entry, then add the new one
    updated = False
    for i, sc in enumerate(scrape_configs):
        if sc.get("job_name") == "azslurm_exporter":
            scrape_configs[i] = new_scrape
            updated = True
            log.info("Updated existing azslurm_exporter scrape config in prometheus.yml")
            break

    if not updated:
        scrape_configs.append(new_scrape)
        log.info("Added azslurm_exporter scrape config to prometheus.yml")

    prom_yaml["scrape_configs"] = scrape_configs

    # Write back to prom_config
    with open(prom_config, "w") as f:
        yaml.safe_dump(prom_yaml, f, default_flow_style=False)

    # Send SIGHUP to Prometheus to reload its configuration
    _reload_prometheus()

def setup_azslurm_exporter_systemd(venv: str, port: int = 9101) -> None:
    """
    Setup the azslurm-exporter.service to be run and managed by systemd
    """

    service_path = "/etc/systemd/system/azslurm-exporter.service"
    service_content = f"""[Unit]
Description=AzSlurm Exporter Daemon
After=network.target

[Service]
ExecStart={venv}/bin/azslurm-exporter
Restart=always
User=root
Group=root
Environment="PATH={venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="AZSLURM_EXPORTER_PORT={port}"


[Install]
WantedBy=multi-user.target
"""
    with open(service_path, "w") as f:
            f.write(service_content)
    log.info("Wrote systemd service file to %s", service_path)

    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        log.error("systemctl daemon-reload failed: %s", e.stderr)
        raise SystemdSetupException

    try:
        subprocess.run(["systemctl", "enable", "azslurm-exporter"], check=True, capture_output=True, text=True)
        log.info("azslurm-exporter service enabled")
    except subprocess.CalledProcessError as e:
        log.error("Failed to enable azslurm-exporter: %s", e.stderr)
        raise SystemdSetupException

LOG_FILES = [
    "/var/log/azslurm-exporter.log",
    "/var/log/azslurm-exporter-install.log",
]

def create_log_files() -> None:
    """Create the exporter log files with world-read/write permissions so any user can run the exporter."""
    for log_file in LOG_FILES:
        if not os.path.exists(log_file):
            open(log_file, "a").close()
        os.chmod(log_file, 0o666)
        log.info("Created log file %s with rw-rw-rw- permissions", log_file)

def _reload_prometheus() -> None:
    """Send SIGHUP to the Prometheus process to trigger a configuration reload."""

    try:
        result = subprocess.run(
            ["pgrep", "-f", "prometheus"],
            capture_output=True,
            text=True,
            check=True,
        )
        pids = result.stdout.strip().splitlines()
        if not pids:
            log.warning("No Prometheus process found; skipping config reload.")
            return

        for pid in pids:
            pid_int = int(pid.strip())
            os.kill(pid_int, signal.SIGHUP)
            log.info("Sent SIGHUP to Prometheus process (PID %d) to reload configuration.", pid_int)

    except subprocess.CalledProcessError:
        log.warning("Could not find Prometheus process; skipping config reload.")
    except (ValueError, ProcessLookupError, PermissionError) as e:
        log.warning("Failed to send SIGHUP to Prometheus: %s", e)

def main():
    create_log_files()
    conf_file = resources.files("exporter").joinpath("exporter_logging.conf")
    logging.config.fileConfig(str(conf_file))
    venv = sys.prefix
    port = int(os.environ.get("AZSLURM_EXPORTER_PORT", 9101))
    try:
        setup_azslurm_exporter_systemd(venv=venv, port=port)
        add_azslurm_exporter_scraper("/opt/prometheus/prometheus.yml", port=port)
    except PrometheusNotFoundException:
        sys.exit(1)
    except SystemdSetupException:
        sys.exit(1)