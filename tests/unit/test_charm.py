# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, patch

from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ExecError

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

    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.multus_is_configured")
    @patch("ops.model.Container.exists")
    def test_given_multus_not_configured_when_config_changed_then_status_is_waiting(
        self,
        patch_exists,
        patch_multus_is_configured,
    ):
        patch_exists.return_value = True
        patch_multus_is_configured.return_value = False
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for statefulset to be patched"),
        )

    @patch("ops.model.Container.exec")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.multus_is_configured")
    @patch("ops.model.Container.exists")
    def test_given_workload_does_not_have_netadmin_capability_when_config_changed_then_status_is_waiting(  # noqa: E501
        self,
        patch_exists,
        patch_multus_is_configured,
        patch_exec,
    ):
        patch_exists.return_value = True
        patch_multus_is_configured.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)
        patch_exec.side_effect = ExecError(
            exit_code=1,
            command=[""],
            stderr="",
            stdout="",
        )

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for pod to have NET_ADMIN capability"),
        )

    @patch("ops.model.Container.push")
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.multus_is_configured")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_config_is_written_to_workload(
        self,
        patch_dir_exists,
        patch_multus_is_configured,
        patch_check_output,
        patch_push,
    ):
        patch_check_output.return_value = b"1.2.3.4"
        patch_multus_is_configured.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        expected_config_file_content = read_file("tests/unit/expected_config.yaml")

        patch_push.assert_called_with(
            source=expected_config_file_content, path="/etc/gnbsim/gnb.conf"
        )

    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.multus_is_configured")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_status_is_active(
        self,
        patch_dir_exists,
        patch_multus_is_configured,
        patch_check_output,
    ):
        patch_check_output.return_value = b"1.2.3.4"
        patch_multus_is_configured.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self.harness.update_config(key_values={})

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("ops.model.Container.push", new=Mock)
    @patch("charm.check_output")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.multus_is_configured")
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_upf_route_is_created(
        self,
        patch_dir_exists,
        patch_exec,
        patch_multus_is_configured,
        patch_check_output,
    ):
        upf_ip_address = "1.1.1.1"
        upf_gateway = "2.2.2.2"
        patch_check_output.return_value = b"1.2.3.4"
        patch_multus_is_configured.return_value = True
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
    def test_given_simulation_command_fails_when_start_simulation_action_then_event_fails(
        self, patch_exists, patch_exec, patch_check_output
    ):
        patch_check_output.return_value = b"1.2.3.4"
        event = Mock()
        patch_exists.return_value = True
        patch_exec.side_effect = ExecError(command=[""], exit_code=1, stderr="", stdout="")
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="Failed to execute simulation")

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

        event.set_results.assert_called_with({"success": "false"})

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

        event.set_results.assert_called_with({"success": "true"})
