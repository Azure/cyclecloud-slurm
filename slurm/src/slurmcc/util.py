import logging
from abc import ABC, abstractmethod
import os
import random
import subprocess as subprocesslib
import tempfile
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union

from . import AzureSlurmError, custom_chaos_mode


class SrunExitCodeException(Exception):
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"srun command failed with exit code {returncode}")
class SrunOutput:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

class NativeSlurmCLI(ABC):
    @abstractmethod
    def scontrol(self, args: List[str], retry: bool = True) -> str:
        ...

    @abstractmethod
    def srun(self, hostname: List[str], user_command: str, timeout: int) -> SrunOutput:
        ...

class NativeSlurmCLIImpl(NativeSlurmCLI):
    def scontrol(self, args: List[str], retry: bool = True) -> str:
        assert args[0] != "scontrol"
        full_args = ["scontrol"] + args
        if retry:
            return retry_subprocess(lambda: check_output(full_args)).strip()
        return check_output(full_args).strip()

    def srun(self, hostlist: List[str], user_command: str, timeout: int, shell=False) -> SrunOutput:
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            temp_file_path = temp_file.name

            try:
                command = f"bash -c '{user_command}'" if shell else user_command
                srun_command = f"srun -w {','.join(hostlist)} --error {temp_file_path} {command}"
                logging.debug(srun_command)
                result = subprocesslib.run(srun_command, check=True, timeout=timeout, shell=True,stdout=subprocesslib.PIPE, stderr=subprocesslib.PIPE, universal_newlines=True)
                return SrunOutput(returncode=result.returncode, stdout=result.stdout, stderr=None)
            except subprocesslib.CalledProcessError as e:
                with open(temp_file_path, 'r') as f:
                    stderr_content = f.read()
                raise SrunExitCodeException(returncode=e.returncode,stdout=e.stdout, stderr=stderr_content)
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

def srun(hostlist: List[str], user_command: str, timeout: int = 120) -> SrunOutput:
    assert hostlist != None
    assert user_command != None
    return SLURM_CLI.srun(hostlist, user_command, timeout=timeout)

TEST_MODE = False
def is_slurmctld_up() -> bool:
    if TEST_MODE:
        return True
    try:
        SLURM_CLI.scontrol(["ping"], retry=False)
        return True
    except Exception:
        return False


def show_nodes(node_list: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    args = ["show", "nodes"]
    if not is_autoscale_enabled():
        args.append("--future")
    if node_list:
        args.append(",".join(node_list))
    stdout = scontrol(args)
    return parse_show_nodes(stdout)


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
    nodes_str = ",".join(sorted_nodes)
    return scontrol_func(["show", "hostlist", nodes_str])


def from_hostlist(hostlist_expr: str) -> List[str]:
    """
    convert name-1,name-2,name-3,name-4,name-5 into name-[1-5]
    """
    assert isinstance(hostlist_expr, str)
    stdout = scontrol(["show", "hostnames", hostlist_expr])
    return [x.strip() for x in stdout.split()]


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