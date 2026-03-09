import yaml
import os
import logging
import logging.config
import sys
import subprocess
from importlib import resources

log = logging.getLogger("installer")

class PrometheusNotFoundException(Exception):
    pass

class SystemdSetupException(Exception):
    pass

def add_azslurm_exporter_scraper(prom_config: str) -> None:
    """
    Add azslurm_exporter scrape config to prometheus.yml so Prometheus can scrape the azslurm_exporter server at
    a given interval and ingest the metrics.
    """

    if not os.path.isfile(prom_config):
        log.error("Prometheus configuration file not found, exiting azslurm_exporter configuration.")
        raise PrometheusNotFoundException

    with open(prom_config, "r") as f:
        prom_content = f.read()
        if "azslurm_exporter" in prom_content:
            log.info("AzSlurm Exporter is already configured in Prometheus")
            return

    # Merge YAML files
    with open(prom_config, "r") as f:
        prom_yaml = yaml.safe_load(f) or {}
    exporter_yaml_content = {
    "scrape_configs": [
        {
            "job_name": "azslurm_exporter",
            "static_configs": [
                {"targets": ["instance_name:9101"]}
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
    ]
}

    # Simple merge: add/replace scrape_configs
    def merge_scrape_configs(base, overlay):
        base_scrapes = base.get("scrape_configs", [])
        overlay_scrapes = overlay.get("scrape_configs", [])
        base["scrape_configs"] = base_scrapes + overlay_scrapes
        return base

    merged_yaml = merge_scrape_configs(prom_yaml, exporter_yaml_content)

    # Replace instance_name placeholder
    hostname = os.uname().nodename
    merged_str = yaml.safe_dump(merged_yaml, default_flow_style=False)
    merged_str = merged_str.replace("instance_name", hostname)

    # Write back to prom_config
    with open(prom_config, "w") as f:
        f.write(merged_str)
    log.info("Added azslurm_exporter scrape config to prometheus.yml")

def setup_azslurm_exporter_systemd(venv: str) -> None:
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

def main():
    conf_file = resources.files("exporter").joinpath("exporter_logging.conf")
    logging.config.fileConfig(str(conf_file))
    venv = sys.prefix
    try:
        setup_azslurm_exporter_systemd(venv=venv)
        add_azslurm_exporter_scraper("/opt/prometheus/prometheus.yml")
    except PrometheusNotFoundException:
        sys.exit(1)
    except SystemdSetupException:
        sys.exit(1)