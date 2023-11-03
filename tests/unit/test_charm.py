# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import Mock, call, patch

from ops import testing
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ChangeError, ExecError

from charm import GNBSIMOperatorCharm

MULTUS_LIB_PATH = "charms.kubernetes_charm_libraries.v0.multus"
GNB_IDENTITY_LIB_PATH = "charms.sdcore_gnbsim.v0.fiveg_gnb_identity"
IP_ROUTER_LIB_PATH = "charms.ip_router_interface.v0.ip_router_interface"
DEFAULT_UPF_IP_ADDRESS = "192.168.252.3"
DEFAULT_UPF_GATEWAY = "192.168.251.1"


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


def get_expected_config(upf_ip_address: str = "", upf_gateway: str = "") -> str:
    """Reads the tests/unit/expected_config.yaml file.

    Replaces the the value of the UPF IP adress and the UPF gateway with the
    given arguments.

    Args:
        upf_ip_address: new UPF IP address to use in config
        upf_gateway: new UPF gateway to use in the config
    Returns:
        str: content of the file with the replace values.
    """
    config_file_content = read_file("tests/unit/expected_config.yaml")
    if upf_ip_address and upf_gateway:
        replaced_file_content = config_file_content.replace(DEFAULT_UPF_IP_ADDRESS, upf_ip_address)
        replaced_file_content = replaced_file_content.replace(DEFAULT_UPF_GATEWAY, upf_gateway)
        return replaced_file_content
    return config_file_content


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

    def test_given_default_config_when_config_changed_then_status_is_blocked(self):
        self.harness.update_config(key_values={"usim-opc": ""})

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Configurations are invalid: ['usim-opc']"),
        )

    def test_given_cant_connect_to_workload_when_config_changed_then_status_is_waiting(self):
        self._create_n2_relation()
        self.harness.set_can_connect(container="gnbsim", val=False)

        self.harness.update_config(key_values={})

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting for container to be ready"),
        )

    @patch("ops.model.Container.exists")
    def test_given_storage_not_attached_when_config_changed_then_status_is_waiting(
        self, patch_exists
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
        self, patch_exists, patch_is_ready
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

    def test_given_n2_relation_not_created_when_config_changed_then_status_is_blocked(self):
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
        self, patch_dir_exists, patch_is_ready, patch_push
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
        self, patch_dir_exists, patch_is_ready, patch_push
    ):
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self._n2_data_available()

        self.harness.update_config(key_values={})

        expected_config = get_expected_config()
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_and_n2_info_available_when_n2_relation_joined_then_config_is_written_to_workload(  # noqa: E501
        self, patch_dir_exists, patch_is_ready, patch_push
    ):
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self._n2_data_available()

        expected_config = get_expected_config()
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    def test_given_default_config_when_config_changed_then_status_is_active(
        self, patch_dir_exists, patch_is_ready
    ):
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)

        self._n2_data_available()

        self.harness.update_config(key_values={})

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_ip_router_relation_when_config_changed_then_upf_config_is_taken_from_relation(  # noqa: E501
        self, patch_exec, patch_get_routing_table, patch_push
    ):
        upf_network = "1.1.1.1/24"
        upf_gateway = "2.2.2.2"
        networks = [
            {"network": upf_network, "gateway": upf_gateway},
            {"network": "3.3.3.3/24", "gateway": "4.4.4.4"},
        ]
        routing_table = {"ip_router_access": networks}
        patch_get_routing_table.return_value = routing_table
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()
        self.harness.update_config(key_values={})

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", upf_network, "via", upf_gateway],
            timeout=300,
        )
        expected_config = get_expected_config(upf_network, upf_gateway)
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_ip_router_relation_created_and_empty_routing_table_then_upf_config_uses_config_values(  # noqa: E501
        self, patch_exec, patch_get_routing_table, patch_push
    ):
        patch_get_routing_table.return_value = {}
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()

        self.harness.update_config(key_values={})

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", DEFAULT_UPF_IP_ADDRESS, "via", DEFAULT_UPF_GATEWAY],
            timeout=300,
        )
        expected_config = get_expected_config()
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_no_access_network_when_config_changed_then_upf_config_uses_config_values(
        self, patch_exec, patch_get_routing_table, patch_push
    ):
        networks = [{"network": "1.1.1.1", "gateway": "2.2.2.2"}]
        routing_table = {"some_name": networks}
        patch_get_routing_table.return_value = routing_table
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()

        self.harness.update_config(key_values={})

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", DEFAULT_UPF_IP_ADDRESS, "via", DEFAULT_UPF_GATEWAY],
            timeout=300,
        )
        expected_config = get_expected_config()
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_no_ip_router_relation_when_config_changed_then_upf_route_uses_config_values(
        self, patch_exec, patch_get_routing_table, patch_push
    ):
        self.harness.set_can_connect(container="gnbsim", val=True)
        self._n2_data_available()

        self.harness.update_config(key_values={})
        patch_get_routing_table.assert_not_called()
        patch_exec.assert_called_with(
            command=["ip", "route", "replace", DEFAULT_UPF_IP_ADDRESS, "via", DEFAULT_UPF_GATEWAY],
            timeout=300,
        )
        expected_config = get_expected_config()
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.request_network")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table", Mock(return_value={}))
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exists", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    def test_given_ip_router_relation_when_config_changed_then_ip_router_network_is_requested(
        self, _, patch_request_network
    ):
        user_plane_network = "1.1.1.1"
        user_plane_gateway = "2.2.2.2"
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()

        self.harness.update_config(
            key_values={
                "user-plane-network": user_plane_network,
                "user-plane-gateway": user_plane_gateway,
            }
        )
        networks = [{"network": user_plane_network, "gateway": user_plane_gateway}]
        patch_request_network.assert_called_with(
            requested_networks=networks, custom_network_name="ip-router"
        )

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.request_network")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table", Mock(return_value={}))
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exists", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    def test_given_default_user_plane_network_when_config_changed_then_ip_router_network_is_requested(  # noqa: E501
        self, _, patch_request_network
    ):
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()

        self.harness.update_config(key_values={})
        default_user_plane_netowork = "192.168.251.0/24"
        default_user_plane_gateway = "192.168.251.1"
        networks = [
            {"network": default_user_plane_netowork, "gateway": default_user_plane_gateway}
        ]
        patch_request_network.assert_called_with(
            requested_networks=networks, custom_network_name="ip-router"
        )

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.request_network")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exists", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    def test_given_no_ip_router_relation_when_config_changed_then_ip_router_network_is_not_requested(  # noqa: E501
        self, _, patch_request_network
    ):
        self.harness.set_can_connect(container="gnbsim", val=True)
        self._n2_data_available()
        self.harness.update_config(key_values={"user-plane-gateway": "1.1.1.1"})
        patch_request_network.assert_not_called()

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table", Mock(return_value={}))
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_ip_router_relation_when_routing_table_is_updated_then_upf_config_comes_from_relation(  # noqa: E501
        self, patch_exec, patch_push
    ):
        upf_network = "1.1.1.1"
        upf_gateway = "2.2.2.2"
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()
        networks = [
            {"network": upf_network, "gateway": upf_gateway},
            {"network": "192.168.251.0/24", "gateway": "192.168.251.1"},
        ]
        routing_table = {"ip_router_access": networks}

        event = Mock()
        event.routing_table = {"networks": routing_table}
        self.harness.charm._update_upf_config(event=event)

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", upf_network, "via", upf_gateway],
            timeout=300,
        )
        expected_config = get_expected_config(upf_network, upf_gateway)
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table", Mock(return_value={}))
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_no_ip_router_relation_when_routing_table_is_updated_event_then_new_upf_config_is_not_used(  # noqa: E501
        self, patch_exec, patch_push
    ):
        upf_network = "1.1.1.1"
        upf_gateway = "2.2.2.2"
        self.harness.set_can_connect(container="gnbsim", val=True)
        self._n2_data_available()
        networks = [{"network": upf_network, "gateway": upf_gateway}]
        routing_table = {"ip_router_access": networks}

        event = Mock()
        event.routing_table = {"networks": routing_table}
        self.harness.charm._update_upf_config(event=event)

        self.assertNotIn(upf_network, patch_exec.call_args.kwargs["command"])
        self.assertNotIn(upf_gateway, patch_exec.call_args.kwargs["command"])
        self.assertNotIn(upf_network, patch_push.call_args.kwargs["source"])
        self.assertNotIn(upf_gateway, patch_push.call_args.kwargs["source"])

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table", Mock(return_value={}))
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_empty_routing_table_when_routing_table_is_updated_event_then_default_upf_config_is_set(  # noqa: E501
        self, patch_exec, patch_push
    ):
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()

        event = Mock()
        event.routing_table = {"networks": {}}
        self.harness.charm._update_upf_config(event=event)

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", DEFAULT_UPF_IP_ADDRESS, "via", DEFAULT_UPF_GATEWAY],
            timeout=300,
        )
        expected_config = get_expected_config()
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    @patch("ops.model.Container.push")
    @patch(f"{IP_ROUTER_LIB_PATH}.RouterRequires.get_routing_table")
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready", Mock(return_value=True))
    @patch("ops.model.Container.exec")
    @patch("ops.model.Container.exists", Mock(return_value=True))
    def test_given_no_access_network_when_routing_table_is_updated_event_then_default_upf_config_is_set(  # noqa: E501
        self, patch_exec, patch_get_routing_table, patch_push
    ):
        self.harness.set_can_connect(container="gnbsim", val=True)
        self.harness.add_relation("ip-router", "ip_router_provider_app")
        self._n2_data_available()
        networks = [{"network": "192.168.0.0/24", "gateway": "192.168.0.1"}]
        routing_table = {"some_network": networks}
        patch_get_routing_table.return_value = routing_table

        event = Mock()
        event.routing_table = {"networks": routing_table}
        self.harness.charm._update_upf_config(event=event)

        patch_exec.assert_called_with(
            command=["ip", "route", "replace", DEFAULT_UPF_IP_ADDRESS, "via", DEFAULT_UPF_GATEWAY],
            timeout=300,
        )
        expected_config = get_expected_config()
        patch_push.assert_called_with(source=expected_config, path="/etc/gnbsim/gnb.conf")

    def test_given_cant_connect_to_workload_when_start_simulation_action_then_event_fails(self):
        event = Mock()
        self.harness.set_can_connect(container="gnbsim", val=False)

        self.harness.charm._on_start_simulation_action(event=event)

        event.fail.assert_called_with(message="Container is not ready")

    @patch("ops.model.Container.exists")
    def test_given_config_file_not_written_when_start_simulation_action_then_event_fails(
        self, patch_exists
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
        nad = self.harness.charm._network_attachment_definitions_from_config()
        config = json.loads(nad[0].spec["config"])
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
        nad = self.harness.charm._network_attachment_definitions_from_config()
        config = json.loads(nad[0].spec["config"])
        self.assertEqual(config["master"], "gnb")
        self.assertEqual(config["type"], "macvlan")

    @patch(f"{GNB_IDENTITY_LIB_PATH}.GnbIdentityProvides.publish_gnb_identity_information")
    def test_given_fiveg_gnb_identity_relation_created_when_fiveg_gnb_identity_request_then_gnb_name_and_tac_are_published(  # noqa: E501
        self, patched_publish_gnb_identity
    ):
        self.harness.set_leader(is_leader=True)
        test_tac = "012"
        test_tac_int = 18
        expected_gnb_name = f"{self.namespace}-gnbsim-{self.harness.charm.app.name}"
        self.harness.update_config(key_values={"tac": test_tac})
        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

        patched_publish_gnb_identity.assert_called_once_with(
            relation_id=relation_id, gnb_name=expected_gnb_name, tac=test_tac_int
        )

    @patch(f"{GNB_IDENTITY_LIB_PATH}.GnbIdentityProvides.publish_gnb_identity_information")
    def test_given_no_tac_in_config_when_fiveg_gnb_identity_request_then_default_tac_is_published(
        self, patched_publish_gnb_identity
    ):
        self.harness.set_leader(is_leader=True)
        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")
        expected_gnb_name = f"{self.namespace}-gnbsim-{self.harness.charm.app.name}"
        default_tac_int = 1

        patched_publish_gnb_identity.assert_called_once_with(
            relation_id=relation_id, gnb_name=expected_gnb_name, tac=default_tac_int
        )

    @patch(f"{GNB_IDENTITY_LIB_PATH}.GnbIdentityProvides.publish_gnb_identity_information")
    def test_given_tac_is_not_hexadecimal_when_fiveg_gnb_identity_request_then_information_is_not_published(  # noqa: E501
        self, patched_publish_gnb_identity
    ):
        self.harness.set_leader(is_leader=True)
        test_tac = "gg"
        self.harness.update_config(key_values={"tac": test_tac})
        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

        patched_publish_gnb_identity.assert_not_called()

    @patch(f"{GNB_IDENTITY_LIB_PATH}.GnbIdentityProvides.publish_gnb_identity_information")
    def tests_given_unit_is_not_leader_when_fiveg_gnb_identity_requests_then_information_is_not_published(  # noqa: E501
        self, patched_publish_gnb_identity
    ):
        self.harness.update_config(key_values={"tac": "12345"})
        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")

        patched_publish_gnb_identity.assert_not_called()

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    @patch(f"{GNB_IDENTITY_LIB_PATH}.GnbIdentityProvides.publish_gnb_identity_information")
    def test_given_fiveg_gnb_identity_relation_exists_when_tac_config_changed_then_new_tac_is_published(  # noqa: E501
        self, patched_publish_gnb_identity, patch_dir_exists, patch_is_ready
    ):
        self.harness.set_leader(is_leader=True)
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)
        self._n2_data_available()

        relation_id = self.harness.add_relation("fiveg_gnb_identity", "gnb_identity_requirer_app")
        self.harness.add_relation_unit(relation_id, "gnb_identity_requirer_app/0")
        default_tac_int = 1
        test_tac = "F"
        test_tac_int = 15
        expected_gnb_name = f"{self.namespace}-gnbsim-{self.harness.charm.app.name}"

        expected_calls = [
            call(relation_id=relation_id, gnb_name=expected_gnb_name, tac=default_tac_int),
            call(relation_id=relation_id, gnb_name=expected_gnb_name, tac=test_tac_int),
        ]
        self.harness.update_config(key_values={"tac": test_tac})
        patched_publish_gnb_identity.assert_has_calls(expected_calls)

    @patch("ops.model.Container.push", new=Mock)
    @patch(f"{MULTUS_LIB_PATH}.KubernetesMultusCharmLib.is_ready")
    @patch("ops.model.Container.exec", new=Mock)
    @patch("ops.model.Container.exists")
    @patch(f"{GNB_IDENTITY_LIB_PATH}.GnbIdentityProvides.publish_gnb_identity_information")
    def test_given_fiveg_gnb_identity_relation_not_created_does_not_publish_information(
        self, patched_publish_gnb_identity, patch_dir_exists, patch_is_ready
    ):
        self.harness.set_leader(is_leader=True)
        patch_is_ready.return_value = True
        patch_dir_exists.return_value = True
        self.harness.set_can_connect(container="gnbsim", val=True)
        self._n2_data_available()
        self.harness.update_config(key_values={"tac": "12345"})

        patched_publish_gnb_identity.assert_not_called()
