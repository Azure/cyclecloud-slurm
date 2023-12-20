import logging
from abc import ABC, abstractmethod
import random
import subprocess as subprocesslib
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union

from . import AzureSlurmError, custom_chaos_mode


class NativeSlurmCLI(ABC):
    @abstractmethod
    def scontrol(self, args: List[str], retry: bool = True) -> str:
        ...


class NativeSlurmCLIImpl(NativeSlurmCLI):
    def scontrol(self, args: List[str], retry: bool = True) -> str:
        assert args[0] != "scontrol"
        full_args = ["scontrol"] + args
        if retry:
            return retry_subprocess(lambda: check_output(full_args)).strip()
        return check_output(full_args).strip()


SLURM_CLI: NativeSlurmCLI = NativeSlurmCLIImpl()


def set_slurm_cli(cli: NativeSlurmCLI) -> None:
    global SLURM_CLI
    SLURM_CLI = cli


def scontrol(args: List[str], retry: bool = True) -> str:
    assert args[0] != "scontrol"
    return SLURM_CLI.scontrol(args, retry)


def is_slurmctld_up() -> bool:
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

    ret.append(current_node)
    return ret


def to_hostlist(nodes: Union[str, List[str]]) -> str:
    """
    convert name-[1-5] into name-1 name-2 name-3 name-4 name-5
    """
    if isinstance(nodes, list):
        nodes_str = ",".join(nodes)
    else:
        nodes_str = nodes

    return scontrol(["show", "hostlist", nodes_str])


def from_hostlist(hostlist_expr: str) -> List[str]:
    """
    convert name-1,name-2,name-3,name-4,name-5 into name-[1-5]
    """
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
        return nodename


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


def is_autoscale_enabled(subprocess_module: Optional[Any] = None) -> bool:
    global _IS_AUTOSCALE_ENABLED
    if _IS_AUTOSCALE_ENABLED is not None:
        return _IS_AUTOSCALE_ENABLED
    if subprocess_module is None:
        import subprocess as subprocess_module_tmp

        subprocess_module = subprocess_module_tmp

    try:
        lines = (
            subprocess_module.check_output(["scontrol", "show", "config"])
            .decode()
            .strip()
            .splitlines()
        )
    except Exception:
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