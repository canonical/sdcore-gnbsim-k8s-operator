# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import Mock, patch

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

    def _create_n2_relation(self) -> int:
        """Creates a relation between gnbsim and amf.

        Returns:
            int: Id of the created relation
        """
        amf_relation_id = self.harness.add_relation(relation_name="fiveg-n2", remote_app="amf")
        self.harness.add_relation_unit(relation_id=amf_relation_id, remote_unit_name="amf/0")
        return amf_relation_id

    def _n2_data_available(self) -> None:
        """Creates the N2 relation and sets the relation data in the n2 relation."""
        amf_relation_id = self._create_n2_relation()
        self.harness.update_relation_data(
            relation_id=amf_relation_id,
            app_or_unit="amf",
            key_values={
                "amf_hostname": "amf",
                "amf_port": "38412",
                "amf_ip_address": "1.1.1.1",
            },
        )

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
        self._create_n2_relation()
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
        self._create_n2_relation()

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
        self._create_n2_relation()

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for Multus to be ready"),
        )

    def test_given_n2_relation_not_created_when_config_changed_then_status_is_blocked(
        self,
    ):
        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Waiting for N2 relation to be created"),
        )

    @patch("ops.model.Container.push")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_n2_information_not_available_when_config_changed_then_status_is_waiting(
        self,
        patch_dir_exists,
        patch_is_ready,
        patch_push,
    ):
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)
        self._create_n2_relation()

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for N2 information"),
        )

    @patch("ops.model.Container.push")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_and_n2_info_when_config_changed_then_config_is_written_to_workload(  # noqa: E501
        self,
        patch_dir_exists,
        patch_is_ready,
        patch_push,
    ):
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self._n2_data_available()

        self.harness.update_config(key_values={})

        expected_config_file_content = read_file("tests/unit/expected_config.yaml")
        patch_push.assert_called_with(
            source=expected_config_file_content, path="/etc/gnbsim/gnb.conf"
        )

    @patch("ops.model.Container.push")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_and_n2_info_available_when_n2_relation_joined_then_config_is_written_to_workload(  # noqa: E501
        self,
        patch_dir_exists,
        patch_is_ready,
        patch_push,
    ):
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self._n2_data_available()

        expected_config_file_content = read_file("tests/unit/expected_config.yaml")
        patch_push.assert_called_with(
            source=expected_config_file_content, path="/etc/gnbsim/gnb.conf"
        )

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_status_is_active(
        self,
        patch_dir_exists,
        patch_is_ready,
    ):
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self._n2_data_available()

        self.harness.update_config(key_values={})

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_upf_route_is_created(
        self,
        patch_dir_exists,
        patch_exec,
        patch_is_ready,
    ):
        upf_ip_address = "1.1.1.1"
        upf_gateway = "2.2.2.2"
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self._n2_data_available()

        self.harness.update_config(
            key_values={
                "upf-ip-address": upf_ip_address,
                "upf-gateway": upf_gateway,
            }
        )

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", upf_ip_address, "via", upf_gateway],
            timeout=300,
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

    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_command_fails_with_execerror_when_start_simulation_action_then_event_fails(  # noqa: E501
        self, patch_exists, patch_exec
    ):
        stderr = "whatever stderr content"
        event = Mock()
        patch_exists.return_value = True
        patch_exec.side_effect = ExecError(command=[""], exit_code=1, stderr=stderr, stdout="")
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message=f"Failed to execute simulation: {stderr}")

    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_command_fails_with_changeerror_when_start_simulation_action_then_event_fails(  # noqa: E501
        self, patch_exists, patch_exec
    ):
        error = "whatever error content"
        event = Mock()
        patch_exists.return_value = True
        patch_exec.side_effect = ChangeError(err=error, change=None)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message=f"Failed to execute simulation: {error}")

    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_no_stderr_when_start_simulation_action_then_event_fails(
        self, patch_exists, patch_exec
    ):
        event = Mock()
        patch_exists.return_value = True
        patch_process = Mock()
        patch_exec.return_value = patch_process
        patch_process.wait_output.return_value = ("whatever stdout", None)
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="No output in simulation")

    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_fails_when_start_simulation_action_then_simulation_result_is_false(
        self, patch_exists, patch_exec
    ):
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

    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_can_connect_to_workload_when_start_simulation_action_then_simulation_is_started(
        self, patch_exists, patch_exec
    ):
        event = Mock()
        patch_exists.return_value = True
        patch_process = Mock()
        patch_exec.return_value = patch_process
        patch_process.wait_output.return_value = ("Whatever stdout", "Whatever stderr")
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.charm._on_start_simulation_action(event=event)

        patch_exec.assert_any_call(
            command=["/bin/gnbsim", "--cfg", "/etc/gnbsim/gnb.conf"], timeout=300
        )

    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_simulation_succeeds_when_start_simulation_action_then_simulation_result_is_true(
        self, patch_exists, patch_exec
    ):
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

    def test_given_default_config_when_network_attachment_definitions_from_config_is_called_then_no_interface_specified_in_nad(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        self.harness.update_config(
            key_values={
                "gnb-ip-address": "192.168.251.5",
            }
        )
        nad = self.harness.charm._network_attachment_definition_from_config()
        config = json.loads(nad["config"])
        self.assertNotIn("master", config)
        self.assertEqual("bridge", config["type"])
        self.assertEqual(config["bridge"], "ran-br")

    def test_given_default_config_with_interfaces_when_network_attachment_definitions_from_config_is_called_then_interfaces_specified_in_nad(  # noqa: E501
        self,
    ):
        self.harness.disable_hooks()
        self.harness.update_config(
            key_values={
                "gnb-ip-address": "192.168.251.5",
                "gnb-interface": "gnb",
            }
        )
        nad = self.harness.charm._network_attachment_definition_from_config()
        config = json.loads(nad["config"])
        self.assertEqual(config["master"], "gnb")
        self.assertEqual(config["type"], "macvlan")
