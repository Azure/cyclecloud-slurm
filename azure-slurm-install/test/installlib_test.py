from copy import deepcopy
import installlib
from installlib import CCNode
import logging
from typing import Dict
import pytest


base_software_configuration = {
    "slurm": {"nodename_as_hostname": True},
    "cyclecloud": {"hosts": {"standalone_dns": {"enabled": False}}},
}


@pytest.fixture
def mock_clock():
    yield installlib.use_mock_clock()


def _node(
    name: str,
    hostname: str,
    private_ipv4="10.1.0.5",
    status="Allocation",
    node_prefix=None,
    software_configuration=None,
) -> CCNode:
    if not software_configuration:
        software_configuration = deepcopy(base_software_configuration)
    if node_prefix:
        software_configuration["slurm"]["node_prefix"] = node_prefix

    return CCNode(
        name=name,
        nodearray_name="execute",
        hostname=hostname,
        private_ipv4="10.1.0.5",
        status=status,
        software_configuration=software_configuration or {},
    )


def test_is_valid_hostname(mock_clock) -> None:
    assert not installlib.is_valid_hostname({}, _node("node1", "random"))
    assert installlib.is_valid_hostname({}, _node("node1", "node1"))
    assert installlib.is_valid_hostname(
        {}, _node("node1", "prefix-node1", node_prefix="prefix-")
    )

    assert not installlib.is_valid_hostname(
        {}, _node("NoDe1", "prefix-NoDe1", node_prefix="prefix-")
    )
    assert installlib.is_valid_hostname(
        {}, _node("NoDe1", "prefix-node1", node_prefix="prefix-")
    )

    # let's setup a noe that should have a hostname like ip-XXXXXXX
    soft_config = deepcopy(base_software_configuration)
    soft_config["cyclecloud"]["hosts"]["standalone_dns"]["enabled"] = True
    # first - fail if it has a non ip-* hostname.
    assert not installlib.is_valid_hostname(
        {},
        _node(
            "node1",
            "prefix-node1",
            node_prefix="prefix-",
            software_configuration=soft_config,
        ),
    )
    assert installlib.is_valid_hostname(
        {},
        _node(
            "node1",
            "ip-0A010005",
            node_prefix="prefix-",
            software_configuration=soft_config,
        ),
    )

    # and lastly, make sure custom names work.
    assert installlib.is_valid_hostname(
        {"valid_hostnames": ["^justthisone$"]},
        _node(
            "node1",
            "justthisone",
            node_prefix="prefix-",
            software_configuration=soft_config,
        ),
    )

    assert not installlib.is_valid_hostname(
        {"valid_hostnames": ["^justthisone$"]},
        _node(
            "node1",
            "butnotthisone",
            node_prefix="prefix-",
            software_configuration=soft_config,
        ),
    )


def test_is_standalone_dns(mock_clock) -> None:
    soft_config = deepcopy(base_software_configuration)

    assert not installlib.is_standalone_dns(
        _node(name="node1", hostname="node1", software_configuration=soft_config)
    )
    soft_config["cyclecloud"]["hosts"]["standalone_dns"]["enabled"] = True
    assert installlib.is_standalone_dns(
        _node(name="node1", hostname="node1", software_configuration=soft_config)
    )


def test_get_ccnode(mock_clock) -> None:

    expected = CCNode(
        name="node1",
        nodearray_name="execute",
        hostname="prefix-node1",
        private_ipv4="10.1.0.5",
        status="Allocation",
        software_configuration=base_software_configuration,
    )

    cluster_status = {
        "nodes": [
            {
                "Name": "node1",
                "Template": "execute",
                "PrivateIp": "10.1.0.5",
                "Hostname": "prefix-node1",
                "Status": "Allocation",
                "Configuration": base_software_configuration,
            }
        ]
    }

    actual = installlib.get_ccnode(
        {},
        "node1",
        lambda config: cluster_status,
    )
    assert expected == actual

    try:
        installlib.get_ccnode(
            {},
            "node2",
            lambda config: cluster_status,
        )
        assert False
    except RuntimeError as e:
        assert "Node node2 not found in cluster status!" in str(e)


def test_await_node_hostname_nodename_as_hostname(mock_clock) -> None:
    """
    This is a bit of a lengthy test, but the point is to ensure that
    we continue to ask cluster status for the node until the hostname
    is correct.
    """
    soft_config = deepcopy(base_software_configuration)
    soft_config["slurm"]["node_prefix"] = "prefix-"

    class IterativeClusterStatus:
        def __init__(self):
            self.iters = 0
            self.cluster_status = {
                "nodes": [
                    {
                        "Name": "node1",
                        "Template": "execute",
                        "PrivateIp": "10.1.0.5",
                        "Hostname": "random",
                        "Status": "Allocation",
                        "Configuration": soft_config,
                    }
                ]
            }

        def __call__(self, config: Dict) -> Dict:
            """
            This is the meat of the test - we assert that
            we keep retrying until the hostname is correct.
            """
            self.iters += 1
            if self.iters == 1:
                logging.warning("Iter 1")
                return self.cluster_status
            if self.iters == 2:
                logging.warning("Iter 2")
                assert self.cluster_status["nodes"][0]["Hostname"] == "random"
                self.cluster_status["nodes"][0]["Hostname"] = "prefix-node1"
                return self.cluster_status
            raise RuntimeError(f"Reached iter {self.iters}")

    actual = installlib.await_node_hostname(
        config={},
        node_name="node1",
        timeout=300,
        cluster_status_func=IterativeClusterStatus(),
    )

    expected = CCNode(
        name="node1",
        nodearray_name="execute",
        hostname="prefix-node1",
        private_ipv4="10.1.0.5",
        status="Allocation",
        software_configuration=soft_config,
    )

    assert actual.to_dict() == expected.to_dict()