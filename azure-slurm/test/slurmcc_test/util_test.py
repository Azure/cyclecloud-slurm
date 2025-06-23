from slurmcc.util import to_hostlist, get_sort_key_func, run, _show_nodes, set_slurm_cli, _from_hostlist
from slurmcc_test.testutil import MockNativeSlurmCLI
from typing import List
import subprocess

def scontrol_func(args: List[str], retry: bool = True) -> str:
    if len(args) < 2:
        raise RuntimeError()
    if args[0:2] == ["show", "hostlist"]:
        return fake_to_hostlist(args[2])
    

def fake_to_hostlist(expr: str) -> str:
    """
    this function will take a list of nodes like name-[1-5],other and convert it into a comma separated list of nodes
    like name-1,name-2,name-3,name-4,name-5,other
    """
    if not expr:
        return ""
    nodes = expr.split(",")
    ret = []
    for node in nodes:
        if "[" in node:
            prefix = node[0: node.index("[")]
            first, last = node.replace("]", "").split("[")[1].split("-")[0:2]
            ret.extend([f"{prefix}{i}" for i in range(int(first), int(last) + 1)])
        else:
            ret.append(node)
    return ",".join(ret)


def test_get_sort_key_func() -> None:
    assert ["name-1", "dyn"] == sorted(["name-1","dyn"], key=get_sort_key_func(is_hpc=False))
    assert ["dyna", "dynb"] == sorted(["dyna","dynb"], key=get_sort_key_func(is_hpc=False))


def test_to_hostlist() -> None:
    assert "name-1,dyn" == to_hostlist(["name-1","dyn"], scontrol_func)
    assert "name-1,dyn" == to_hostlist(["dyn","name-1"], scontrol_func)

def test_run_function() -> None:
    out = run(['ls', '-l'], shell=True)
    assert out.returncode == 0

    out = run(['cat', '/proc/loadavg'], shell=False)
    assert out.returncode == 0

    # test case for permissions errors
    try:
        out=run(['touch', '/root/.test'])
    except subprocess.CalledProcessError as e:
        assert out.returncode != 0


def test_show_nodes() -> None:
    cli = MockNativeSlurmCLI()
    node_list = ["htc-1", "htc-2", "htc-3", "htc-4"]
    set_slurm_cli(cli)
    cli.create_nodes(node_list, ["cloud"], ["htc"])
    complete = _show_nodes(node_list, 4)
    split = _show_nodes(node_list, 2)
    assert split == complete


def test_from_hostlist() -> None:
    cli = MockNativeSlurmCLI()
    node_list = ["htc-1", "htc-2", "htc-3", "htc-4"]
    set_slurm_cli(cli)
    def simple_scontrol(args, ignore):
        assert args[0] == "show"
        assert args[1] == "hostnames"
        if args[2] == "htc-1,htc-2":
            return "htc-[1-2]"
        if args[2] == "htc-3,htc-4":
            return "htc-[3-4]"
        if args[2] == "htc-1,htc-2,htc-3,htc-4":
            return "htc-[1-4]"
        raise RuntimeError(args)
        
    
    cli.create_nodes(node_list, ["cloud"], ["htc"])
    cli.scontrol = simple_scontrol
    complete = _from_hostlist(",".join(node_list), 4)
    split = _from_hostlist(",".join(node_list), 2)
    assert split != complete
    assert complete == ["htc-[1-4]"]
    assert split == ["htc-[1-2]", "htc-[3-4]"]