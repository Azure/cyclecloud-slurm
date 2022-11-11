import grp
import json
import logging
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import time
from types import TracebackType
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union


class ConvergeError(RuntimeError):
    pass


class ConvergeRetry(RuntimeError):
    pass


def blob_download(filename: str, project: str, node: Dict) -> str:

    downloads_dir = node["blobs"].get("downloads", "/opt/azurehpc/blobs")
    if not os.path.exists(downloads_dir):
        os.makedirs(downloads_dir)

    dest = os.path.join(downloads_dir, filename)
    if node["blobs"]["type"] == "simple":
        return dest
        # src = os.path.join(node["blobs"]["url"], filename)
        # shutil.copyfile(src=src, dst=dest)
    elif node["blobs"]["type"] == "jetpack":
        subprocess.check_call(
            ["jetpack", "download", filename, f"--project={project}", dest]
        )
        return dest
    else:
        raise ConvergeError("Only blobs.type==simple or jetpack is valid at this time")


def link(
    src: str, dst: str, owner: Optional[str] = None, group: Optional[str] = None
) -> None:
    if not os.path.islink(dst):
        logging.info("Linking {dst} to {src}".format(**locals()))
        os.symlink(src, dst)
        # chown(to, owner, group)
    else:
        logging.info("Link {dst} already exists".format(**locals()))


def chown(
    dest: str,
    owner: Optional[str] = None,
    group: Optional[str] = None,
    recursive: bool = False,
) -> None:
    pwd_record = uid = gid = None

    if owner:
        pwd_record = pwd.getpwnam(owner)
        uid = pwd_record.pw_uid
        gid = pwd_record.pw_gid

    if group:
        gid = grp.getgrnam(group).gr_gid
    elif pwd_record:
        group = pwd_record.pw_name

    if uid and gid:
        recursive_arg = "-R" if recursive else ""
        logging.info(f"chown {recursive_arg} {dest} with {owner}({uid}):{group}({gid})")
        os.chown(dest, uid=uid, gid=gid)
        if recursive and os.path.isdir(dest):
            # TODO should probably use OS version
            for fil in os.listdir(dest):
                chown(os.path.join(dest, fil), owner, group, recursive=recursive)


def chmod(dest: str, mode: Optional[Union[str, int]], recursive: bool = False) -> None:
    if mode is not None:
        # if isinstance(mode, str):
        #     mode = int(mode)
        logging.info(f"chmod {mode} {dest}")
        if recursive:
            cmd = ["chmod", "-R", str(mode), dest]
        else:
            cmd = ["chmod", str(mode), dest]
        print(" ".join(cmd))
        subprocess.check_call(cmd)
        # os.chmod(dest, mode)

        # if recursive and os.path.isdir(dest):
        #     for fil in os.listdir(dest):
        #         chmod(os.path.join(dest, fil), mode, recursive=recursive)


def copy_file(
    source: str, dest: str, owner: str, group: str, mode: Union[str, int]
) -> None:
    shutil.copyfile(src=source, dst=dest)
    chown(dest, owner=owner, group=group)
    chmod(dest, mode)


def file(
    dest: str,
    content: Union[bytes, str] = "",
    owner: Optional[str] = None,
    group: Optional[str] = None,
    mode: Optional[Union[str, int]] = None,
) -> None:
    io_mode = "a" if isinstance(content, str) else "ab"
    tmp_dest = dest + ".tmp"
    with open(tmp_dest, io_mode) as fw:
        fw.write(content)
    chown(tmp_dest, owner, group)
    chmod(tmp_dest, mode)
    shutil.move(tmp_dest, dest)


# TODO!!!
def cookbook_file(
    dest: str, source: str, owner: str, group: str, mode: Union[str, int]
) -> None:
    full_source = os.path.abspath(os.path.join("cookbook_files", source))
    if isinstance(mode, str):
        mode = int(mode)
    copy_file(full_source, dest, owner, group, mode)


def template(
    dest: str,
    owner: str,
    group: str,
    source: str,
    mode: Union[str, int] = 600,
    variables: Optional[Dict] = None,
) -> None:
    if not os.path.exists(dest):
        variables = variables or {}
        if isinstance(mode, str):
            mode = int(mode)

        if not os.path.exists(source):
            raise ConvergeError(f"Template {source} does not exist!")
        with open(source) as fr:
            contents = fr.read()

        with open(dest, "w") as fw:

            fw.write(contents.format(**variables))

    chmod(dest, mode)
    if owner and group:
        chown(dest, owner, group)


def group(group_name: str, gid: Optional[int]) -> None:
    groups = dict([(g.gr_name, g.gr_gid) for g in grp.getgrall()])
    if group_name in groups:
        # group already exists
        # TODO logging
        return
    if gid is not None:
        cmd = ["groupadd", "-g", str(gid), group_name]
    else:
        cmd = ["groupadd", group_name]
    subprocess.check_call(cmd)


def group_members(group_name: str, members: List[str], append: bool = True) -> None:
    assert append
    for member in members:
        subprocess.check_call(["usermod", "-a", "-G", group_name, member])


def user(
    user_name: str,
    comment: str,
    shell: Optional[str] = None,
    uid: Optional[int] = None,
    gid: Optional[int] = None,
) -> None:
    users = dict([(p.pw_name, p.pw_uid) for p in pwd.getpwall()])
    if user_name in users:
        return
    logging.info(comment)
    cmd = ["useradd"]
    if uid:
        cmd += ["-u", str(uid)]
    if gid:
        cmd += ["-g", str(gid)]
    if shell:
        cmd += ["-s", shell]
    subprocess.check_call(cmd + [user_name])


class guard:
    def __init__(self, path: str, content: str = "") -> None:
        self.path = path
        self.content = content

    def __enter__(self) -> "guard":
        return self

    def __exit__(
        self,
        exctype: Optional[Type[BaseException]],
        excinst: Optional[BaseException],
        exctb: Optional[TracebackType],
    ) -> bool:
        if not exctype:
            with open(self.path, "w") as fw:
                fw.write(self.content)
            return False
        return True


def directory(
    path: str,
    owner: Optional[str] = None,
    group: Optional[str] = None,
    mode: Optional[int] = None,
    recursive: bool = False,
) -> None:

    if not os.path.exists(path):
        os.makedirs(path)
    chown(path, owner, group, recursive)
    chmod(path, mode, recursive)


def create_service(
    name: str,
    exec_start: str,
    working_dir: str = "",
    user: str = "root",
) -> None:

    service_desc = f"""
[Unit]
Description={name}

[Service]
User={user}
{"WorkingDirectory="+working_dir if working_dir else ""}
ExecStart={exec_start}
Restart=always

[Install]
WantedBy=multi-user.target"""
    with open(f"/etc/systemd/system/{name}.service", "w") as fw:
        fw.write(service_desc)


def enable_service(name: str) -> None:
    execute(f"enable service {name}", command=["systemctl", "enable", name])


def start_service(name: str) -> None:
    execute(f"start service {name}", command=["systemctl", "start", name])


def restart_service(name: str) -> None:
    execute(f"restart service {name}", command=["systemctl", "restart", name])


def cron(desc: str, minute: str, command: str) -> None:
    temp_name = tempfile.mktemp(".crontab")
    try:
        with open(temp_name, "w") as fw:
            fw.write(f"# {desc}\n")
            fw.write(f"{minute} * * * * {command}\n")
        with open(temp_name) as fr:
            print("Adding crontab:")
            print(fr.read())
        subprocess.check_call(["crontab", temp_name])
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def _merge_dict(a: Dict, b: Dict) -> Dict:
    for akey, avalue in a.items():
        if isinstance(avalue, dict):
            bvalue = b.setdefault(akey, {})
            _merge_dict(avalue, bvalue)
        else:
            b[akey] = avalue

    return b


def read_node(path: str, initializer: "Initializer") -> Dict:
    with open(path) as fr:
        node = json.load(fr)

    defaults = initializer.defaults()
    if node.pop("_", {}):
        logging.warning("Purging top level key '_'")
    node["_"] = {}
    initializer.initialize(node)
    return _merge_dict(node, defaults)


class Initializer:
    def initialize(self, node: Dict) -> None:
        pass

    def defaults(self) -> Dict:
        return {}


def execute(
    desc: str,
    command: Union[str, List[str]],
    stdout: Optional[str] = None,
    retries: int = 0,
    retry_delay: int = 0,
    guard_file: Optional[str] = None,  #
) -> None:
    if guard_file and os.path.exists(guard_file):
        logging.info(f"Skipping '{desc}' because {guard_file} exists.")
        return

    logging.getLogger("audit").info(f"execute: {desc}")
    logging.info(f"execute: {desc}")
    if stdout and os.path.exists(stdout):
        return

    for attempt in range(min(0, retries) + 1):
        try:
            stdout_content = subprocess.check_output(command)
            if stdout:
                with open(stdout, "w") as fw:
                    fw.write(stdout_content.decode())
        except:
            if retries and attempt < retries:
                logging.exception(
                    f"Attempt {attempt + 1}. Sleeping {retry_delay} seconds"
                )
                time.sleep(retry_delay)
            else:
                raise
    if guard_file:
        with open(guard_file, "w") as fw:
            fw.write("")


def _waagent_service_name(platform_family: str) -> str:
    if platform_family in ["ubuntu", "debian"]:
        waagent_service_name = "walinuxagent"
    else:
        waagent_service_name = "waagent"
    return waagent_service_name


def _ensure_monitoring(platform_family: str) -> None:
    with open("/etc/waagent.conf") as fr:
        lines = fr.readlines()

    modified = False
    for i in range(len(lines)):
        line = lines[i].strip().lower()
        if re.match("^provisioning.monitorhostname=n$", line):
            lines[i] = "Provisioning.MonitorHostName=y\n"
            modified = True

    if modified:
        with open("/etc/waagent.conf.tmp", "w") as fw:
            for line in lines:
                fw.write(line)
        restart_service(_waagent_service_name(platform_family))


def _wait_for_hostname(hostname: str) -> None:
    attempts = 12
    retry_delay = 10

    for a in range(attempts):
        nslookup_stdout = _unchecked_output(["nslookup", hostname])
        if hostname in nslookup_stdout:
            return
        logging.info(f"{a}/{attempts} waiting for hostname to register in dns.")
        time.sleep(retry_delay)
    raise RuntimeError("Could not register hostname in DNS")


def _unchecked_output(cmd: List[str]) -> str:
    try:
        return subprocess.check_output(cmd).decode()
    except Exception as e:
        logging.debug(f"attempt to run {' '.join(cmd)} failed: {e}")
        return ""


def set_hostname(
    hostname: str, platform_family: str, monitor_hostname: bool = True
) -> None:
    if monitor_hostname:
        _ensure_monitoring(platform_family)
    pub_hostname_path = "/var/lib/waagent/published_hostname"

    nslookup_stdout = _unchecked_output(["nslookup", hostname])
    hostname_stdout = _unchecked_output(["hostname"])
    pub_hostname_exists = os.path.exists(pub_hostname_path)
    if (
        hostname not in nslookup_stdout
        and hostname not in hostname_stdout
        and pub_hostname_exists
    ):
        os.remove(pub_hostname_path)
        restart_service(_waagent_service_name(platform_family))

    execute("set hostname", command=["hostnamectl", "set-hostname", hostname])
    execute(
        "update hostname via jetpack",
        command=[
            "/opt/cycle/jetpack/system/embedded/bin/python",
            "-c",
            "import jetpack.converge as jc; jc._send_installation_status('warning')",
        ],
    )
