# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import pytest
from charm import GNBSIMOperatorCharm
from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ChangeError

MULTUS_LIB = "charms.kubernetes_charm_libraries.v0.multus.KubernetesMultusCharmLib"
GNB_IDENTITY_PROVIDES = "charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity.GnbIdentityProvides"
NAMESPACE = "whatever"

def read_file(path: str) -> str:
    """Read a file and returns as a string.

    Args:
        path (str): path to the file.

    Returns:
        str: content of the file.
    """
    with open(path, "r") as f:
        content = f.read()
    return content

def create_n2_relation(harness) -> int:
    """Create a relation between gnbsim and AMF.

    Returns:
        int: Id of the created relation
    """
    amf_relation_id = harness.add_relation(relation_name="fiveg-n2", remote_app="amf")
    harness.add_relation_unit(relation_id=amf_relation_id, remote_unit_name="amf/0")
    return amf_relation_id

def set_n2_relation_data(harness) -> int:
    """Create the N2 relation, sets the relation data in the n2 relation and returns its ID.

    Returns:
        int: ID of the created relation
    """
    amf_relation_id = create_n2_relation(harness)
    harness.update_relation_data(
        relation_id=amf_relation_id,
        app_or_unit="amf",
        key_values={
            "amf_hostname": "amf",
            "amf_port": "38412",
            "amf_ip_address": "1.1.1.1",
        },
    )
    return amf_relation_id

def set_up_active_status_charm(harness):
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    harness.set_can_connect(container="gnbsim", val=True)
    set_n2_relation_data(harness)
    harness.evaluate_status()
    assert harness.charm.unit.status == ActiveStatus()


@pytest.fixture
def harness(mocker):
    mocker.patch("lightkube.core.client.GenericSyncClient")
    mocker.patch("charm.KubernetesServicePatch")
    mocker.patch(f"{MULTUS_LIB}.is_ready", return_value=True)
    harness = testing.Harness(GNBSIMOperatorCharm)
    harness.set_model_name(name=NAMESPACE)
    harness.begin()
    yield harness
    harness.cleanup()


@pytest.mark.parametrize("config_param", [("usim-opc"),
                                        ("gnb-ip-address"),
                                        ("icmp-packet-destination"),
                                        ("imsi"),
                                        ("mcc"),
                                        ("mnc"),
                                        ("usim-key"),
                                        ("usim-sequence-number"),
                                        ("sd"),
                                        ("tac"),
                                        ("upf-subnet"),
                                        ("upf-gateway")])
def test_given_invalid_config_when_config_changed_then_status_is_blocked(harness, config_param):
    harness.update_config(key_values={config_param: ""})
    harness.evaluate_status()

    assert harness.charm.unit.status == BlockedStatus(
                                            f"Configurations are invalid: ['{config_param}']"
                                        )

def test_given_cant_connect_to_workload_when_config_changed_then_status_is_waiting(harness):
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    set_n2_relation_data(harness)
    harness.set_can_connect(container="gnbsim", val=False)

    harness.update_config(key_values={})
    harness.evaluate_status()

    assert harness.charm.unit.status == WaitingStatus("Waiting for container to be ready")

def test_given_storage_not_attached_when_config_changed_then_status_is_waiting(harness):
    harness.handle_exec("gnbsim", [], result=0)
    harness.set_can_connect(container="gnbsim", val=True)
    set_n2_relation_data(harness)

    harness.update_config(key_values={})
    harness.evaluate_status()

    assert harness.charm.unit.status == WaitingStatus("Waiting for storage to be attached")

def test_given_multus_not_ready_when_config_changed_then_status_is_waiting(harness, mocker):
    mocker.patch(f"{MULTUS_LIB}.is_ready", return_value=False)
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    harness.set_can_connect(container="gnbsim", val=True)

    create_n2_relation(harness)

    harness.update_config(key_values={})
    harness.evaluate_status()

    assert harness.charm.unit.status == WaitingStatus("Waiting for Multus to be ready")

def test_given_n2_relation_not_created_when_config_changed_then_status_is_blocked(harness):
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    harness.set_can_connect(container="gnbsim", val=True)

    harness.update_config(key_values={})
    harness.evaluate_status()

    assert harness.charm.unit.status == BlockedStatus("Waiting for N2 relation to be created")

def test_given_active_status_when_n2_relation_breaks_then_status_is_blocked(harness):
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    harness.set_can_connect(container="gnbsim", val=True)
    n2_relation_id = set_n2_relation_data(harness)
    harness.evaluate_status()

    harness.remove_relation(n2_relation_id)
    harness.evaluate_status()

    assert harness.charm.unit.status == BlockedStatus("Waiting for N2 relation to be created")

def test_given_n2_information_not_available_when_config_changed_then_status_is_waiting(harness):
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    harness.set_can_connect(container="gnbsim", val=True)
    create_n2_relation(harness)

    harness.update_config(key_values={})
    harness.evaluate_status()

    assert harness.charm.unit.status == WaitingStatus("Waiting for N2 information")

def test_given_default_config_and_n2_info_when_config_changed_then_config_is_written_to_workload(
    harness,
):
    set_up_active_status_charm(harness)
    root = harness.get_filesystem_root("gnbsim")

    harness.update_config(key_values={})

    expected_config_file_content = read_file("tests/unit/expected_config.yaml")
    assert (root / "etc/gnbsim/gnb.conf").read_text() == expected_config_file_content


def test_given_default_config_and_n2_info_available_when_n2_relation_joined_then_config_is_written_to_workload(  # noqa: E501
    harness,
):
    set_up_active_status_charm(harness)
    root = harness.get_filesystem_root("gnbsim")

    expected_config_file_content = read_file("tests/unit/expected_config.yaml")
    assert (root / "etc/gnbsim/gnb.conf").read_text() == expected_config_file_content


def test_given_n2_relation_storage_attached_and_can_connect_when_config_changed_then_status_is_active(  # noqa: E501
    harness
):
    set_up_active_status_charm(harness)

    harness.update_config(key_values={})
    harness.charm.on.update_status.emit()

    assert harness.charm.unit.status == ActiveStatus()

def test_given_default_config_when_config_changed_then_upf_route_is_created(harness):
    harness.add_storage("config", attach=True)
    upf_subnet = "1.1.0.0/16"
    upf_gateway = "2.2.2.2"

    ip_route_called = False
    timeout = 0
    ip_route_cmd = ["ip", "route", "replace", upf_subnet, "via", upf_gateway]

    def ip_route_handler(args: testing.ExecArgs) -> testing.ExecResult:
        nonlocal ip_route_called
        nonlocal timeout
        ip_route_called = True
        timeout = args.timeout
        return testing.ExecResult()

    harness.handle_exec("gnbsim", ip_route_cmd, handler=ip_route_handler)
    harness.handle_exec("gnbsim", [], result=0)

    harness.set_can_connect(container="gnbsim", val=True)

    set_n2_relation_data(harness)

    harness.update_config(
        key_values={
            "upf-subnet": upf_subnet,
            "upf-gateway": upf_gateway,
        }
    )

    assert ip_route_called
    assert timeout == 300

def test_given_cant_connect_to_workload_when_start_simulation_action_then_event_fails(
    harness, mocker
):
    event = mocker.Mock()
    harness.set_can_connect(container="gnbsim", val=False)

    harness.charm._on_start_simulation_action(event=event)

    event.fail.assert_called_once_with(message="Container is not ready")


def test_given_config_file_not_written_when_start_simulation_action_then_event_fails(
    harness, mocker
):
    event = mocker.Mock()
    harness.set_can_connect(container="gnbsim", val=True)
    harness.add_storage("config", attach=True)

    harness.charm._on_start_simulation_action(event=event)

    event.fail.assert_called_with(message="Config file is not written")

def test_given_simulation_command_fails_with_execerror_when_start_simulation_action_then_event_fails(  # noqa: E501
    harness, mocker
):
    harness.add_storage("config", attach=True)
    root = harness.get_filesystem_root("gnbsim")
    (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
    stderr = "whatever stderr content"
    event = mocker.Mock()

    def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
        return testing.ExecResult(stderr=stderr, exit_code=1)

    harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
    harness.set_can_connect(container="gnbsim", val=True)

    harness.charm._on_start_simulation_action(event=event)

    event.fail.assert_called_with(message=f"Failed to execute simulation: {stderr}")

def test_given_simulation_command_fails_with_changeerror_when_start_simulation_action_then_event_fails(  # noqa: E501
    harness, mocker
):
    harness.add_storage("config", attach=True)
    root = harness.get_filesystem_root("gnbsim")
    (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
    error = "whatever error content"
    event = mocker.Mock()

    def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
        raise ChangeError(err=error, change=None)  # type: ignore[arg-type]

    harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
    harness.set_can_connect(container="gnbsim", val=True)

    harness.charm._on_start_simulation_action(event=event)

    event.fail.assert_called_with(message=f"Failed to execute simulation: {error}")

def test_given_no_stderr_when_start_simulation_action_then_event_fails(harness, mocker):
    harness.add_storage("config", attach=True)
    root = harness.get_filesystem_root("gnbsim")
    (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
    event = mocker.Mock()
    harness.handle_exec("gnbsim", ["/bin/gnbsim"], result=0)
    harness.set_can_connect(container="gnbsim", val=True)

    harness.charm._on_start_simulation_action(event=event)

    event.fail.assert_called_with(message="No output in simulation")

def test_given_simulation_fails_when_start_simulation_action_then_simulation_result_is_false(
    harness, mocker
):
    harness.add_storage("config", attach=True)
    root = harness.get_filesystem_root("gnbsim")
    (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
    event = mocker.Mock()

    def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
        return testing.ExecResult(
            stdout="whatever stdout",
            stderr="Profile Status: FAILED",
        )

    harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
    harness.set_can_connect(container="gnbsim", val=True)

    harness.charm._on_start_simulation_action(event=event)

    event.set_results.assert_called_with(
        {"success": "false", "info": "run juju debug-log to get more information."}
    )

def test_given_can_connect_to_workload_when_start_simulation_action_then_simulation_is_started(
    harness, mocker
):
    harness.add_storage("config", attach=True)
    root = harness.get_filesystem_root("gnbsim")
    (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
    event = mocker.Mock()

    gnbsim_called = False
    timeout = 0
    gnbsim_cmd = ["/bin/gnbsim", "--cfg", "/etc/gnbsim/gnb.conf"]

    def gnbsim_handler(args: testing.ExecArgs) -> testing.ExecResult:
        nonlocal gnbsim_called
        nonlocal timeout
        gnbsim_called = True
        timeout = args.timeout
        return testing.ExecResult(
            stdout="Whatever stdout",
            stderr="Whatever stderr",
        )

    harness.handle_exec("gnbsim", gnbsim_cmd, handler=gnbsim_handler)
    harness.set_can_connect(container="gnbsim", val=True)

    harness.charm._on_start_simulation_action(event=event)

    assert gnbsim_called
    assert timeout == 300

def test_given_simulation_succeeds_when_start_simulation_action_then_simulation_result_is_true(
    harness, mocker
):
    harness.add_storage("config", attach=True)
    root = harness.get_filesystem_root("gnbsim")
    (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
    event = mocker.Mock()

    def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
        return testing.ExecResult(
            stdout="whatever stdout",
            stderr="Profile Status: PASS",
        )

    harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
    harness.set_can_connect(container="gnbsim", val=True)

    harness.charm._on_start_simulation_action(event=event)

    event.set_results.assert_called_with(
        {"success": "true", "info": "run juju debug-log to get more information."}
    )

def test_given_default_config_when_network_attachment_definitions_from_config_is_called_then_no_interface_specified_in_nad(  # noqa: E501
    harness
):
    harness.disable_hooks()
    harness.update_config(
        key_values={
            "gnb-ip-address": "192.168.251.5",
        }
    )
    nad = harness.charm._network_attachment_definitions_from_config()
    config = json.loads(nad[0].spec["config"])

    assert "master" not in config
    assert "bridge" == config["type"]
    assert config["bridge"] == "ran-br"

def test_given_default_config_with_interfaces_when_network_attachment_definitions_from_config_is_called_then_interfaces_specified_in_nad(  # noqa: E501
    harness
):
    harness.disable_hooks()
    harness.update_config(
        key_values={
            "gnb-ip-address": "192.168.251.5",
            "gnb-interface": "gnb",
        }
    )
    nad = harness.charm._network_attachment_definitions_from_config()
    config = json.loads(nad[0].spec["config"])
    assert config["master"] == "gnb"
    assert config["type"] == "macvlan"

def test_given_fiveg_gnb_identity_relation_created_then_gnb_name_and_tac_are_published(
    harness, mocker
):
    patched_publish_gnb_identity = mocker.patch(
        f"{GNB_IDENTITY_PROVIDES}.publish_gnb_identity_information"
    )
    harness.set_leader(is_leader=True)
    set_up_active_status_charm(harness)
    test_tac = "012"
    test_tac_int = 18
    expected_gnb_name = f"{NAMESPACE}-gnbsim-{harness.charm.app.name}"
    harness.update_config(key_values={"tac": test_tac})

    relation_id = harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
    harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

    patched_publish_gnb_identity.assert_called_once_with(
        relation_id=relation_id, gnb_name=expected_gnb_name, tac=test_tac_int
    )

def test_given_no_tac_in_config_when_fiveg_gnb_identity_relation_is_added_then_default_tac_is_published(  # noqa: E501
    harness, mocker
):
    patched_publish_gnb_identity = mocker.patch(
        f"{GNB_IDENTITY_PROVIDES}.publish_gnb_identity_information"
    )
    harness.set_leader(is_leader=True)
    set_up_active_status_charm(harness)

    relation_id = harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
    harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")
    expected_gnb_name = f"{NAMESPACE}-gnbsim-{harness.charm.app.name}"
    default_tac_int = 1

    patched_publish_gnb_identity.assert_called_once_with(
        relation_id=relation_id, gnb_name=expected_gnb_name, tac=default_tac_int
    )

def test_given_tac_is_not_hexadecimal_when_update_config_then_charm_status_is_blocked(
    harness,
):
    harness.set_leader(is_leader=True)
    set_up_active_status_charm(harness)

    test_tac = "gg"
    harness.update_config(key_values={"tac": test_tac})
    harness.evaluate_status()

    assert harness.charm.unit.status == BlockedStatus("Configurations are invalid: ['tac']")


def test_given_tac_is_not_hexadecimal_when_fiveg_gnb_identity_relation_is_added_then_gnb_identity_is_not_published(  # noqa: E501
    harness, mocker
):
    patched_publish_gnb_identity = mocker.patch(
        f"{GNB_IDENTITY_PROVIDES}.publish_gnb_identity_information"
    )
    harness.set_leader(is_leader=True)
    set_up_active_status_charm(harness)

    test_tac = "gg"
    harness.update_config(key_values={"tac": test_tac})

    relation_id = harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
    harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

    patched_publish_gnb_identity.assert_not_called()

def tests_given_unit_is_not_leader_when_fiveg_gnb_identity_relation_is_added_then_gnb_identity_is_not_published(  # noqa: E501
    harness, mocker
):
    patched_publish_gnb_identity = mocker.patch(
        f"{GNB_IDENTITY_PROVIDES}.publish_gnb_identity_information"
    )
    harness.set_leader(is_leader=False)
    set_up_active_status_charm(harness)

    relation_id = harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
    harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

    patched_publish_gnb_identity.assert_not_called()


def test_given_fiveg_gnb_identity_relation_exists_when_tac_config_changed_then_new_tac_is_published(  # noqa: E501
    harness, mocker
):
    patched_publish_gnb_identity = mocker.patch(
        f"{GNB_IDENTITY_PROVIDES}.publish_gnb_identity_information"
    )
    harness.set_leader(is_leader=True)
    set_up_active_status_charm(harness)

    relation_id = harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
    harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")
    default_tac_int = 1
    test_tac = "F"
    test_tac_int = 15
    expected_gnb_name = f"{NAMESPACE}-gnbsim-{harness.charm.app.name}"

    expected_calls = [
        mocker.call(relation_id=relation_id, gnb_name=expected_gnb_name, tac=default_tac_int),
        mocker.call(relation_id=relation_id, gnb_name=expected_gnb_name, tac=test_tac_int),
    ]
    harness.update_config(key_values={"tac": test_tac})
    patched_publish_gnb_identity.assert_has_calls(expected_calls)


def test_given_fiveg_gnb_identity_relation_not_created_when_update_config_does_not_publish_gnb_identity(  # noqa: E501
    harness, mocker
):
    patched_publish_gnb_identity = mocker.patch(
        f"{GNB_IDENTITY_PROVIDES}.publish_gnb_identity_information"
    )
    harness.set_leader(is_leader=True)
    set_up_active_status_charm(harness)

    harness.update_config(key_values={"tac": "12345"})

    patched_publish_gnb_identity.assert_not_called()


def test_given_multus_disabled_then_status_is_blocked(harness, mocker):
    mocker.patch(f"{MULTUS_LIB}.multus_is_available", return_value=False)
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    harness.set_can_connect(container="gnbsim", val=True)
    set_n2_relation_data(harness)

    harness.charm.on.update_status.emit()
    harness.evaluate_status()

    assert harness.charm.unit.status == BlockedStatus("Multus is not installed or enabled")

def test_given_multus_disabled_then_enabled_then_status_is_active(harness, mocker):
    patch_multus_available = mocker.patch(f"{MULTUS_LIB}.multus_is_available")
    patch_multus_available.side_effect = [False, False, True, True]
    harness.handle_exec("gnbsim", [], result=0)
    harness.add_storage("config", attach=True)
    harness.set_can_connect(container="gnbsim", val=True)
    set_n2_relation_data(harness)

    harness.charm.on.update_status.emit()
    harness.evaluate_status()

    assert harness.charm.unit.status ==  ActiveStatus()
