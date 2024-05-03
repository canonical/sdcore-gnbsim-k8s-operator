# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from unittest.mock import Mock, call, patch

import pytest
from charm import GNBSIMOperatorCharm
from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ChangeError

MULTUS_LIB = "charms.kubernetes_charm_libraries.v0.multus.KubernetesMultusCharmLib"
GNB_IDENTITY_LIB = "charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity.GnbIdentityProvides"
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

class TestCharm:

    patcher_lightkube_client = patch("lightkube.core.client.GenericSyncClient")
    patcher_k8s_service_patch = patch("charm.KubernetesServicePatch")
    patcher_multus_ready = patch(f"{MULTUS_LIB}.is_ready")
    patcher_multus_available = patch(f"{MULTUS_LIB}.multus_is_available")
    patcher_gnb_identity = patch(f"{GNB_IDENTITY_LIB}.publish_gnb_identity_information")

    @pytest.fixture()
    def setUp(self):
        self.mock_lightkube_client = TestCharm.patcher_lightkube_client.start()
        self.mock_k8s_service_patch = TestCharm.patcher_k8s_service_patch.start()
        self.mock_multus_ready = TestCharm.patcher_multus_ready.start()
        self.mock_multus_available = TestCharm.patcher_multus_available.start()
        self.mock_gnb_identity = TestCharm.patcher_gnb_identity.start()

    def tearDown(self) -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def harness(self, setUp, request):
        self.mock_multus_ready.return_value = True
        self.mock_multus_available.return_value = True
        self.harness = testing.Harness(GNBSIMOperatorCharm)
        self.harness.set_model_name(name=NAMESPACE)
        self.harness.begin()
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.tearDown)

    def set_up_active_status_charm(self):
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.set_n2_relation_data()
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == ActiveStatus()

    def create_n2_relation(self) -> int:
        """Create a relation between gnbsim and AMF.

        Returns:
            int: Id of the created relation
        """
        amf_relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="amf") # type: ignore[attr-defined]
        self.harness.add_relation_unit(relation_id=amf_relation_id, remote_unit_name="amf/0") # type: ignore[attr-defined]
        return amf_relation_id

    def set_n2_relation_data(self) -> int:
        """Create the N2 relation, set the relation data in the n2 relation and return its ID.

        Returns:
            int: ID of the created relation
        """
        amf_relation_id = self.create_n2_relation()
        self.harness.update_relation_data( # type: ignore[attr-defined]
            relation_id=amf_relation_id,
            app_or_unit="amf",
            key_values={
                "amf_hostname": "amf",
                "amf_port": "38412",
                "amf_ip_address": "1.1.1.1",
            },
        )
        return amf_relation_id

    @pytest.mark.parametrize(
        "config_param",
        [
            ("usim-opc"),
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
            ("upf-gateway")
        ]
    )
    def test_given_invalid_config_when_config_changed_then_status_is_blocked(self, config_param):
        self.harness.update_config(key_values={config_param: ""})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
            f"Configurations are invalid: ['{config_param}']"
        )

    def test_given_cant_connect_to_workload_when_config_changed_then_status_is_waiting(self):
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.set_n2_relation_data()
        self.harness.set_can_connect(container="gnbsim", val=False)

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus("Waiting for container to be ready")

    def test_given_storage_not_attached_when_config_changed_then_status_is_waiting(self):
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.set_n2_relation_data()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus(
                                                    "Waiting for storage to be attached"
                                                )

    def test_given_multus_not_ready_when_config_changed_then_status_is_waiting(
        self
    ):
        self.mock_multus_ready.return_value = False
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.create_n2_relation()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus("Waiting for Multus to be ready")

    def test_given_n2_relation_not_created_when_config_changed_then_status_is_blocked(self):
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
                                                    "Waiting for N2 relation to be created"
                                                )

    def test_given_gnbsim_charm_in_active_state_when_n2_relation_breaks_then_status_is_blocked(
        self
    ):
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.harness.set_can_connect(container="gnbsim", val=True)
        n2_relation_id = self.set_n2_relation_data()

        self.harness.remove_relation(n2_relation_id)
        self.harness.evaluate_status()

        assert self.harness.model.unit.status == BlockedStatus(
                                                    "Waiting for N2 relation to be created"
                                                )

    def test_given_n2_information_not_available_when_config_changed_then_status_is_waiting(self):
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.create_n2_relation()

        self.harness.update_config(key_values={})
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == WaitingStatus("Waiting for N2 information")

    def test_given_default_config_and_n2_info_when_config_changed_then_config_is_written_to_workload(  # noqa: E501
        self
    ):
        self.set_up_active_status_charm()
        root = self.harness.get_filesystem_root("gnbsim")

        self.harness.update_config(key_values={})

        expected_config_file_content = read_file("tests/unit/expected_config.yaml")
        assert (root / "etc/gnbsim/gnb.conf").read_text() == expected_config_file_content

    def test_given_default_config_and_n2_info_available_when_n2_relation_joined_then_config_is_written_to_workload(  # noqa: E501
        self
    ):
        self.set_up_active_status_charm()
        root = self.harness.get_filesystem_root("gnbsim")

        expected_config_file_content = read_file("tests/unit/expected_config.yaml")
        assert (root / "etc/gnbsim/gnb.conf").read_text() == expected_config_file_content

    def test_given_default_config_when_config_changed_then_status_is_active(self):
        self.set_up_active_status_charm()

        self.harness.update_config(key_values={})
        self.harness.charm.on.update_status.emit()

        assert self.harness.charm.unit.status == ActiveStatus()

    def test_given_default_config_when_update_status_emit_then_status_is_active(self):
        self.set_up_active_status_charm()

        self.harness.charm.on.update_status.emit()

        assert self.harness.charm.unit.status == ActiveStatus()

    def test_given_default_config_when_config_changed_then_upf_route_is_created(self):
        self.harness.add_storage("config", attach=True)
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

        self.harness.handle_exec("gnbsim", ip_route_cmd, handler=ip_route_handler)
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.set_n2_relation_data()

        self.harness.update_config(
            key_values={
                "upf-subnet": upf_subnet,
                "upf-gateway": upf_gateway,
            }
        )

        assert ip_route_called
        assert timeout == 300

    def test_given_cant_connect_to_workload_when_start_simulation_action_then_event_fails(self):
        event = Mock()
        self.harness.set_can_connect(container="gnbsim", val=False)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="Container is not ready")

    def test_given_config_file_not_written_when_start_simulation_action_then_event_fails(self):
        self.harness.add_storage("config", attach=True)
        event = Mock()
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="Config file is not written")

    def test_given_simulation_command_fails_with_execerror_when_start_simulation_action_then_event_fails(  # noqa: E501
        self
    ):
        self.harness.add_storage("config", attach=True)
        root = self.harness.get_filesystem_root("gnbsim")
        (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
        stderr = "whatever stderr content"
        event = Mock()

        def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
            return testing.ExecResult(stderr=stderr, exit_code=1)

        self.harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message=f"Failed to execute simulation: {stderr}")

    def test_given_simulation_command_fails_with_changeerror_when_start_simulation_action_then_event_fails(  # noqa: E501
        self
    ):
        self.harness.add_storage("config", attach=True)
        root = self.harness.get_filesystem_root("gnbsim")
        (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
        error = "whatever error content"
        event = Mock()

        def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
            raise ChangeError(err=error, change=None)  # type: ignore[arg-type]

        self.harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message=f"Failed to execute simulation: {error}")

    def test_given_no_stderr_when_start_simulation_action_then_event_fails(self):
        self.harness.add_storage("config", attach=True)
        root = self.harness.get_filesystem_root("gnbsim")
        (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
        event = Mock()

        self.harness.handle_exec("gnbsim", ["/bin/gnbsim"], result=0)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="No output in simulation")

    def test_given_simulation_fails_when_start_simulation_action_then_simulation_result_is_false(
        self
    ):
        self.harness.add_storage("config", attach=True)
        root = self.harness.get_filesystem_root("gnbsim")
        (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
        event = Mock()

        def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
            return testing.ExecResult(
                stdout="whatever stdout",
                stderr="Profile Status: FAILED",
            )

        self.harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.set_results.assert_called_with(
            {"success": "false", "info": "run juju debug-log to get more information."}
        )

    def test_given_can_connect_to_workload_when_start_simulation_action_then_simulation_is_started(
        self
    ):
        self.harness.add_storage("config", attach=True)
        root = self.harness.get_filesystem_root("gnbsim")
        (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
        event = Mock()

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

        self.harness.handle_exec("gnbsim", gnbsim_cmd, handler=gnbsim_handler)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        assert gnbsim_called
        assert timeout == 300

    def test_given_simulation_succeeds_when_start_simulation_action_then_simulation_result_is_true(
        self
    ):
        self.harness.add_storage("config", attach=True)
        root = self.harness.get_filesystem_root("gnbsim")
        (root / "etc/gnbsim/gnb.conf").write_text(read_file("tests/unit/expected_config.yaml"))
        event = Mock()

        def gnbsim_handler(_: testing.ExecArgs) -> testing.ExecResult:
            return testing.ExecResult(
                stdout="whatever stdout",
                stderr="Profile Status: PASS",
            )

        self.harness.handle_exec("gnbsim", ["/bin/gnbsim"], handler=gnbsim_handler)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.set_results.assert_called_with(
            {"success": "true", "info": "run juju debug-log to get more information."}
        )

    def test_given_default_config_when_network_attachment_definitions_from_config_is_called_then_no_interface_specified_in_nad(  # noqa: E501
        self
    ):
        self.harness.disable_hooks()
        self.harness.update_config(
            key_values={
                "gnb-ip-address": "192.168.251.5",
            }
        )
        nad = self.harness.charm._network_attachment_definitions_from_config()
        config = json.loads(nad[0].spec["config"])

        assert "master" not in config
        assert config["type"] == "bridge"
        assert config["bridge"] == "ran-br"

    def test_given_default_config_with_interfaces_when_network_attachment_definitions_from_config_is_called_then_interfaces_specified_in_nad(  # noqa: E501
        self
    ):
        self.harness.disable_hooks()
        self.harness.update_config(
            key_values={
                "gnb-ip-address": "192.168.251.5",
                "gnb-interface": "gnb",
            }
        )
        nad = self.harness.charm._network_attachment_definitions_from_config()
        config = json.loads(nad[0].spec["config"])
        assert config["master"] == "gnb"
        assert config["type"] == "macvlan"

    def test_given_fiveg_gnb_identity_relation_created_then_gnb_name_and_tac_are_published(
        self
    ):
        self.set_up_active_status_charm()
        self.harness.set_leader(is_leader=True)

        test_tac = "012"
        test_tac_int = 18
        expected_gnb_name = f"{NAMESPACE}-gnbsim-{self.harness.charm.app.name}"
        self.harness.update_config(key_values={"tac": test_tac})

        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

        self.mock_gnb_identity.assert_called_once_with(
            relation_id=relation_id, gnb_name=expected_gnb_name, tac=test_tac_int
        )

    def test_given_no_tac_in_config_when_fiveg_gnb_identity_relation_is_added_then_default_tac_is_published(  # noqa: E501
        self
    ):
        self.set_up_active_status_charm()
        self.harness.set_leader(is_leader=True)

        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")
        expected_gnb_name = f"{NAMESPACE}-gnbsim-{self.harness.charm.app.name}"
        default_tac_int = 1

        self.mock_gnb_identity.assert_called_once_with(
            relation_id=relation_id, gnb_name=expected_gnb_name, tac=default_tac_int
        )

    def test_given_tac_is_not_hexadecimal_when_update_config_then_charm_status_is_blocked(
        self
    ):
        self.set_up_active_status_charm()
        self.harness.set_leader(is_leader=True)

        test_tac = "gg"
        self.harness.update_config(key_values={"tac": test_tac})
        self.harness.evaluate_status()
        assert self.harness.charm.unit.status == BlockedStatus(
                                                    "Configurations are invalid: ['tac']"
                                                )

    def test_given_tac_is_not_hexadecimal_when_fiveg_gnb_identity_relation_is_added_then_gnb_identity_is_not_published(  # noqa: E501
        self
    ):
        self.set_up_active_status_charm()
        self.harness.set_leader(is_leader=True)

        test_tac = "gg"
        self.harness.update_config(key_values={"tac": test_tac})
        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

        self.mock_gnb_identity.assert_not_called()

    def tests_given_unit_is_not_leader_when_fiveg_gnb_identity_relation_is_added_then_gnb_identity_is_not_published(  # noqa: E501
        self
    ):
        self.set_up_active_status_charm()
        self.harness.set_leader(is_leader=False)

        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

        self.mock_gnb_identity.assert_not_called()

    def test_given_fiveg_gnb_identity_relation_exists_when_tac_config_changed_then_new_tac_is_published(  # noqa: E501
        self
    ):
        self.set_up_active_status_charm()
        self.harness.set_leader(is_leader=True)
        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")
        default_tac_int = 1
        test_tac = "F"
        test_tac_int = 15
        expected_gnb_name = f"{NAMESPACE}-gnbsim-{self.harness.charm.app.name}"

        self.harness.update_config(key_values={"tac": test_tac})

        expected_calls = [
            call(relation_id=relation_id, gnb_name=expected_gnb_name, tac=default_tac_int),
            call(relation_id=relation_id, gnb_name=expected_gnb_name, tac=test_tac_int),
        ]
        self.mock_gnb_identity.assert_has_calls(expected_calls)

    def test_given_fiveg_gnb_identity_relation_not_created_when_update_config_does_not_publish_gnb_identity(  # noqa: E501
        self
    ):
        self.set_up_active_status_charm()
        self.harness.set_leader(is_leader=True)
        self.harness.update_config(key_values={"tac": "12345"})

        self.mock_gnb_identity.assert_not_called()

    def test_given_multus_disabled_then_status_is_blocked(self):
        self.mock_multus_available.return_value = False
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.set_n2_relation_data()

        self.harness.charm.on.update_status.emit()
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == BlockedStatus(
                                                    "Multus is not installed or enabled"
                                                )

    def test_given_multus_disabled_then_enabled_then_status_is_active(
        self
    ):
        self.mock_multus_available.side_effect = [False, False, True, True]
        self.harness.handle_exec("gnbsim", [], result=0)
        self.harness.add_storage("config", attach=True)
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.set_n2_relation_data()

        self.harness.charm.on.update_status.emit()
        self.harness.evaluate_status()

        assert self.harness.charm.unit.status == ActiveStatus()
