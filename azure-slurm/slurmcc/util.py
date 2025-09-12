import logging
from abc import ABC, abstractmethod
import os
import random
import subprocess as subprocesslib
import tempfile
import sys
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union
from pssh.clients.ssh import ParallelSSHClient, SSHClient
from pssh.exceptions import Timeout
import pwd
import grp
import json
from . import AzureSlurmError, custom_chaos_mode

import re
from typing import Literal
from pathlib import Path


class SrunExitCodeException(Exception):
    def __init__(self, returncode: int, stdout: str, stderr: str, stderr_content: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.stderr_content = stderr_content
        super().__init__(f"srun command failed with exit code {returncode}")
class SrunOutput:
    def __init__(self, returncode: int, stdout: str, stderr: str,):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

class NativeSlurmCLI(ABC):
    @abstractmethod
    def scontrol(self, args: List[str], retry: bool = True) -> str:
        ...

    @abstractmethod
    def srun(self, hostlist: List[str], user_command: str, timeout: int, shell: bool, partition: str, gpus: int) -> SrunOutput:
        ...

class NativeSlurmCLIImpl(NativeSlurmCLI):
    def scontrol(self, args: List[str], retry: bool = True) -> str:
        assert args[0] != "scontrol"
        full_args = ["scontrol"] + args
        if retry:
            return retry_subprocess(lambda: check_output(full_args)).strip()
        return check_output(full_args).strip()

    def srun(self, hostlist: List[str], user_command: str, timeout: int, shell: bool, partition: str, gpus: int) -> SrunOutput:
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            temp_file_path = temp_file.name

            try:
                args = []
                args.append("srun")
                if partition:
                    args.append(f"-p {partition}")
                args.append(f"-w {','.join(hostlist)}")
                if gpus:
                    args.append(f"--gpus={gpus}")
                args.append(f"--error={temp_file_path}")
                #adding deadline timeout 1 minute more than the srun timeout to avoid deadline timeout before srun can finish running
                args.append(f"--deadline=now+{timeout+1}minute")
                args.append(f"--time={timeout}")
                command = f"bash -c '{user_command}'" if shell else user_command
                args.append(command)
                srun_command = " ".join(args)
                logging.debug(srun_command)
                #subprocess timeout is in seconds, so we need to convert the timeout to seconds
                #add 3 minutes to it so it doesnt timeout before the srun command can kill the job from its own timeout
                subp_timeout=timeout*60+180
                result = subprocesslib.run(srun_command, check=True, timeout=subp_timeout, shell=True,stdout=subprocesslib.PIPE, stderr=subprocesslib.PIPE, universal_newlines=True)
                return SrunOutput(returncode=result.returncode, stdout=result.stdout, stderr=None)
            except subprocesslib.CalledProcessError as e:
                logging.error(f"Command: {srun_command} failed with return code {e.returncode}")
                with open(temp_file_path, 'r') as f:
                    stderr_content = f.read()
                    if not stderr_content.strip("\n"):
                        stderr_content = None
                raise SrunExitCodeException(returncode=e.returncode,stdout=e.stdout, stderr=e.stderr, stderr_content=stderr_content)
            except subprocesslib.TimeoutExpired:
                logging.error("Srun command timed out!")
                raise

SLURM_CLI: NativeSlurmCLI = NativeSlurmCLIImpl()


def set_slurm_cli(cli: NativeSlurmCLI) -> None:
    global SLURM_CLI
    SLURM_CLI = cli


def scontrol(args: List[str], retry: bool = True) -> str:
    assert args[0] != "scontrol"
    return SLURM_CLI.scontrol(args, retry)

def srun(hostlist: List[str], user_command: str, timeout: int = 2, shell: bool = False, partition: str = None, gpus: int = None) -> SrunOutput:
    #srun --time option is in minutes and needs atleast 1 minute to run
    assert timeout >= 1
    assert hostlist != None
    assert user_command != None
    return SLURM_CLI.srun(hostlist, user_command, timeout=timeout, shell=shell, partition=partition, gpus=gpus)

TEST_MODE = False
def is_slurmctld_up() -> bool:
    if TEST_MODE:
        return True
    try:
        SLURM_CLI.scontrol(["ping"], retry=False)
        return True
    except Exception:
        return False


UpdateT = Literal['add', 'remove', 'set']
def update_suspend_exc_nodes(action: UpdateT, nodes: str) -> None:
    assignment = "="
    if action == "set":
        assignment = "="
    elif action == "remove":
        assignment = "-="
    else:
        assignment = "+="
    scontrol(["update", f"suspendexcnodes{assignment}{nodes}"])


def get_current_suspend_exc_nodes() -> List[str]:
    lines = scontrol(["show", "config"]).splitlines()
    for line in lines:
        line = line.lower()
        if line.startswith("suspendexcnodes"):
            _, node_list = line.split("=", 1)
            return from_hostlist(node_list)
    return []

# Can be adjusted via ENV here, in case even 500 is too large for max args limits.
MAX_NODES_IN_LIST = int(os.getenv("AZSLURM_MAX_NODES_IN_LIST", 500))
def show_nodes(node_list: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    return _show_nodes(node_list, MAX_NODES_IN_LIST)


def _show_nodes(node_list: Optional[List[str]], max_nodes_in_list: int) -> List[Dict[str, Any]]:
    args = ["show", "nodes"]
    if not is_autoscale_enabled():
        args.append("--future")

    if not node_list:
        stdout = scontrol(args)
        return parse_show_nodes(stdout)
    
    # Break up names, so we don't hit max arg length limits.
    ret = []
    for x in range(0, len(node_list), MAX_NODES_IN_LIST):
        sub_list = node_list[x: x + MAX_NODES_IN_LIST]
        if sub_list:
            sub_args = args + [",".join(sub_list)]
            stdout = scontrol(sub_args)
            ret.extend(parse_show_nodes(stdout))
    return ret


def parse_show_nodes(stdout: str) -> List[Dict[str, Any]]:
    ret = []
    current_node = None
    for line in stdout.splitlines():
        line = line.strip()

        for sub_expr in line.split():
            if "=" not in sub_expr:
                continue
            key, value = sub_expr.split("=", 1)
            if key == "NodeName":
                if current_node:
                    ret.append(current_node)
                current_node = {}
            assert current_node is not None
            current_node[key] = value
    if current_node:
        ret.append(current_node)
    return ret


def to_hostlist(nodes: Union[str, List[str]], scontrol_func: Callable=scontrol) -> str:
    return _to_hostlist(nodes, scontrol_func=scontrol, max_nodes_in_list=MAX_NODES_IN_LIST)


def _to_hostlist(nodes: Union[str, List[str]], scontrol_func: Callable=scontrol, max_nodes_in_list: int=MAX_NODES_IN_LIST) -> str:
    """
    convert name-[1-5] into name-1 name-2 name-3 name-4 name-5
    """
    assert nodes
    for n in nodes:
        assert n
    
    if isinstance(nodes, list):
        nodes_str = ",".join(nodes)
    else:
        nodes_str = nodes
    # prevent poor sorting of nodes and getting node lists like htc-1,htc-10-19, htc-2, htc-20-29 etc
    sorted_nodes = sorted(nodes_str.split(","), key=get_sort_key_func(is_hpc=False))
    ret = []
    for i in range(0, len(sorted_nodes), max_nodes_in_list):

        nodes_str = ",".join(sorted_nodes[i: i + max_nodes_in_list])
        ret.append(scontrol_func(["show", "hostlist", nodes_str]))
    return ",".join(ret)


def from_hostlist(hostlist_expr: str) -> List[str]:
    return _from_hostlist(hostlist_expr, MAX_NODES_IN_LIST)


def _from_hostlist(hostlist_expr: str, max_nodes_in_list: int) -> List[str]:
    """
    convert name-1,name-2,name-3,name-4,name-5 into name-[1-5]
    """
    assert isinstance(hostlist_expr, str)

    sub_exprs = hostlist_expr.split(",")
    ret = []
    for i in range(0, len(sub_exprs), max_nodes_in_list):
        sub_expr = ",".join(sub_exprs[i: i + max_nodes_in_list])
        if not sub_expr:
            continue
        stdout = scontrol(["show", "hostnames", sub_expr])
        ret.extend([x.strip() for x in stdout.split()])
    return ret


def run(args: list, stdout=subprocesslib.PIPE, stderr=subprocesslib.PIPE, timeout=120, shell=False, check=True, universal_newlines=True, **kwargs):
    """
    run arbitrary command through subprocess.run with some sensible defaults.
    Standard streams are defaulted to subprocess stdout/stderr pipes.
    Encoding defaulted to string
    Timeout defaulted to 2 minutes.
    """
    try:
        output = subprocesslib.run(args=args, stdout=stdout, stderr=stderr, timeout=timeout, shell=shell, check=check, universal_newlines=universal_newlines, **kwargs)
    except subprocesslib.CalledProcessError as e:
        logging.error(f"cmd: {e.cmd}, rc: {e.returncode}")
        logging.error(e.stderr)
        raise
    except subprocesslib.TimeoutExpired as t:
        logging.error("Timeout Expired")
        raise
    except Exception as e:
        logging.error(e)
        raise
    return output

def run_parallel_cmd(hosts, cmd):
    """
    Run a command in parallel on a list of hosts using SSH as an interactive user from the 'cyclecloud' group.
    This function determines the first interactive user (i.e., a user with a valid login shell) in the 'cyclecloud' group,
    then uses their SSH private key to connect to the specified hosts and execute the given command in parallel.
        hosts (list): List of hostnames to connect to.
        cmd (str): Command to execute on each host.
    Returns:
        output: Result from ParallelSSHClient.run_command.
    Raises:
        ValueError: If the 'cyclecloud' group does not exist or no interactive user is found in the group.
        TimeoutError: If the command execution times out.
        Exception: For other errors encountered during execution.
    """
    def get_group_users(group_name):
        try:
            group_info = grp.getgrnam(group_name)
        except KeyError:
            raise ValueError(f"Group '{group_name}' not found.")

        return group_info.gr_mem

    def user_has_login_shell(username):
        try:
            pw_entry = pwd.getpwnam(username)
            shell = pw_entry.pw_shell
            if shell.endswith('nologin') or shell.endswith('false'):
                return False
            return True
        except KeyError:
            # user entry not found in /etc/passwd
            return False
    try:
        group_name = "cyclecloud"
        users_in_group = get_group_users(group_name)
        interactive_users = [user for user in users_in_group if user_has_login_shell(user)]
        user = interactive_users[0] if interactive_users else None
        if not user:
            raise ValueError(f"No interactive user found in group '{group_name}'.")
        pw_record = pwd.getpwnam(user)
        home_dir = pw_record.pw_dir
        client_kwargs = {"pkey": f"{home_dir}/.ssh/id_rsa"}
        client_kwargs["user"] = user
        client_kwargs["timeout"] = 300
        client = ParallelSSHClient(hosts, **client_kwargs)
        logging.getLogger("pssh").setLevel(logging.ERROR)
        output = client.run_command(cmd)
        client.join(output, timeout=300)
        return output
    except Timeout as te:
        raise Timeout(f"Command timed out: {cmd}. Error: {str(te)}")
    except Exception as e:
        raise Exception(f"Error running command: {cmd}: {str(e)}")
    
def output_block_nodelist(topology_input, table=False):
    """
    Parse a topology file or string and output node information.
    
    Args:
        topology_input: Either a file path (str) or topology content (str)
        table: If True, output in tabular format; if False, output as JSON
    
    Returns:
        If table=False: JSON string of blocks sorted by size
        If table=True: string in tabular format with block names, sizes, and node lists
    """

    # Read content from file or use string directly
    if Path(topology_input).exists():
        with open(topology_input, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = topology_input

    # Check if it's a block topology
    if 'BlockName=' not in content:
        raise ValueError("Input is not a block topology format")

    # Parse blocks
    blocks = []
    lines = content.strip().split('\n')

    for line in lines:
        # Skip comments and empty lines
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Parse BlockName lines
        if line.startswith('BlockName='):
            # Extract block name and nodes
            match = re.match(r'BlockName=([\w-]+)\s+Nodes=(.+)', line)
            if match:
                block_name = match.group(1)
                nodes_str = match.group(2)
                nodelist = [node.strip() for node in nodes_str.split(',')]

                blocks.append({
                    'blockname': block_name,
                    'size': len(nodelist),
                    'nodelist': nodelist
                })

    # Sort blocks by size (smallest to largest)
    blocks.sort(key=lambda x: x['size'])

    if not table:
        # Return JSON format
        return json.dumps(blocks, indent=2)
    else:
        # Print tabular format
        if not blocks:
            print("No blocks found in topology")
            return

        # Calculate column widths
        max_blockname = max(len(b['blockname']) for b in blocks)
        max_blockname = max(max_blockname, len("Block Name"))
        lines = []
        # Header
        lines.append(f"{'Block Name':<{max_blockname}} | {'Size':>6} | {'Nodes'}")
        lines.append(f"{'-' * max_blockname}-+-{'-' * 8}-+-{'-' * 50}")

        # Data rows
        for block in blocks:
            nodes_str = ', '.join(block['nodelist'])
            # Truncate long node lists for display
            if len(nodes_str) > 50:
                nodes_str = nodes_str[:47] + '...'
            lines.append(f"{block['blockname']:<{max_blockname}} | {block['size']:>6} | {nodes_str}")

        # Summary
        lines.append(f"\nTotal blocks: {len(blocks)}")
        lines.append(f"Total nodes: {sum(b['size'] for b in blocks)}")

        return "\n".join(lines) + "\n"
    

def retry_rest(func: Callable, attempts: int = 5) -> Any:
    attempts = max(1, attempts)
    last_exception = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            logging.debug(traceback.format_exc())

            time.sleep(attempt * attempt)

    raise AzureSlurmError(str(last_exception))


def retry_subprocess(func: Callable, attempts: int = 5) -> Any:
    attempts = max(1, attempts)
    last_exception: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            logging.debug(traceback.format_exc())
            logging.warning("Command failed, retrying: %s", str(e))
            time.sleep(attempt * attempt)

    raise AzureSlurmError(str(last_exception))


def check_output(args: List[str], **kwargs: Any) -> str:
    ret = _SUBPROCESS_MODULE.check_output(args=args, **kwargs)
    if not isinstance(ret, str):
        ret = ret.decode()
    return ret


def _raise_proc_exception() -> Any:
    def called_proc_exception(msg: str) -> Any:
        raise subprocesslib.CalledProcessError(1, msg)

    choice: Callable = random.choice([OSError, called_proc_exception])  # type: ignore
    raise choice("Random failure")


class SubprocessModuleWithChaosMode:
    @custom_chaos_mode(_raise_proc_exception)
    def check_call(self, *args, **kwargs):  # type: ignore
        return subprocesslib.check_call(*args, **kwargs)

    @custom_chaos_mode(_raise_proc_exception)
    def check_output(self, *args, **kwargs):  # type: ignore
        return subprocesslib.check_output(*args, **kwargs)

_SUBPROCESS_MODULE = SubprocessModuleWithChaosMode()


def get_sort_key_func(is_hpc: bool) -> Callable[[str], Union[str, int]]:
    return _node_index_and_pg_as_sort_key if is_hpc else _node_index_as_sort_key


def _node_index_as_sort_key(nodename: str) -> Union[str, int]:
    """
    Used to get the key to sort names that don't have name-pg#-# format
    """
    try:
        return int(nodename.split("-")[-1])
    except Exception:
        return int.from_bytes(nodename.encode(), byteorder="little")


def _node_index_and_pg_as_sort_key(nodename: str) -> Union[str, int]:
    """
    Used to get the key to sort names that have name-pg#-# format
    """
    try:
        node_index = int(nodename.split("-")[-1])
        pg = int(nodename.split("-")[-2].replace("pg", "")) * 100000
        return pg + node_index
    except Exception:
        return nodename


_IS_AUTOSCALE_ENABLED = None


def is_autoscale_enabled() -> bool:
    global _IS_AUTOSCALE_ENABLED
    if _IS_AUTOSCALE_ENABLED is not None:
        return _IS_AUTOSCALE_ENABLED
    try:
        with open("/etc/slurm/slurm.conf") as fr:
            lines = fr.readlines()
    except Exception:
        _IS_AUTOSCALE_ENABLED = True
        return _IS_AUTOSCALE_ENABLED

    for line in lines:
        line = line.strip()
        # this can be defined more than once
        if line.startswith("SuspendTime ") or line.startswith("SuspendTime="):
            suspend_time = line.split("=")[1].strip().split()[0]
            try:
                if suspend_time in ["NONE", "INFINITE"] or int(suspend_time) < 0:
                    _IS_AUTOSCALE_ENABLED = False
                else:
                    _IS_AUTOSCALE_ENABLED = True
            except Exception:
                pass

    if _IS_AUTOSCALE_ENABLED is not None:
        return _IS_AUTOSCALE_ENABLED
    logging.warning("Could not determine if autoscale is enabled. Assuming yes")
    return True