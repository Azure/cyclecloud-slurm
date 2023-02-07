import logging
import random
import subprocess as subprocesslib
import time
import traceback
from typing import Any, Callable, List, Optional, Union

from . import custom_chaos_mode

from . import CyclecloudSlurmError

def run_command(cmd: str, stdout=subprocesslib.PIPE, stderr=subprocesslib.PIPE):
    """
    run arbitrary command
    """
    cmd_list = cmd.split(' ')
    logging.debug(cmd_list)
    try:
        output = subprocesslib.run(cmd_list,stdout=stdout,stderr=stderr, check=True,
                       encoding='utf-8')
    except subprocesslib.CalledProcessError as e:
        logging.error(f"cmd: {e.cmd}, rc: {e.returncode}")
        logging.error(e.stderr)
        raise
    logging.debug(f"output: {output.stdout}")
    return output

def to_hostlist(nodes: Union[str, List[str]]) -> str:
    """
    convert name-[1-5] into name-1 name-2 name-3 name-4 name-5
    """
    if isinstance(nodes, list):
        nodes_str = ",".join(nodes)
    else:
        nodes_str = nodes

    return retry_subprocess(
        lambda: check_output(["scontrol", "show", "hostlist", nodes_str])
    ).strip()


def from_hostlist(hostlist_expr: str) -> List[str]:
    """
    convert name-1,name-2,name-3,name-4,name-5 into name-[1-5]
    """
    stdout = retry_subprocess(
        lambda: check_output(["scontrol", "show", "hostnames", hostlist_expr])
    )
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

    raise CyclecloudSlurmError(str(last_exception))


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

    raise CyclecloudSlurmError(str(last_exception))


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
