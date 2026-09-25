import os
from pathlib import Path
import subprocess

import pytest


INSTALLER = Path(__file__).resolve().parents[1] / "ubuntu.sh"


def shell_block(start, end):
    lines = INSTALLER.read_text().splitlines()
    first = next(index for index, line in enumerate(lines) if line.startswith(start))
    last = next(index for index in range(first + 1, len(lines)) if lines[index] == end)
    return "\n".join(lines[first:last + 1])


def run_shell(code, **environment):
    return subprocess.run(
        ["bash", "-eo", "pipefail"], input=code, text=True, capture_output=True,
        env={**os.environ, **environment},
    )


@pytest.mark.parametrize("version,repository", [
    ("20.04", "focal"), ("22.04", "jammy"),
    ("24.04", "noble"), ("26.04", "resolute"),
])
def test_ubuntu_repository(version, repository):
    result = run_shell(
        shell_block('arch=$(dpkg --print-architecture)', "fi") + '\nprintf "%s" "$REPO"',
        UBUNTU_VERSION=version,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "slurm-ubuntu-" + repository


@pytest.mark.parametrize("version,accepted", [("22.04", False), ("24.04", True), ("26.04", True)])
def test_ubuntu_arm64(version, accepted):
    result = run_shell(shell_block('if [ "$arch" == "arm64" ]', "fi"),
                       UBUNTU_VERSION=version, arch="arm64")
    assert (result.returncode == 0) == accepted


@pytest.mark.parametrize("missing,duplicate", [(False, False), (True, False), (False, True)])
def test_local_packages(tmp_path, missing, duplicate):
    for package in ["pmix", "pmix-hwloc", "pmix-libevent", "slurm-smd", "slurm-smd-slurmd"]:
        if missing and package == "pmix-hwloc":
            continue
        (tmp_path / f"{package}_26.05.4-2_amd64.deb").touch()
    if duplicate:
        (tmp_path / "pmix_26.05.4-3_amd64.deb").touch()
    result = run_shell(
        shell_block('if [[ -n "$SLURM_PACKAGE_DIR" ]]', "fi") + '\nprintf "%s" "$all_packages"',
        SLURM_PACKAGE_DIR=str(tmp_path), SLURM_VERSION="26.05.4-2", arch="amd64",
        all_slurm_packages="slurm-smd slurm-smd-slurmd", all_packages="munge",
    )
    assert (result.returncode == 0) == (not missing and not duplicate), result.stderr
    if result.returncode == 0:
        assert len(result.stdout.split()) == 6


@pytest.mark.parametrize("installed,needs_install", [("26.05.4-1", True), ("26.05.4-2", False)])
def test_local_package_release(installed, needs_install):
    result = run_shell(shell_block("dpkg_pkg_install()", "}") + r'''
dpkg-deb() { if [[ "$3" == Package ]]; then printf slurm-smd; else printf 26.05.4-2; fi; }
dpkg-query() { [[ "$2" == '-f=${db:Status-Status} ${Version}' ]] || return 99; printf 'installed %s' "$installed"; }
apt() { printf 'APT:%s\n' "$*"; }
apt-mark() { :; }
dpkg_pkg_install /test/slurm-smd_26.05.4-2_amd64.deb
''', installed=installed)
    assert result.returncode == 0, result.stderr
    assert ("APT:install" in result.stdout) == needs_install


@pytest.mark.parametrize("version,verifier_dd", [("24.04", "default-dd"), ("26.04", "gnu-dd")])
def test_enroot_dd_override_is_scoped(tmp_path, version, verifier_dd):
    verifier = tmp_path / "verify.sh"
    verifier.write_text('#!/bin/bash\ndd\n')
    verifier.chmod(0o755)
    result = run_shell('''
dd() { printf 'default-dd\\n'; }
gnudd() { printf 'gnu-dd\\n'; }
export -f dd gnudd
''' + shell_block("(", ")") + '\ndd\n', UBUNTU_VERSION=version, run_file=str(verifier))
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{verifier_dd}\ndefault-dd\n"