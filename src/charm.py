#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the 5G GNBSIM service for K8s."""

import json
import logging
from typing import List, Optional, Tuple, cast

from charms.kubernetes_charm_libraries.v0.multus import (
    KubernetesMultusCharmLib,
    NetworkAnnotation,
    NetworkAttachmentDefinition,
)
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
)
from charms.sdcore_amf_k8s.v0.fiveg_n2 import N2Requires
from charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity import (
    GnbIdentityProvides,
)
from jinja2 import Environment, FileSystemLoader
from lightkube.models.core_v1 import ServicePort
from lightkube.models.meta_v1 import ObjectMeta
from ops import ActiveStatus, BlockedStatus, CollectStatusEvent, WaitingStatus
from ops.charm import ActionEvent, CharmBase
from ops.framework import EventBase
from ops.main import main
from ops.pebble import ChangeError, ExecError

logger = logging.getLogger(__name__)

BASE_CONFIG_PATH = "/etc/gnbsim"
CONFIG_FILE_NAME = "gnb.conf"
GNB_INTERFACE_NAME = "gnb"
GNB_NETWORK_ATTACHMENT_DEFINITION_NAME = "gnb-net"
N2_RELATION_NAME = "fiveg-n2"
GNB_IDENTITY_RELATION_NAME = "fiveg_gnb_identity"
LOGGING_RELATION_NAME = "logging"
WORKLOAD_VERSION_FILE_NAME = "/etc/workload-version"
NUM_PROFILES = 5


class GNBSIMOperatorCharm(CharmBase):
    """Main class to describe juju event handling for the 5G GNBSIM operator for K8s."""

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
            namespace=self.model.name,
            statefulset_name=self.model.app.name,
            pod_name="-".join(self.model.unit.name.rsplit("/", 1)),
            container_name=self._container_name,
            cap_net_admin=True,
            network_annotations=self._generate_network_annotations(),
            network_attachment_definitions=self._network_attachment_definitions_from_config(),
        )
        self._gnb_identity_provider = GnbIdentityProvides(self, GNB_IDENTITY_RELATION_NAME)
        self._logging = LogForwarder(charm=self, relation_name=LOGGING_RELATION_NAME)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        self.framework.observe(self.on.update_status, self._configure)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.gnbsim_pebble_ready, self._configure)
        self.framework.observe(self.on.start_simulation_action, self._on_start_simulation_action)
        self.framework.observe(self.on.fiveg_n2_relation_joined, self._configure)
        self.framework.observe(self._n2_requirer.on.n2_information_available, self._configure)
        self.framework.observe(
            self._gnb_identity_provider.on.fiveg_gnb_identity_request,
            self._configure,
        )
        self.framework.observe(self.on.remove, self._on_remove)

    def _on_collect_unit_status(self, event: CollectStatusEvent):
        """Check the unit status and set to Unit when CollectStatusEvent is fired.

        Set the workload version if present in workload
        Args:
            event: CollectStatusEvent
        """
        if invalid_configs := self._get_invalid_configs():
            event.add_status(BlockedStatus(f"Configurations are invalid: {invalid_configs}"))
            logger.info(f"Configurations are invalid: {invalid_configs}")
            return
        if not self._relation_created(N2_RELATION_NAME):
            event.add_status(BlockedStatus("Waiting for N2 relation to be created"))
            logger.info("Waiting for N2 relation to be created")
            return
        if not self._container.can_connect():
            event.add_status(WaitingStatus("Waiting for container to be ready"))
            logger.info("Waiting for container to be ready")
            return
        self.unit.set_workload_version(self._get_workload_version())
        if not self._container.exists(path=BASE_CONFIG_PATH):
            event.add_status(WaitingStatus("Waiting for storage to be attached"))
            logger.info("Waiting for storage to be attached")
            return
        if not self._kubernetes_multus.multus_is_available():
            event.add_status(BlockedStatus("Multus is not installed or enabled"))
            logger.info("Multus is not installed or enabled")
            return
        if not self._kubernetes_multus.is_ready():
            event.add_status(WaitingStatus("Waiting for Multus to be ready"))
            logger.info("Waiting for Multus to be ready")
            return
        if not self._n2_requirer.amf_hostname or not self._n2_requirer.amf_port:
            event.add_status(WaitingStatus("Waiting for N2 information"))
            logger.info("Waiting for N2 information")
            return
        event.add_status(ActiveStatus())

    def _configure(self, event: EventBase) -> None:  # noqa: C901
        """Juju event handler.

        Sets unit status, writes gnbsim configuration file and sets ip route.

        Args:
            event: Juju event
        """
        if self._get_invalid_configs():
            return
        if not self._kubernetes_multus.multus_is_available():
            return
        self._kubernetes_multus.configure()
        if not self._relation_created(N2_RELATION_NAME):
            return
        if not self._container.can_connect():
            return
        if not self._container.exists(path=BASE_CONFIG_PATH):
            return
        if not self._kubernetes_multus.is_ready():
            return
        if not self._n2_requirer.amf_hostname or not self._n2_requirer.amf_port:
            return
        if not self._n2_requirer.amf_hostname:
            return
        if not (gnb_ip_address := self._get_gnb_ip_address_from_config()):
            return
        if not (icmp_packet_destination := self._get_icmp_packet_destination_from_config()):
            return
        if not (imsi := self._get_imsi_from_config()):
            return
        if not (mcc := self._get_mcc_from_config()):
            return
        if not (mnc := self._get_mnc_from_config()):
            return
        if not (sd := self._get_sd_from_config()):
            return
        if not (usim_sequence_number := self._get_usim_sequence_number_from_config()):
            return
        if not (sst := self._get_sst_from_config()):
            return
        if not (tac := self._get_tac_from_config()):
            return
        if not (usim_opc := self._get_usim_opc_from_config()):
            return
        if not (usim_key := self._get_usim_key_from_config()):
            return
        if not (dnn := self._get_dnn_from_config()):
            return
        content = self._render_config_file(
            amf_hostname=self._n2_requirer.amf_hostname,
            amf_port=self._n2_requirer.amf_port,
            gnb_ip_address=gnb_ip_address.split("/")[0],
            icmp_packet_destination=icmp_packet_destination,
            imsi=imsi,
            mcc=mcc,
            mnc=mnc,
            sd=sd,
            usim_sequence_number=usim_sequence_number,
            sst=sst,
            tac=tac,
            usim_opc=usim_opc,
            usim_key=usim_key,
            dnn=dnn,
        )
        self._write_config_file(content=content)
        self._update_fiveg_gnb_identity_relation_data()
        self._create_upf_route()

    def _on_start_simulation_action(self, event: ActionEvent) -> None:
        """Run gnbsim simulation leveraging configuration file."""
        if not self._container.can_connect():
            event.fail(message="Container is not ready")
            return
        if not self._config_file_is_written():
            event.fail(message="Config file is not written")
            return
        try:
            _, stderr = self._exec_command_in_workload(
                command=f"/bin/gnbsim --cfg {BASE_CONFIG_PATH}/{CONFIG_FILE_NAME}",
            )
            if not stderr:
                event.fail(message="No output in simulation")
                return
            logger.info("gnbsim simulation output:\n=====\n%s\n=====", stderr)

            count = stderr.count("Profile Status: PASS")
            info = f"{count}/{NUM_PROFILES} profiles passed"
            if count == NUM_PROFILES:
                event.set_results(
                    {
                        "success": "true",
                        "info": info
                    }
                )
            else:
                event.set_results(
                    {
                        "success": "false",
                        "info": info
                    }
                )
        except ExecError as e:
            event.fail(message=f"Failed to execute simulation: {str(e.stderr)}")
        except ChangeError as e:
            event.fail(message=f"Failed to execute simulation: {e.err}")

    def _on_remove(self, _) -> None:
        """Handle the remove event."""
        if not self.unit.is_leader():
            return
        self._kubernetes_multus.remove()

    def _generate_network_annotations(self) -> List[NetworkAnnotation]:
        """Generate a list of NetworkAnnotations to be used by gnbsim's StatefulSet.

        Returns:
            List[NetworkAnnotation]: List of NetworkAnnotations
        """
        return [
            NetworkAnnotation(
                name=GNB_NETWORK_ATTACHMENT_DEFINITION_NAME, interface=GNB_INTERFACE_NAME
            )
        ]

    def _network_attachment_definitions_from_config(self) -> list[NetworkAttachmentDefinition]:
        """Return list of Multus NetworkAttachmentDefinitions to be created based on config."""
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

    def _update_fiveg_gnb_identity_relation_data(self) -> None:
        """Publish GNB name and TAC in the `fiveg_gnb_identity` relation data bag."""
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
        return cast(Optional[str], self.model.config.get("gnb-ip-address"))

    def _get_gnb_interface_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("gnb-interface"))

    def _get_icmp_packet_destination_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("icmp-packet-destination"))

    def _get_imsi_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("imsi"))

    def _get_mcc_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("mcc"))

    def _get_mnc_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("mnc"))

    def _get_sd_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("sd"))

    def _get_sst_from_config(self) -> Optional[int]:
        return cast(Optional[int], self.model.config.get("sst"))

    def _get_tac_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("tac"))

    def _get_upf_gateway_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("upf-gateway"))

    def _get_upf_subnet_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("upf-subnet"))

    def _get_usim_key_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("usim-key"))

    def _get_usim_opc_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("usim-opc"))

    def _get_usim_sequence_number_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("usim-sequence-number"))

    def _get_dnn_from_config(self) -> Optional[str]:
        return cast(Optional[str], self.model.config.get("dnn"))

    def _get_workload_version(self) -> str:
        """Return the workload version.

        Checks for the presence of /etc/workload-version file
        and if present, returns the contents of that file. If
        the file is not present, an empty string is returned.

        Returns:
            string: A human readable string representing the
            version of the workload
        """
        if self._container.exists(path=f"{WORKLOAD_VERSION_FILE_NAME}"):
            version_file_content = self._container.pull(
                path=f"{WORKLOAD_VERSION_FILE_NAME}"
            ).read()
            return version_file_content
        return ""

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
        dnn: str,
    ) -> str:
        """Render config file based on parameters.

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
            dnn: Data Network Name

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
            dnn=dnn,
        )

    def _get_invalid_configs(self) -> list[str]:  # noqa: C901
        """Get list of invalid Juju configurations."""
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
        """Create route to reach the UPF."""
        self._exec_command_in_workload(
            command=f"ip route replace {self._get_upf_subnet_from_config()} via {self._get_upf_gateway_from_config()}"  # noqa: E501
        )
        logger.info("UPF route created")

    def _exec_command_in_workload(
        self,
        command: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Execute command in workload container.

        Args:
            command: Command to execute
        """
        process = self._container.exec(
            command=command.split(),
            timeout=300,
        )
        return process.wait_output()

    def _relation_created(self, relation_name: str) -> bool:
        """Return whether a given Juju relation was created.

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
