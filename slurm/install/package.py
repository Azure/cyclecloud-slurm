import argparse
import configparser
import glob
import os
import shutil
import sys
import tarfile
import tempfile
from argparse import Namespace
from subprocess import check_call
from typing import Dict, List, Optional

CYCLECLOUD_API_VERSION = "8.1.0"


def get_cycle_libs(args: Namespace) -> List[str]:
    ret = []

    cyclecloud_api_file = "cyclecloud_api-{}-py2.py3-none-any.whl".format(
        CYCLECLOUD_API_VERSION
    )

    # TODO RDH!!!
    cyclecloud_api_url = "https://github.com/Azure/cyclecloud-gridengine/releases/download/2.0.0/cyclecloud_api-8.0.1-py2.py3-none-any.whl"
    to_download = {
        cyclecloud_api_file: (args.cyclecloud_api, cyclecloud_api_url),
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

    if not os.path.exists("libs"):
        os.makedirs("libs")

    argument_parser = argparse.ArgumentParser(
        "Builds CycleCloud Slurm project with all dependencies.\n"
        + "If you don't specify local copies of cyclecloud-api they will be downloaded from github."
    )
    argument_parser.add_argument("--cyclecloud-api", default=None)
    argument_parser.add_argument("--platform", default="rhel")
    argument_parser.add_argument("--platform-version", default="el8")
    argument_parser.add_argument("--arch", default="x86_64")
    args = argument_parser.parse_args()

    cycle_libs = get_cycle_libs(args)

    parser = configparser.ConfigParser()
    ini_path = os.path.abspath("../../project.ini")

    with open(ini_path) as fr:
        parser.read_file(fr)

    version = parser.get("project", "version")

    if not version:
        raise RuntimeError("Missing [project] -> version in {}".format(ini_path))

    slurm_version = parser.get("config slurm.version", "DefaultValue")
    if not slurm_version:
        raise RuntimeError(
            "Missing [config slurm.version] -> DefaultValue in {}".format(ini_path)
        )

    if not os.path.exists("dist"):
        os.makedirs("dist")

    tf = tarfile.TarFile.gzopen(
        "dist/azure-slurm-install-pkg-{}.tar.gz".format(version), "w"
    )

    build_dir = tempfile.mkdtemp("azure-slurm-install")

    def _add(name: str, path: Optional[str] = None, mode: Optional[int] = None) -> None:
        path = path or name
        tarinfo = tarfile.TarInfo("azure-slurm-install/" + name)
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

    check_call(["pip3", "download"] + packages, cwd=build_dir)

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
        if fil.startswith("certifi-20"):
            print("WARNING: Ignoring duplicate certifi {}".format(fil))
            continue
        path = os.path.join(build_dir, fil)
        _add("packages/" + fil, path)

    _add("install.sh", mode=os.stat("install.sh")[0])

    _add("install_logging.conf", "conf/install_logging.conf")
    _add("installlib.py", "installlib.py")
    _add("install.py", "install.py")

    for fil in os.listdir("templates"):
        _add(f"templates/{fil}", f"templates/{fil}")

    blobs = []
    if args.platform == "ubuntu":
        _add("ubuntu.sh", "ubuntu.sh", 600)
        for slurmpkg in [
            "slurm",
            "slurm-devel",
            "slurm-example-configs",
            "slurm-slurmctld",
            "slurm-slurmdbd",
            "slurm-slurmd",
        ]:
            blobs.append(f"{slurmpkg}_{slurm_version}_amd64.deb")
    else:
        _add("rhel.sh", "rhel.sh", 600)
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
            blobs.append(
                f"{slurmpkg}-{slurm_version}.{args.platform_version}.{args.arch}.rpm"
            )
    for blob in blobs:
        _add(f"blobs/{blob}", os.path.abspath(f"../../blobs/{blob}"))


if __name__ == "__main__":
    execute()
