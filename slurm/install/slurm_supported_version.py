import argparse
from typing import Dict, List
import configparser
import os


SUPPORTED_VERSIONS = {
    "22.05.9": {
        "rhel": [{"platform_version": "el8", "arch": "x86_64"},
                 {"platform_version": "el7", "arch": "x86_64"}],
        "debian": [{"arch": "amd64"}],
    },
    "23.02.5": {
        "rhel": [{"platform_version": "el8", "arch": "x86_64"},
                 {"platform_version": "el7", "arch": "x86_64"}],
        "debian": [{"arch": "amd64"}],
    }
}

CURRENT_DOWNLOAD_URL = "https://github.com/Azure/cyclecloud-slurm/releases/download/2023-08-07-bins"


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

    ret = {}
    for slurm_version, distros in SUPPORTED_VERSIONS.items():
        ret[slurm_version] = required_bins = []
        for debian_version in distros["debian"]:
            for slurmpkg in [
                "slurm",
                "slurm-devel",
                "slurm-example-configs",
                "slurm-libpmi",
                "slurm-perlapi",
                "slurm-slurmctld",
                "slurm-slurmdbd",
                "slurm-slurmd",
            ]:
                required_bins.append(
                    f"{slurmpkg}_{slurm_version}-1_{debian_version['arch']}.deb"
                )
        for rhel_version in distros["rhel"]:

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
            ]:
                required_bins.append(
                    f"{slurmpkg}-{slurm_version}-1.{rhel_version['platform_version']}.{rhel_version['arch']}.rpm"
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
