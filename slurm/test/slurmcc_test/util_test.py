from slurmcc.util import to_hostlist, get_sort_key_func
from typing import List

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