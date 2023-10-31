import argparse
from typing import Dict, List
import configparser
import os


SUPPORTED_VERSIONS = {
    "22.05.10": {
        "rhel": {
            "rhel8": {"platform_version": "el8", "arch": "x86_64"},
            "centos7": {"platform_version": "el7", "arch": "x86_64"}
        },
        "debian": {
            "ubuntu20": {"arch": "amd64"},
            "ubuntu22": {"arch": "amd64"}
        }
    },
    "23.02.6": {
        "rhel": {
            "rhel8": {"platform_version": "el8", "arch": "x86_64"},
            "centos7": {"platform_version": "el7", "arch": "x86_64"}
        },
        "debian": {
            "ubuntu20": {"arch": "amd64"},
            "ubuntu22": {"arch": "amd64"}
        }
    }
}

CURRENT_DOWNLOAD_URL = "https://github.com/Azure/cyclecloud-slurm/releases/download/2023-10-27-bins"


def get_required_packages() -> Dict[str, List[str]]:
    mydir = os.path.dirname(os.path.abspath(__file__))
    pardir = os.path.dirname(os.path.dirname(mydir))

    ini = configparser.ConfigParser()

    ini.read(os.path.join(pardir, "project.ini"))
    expr = ini.get("config slurm.version", "Config.Entries")
    clean_expr = expr[expr.index("[") + 1 : expr.rindex("]")].replace('"', "")

    toks = clean_expr.split(",")
    referenced_versions = set()
    for tok in toks:
        _, _referenced_version = tok.strip("]").strip("[").split("=")
        _referenced_version = _referenced_version.strip("-1")
        referenced_versions.add(_referenced_version)

    assert referenced_versions == set(
        SUPPORTED_VERSIONS.keys()
    ), f"Expected {referenced_versions} == {set(SUPPORTED_VERSIONS.keys())}"

    ret = []
    for slurm_version,ostype in SUPPORTED_VERSIONS.items():

        for distro,pkg in ostype["debian"].items():
            for slurmpkg in [
                "slurm",
                "slurm-devel",
                "slurm-example-configs",
                "slurm-libpmi",
                "slurm-perlapi",
                "slurm-slurmctld",
                "slurm-slurmdbd",
                "slurm-slurmd",
                "slurm-slurmrestd",
                "slurm-contribs",
                "slurm-pam-slurm",
                "slurm-torque",
                "slurm-openlava",
            ]:
                ret.append(
                    f"{distro}/{slurmpkg}_{slurm_version}-1_{pkg['arch']}.deb"
                )
        for distro,pkg in ostype["rhel"].items():

            for slurmpkg in [
                "slurm",
                "slurm-devel",
                "slurm-example-configs",
                "slurm-slurmctld",
                "slurm-slurmd",
                "slurm-slurmdbd",
                "slurm-libpmi",
                "slurm-perlapi",
                "slurm-torque",
                "slurm-openlava",
                "slurm-slurmrestd",
                "slurm-pam_slurm",
                "slurm-contribs"
            ]:
                ret.append(
                    f"{distro}/{slurmpkg}-{slurm_version}-1.{pkg['platform_version']}.{pkg['arch']}.rpm"
                )
    return ret


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--short", default=False, action="store_true")
    args = parser.parse_args()
    for version in SUPPORTED_VERSIONS:
        if args.short:
            print(version.split("-")[0])
        else:
            print(version)


if __name__ == "__main__":
    main()
