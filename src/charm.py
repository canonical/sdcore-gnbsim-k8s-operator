#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the 5G GNBSIM service for K8s."""

import json
import logging
from typing import List, Optional, Tuple

from charms.kubernetes_charm_libraries.v0.multus import (  # type: ignore[import]
    KubernetesMultusCharmLib,
    NetworkAnnotation,
    NetworkAttachmentDefinition,
)
from charms.loki_k8s.v1.loki_push_api import LogForwarder  # type: ignore[import]
from charms.observability_libs.v1.kubernetes_service_patch import (  # type: ignore[import]
    KubernetesServicePatch,
)
from charms.sdcore_amf_k8s.v0.fiveg_n2 import N2Requires  # type: ignore[import]
from charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity import (  # type: ignore[import]
    GnbIdentityProvides,
)
from jinja2 import Environment, FileSystemLoader
from lightkube.models.core_v1 import ServicePort
from lightkube.models.meta_v1 import ObjectMeta
from ops.charm import ActionEvent, CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Handle
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ChangeError, ExecError

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/etc/gnbsim"
CONFIG_FILE_NAME = "gnb.conf"
GNB_INTERFACE_NAME = "gnb"
GNB_NETWORK_ATTACHMENT_DEFINITION_NAME = "gnb-net"
N2_RELATION_NAME = "fiveg-n2"
GNB_IDENTITY_RELATION_NAME = "fiveg_gnb_identity"
LOGGING_RELATION_NAME = "logging"


class NadConfigChangedEvent(EventBase):
    """Event triggered when an existing network attachment definition is changed."""

    def __init__(self, handle: Handle):
        super().__init__(handle)


class KubernetesMultusCharmEvents(CharmEvents):
    """Kubernetes Multus Charm Events."""

    nad_config_changed = EventSource(NadConfigChangedEvent)


class GNBSIMOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the 5G GNBSIM operator for K8s."""

    on = KubernetesMultusCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self._container_name = self._service_name = "gnbsim"
        self._container = self.unit.get_container(self._container_name)
        self._n2_requirer = N2Requires(self, N2_RELATION_NAME)
        self._service_patcher = KubernetesServicePatch(
            charm=self,
            ports=[
                ServicePort(name="ngapp", port=38412, protocol="SCTP"),
            ],
        )
        self._kubernetes_multus = KubernetesMultusCharmLib(
            charm=self,
            container_name=self._container_name,
            cap_net_admin=True,
            network_annotations_func=self._generate_network_annotations,
            network_attachment_definitions_func=self._network_attachment_definitions_from_config,
            refresh_event=self.on.nad_config_changed,
        )
        self._gnb_identity_provider = GnbIdentityProvides(self, GNB_IDENTITY_RELATION_NAME)
        self._logging = LogForwarder(charm=self, relation_name=LOGGING_RELATION_NAME)
        self.framework.observe(self.on.update_status, self._configure)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.gnbsim_pebble_ready, self._configure)
        self.framework.observe(self.on.start_simulation_action, self._on_start_simulation_action)
        self.framework.observe(self.on.fiveg_n2_relation_joined, self._configure)
        self.framework.observe(self.on.fiveg_n2_relation_broken, self._on_n2_relation_broken)
        self.framework.observe(self._n2_requirer.on.n2_information_available, self._configure)
        self.framework.observe(
            self._gnb_identity_provider.on.fiveg_gnb_identity_request,
            self._configure,
        )

    def _configure(self, event: EventBase) -> None:
        """Juju event handler.

        Sets unit status, writes gnbsim configuration file and sets ip route.

        Args:
            event: Juju event
        """
        if invalid_configs := self._get_invalid_configs():
            self.unit.status = BlockedStatus(f"Configurations are invalid: {invalid_configs}")
            return
        self.on.nad_config_changed.emit()
        if not self._relation_created(N2_RELATION_NAME):
            self.unit.status = BlockedStatus("Waiting for N2 relation to be created")
            return
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for container to be ready")
            return
        if not self._container.exists(path=BASE_CONFIG_PATH):
            self.unit.status = WaitingStatus("Waiting for storage to be attached")
            return
        if not self._kubernetes_multus.is_ready():
            self.unit.status = WaitingStatus("Waiting for Multus to be ready")
            return

        if not self._n2_requirer.amf_hostname or not self._n2_requirer.amf_port:
            self.unit.status = WaitingStatus("Waiting for N2 information")
            return

        content = self._render_config_file(
            amf_hostname=self._n2_requirer.amf_hostname,  # type: ignore[arg-type]
            amf_port=self._n2_requirer.amf_port,  # type: ignore[arg-type]
            gnb_ip_address=self._get_gnb_ip_address_from_config().split("/")[0],  # type: ignore[arg-type, union-attr]  # noqa: E501
            icmp_packet_destination=self._get_icmp_packet_destination_from_config(),  # type: ignore[arg-type]  # noqa: E501
            imsi=self._get_imsi_from_config(),  # type: ignore[arg-type]
            mcc=self._get_mcc_from_config(),  # type: ignore[arg-type]
            mnc=self._get_mnc_from_config(),  # type: ignore[arg-type]
            sd=self._get_sd_from_config(),  # type: ignore[arg-type]
            usim_sequence_number=self._get_usim_sequence_number_from_config(),  # type: ignore[arg-type]  # noqa: E501
            sst=self._get_sst_from_config(),  # type: ignore[arg-type]
            tac=self._get_tac_from_config(),  # type: ignore[arg-type]
            usim_opc=self._get_usim_opc_from_config(),  # type: ignore[arg-type]
            usim_key=self._get_usim_key_from_config(),  # type: ignore[arg-type]
        )
        self._write_config_file(content=content)
        self._update_fiveg_gnb_identity_relation_data()
        self._create_upf_route()
        self.unit.status = ActiveStatus()

    def _on_start_simulation_action(self, event: ActionEvent) -> None:
        """Runs gnbsim simulation leveraging configuration file."""
        if not self._container.can_connect():
            event.fail(message="Container is not ready")
            return
        if not self._config_file_is_written():
            event.fail(message="Config file is not written")
            return
        try:
            stdout, stderr = self._exec_command_in_workload(
                command=f"/bin/gnbsim --cfg {BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}",
            )
            if not stderr:
                event.fail(message="No output in simulation")
                return
            logger.info("gnbsim simulation output:\n=====\n%s\n=====", stderr)
            event.set_results(
                {
                    "success": "true" if "Profile Status: PASS" in stderr else "false",
                    "info": "run juju debug-log to get more information.",
                }
            )
        except ExecError as e:
            event.fail(message=f"Failed to execute simulation: {str(e.stderr)}")
        except ChangeError as e:
            event.fail(message=f"Failed to execute simulation: {e.err}")

    def _generate_network_annotations(self) -> List[NetworkAnnotation]:
        """Generates a list of NetworkAnnotations to be used by gnbsim's StatefulSet.

        Returns:
            List[NetworkAnnotation]: List of NetworkAnnotations
        """
        return [
            NetworkAnnotation(
                name=GNB_NETWORK_ATTACHMENT_DEFINITION_NAME, interface=GNB_INTERFACE_NAME
            )
        ]

    def _network_attachment_definitions_from_config(self) -> list[NetworkAttachmentDefinition]:
        """Returns list of Multus NetworkAttachmentDefinitions to be created based on config."""
        gnb_nad_config = {
            "cniVersion": "0.3.1",
            "ipam": {
                "type": "static",
                "addresses": [
                    {
                        "address": self._get_gnb_ip_address_from_config(),
                    }
                ],
            },
            "capabilities": {"mac": True},
        }
        if (gnb_interface := self._get_gnb_interface_from_config()) is not None:
            gnb_nad_config.update({"type": "macvlan", "master": gnb_interface})
        else:
            gnb_nad_config.update({"type": "bridge", "bridge": "ran-br"})
        return [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(name=GNB_NETWORK_ATTACHMENT_DEFINITION_NAME),
                spec={"config": json.dumps(gnb_nad_config)},
            ),
        ]

    def _on_n2_relation_broken(self, event: EventBase):
        self.unit.status = BlockedStatus("Waiting for N2 relation to be created")

    def _update_fiveg_gnb_identity_relation_data(self) -> None:
        """Publishes GNB name and TAC in the `fiveg_gnb_identity` relation data bag."""
        if not self.unit.is_leader():
            return
        fiveg_gnb_identity_relations = self.model.relations.get(GNB_IDENTITY_RELATION_NAME)
        if not fiveg_gnb_identity_relations:
            logger.info("No %s relations found.", GNB_IDENTITY_RELATION_NAME)
            return

        tac = self._get_tac_as_int()
        if not tac:
            logger.error(
                "TAC value cannot be published on the %s relation", GNB_IDENTITY_RELATION_NAME
            )
            return
        for gnb_identity_relation in fiveg_gnb_identity_relations:
            self._gnb_identity_provider.publish_gnb_identity_information(
                relation_id=gnb_identity_relation.id, gnb_name=self._gnb_name, tac=tac
            )

    def _get_gnb_ip_address_from_config(self) -> Optional[str]:
        return self.model.config.get("gnb-ip-address")

    def _get_gnb_interface_from_config(self) -> Optional[str]:
        return self.model.config.get("gnb-interface")

    def _get_icmp_packet_destination_from_config(self) -> Optional[str]:
        return self.model.config.get("icmp-packet-destination")

    def _get_imsi_from_config(self) -> Optional[str]:
        return self.model.config.get("imsi")

    def _get_mcc_from_config(self) -> Optional[str]:
        return self.model.config.get("mcc")

    def _get_mnc_from_config(self) -> Optional[str]:
        return self.model.config.get("mnc")

    def _get_sd_from_config(self) -> Optional[str]:
        return self.model.config.get("sd")

    def _get_sst_from_config(self) -> Optional[int]:
        return int(self.model.config.get("sst"))  # type: ignore[arg-type]

    def _get_tac_from_config(self) -> Optional[str]:
        return self.model.config.get("tac")

    def _get_upf_gateway_from_config(self) -> Optional[str]:
        return self.model.config.get("upf-gateway")

    def _get_upf_subnet_from_config(self) -> Optional[str]:
        return self.model.config.get("upf-subnet")

    def _get_usim_key_from_config(self) -> Optional[str]:
        return self.model.config.get("usim-key")

    def _get_usim_opc_from_config(self) -> Optional[str]:
        return self.model.config.get("usim-opc")

    def _get_usim_sequence_number_from_config(self) -> Optional[str]:
        return self.model.config.get("usim-sequence-number")

    def _write_config_file(self, content: str) -> None:
        self._container.push(source=content, path=f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}")
        logger.info("Config file written")

    def _config_file_is_written(self) -> bool:
        if not self._container.exists(f"{BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}"):
            return False
        return True

    def _render_config_file(
        self,
        *,
        amf_hostname: str,
        amf_port: int,
        gnb_ip_address: str,
        icmp_packet_destination: str,
        imsi: str,
        mcc: str,
        mnc: str,
        sd: str,
        sst: int,
        tac: str,
        usim_key: str,
        usim_opc: str,
        usim_sequence_number: str,
    ) -> str:
        """Renders config file based on parameters.

        Args:
            amf_hostname: AMF hostname
            amf_port: AMF port
            gnb_ip_address: gNodeB IP address
            icmp_packet_destination: Default ICMP packet destination
            imsi: International Mobile Subscriber Identity
            mcc: Mobile Country Code
            mnc: Mobile Network Code
            sd: Slice ID
            sst: Slice Selection Type
            tac: Tracking Area Code
            usim_key: USIM key
            usim_opc: USIM OPC
            usim_sequence_number: USIM sequence number

        Returns:
            str: Rendered gnbsim configuration file
        """
        jinja2_env = Environment(loader=FileSystemLoader("src/templates"))
        template = jinja2_env.get_template("config.yaml.j2")
        return template.render(
            amf_hostname=amf_hostname,
            amf_port=amf_port,
            gnb_ip_address=gnb_ip_address,
            icmp_packet_destination=icmp_packet_destination,
            imsi=imsi,
            mcc=mcc,
            mnc=mnc,
            sd=sd,
            sst=sst,
            tac=tac,
            usim_key=usim_key,
            usim_opc=usim_opc,
            usim_sequence_number=usim_sequence_number,
        )

    def _get_invalid_configs(self) -> list[str]:  # noqa: C901
        """Gets list of invalid Juju configurations."""
        invalid_configs = []
        if not self._get_gnb_ip_address_from_config():
            invalid_configs.append("gnb-ip-address")
        if not self._get_icmp_packet_destination_from_config():
            invalid_configs.append("icmp-packet-destination")
        if not self._get_imsi_from_config():
            invalid_configs.append("imsi")
        if not self._get_mcc_from_config():
            invalid_configs.append("mcc")
        if not self._get_mnc_from_config():
            invalid_configs.append("mnc")
        if not self._get_sd_from_config():
            invalid_configs.append("sd")
        if not self._get_sst_from_config():
            invalid_configs.append("sst")
        if not self._get_tac_from_config() or not self._get_tac_as_int():
            invalid_configs.append("tac")
        if not self._get_upf_gateway_from_config():
            invalid_configs.append("upf-gateway")
        if not self._get_upf_subnet_from_config():
            invalid_configs.append("upf-subnet")
        if not self._get_usim_key_from_config():
            invalid_configs.append("usim-key")
        if not self._get_usim_opc_from_config():
            invalid_configs.append("usim-opc")
        if not self._get_usim_sequence_number_from_config():
            invalid_configs.append("usim-sequence-number")
        return invalid_configs

    def _create_upf_route(self) -> None:
        """Creates route to reach the UPF."""
        self._exec_command_in_workload(
            command=f"ip route replace {self._get_upf_subnet_from_config()} via {self._get_upf_gateway_from_config()}"  # noqa: E501
        )
        logger.info("UPF route created")

    def _exec_command_in_workload(
        self,
        command: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Executes command in workload container.

        Args:
            command: Command to execute
        """
        process = self._container.exec(
            command=command.split(),
            timeout=300,
        )
        return process.wait_output()

    def _relation_created(self, relation_name: str) -> bool:
        """Returns whether a given Juju relation was crated.

        Args:
            relation_name (str): Relation name

        Returns:
            bool: Whether the relation was created.
        """
        return bool(self.model.relations[relation_name])

    @property
    def _gnb_name(self) -> str:
        """The gNB's name contains the model name and the app name.

        Returns:
            str: the gNB's name.
        """
        return f"{self.model.name}-gnbsim-{self.app.name}"

    def _get_tac_as_int(self) -> Optional[int]:
        """Convert the TAC value in the config to an integer.

        Returns:
            TAC as an integer. None if the config value is invalid.
        """
        tac = None
        try:
            tac = int(self.model.config.get("tac"), 16)  # type: ignore[arg-type]
        except ValueError:
            logger.error("Invalid TAC value in config: it cannot be converted to integer.")
        return tac


if __name__ == "__main__":  # pragma: nocover
    main(GNBSIMOperatorCharm)
