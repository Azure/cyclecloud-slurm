import argparse
import configparser
import glob
import pip
import os
import shutil
import sys
import tarfile
import tempfile
from argparse import Namespace
from subprocess import check_call
from typing import Dict, List, Optional

def build_sdist() -> str:
    check_call([sys.executable, "setup.py", "sdist"])
    # sometimes this is azure-slurm, sometimes it is azure_slurm, depenends on the build system version.
    sdists = glob.glob("dist/azure*slurm*exporter*.tar.gz")
    assert len(sdists) == 1, f"Found %d sdist packages, expected 1 - see {os.path.abspath('dist/azure-slurm-exporter*.tar.gz')}" % len(sdists)
    path = sdists[0]
    fname = os.path.basename(path)
    dest = os.path.join("libs", fname)
    if os.path.exists(dest):
        os.remove(dest)
    shutil.move(path, dest)
    return fname

def execute() -> None:

    expected_cwd = os.path.abspath(os.path.dirname(__file__))
    os.chdir(expected_cwd)

    print("Running from", expected_cwd)

    if not os.path.exists("libs"):
        os.makedirs("libs")

    parser = configparser.ConfigParser()
    ini_path = os.path.abspath("../project.ini")

    with open(ini_path) as fr:
        parser.read_file(fr)

    version = parser.get("project", "version")
    if not version:
        raise RuntimeError("Missing [project] -> version in {}".format(ini_path))

    ret = [build_sdist()]

    if not os.path.exists("dist"):
        os.makedirs("dist")

    tf = tarfile.TarFile.gzopen(
        "dist/azure-slurm-exporter-pkg-{}.tar.gz".format(version), "w"
    )

    build_dir = tempfile.mkdtemp("azure-slurm-exporter")


    def _add(name: str, path: Optional[str] = None, mode: Optional[int] = None) -> None:
        path = path or name
        tarinfo = tarfile.TarInfo("azure-slurm-exporter/" + name)
        tarinfo.size = os.path.getsize(path)
        tarinfo.mtime = int(os.path.getmtime(path))
        if mode:
            tarinfo.mode = mode

        with open(path, "rb") as fr:
            tf.addfile(tarinfo, fr)

    packages = []
    for dep in ret:
        dep_path = os.path.abspath(os.path.join("libs", dep))
        _add("packages/" + dep, dep_path)
        packages.append(dep_path)
    mypip = shutil.which("pip3")
    print("my pip", mypip)
    check_call([mypip, "download"] + packages, cwd=build_dir)

    print("Using build dir", build_dir)
    by_package: Dict[str, List[str]] = {}
    for fil in os.listdir(build_dir):
        toks = fil.split("-", 1)
        package = toks[0]
        if package not in by_package:
            by_package[package] = []
        by_package[package].append(fil)

    for package, fils in by_package.items():

        if len(fils) > 1:
            print("WARNING: Ignoring duplicate package found:", package, fils)
            assert False

    for fil in os.listdir(build_dir):
        # Skip platform-specific or unnecessary packages
        skip_packages = ["aiohttp", "frozenlist","multidict","propcache","yarl"]
        if any(pkg in fil.lower() for pkg in skip_packages):
            print(f"WARNING: Ignoring unnecessary package {fil}, platform specific or not needed.")
            continue
        path = os.path.join(build_dir, fil)
        _add("packages/" + fil, path)

    _add("exporter_logging.conf", "conf/exporter_logging.conf")
    _add("install.sh", "install.sh", mode=os.stat("install.sh")[0])


if __name__ == "__main__":
    execute()
