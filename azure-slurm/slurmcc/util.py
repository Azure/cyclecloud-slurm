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
import re

from . import AzureSlurmError, custom_chaos_mode


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

def visualize_block(topology_str: str, min_block_size: int, max_block_size: int = 1) -> str:
    """
    Visualizes a block topology string as ASCII art.

    Args:
        topology_str (str): The topology string (output from write_block_topology).
        max_block_size (int, optional): Maximum block size for grid visualization. Defaults to 1.
    Returns:
        str: ASCII visualization of the block topology.
    """
    block_pattern = re.compile(
        r"# Number of Nodes in block(?P<block_idx>\d+): (?P<size>\d+)\n"
        r"# ClusterUUID and CliqueID: (?P<uuid>.*)\n"
        r"(?:# Warning:.*\n){0,2}"
        r"(?P<block_line>(#)?BlockName=block\d+ Nodes=(?P<nodes>[^\n]+))"
    )
    blocks = []
    for match in block_pattern.finditer(topology_str):
        block_idx = int(match.group("block_idx"))
        size = int(match.group("size"))
        uuid = match.group("uuid").strip()
        nodes = match.group("nodes").split(",")
        block_line = match.group("block_line")
        commented = block_line.strip().startswith("#BlockName")
        blocks.append({
            "block_idx": block_idx,
            "size": size,
            "uuid": uuid,
            "nodes": nodes,
            "commented": commented,
        })

    if not blocks:
        return "# No valid blocks found in topology string.\n"

    visualizations = []
    if max_block_size <= 0:
        raise ValueError("max_block_size must be greater than 0")
    best_rows, best_cols = max_block_size, 1
    min_diff = max_block_size - 1
    for cols in range(1, max_block_size + 1):
        if max_block_size % cols == 0:
            rows = max_block_size // cols
            diff = abs(rows - cols)
            if diff < min_diff or (diff == min_diff and cols > best_cols):
                best_rows, best_cols = rows, cols
                min_diff = diff
    if best_rows < best_cols:
        best_rows, best_cols = best_cols, best_rows
    for block in blocks:
        block_idx = block["block_idx"]
        size = block["size"]
        uuid = block["uuid"]
        nodes = block["nodes"]
        commented = block["commented"]
        header = f"block {block_idx}  : # of Nodes = {size}"
        uuid_line = f"ClusterUUID + CliqueID : {uuid}"
        ineligible_line = ""
        if commented:
            ineligible_line = (
                f"** This block is ineligible for scheduling because # of nodes < min block size {min_block_size}**"
            )
        grid = []
        for r in range(best_rows):
            row = []
            for c in range(best_cols):
                idx = r * best_cols + c
                if idx < len(nodes):
                    row.append(nodes[idx])
                else:
                    row.append("X")
            grid.append(row)
        col_width = max(7, max((len(n) for n in nodes), default=2) + 2)
        sep = "|" + "|".join("-" * col_width for _ in range(best_cols)) + "|"
        grid_lines = [sep]
        for i, row in enumerate(grid):
            grid_lines.append(
                "|" + "|".join(f"{cell:^{col_width}}" for cell in row) + "|"
            )
            grid_lines.append(sep)
        visualizations.append(
            "\n".join(
                filter(
                    None,
                    [
                        header,
                        uuid_line,
                        ineligible_line,
                        "\n".join(grid_lines),
                    ],
                )
            )
        )
    return "\n\n".join(visualizations) + "\n"

def visualize_tree(topology_str: str) -> str:
    """
    Visualizes a tree topology string as ASCII art.

    Args:
        topology_str (str): The topology string (output from write_tree_topology).
    Returns:
        str: ASCII visualization of the tree topology.
    """
    switch_pattern = re.compile(
        r"# Number of Nodes in sw(?P<sw_idx>\d+): (?P<size>\d+)\n"
        r"SwitchName=sw(?P<sw_idx2>\d+) Nodes=(?P<nodes>[^\n]+)"
    )
    parent_switch_pattern = re.compile(
        r"SwitchName=sw(?P<parent_idx>\d+) Switches=(?P<children>[^\n]+)"
    )

    switches = []
    for match in switch_pattern.finditer(topology_str):
        sw_idx = int(match.group("sw_idx"))
        size = int(match.group("size"))
        nodes = match.group("nodes").split(",")
        switches.append({
            "sw_idx": sw_idx,
            "size": size,
            "nodes": nodes,
        })

    parent_switch = None
    parent_match = parent_switch_pattern.search(topology_str)
    if parent_match:
        parent_idx = int(parent_match.group("parent_idx"))
        children = parent_match.group("children").split(",")
        parent_switch = {
            "parent_idx": parent_idx,
            "children": children,
        }

    if not switches:
        return "# No valid switches found in topology string.\n"

    lines = []
    def draw_tree(parent, children, switches_dict, prefix=""):
        for i, sw in enumerate(children):
            is_last = (i == len(children) - 1)
            branch = "└── " if is_last else "├── "
            sw_idx = int(sw.replace("sw", ""))
            sw_info = switches_dict.get(sw_idx)
            if sw_info:
                lines.append(f"{prefix}{branch}Switch {sw_idx} ({sw_info['size']} nodes)")
                node_prefix = "    " if is_last else "│   "
                for j, node in enumerate(sw_info["nodes"]):
                    node_branch = "└── " if j == len(sw_info["nodes"]) - 1 else "├── "
                    lines.append(f"{prefix}{node_prefix}{node_branch}{node}")
            else:
                lines.append(f"{prefix}{branch}{sw}")

    switches_dict = {sw["sw_idx"]: sw for sw in switches}

    if parent_switch:
        lines.append(f"Switch {parent_switch['parent_idx']} (root)")
        draw_tree(parent_switch['parent_idx'], parent_switch['children'], switches_dict)
    else:
        for sw in switches:
            lines.append(f"Switch {sw['sw_idx']} ({sw['size']} nodes)")
            for j, node in enumerate(sw["nodes"]):
                node_branch = "└── " if j == len(sw["nodes"]) - 1 else "├── "
                lines.append(f"    {node_branch}{node}")

    return "\n".join(lines) + "\n"