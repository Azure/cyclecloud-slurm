import configparser
import os
import subprocess
import sys
import tarfile
import requests
import tempfile
from typing import Optional

def execute() -> None:
    ENROOT_VERSION = "4.0.1"
    PYXIS_VERSION = "0.21.0"

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

    def _download(url: str, dest: str) -> None:
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        except requests.RequestException as e:
            print(f"Error downloading {url}: {e}")

    artifacts_dir = "artifacts"
    os.makedirs(artifacts_dir, exist_ok=True)

    def _add(name: str, path: Optional[str] = None, mode: Optional[int] = None) -> None:
        path = path or name
        tarinfo = tarfile.TarInfo(f"azure-slurm-install/{name}")
        tarinfo.size = os.path.getsize(path)
        tarinfo.mtime = int(os.path.getmtime(path))
        if mode:
            tarinfo.mode = mode

        with open(path, "rb") as fr:
            tf.addfile(tarinfo, fr)

    def _create_combined_certs() -> None:
        """
        Download and combine three SSL certificates required for Azure MySQL:
        1. DigiCert Global Root CA
        2. DigiCert Global Root G2
        3. Microsoft RSA Root Certificate Authority 2017 (converted from DER to PEM)
        """
        cert_urls = {
            "digicert_root_ca": "https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem",
            "digicert_root_g2": "https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem",
            "microsoft_rsa_2017": "https://www.microsoft.com/pkiops/certs/Microsoft%20RSA%20Root%20Certificate%20Authority%202017.crt"
        }

        combined_pem = ""

        with tempfile.TemporaryDirectory() as tmpdir:
            # Download DigiCert Global Root CA
            digicert_ca_path = os.path.join(tmpdir, "DigiCertGlobalRootCA.crt.pem")
            _download(cert_urls["digicert_root_ca"], digicert_ca_path)
            with open(digicert_ca_path, "r") as f:
                combined_pem += f.read() + "\n"

            # Download DigiCert Global Root G2
            digicert_g2_path = os.path.join(tmpdir, "DigiCertGlobalRootG2.crt.pem")
            _download(cert_urls["digicert_root_g2"], digicert_g2_path)
            with open(digicert_g2_path, "r") as f:
                combined_pem += f.read() + "\n"

            # Download Microsoft RSA 2017 (DER format)
            microsoft_der_path = os.path.join(tmpdir, "MicrosoftRSA2017.crt")
            _download(cert_urls["microsoft_rsa_2017"], microsoft_der_path)

            # Convert DER to PEM
            microsoft_pem_path = os.path.join(tmpdir, "MicrosoftRSA2017.pem")
            subprocess.check_call([
                "openssl", "x509",
                "-inform", "DER",
                "-in", microsoft_der_path,
                "-out", microsoft_pem_path
            ])
            with open(microsoft_pem_path, "r") as f:
                combined_pem += f.read() + "\n"
        cert_name = f"AzureCA_{version}.pem"
        # Write combined certificates to AzureCA_{version}.pem
        with open(cert_name, "w") as f:
            f.write(combined_pem)
        _add(cert_name,cert_name)

    #Download EPEL
    for ver in ["8", "9"]:
        url = f"https://dl.fedoraproject.org/pub/epel/epel-release-latest-{ver}.noarch.rpm"
        dest = os.path.join(artifacts_dir, f"epel-release-latest-{ver}.noarch.rpm")
        _download(url, dest)
        _add(dest, dest)

    # Download Pyxis and Enroot packages
    for arch in ["x86_64", "aarch64"]:
        enroot_check_url = f"https://github.com/NVIDIA/enroot/releases/download/v{ENROOT_VERSION}/enroot-check_{ENROOT_VERSION}_{arch}.run"
        enroot_check_dest = os.path.join(artifacts_dir, f"enroot-check_{ENROOT_VERSION}_{arch}.run")
        _download(enroot_check_url, enroot_check_dest)
        _add(enroot_check_dest, enroot_check_dest)
        enroot_rpm_url = f"https://github.com/NVIDIA/enroot/releases/download/v{ENROOT_VERSION}/enroot-{ENROOT_VERSION}-1.el8.{arch}.rpm"
        enroot_rpm_dest = os.path.join(artifacts_dir, f"enroot-{ENROOT_VERSION}-1.el8.{arch}.rpm")
        _download(enroot_rpm_url, enroot_rpm_dest)
        _add(enroot_rpm_dest, enroot_rpm_dest)
        enroot_caps_url = f"https://github.com/NVIDIA/enroot/releases/download/v{ENROOT_VERSION}/enroot+caps-{ENROOT_VERSION}-1.el8.{arch}.rpm"
        enroot_caps_dest = os.path.join(artifacts_dir, f"enroot+caps-{ENROOT_VERSION}-1.el8.{arch}.rpm")
        _download(enroot_caps_url, enroot_caps_dest)
        _add(enroot_caps_dest, enroot_caps_dest)

    for arch in ["amd64", "arm64"]:
        enroot_deb_url = f"https://github.com/NVIDIA/enroot/releases/download/v{ENROOT_VERSION}/enroot_{ENROOT_VERSION}-1_{arch}.deb"
        enroot_deb_dest = os.path.join(artifacts_dir, f"enroot_{ENROOT_VERSION}-1_{arch}.deb")
        _download(enroot_deb_url, enroot_deb_dest)
        _add(enroot_deb_dest, enroot_deb_dest)
        enroot_caps_url = f"https://github.com/NVIDIA/enroot/releases/download/v{ENROOT_VERSION}/enroot+caps_{ENROOT_VERSION}-1_{arch}.deb"
        enroot_caps_dest = os.path.join(artifacts_dir, f"enroot+caps_{ENROOT_VERSION}-1_{arch}.deb")
        _download(enroot_caps_url, enroot_caps_dest)
        _add(enroot_caps_dest, enroot_caps_dest)

    pyxis_url = f"https://github.com/NVIDIA/pyxis/archive/refs/tags/v{PYXIS_VERSION}.tar.gz"
    pyxis_dest = os.path.join(artifacts_dir, f"pyxis-{PYXIS_VERSION}.tar.gz")
    _download(pyxis_url, pyxis_dest)
    _add(pyxis_dest, pyxis_dest)

    _create_combined_certs()
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
    _add("azurelinux.sh", "azurelinux.sh", 600)
    _add("imex_prolog.sh", "imex_prolog.sh", 600)
    _add("imex_epilog.sh", "imex_epilog.sh", 600)
    _add("suse.sh", "suse.sh", 600)
    _add("start-services.sh", "start-services.sh", 555)
    _add("capture_logs.sh", "capture_logs.sh", 755)

    for fil in os.listdir("templates"):
        if os.path.isfile(f"templates/{fil}"):
            _add(f"templates/{fil}", f"templates/{fil}")

if __name__ == "__main__":
    execute()
