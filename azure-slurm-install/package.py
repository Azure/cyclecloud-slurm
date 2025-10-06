import configparser
import os
import subprocess
import sys
import tarfile
import requests
from typing import Optional

def execute() -> None:

    expected_cwd = os.path.abspath(os.path.dirname(__file__))
    os.chdir(expected_cwd)

    if not os.path.exists("libs"):
        os.makedirs("libs")

    parser = configparser.ConfigParser()
    ini_path = os.path.abspath("../project.ini")

    with open(ini_path) as fr:
        parser.read_file(fr)

    version = parser.get("project", "version")

    if not version:
        raise RuntimeError("Missing [project] -> version in {}".format(ini_path))

    if not os.path.exists("dist"):
        os.makedirs("dist")

    tf = tarfile.TarFile.gzopen(
        f"dist/azure-slurm-install-pkg-{version}.tar.gz", "w"
    )

    def _download_file(url: str, dest: str) -> None:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    artifacts_dir = "artifacts"
    os.makedirs(artifacts_dir, exist_ok=True)

    epel8_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm"
    epel9_url = "https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm"

    epel8_dest = os.path.join(artifacts_dir, "epel-release-latest-8.noarch.rpm")
    epel9_dest = os.path.join(artifacts_dir, "epel-release-latest-9.noarch.rpm")

    _download_file(epel8_url, epel8_dest)
    _download_file(epel9_url, epel9_dest)

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
    _add("slurmel8insiders.repo", "slurmel8insiders.repo")
    _add("slurmel9insiders.repo", "slurmel9insiders.repo")
    _add("slurmel8.repo", "slurmel8.repo")
    _add("slurmel9.repo", "slurmel9.repo")
    _add("ubuntu.sh", "ubuntu.sh", 600)
    _add("rhel.sh", "rhel.sh", 600)
    _add("imex_prolog.sh", "imex_prolog.sh", 600)
    _add("imex_epilog.sh", "imex_epilog.sh", 600)
    _add("AzureCA.pem", "AzureCA.pem")
    _add("suse.sh", "suse.sh", 600)
    _add("start-services.sh", "start-services.sh", 555)
    _add("capture_logs.sh", "capture_logs.sh", 755)
    _add(epel8_dest, epel8_dest)
    _add(epel9_dest, epel9_dest)

    for fil in os.listdir("templates"):
        if os.path.isfile(f"templates/{fil}"):
            _add(f"templates/{fil}", f"templates/{fil}")

if __name__ == "__main__":
    execute()
