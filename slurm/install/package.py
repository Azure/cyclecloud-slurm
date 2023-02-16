import configparser
import os
import subprocess
import sys
import tarfile
from typing import Optional

import slurm_supported_version


def download_bins() -> None:
    with open("download-slurm-pkgs.sh", "w") as fw:
        fw.write(f"""#!/usr/bin/env bash
cd $(dirname $0)
mkdir -p slurm-pkgs
""")    
        slurm_bins_by_version = slurm_supported_version.get_required_packages()
        url_root = slurm_supported_version.CURRENT_DOWNLOAD_URL
        for _, pkgs in slurm_bins_by_version.items():
            for pkg in pkgs:
                fw.write(f"""
if [ ! -e slurm-pkgs/{pkg} ]; then
    wget -O slurm-pkgs/{pkg} {url_root}/{pkg}
fi
""")

    print(
        "Downloading slurm packages... if you hit an error, just run ./download-slurm-pkgs.sh again"
    )
    exit_code = subprocess.call(["bash", "download-slurm-pkgs.sh"])
    if exit_code == 0:
        print("Success. Deleting download-slurm-pkgs.sh")
        # only remove this on the happy case
        os.remove("download-slurm-pkgs.sh")
    else:
        print("  WARNING: Not all slurm packages were downloaded. You might be rate limited.")
        print("  Just run 'bash download-slurm-pkgs.sh' again")
        sys.exit(1)


def execute() -> None:
    
    expected_cwd = os.path.abspath(os.path.dirname(__file__))
    os.chdir(expected_cwd)

    download_bins()

    if not os.path.exists("libs"):
        os.makedirs("libs")

    parser = configparser.ConfigParser()
    ini_path = os.path.abspath("../../project.ini")

    with open(ini_path) as fr:
        parser.read_file(fr)

    version = parser.get("project", "version")

    if not version:
        raise RuntimeError("Missing [project] -> version in {}".format(ini_path))

    slurm_bins_by_version = slurm_supported_version.get_required_packages()

    if not os.path.exists("dist"):
        os.makedirs("dist")

    tf = tarfile.TarFile.gzopen(
        f"dist/azure-slurm-install-pkg-{version}.tar.gz", "w"
    )

    def _add(name: str, path: Optional[str] = None, mode: Optional[int] = None) -> None:
        path = path or name
        tarinfo = tarfile.TarInfo(f"azure-slurm-install/{name}")
        tarinfo.size = os.path.getsize(path)
        tarinfo.mtime = int(os.path.getmtime(path))
        if mode:
            tarinfo.mode = mode

        with open(path, "rb") as fr:
            tf.addfile(tarinfo, fr)

    _add("install.sh", "install.sh", mode=os.stat("install.sh")[0])
    _add("install_logging.conf", "conf/install_logging.conf")
    _add("installlib.py", "installlib.py")
    _add("install.py", "install.py")
    _add("ubuntu.sh", "ubuntu.sh", 600)
    _add("rhel.sh", "rhel.sh", 600)

    for fil in os.listdir("templates"):
        if os.path.isfile(f"templates/{fil}"):
            _add(f"templates/{fil}", f"templates/{fil}")

    for _, slurm_bins_by_version in slurm_bins_by_version.items():
        for rbin in slurm_bins_by_version:
            _add(f"slurm-pkgs/{rbin}", os.path.abspath(f"slurm-pkgs/{rbin}"))


if __name__ == "__main__":
    execute()
