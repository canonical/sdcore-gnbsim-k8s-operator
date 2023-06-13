# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, PropertyMock, patch

from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ChangeError, ExecError

from charm import GNBSIMOperatorCharm

MULTUS_LIB_PATH = "charms.kubernetes_charm_libraries.v0.multus"


def read_file(path: str) -> str:
    """Reads a file and returns as a string.

    Args:
        path (str): path to the file.

    Returns:
        str: content of the file.
    """
    with open(path, "r") as f:
        content = f.read()
    return content


class TestCharm(unittest.TestCase):
    @patch("lightkube.core.client.GenericSyncClient")
    @patch(
        "charm.KubernetesServicePatch",
        lambda charm, ports: None,
    )
    def setUp(self, patch_k8s_client):
        self.namespace = "whatever"
        self.harness = testing.Harness(GNBSIMOperatorCharm)
        self.harness.set_model_name(name=self.namespace)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_given_default_config_when_config_changed_then_status_is_blocked(
        self,
    ):
        self.harness.update_config(key_values={"usim-opc": ""})

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Configurations are invalid: ['usim-opc']"),
        )

    def test_given_cant_connect_to_workload_when_config_changed_then_status_is_waiting(
        self,
    ):
        self.harness.set_can_connect(container="gnbsim", val=False)

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for container to be ready"),
        )

    @patch("ops.model.Container.exists")
    def test_given_storage_not_attached_when_config_changed_then_status_is_waiting(
        self,
        patch_exists,
    ):
        patch_exists.return_value = False
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for storage to be attached"),
        )

    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exists")
    def test_given_multus_not_ready_when_config_changed_then_status_is_waiting(
        self,
        patch_exists,
        patch_is_ready,
    ):
        patch_exists.return_value = True
        patch_is_ready.return_value = False
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for Multus to be ready"),
        )

    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_n2_information_not_available_when_config_changed_then_status_is_waiting(
        self,
        patch_dir_exists,
        patch_is_ready,
        patch_check_output,
        patch_push,
    ):
        patch_check_output.return_value = b"1.2.3.4"
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for N2 information"),
        )

    @patch("charms.sdcore_amf.v0.fiveg_n2.N2Requires.amf_hostname", new_callable=PropertyMock)
    @patch("charms.sdcore_amf.v0.fiveg_n2.N2Requires.amf_port", new_callable=PropertyMock)
    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_and_n2_info_when_config_changed_then_config_is_written_to_workload(  # noqa: E501
        self,
        patch_dir_exists,
        patch_is_ready,
        patch_check_output,
        patch_push,
        patch_amf_port,
        patch_amf_hostname,
    ):
        patch_amf_port.return_value = 38412
        patch_amf_hostname.return_value = "amf"
        patch_check_output.return_value = b"1.2.3.4"
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        expected_config_file_content = read_file("tests/unit/expected_config.yaml")
        patch_push.assert_called_with(
            source=expected_config_file_content, path="/etc/gnbsim/gnb.conf"
        )

    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_n2_relation_joined_then_config_is_written_to_workload(
        self,
        patch_dir_exists,
        patch_is_ready,
        patch_check_output,
        patch_push,
    ):
        patch_check_output.return_value = b"1.2.3.4"
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        amf_relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="amf")
        self.harness.add_relation_unit(relation_id=amf_relation_id, remote_unit_name="amf/0")
        self.harness.update_relation_data(
            relation_id=amf_relation_id,
            app_or_unit="amf",
            key_values={
                "amf_hostname": "amf",
                "amf_port": "38412",
                "amf_ip_address": "1.1.1.1",
            },
        )

        expected_config_file_content = read_file("tests/unit/expected_config.yaml")
        patch_push.assert_called_with(
            source=expected_config_file_content, path="/etc/gnbsim/gnb.conf"
        )

    @patch("charms.sdcore_amf.v0.fiveg_n2.N2Requires.amf_hostname", new_callable=PropertyMock)
    @patch("charms.sdcore_amf.v0.fiveg_n2.N2Requires.amf_port", new_callable=PropertyMock)
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_status_is_active(
        self,
        patch_dir_exists,
        patch_is_ready,
        patch_check_output,
        patch_amf_port,
        patch_amf_hostname,
    ):
        patch_amf_port.return_value = 38412
        patch_amf_hostname.return_value = "amf"
        patch_check_output.return_value = b"1.2.3.4"
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charms.sdcore_amf.v0.fiveg_n2.N2Requires.amf_hostname", new_callable=PropertyMock)
    @patch("charms.sdcore_amf.v0.fiveg_n2.N2Requires.amf_port", new_callable=PropertyMock)
    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_upf_route_is_created(
        self,
        patch_dir_exists,
        patch_exec,
        patch_is_ready,
        patch_check_output,
        patch_amf_port,
        patch_amf_hostname,
    ):
        patch_amf_port.return_value = 38412
        patch_amf_hostname.return_value = "amf"
        upf_ip_address = "1.1.1.1"
        upf_gateway = "2.2.2.2"
        patch_check_output.return_value = b"1.2.3.4"
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(
            key_values={
                "upf-ip-address": upf_ip_address,
                "upf-gateway": upf_gateway,
            }
        )

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", upf_ip_address, "via", upf_gateway],
            timeout=30,
            environment=None,
        )

    def test_given_cant_connect_to_workload_when_start_simulation_action_then_event_fails(self):
        event = Mock()
        self.harness.set_can_connect(container="gnbsim", val=False)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="Container is not ready")

    @patch("ops.model.Container.exists")
    def test_given_config_file_not_written_when_start_simulation_action_then_event_fails(
        self,
        patch_exists,
    ):
        event = Mock()
        patch_exists.return_value = False
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="Config file is not written")

    @patch("charm.check_output")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_command_fails_with_execerror_when_start_simulation_action_then_event_fails(  # noqa: E501
        self, patch_exists, patch_exec, patch_check_output
    ):
        stderr = "whatever stderr content"
        patch_check_output.return_value = b"1.2.3.4"
        event = Mock()
        patch_exists.return_value = True
        patch_exec.side_effect = ExecError(command=[""], exit_code=1, stderr=stderr, stdout="")
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message=f"Failed to execute simulation: {stderr}")

    @patch("charm.check_output")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_command_fails_with_changeerror_when_start_simulation_action_then_event_fails(  # noqa: E501
        self, patch_exists, patch_exec, patch_check_output
    ):
        error = "whatever error content"
        patch_check_output.return_value = b"1.2.3.4"
        event = Mock()
        patch_exists.return_value = True
        patch_exec.side_effect = ChangeError(err=error, change=None)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message=f"Failed to execute simulation: {error}")

    @patch("charm.check_output")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_no_stderr_when_start_simulation_action_then_event_fails(
        self, patch_exists, patch_exec, patch_check_output
    ):
        patch_check_output.return_value = b"1.2.3.4"
        event = Mock()
        patch_exists.return_value = True
        patch_process = Mock()
        patch_exec.return_value = patch_process
        patch_process.wait_output.return_value = ("whatever stdout", None)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="No output in simulation")

    @patch("charm.check_output")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_fails_when_start_simulation_action_then_simulation_result_is_false(
        self, patch_exists, patch_exec, patch_check_output
    ):
        patch_check_output.return_value = b"1.2.3.4"
        event = Mock()
        patch_exists.return_value = True
        patch_process = Mock()
        patch_exec.return_value = patch_process
        patch_process.wait_output.return_value = ("whatever stdout", "Profile Status: FAILED")
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.set_results.assert_called_with(
            {"success": "false", "info": "run juju debug-log to get more information."}
        )

    @patch("charm.check_output")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_succeeds_swhen_start_simulation_action_then_simulation_result_is_true(  # noqa: E501
        self, patch_exists, patch_exec, patch_check_output
    ):
        patch_check_output.return_value = b"1.2.3.4"
        event = Mock()
        patch_exists.return_value = True
        patch_process = Mock()
        patch_exec.return_value = patch_process
        patch_process.wait_output.return_value = ("whatever stdout", "Profile Status: PASS")
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.set_results.assert_called_with(
            {"success": "true", "info": "run juju debug-log to get more information."}
        )
