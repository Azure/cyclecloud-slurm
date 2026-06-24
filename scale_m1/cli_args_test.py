"""Tests for scale_m1 CLI argument handling: racks-vs-nodes sizing,
overprovision resolution, and the shebang/constant invariants."""
import os

import pytest

import scale_to_n_nodes
from scale_to_n_nodes import (
    NODES_PER_RACK,
    build_parser,
    mock_available,
    resolve_overprovision,
    resolve_target_count,
)


def _parse(argv):
    return build_parser().parse_args(argv)


# --- target count resolution (--racks vs -n/--target-count) ---


def test_racks_flag_sets_target_to_racks_times_18():
    args = _parse(["power_up", "--racks", "28"])
    assert resolve_target_count(args) == 28 * NODES_PER_RACK


def test_target_count_still_supported():
    args = _parse(["power_up", "--target-count", "504"])
    assert resolve_target_count(args) == 504


def test_racks_and_target_count_together_errors():
    # argparse mutually exclusive group exits with code 2.
    with pytest.raises(SystemExit):
        _parse(["power_up", "--target-count", "504", "--racks", "28"])


def test_neither_racks_nor_target_errors():
    # the group is required=True, so omitting both exits.
    with pytest.raises(SystemExit):
        _parse(["power_up"])


def test_racks_must_be_positive():
    args = _parse(["prune", "--racks", "0"])
    with pytest.raises(SystemExit):
        resolve_target_count(args)


def test_negative_target_count_errors():
    args = _parse(["prune", "--target-count", "-5"])
    with pytest.raises(SystemExit):
        resolve_target_count(args)


# --- overprovision resolution ---


def test_overprovision_racks_sets_buffer():
    args = _parse(["power_up", "--racks", "28", "--overprovision-racks", "6"])
    assert resolve_overprovision(args) == 6 * NODES_PER_RACK


def test_overprovision_nodes_supported():
    args = _parse(["power_up", "--target-count", "504", "--overprovision", "108"])
    assert resolve_overprovision(args) == 108


def test_overprovision_racks_zero_accepted():
    args = _parse(["power_up", "--racks", "28", "--overprovision-racks", "0"])
    assert resolve_overprovision(args) == 0


def test_overprovision_racks_negative_errors():
    args = _parse(["power_up", "--racks", "28", "--overprovision-racks", "-1"])
    with pytest.raises(SystemExit):
        resolve_overprovision(args)


def test_overprovision_omitted_defaults_to_zero():
    args = _parse(["power_up", "--racks", "28"])
    assert resolve_overprovision(args) == 0


def test_overprovision_negative_nodes_errors():
    args = _parse(["power_up", "--target-count", "504", "--overprovision", "-1"])
    with pytest.raises(SystemExit):
        resolve_overprovision(args)


def test_overprovision_racks_and_overprovision_together_errors():
    with pytest.raises(SystemExit):
        _parse(
            ["power_up", "--racks", "28", "--overprovision", "1", "--overprovision-racks", "1"]
        )


# --- racks supported on prune / prune_now too ---


@pytest.mark.parametrize("cmd", ["prune", "prune_now", "power_up"])
def test_racks_supported_on_all_scaling_subcommands(cmd):
    args = _parse([cmd, "--racks", "10"])
    assert resolve_target_count(args) == 10 * NODES_PER_RACK


# --- conditional --mock flag on prune ---


def test_prune_mock_flag_available_when_mock_importable():
    # In the source tree mock.py is importable, so --mock is registered.
    assert mock_available() is True
    args = _parse(["prune", "--racks", "10", "--mock"])
    assert args.mock_topology is True


def test_prune_mock_defaults_false_when_omitted():
    args = _parse(["prune", "--racks", "10"])
    assert args.mock_topology is False


def test_prune_mock_hidden_when_mock_unavailable(monkeypatch):
    monkeypatch.setattr(scale_to_n_nodes, "mock_available", lambda: False)
    with pytest.raises(SystemExit):
        _parse(["prune", "--racks", "10", "--mock"])


# --- shebang / constant invariants ---


def test_nodes_per_rack_constant_value():
    assert NODES_PER_RACK == 18


def test_round_up_to_rack_uses_constant():
    scaler = scale_to_n_nodes.NodeScaler.__new__(scale_to_n_nodes.NodeScaler)
    assert scaler.round_up_to_rack(1) == NODES_PER_RACK
    assert scaler.round_up_to_rack(NODES_PER_RACK) == NODES_PER_RACK
    assert scaler.round_up_to_rack(NODES_PER_RACK + 1) == 2 * NODES_PER_RACK


def test_shebang_uses_unversioned_python3():
    source = os.path.join(os.path.dirname(__file__), "scale_to_n_nodes.py")
    with open(source) as fh:
        first_line = fh.readline().strip()
    assert first_line.startswith("#!")
    assert first_line.endswith("/python3"), first_line
    assert "python3.11" not in first_line
