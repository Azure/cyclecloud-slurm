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

SCALELIB_VERSION = "1.0.2"
CYCLECLOUD_API_VERSION = "8.4.1"


def build_sdist() -> str:
    check_call([sys.executable, "setup.py", "sdist"], cwd="slurm")
    sdists = glob.glob("slurm/dist/azure-slurm-*.tar.gz")
    assert len(sdists) == 1, f"Found %d sdist packages, expected 1 - see {os.path.abspath('slurm/dist/azure-slurm-*.tar.gz')}" % len(sdists)
    path = sdists[0]
    fname = os.path.basename(path)
    dest = os.path.join("libs", fname)
    if os.path.exists(dest):
        os.remove(dest)
    shutil.move(path, dest)
    return fname


def get_cycle_libs(args: Namespace) -> List[str]:
    ret = [build_sdist()]

    scalelib_file = "cyclecloud-scalelib-{}.tar.gz".format(SCALELIB_VERSION)
    cyclecloud_api_file = "cyclecloud_api-{}-py2.py3-none-any.whl".format(
        CYCLECLOUD_API_VERSION
    )
    # swagger_file = "swagger-client-1.0.0.tar.gz"

    scalelib_url = "https://github.com/Azure/cyclecloud-scalelib/archive/refs/tags/{}.tar.gz".format(
        SCALELIB_VERSION
    )
    
    cyclecloud_api_url = "https://github.com/Azure/cyclecloud-slurm/releases/download/2023-09-14-bins/cyclecloud_api-8.4.1-py2.py3-none-any.whl"
    to_download = {
        scalelib_file: (args.scalelib, scalelib_url),
        cyclecloud_api_file: (args.cyclecloud_api, cyclecloud_api_url),
        # swagger_file: (args.swagger, None)
    }

    for lib_file in to_download:
        arg_override, url = to_download[lib_file]
        if arg_override:
            if not os.path.exists(arg_override):
                print(arg_override, "does not exist", file=sys.stderr)
                sys.exit(1)
            fname = os.path.basename(arg_override)
            orig = os.path.abspath(arg_override)
            dest = os.path.abspath(os.path.join("libs", fname))
            if orig != dest:
                shutil.copyfile(orig, dest)
            ret.append(fname)
        else:
            dest = os.path.join("libs", lib_file)
            check_call(["curl", "-L", "-k", "-s", "-f", "-o", dest, url])
            ret.append(lib_file)
            print("Downloaded", lib_file, "to")

    return ret


def execute() -> None:
    expected_cwd = os.path.abspath(os.path.dirname(__file__))
    os.chdir(expected_cwd)

    print("Running from", expected_cwd)

    if not os.path.exists("libs"):
        os.makedirs("libs")

    argument_parser = argparse.ArgumentParser(
        "Builds Azure Slurm project with all dependencies.\n"
        + "If you don't specify local copies of scalelib or cyclecloud-api they will be downloaded from github."
    )
    argument_parser.add_argument("--scalelib", default=None)
    # argument_parser.add_argument("--swagger", default=None)
    argument_parser.add_argument("--cyclecloud-api", default=None)
    args = argument_parser.parse_args()

    cycle_libs = get_cycle_libs(args)

    parser = configparser.ConfigParser()
    ini_path = os.path.abspath("project.ini")

    with open(ini_path) as fr:
        parser.read_file(fr)

    version = parser.get("project", "version")
    if not version:
        raise RuntimeError("Missing [project] -> version in {}".format(ini_path))

    if not os.path.exists("dist"):
        os.makedirs("dist")

    tf = tarfile.TarFile.gzopen(
        "dist/azure-slurm-pkg-{}.tar.gz".format(version), "w"
    )

    build_dir = tempfile.mkdtemp("azure-slurm")

    def _add(name: str, path: Optional[str] = None, mode: Optional[int] = None) -> None:
        path = path or name
        tarinfo = tarfile.TarInfo("azure-slurm/" + name)
        tarinfo.size = os.path.getsize(path)
        tarinfo.mtime = int(os.path.getmtime(path))
        if mode:
            tarinfo.mode = mode

        with open(path, "rb") as fr:
            tf.addfile(tarinfo, fr)

    packages = []
    for dep in cycle_libs:
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
        if package == "cyclecloud":
            package = "{}-{}".format(toks[0], toks[1])
        if package not in by_package:
            by_package[package] = []
        by_package[package].append(fil)

    for package, fils in by_package.items():
        
        if len(fils) > 1:
            print("WARNING: Ignoring duplicate package found:", package, fils)
            assert False

    for fil in os.listdir(build_dir):
        if "pyyaml" in fil.lower():
            print(f"WARNING: Ignoring unnecessary PyYaml {fil}, also it is platform (ubuntu/rhel) specific.")
            continue
        path = os.path.join(build_dir, fil)
        _add("packages/" + fil, path)

    _add("install.sh", "install.sh", mode=os.stat("install.sh")[0])
    _add("sbin/resume_fail_program.sh", "sbin/resume_fail_program.sh")
    _add("sbin/prolog.sh", "sbin/prolog.sh")
    _add("sbin/resume_program.sh", "sbin/resume_program.sh")
    _add("sbin/return_to_idle.sh", "sbin/return_to_idle.sh")
    _add("sbin/return_to_idle_legacyfin.sh", "sbin/return_to_idle_legacy.sh")
    _add("sbin/suspend_program.sh", "sbin/suspend_program.sh")
    _add("sbin/get_acct_info.sh", "sbin/get_acct_info.sh")
    _add("logging.conf", "slurm/conf/logging.conf")
    


if __name__ == "__main__":
    execute()
