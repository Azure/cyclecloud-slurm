from copy import deepcopy
from http.server import BaseHTTPRequestHandler, HTTPServer
import installlib
from installlib import CCNode
import json
import logging
import ssl
import subprocess
from threading import Thread
from typing import Dict
from urllib.error import URLError
import pytest


base_software_configuration = {
    "slurm": {"nodename_as_hostname": True},
    "cyclecloud": {"hosts": {"standalone_dns": {"enabled": False}}},
}


@pytest.fixture
def mock_clock():
    yield installlib.use_mock_clock()


@pytest.fixture(scope="module")
def tls_certificates(tmpdir_factory):
    directory = tmpdir_factory.mktemp("cluster-status-tls")
    openssl_config = directory.join("openssl.cnf")
    openssl_config.write(
        "[req]\n"
        "distinguished_name = subject\n"
        "x509_extensions = extensions\n"
        "prompt = no\n"
        "[subject]\n"
        "CN = cyclecloud.test\n"
        "[extensions]\n"
        "basicConstraints = critical,CA:TRUE\n"
        "keyUsage = critical,digitalSignature,keyEncipherment,keyCertSign\n"
        "extendedKeyUsage = serverAuth\n"
        "subjectAltName = IP:127.0.0.1\n"
        "subjectKeyIdentifier = hash\n"
        "authorityKeyIdentifier = keyid:always\n"
    )
    certificates = {}
    for name in ("server", "untrusted"):
        cert = directory.join(f"{name}.pem")
        key = directory.join(f"{name}.key")
        subprocess.check_output(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-config",
                str(openssl_config),
                "-keyout",
                str(key),
                "-out",
                str(cert),
            ],
            stderr=subprocess.STDOUT,
        )
        certificates[name] = (cert, key)
    return certificates


@pytest.fixture
def jetpack_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(installlib, "jetpack_home", lambda: str(tmp_path))
    connection_file = tmp_path / "config" / "connection.json"
    connection_file.parent.mkdir()
    return connection_file


@pytest.fixture
def cluster_status_https(tls_certificates, tmpdir, monkeypatch, jetpack_connection):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            body = b'{"nodes": [{"Name": "node1"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    cert, key = tls_certificates["server"]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever)
    # Isolate trust and proxy settings from the developer's environment.
    monkeypatch.setenv("SSL_CERT_FILE", str(tls_certificates["untrusted"][0]))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmpdir.mkdir("empty-ca-directory")))
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    jetpack_connection.write_text(json.dumps({
        "url": f"https://127.0.0.1:{server.server_port}/",
        "username": "user",
        "password": "password",
    }))
    config = {
        "cyclecloud": {
            "config": {
                # Jetpack connection details must take precedence.
                "web_server": "https://127.0.0.1:0/",
                "username": "legacy-user",
                "password": "legacy-password",
                "cert": tls_certificates["untrusted"][0].read(),
            },
            "cluster": {"name": "test cluster"},
        }
    }
    thread.start()
    try:
        yield config, requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("skip_validation", [False, True])
def test_cluster_status_trusted_certificate(
    cluster_status_https, tls_certificates, jetpack_connection, skip_validation
) -> None:
    config, requests = cluster_status_https
    connection = json.loads(jetpack_connection.read_text())
    connection["cert"] = tls_certificates["server"][0].read()
    connection["url"] = connection["url"].replace("127.0.0.1", "localhost")
    jetpack_connection.write_text(json.dumps(connection))
    config["cyclecloud"]["skip_ssl_validation"] = skip_validation

    assert installlib.cluster_status(config) == {"nodes": [{"Name": "node1"}]}
    assert requests == [
        ("/clusters/test%20cluster/nodes", "Basic dXNlcjpwYXNzd29yZA==")
    ]


@pytest.mark.parametrize("skip_validation", [False, True])
def test_cluster_status_untrusted_certificate(
    cluster_status_https, tls_certificates, jetpack_connection, skip_validation
) -> None:
    config, requests = cluster_status_https
    connection = json.loads(jetpack_connection.read_text())
    connection["cert"] = tls_certificates["untrusted"][0].read()
    jetpack_connection.write_text(json.dumps(connection))
    config["cyclecloud"]["config"]["cert"] = tls_certificates["server"][0].read()
    config["cyclecloud"]["skip_ssl_validation"] = skip_validation

    with pytest.raises(URLError) as exc:
        installlib.cluster_status(config)
    assert isinstance(exc.value.reason, ssl.SSLCertVerificationError)
    assert requests == []


@pytest.mark.parametrize("cert_config", [{}, {"cert": None}])
@pytest.mark.parametrize("skip_validation", [None, False, True])
def test_cluster_status_without_certificate(
    cluster_status_https, jetpack_connection, cert_config, skip_validation
) -> None:
    config, requests = cluster_status_https
    connection = json.loads(jetpack_connection.read_text())
    connection.update(cert_config)
    jetpack_connection.write_text(json.dumps(connection))
    if skip_validation is not None:
        config["cyclecloud"]["skip_ssl_validation"] = skip_validation

    if skip_validation:
        assert installlib.cluster_status(config) == {"nodes": [{"Name": "node1"}]}
        assert len(requests) == 1
    else:
        with pytest.raises(URLError) as exc:
            installlib.cluster_status(config)
        assert isinstance(exc.value.reason, ssl.SSLCertVerificationError)
        assert requests == []


@pytest.mark.parametrize("connection_state", ["missing", "empty"])
@pytest.mark.parametrize("skip_validation", [None, False, True])
def test_cluster_status_legacy_connection(
    cluster_status_https, tls_certificates, jetpack_connection,
    connection_state, skip_validation
) -> None:
    config, requests = cluster_status_https
    connection = json.loads(jetpack_connection.read_text())
    config["cyclecloud"]["config"] = {
        "web_server": connection["url"],
        "username": connection["username"],
        "password": connection["password"],
        # A legacy certificate must not be used as Jetpack trust material.
        "cert": tls_certificates["server"][0].read(),
    }
    if connection_state == "missing":
        jetpack_connection.unlink()
    else:
        jetpack_connection.write_text("{}")
    if skip_validation is not None:
        config["cyclecloud"]["skip_ssl_validation"] = skip_validation

    if skip_validation:
        assert installlib.cluster_status(config) == {"nodes": [{"Name": "node1"}]}
        assert requests == [
            ("/clusters/test%20cluster/nodes", "Basic dXNlcjpwYXNzd29yZA==")
        ]
    else:
        with pytest.raises(URLError) as exc:
            installlib.cluster_status(config)
        assert isinstance(exc.value.reason, ssl.SSLCertVerificationError)
        assert requests == []


def test_cluster_status_default_trust_store(
    cluster_status_https, tls_certificates, monkeypatch
) -> None:
    config, requests = cluster_status_https
    monkeypatch.setenv("SSL_CERT_FILE", str(tls_certificates["server"][0]))

    assert installlib.cluster_status(config) == {"nodes": [{"Name": "node1"}]}
    assert len(requests) == 1


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