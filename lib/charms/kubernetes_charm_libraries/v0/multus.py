# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Library used to leverage the Multus Kubernetes CNI in charms.

- On a BoundEvent (e.g. self.on.nad_config_changed which is originated from NadConfigChangedEvent),
 it will:
  - Configure the requested network attachment definitions
  - Patch the statefulset with the necessary annotations for the container to have interfaces
    that use those new network attachments.
  - If an existing NAD config changed, it triggers pod restart to make the new config effective
- On charm removal, it will:
  - Delete the created network attachment definitions

## Usage

```python

from charms.kubernetes_charm_libraries.v0.multus import (
    KubernetesMultusCharmLib,
    NetworkAttachmentDefinition,
    NetworkAnnotation
)

class NadConfigChangedEvent(EventBase):


class KubernetesMultusCharmEvents(CharmEvents):

    nad_config_changed = EventSource(NadConfigChangedEvent)


class YourCharm(CharmBase):

    on = KubernetesMultusCharmEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self._kubernetes_multus = KubernetesMultusCharmLib(
            charm=self,
            container_name=self._container_name,
            cap_net_admin=True,
            privileged=True,
            network_annotations=[
                NetworkAnnotation(
                    name=NETWORK_ATTACHMENT_DEFINITION_NAME,
                    interface=INTERFACE_NAME,
                )
            ],
            network_attachment_definitions_func=self._network_attachment_definitions_from_config,
            refresh_event=self.on.nad_config_changed,
        )

    def _network_attachment_definitions_from_config(self) -> list[NetworkAttachmentDefinition]:
        return [
            NetworkAttachmentDefinition(
                metadata=ObjectMeta(name=NETWORK_ATTACHMENT_DEFINITION_NAME),
                spec={
                    "config": json.dumps(
                        {
                            "cniVersion": "0.3.1",
                            "type": "macvlan",
                            "ipam": {
                                "type": "static",
                                "routes": [
                                    {
                                        "dst": self._get_upf_ip_address_from_config(),
                                        "gw": self._get_upf_gateway_from_config(),
                                    }
                                ],
                                "addresses": [
                                    {
                                        "address": self._get_interface_ip_address_from_config(),
                                    }
                                ],
                            },
                        }
                    )
                },
            ),
        ]

    def _on_config_changed(self, event: EventBase):
        if not self.unit.is_leader():
            return
        if self._get_invalid_configs():
            return
        # Fire the NadConfigChangedEvent if the configs are valid.
        self.on.nad_config_changed.emit()
```
"""

import json
import logging
from dataclasses import asdict, dataclass
from json.decoder import JSONDecodeError
from typing import Callable, Union

import httpx
from lightkube import Client
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import GenericNamespacedResource, create_namespaced_resource
from lightkube.models.apps_v1 import StatefulSetSpec
from lightkube.models.core_v1 import (
    Capabilities,
    Container,
    PodSpec,
    PodTemplateSpec,
    SecurityContext,
)
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Pod
from lightkube.types import PatchType
from ops.charm import CharmBase, RemoveEvent
from ops.framework import BoundEvent, Object

# The unique Charmhub library identifier, never change it
LIBID = "75283550e3474e7b8b5b7724d345e3c2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 8


logger = logging.getLogger(__name__)

_NetworkAttachmentDefinition = create_namespaced_resource(
    group="k8s.cni.cncf.io",
    version="v1",
    kind="NetworkAttachmentDefinition",
    plural="network-attachment-definitions",
)


class NetworkAttachmentDefinition(_NetworkAttachmentDefinition):  # type: ignore[valid-type, misc]
    """Object to represent Kubernetes Multus NetworkAttachmentDefinition."""

    def __eq__(self, other):
        """Validates equality between two NetworkAttachmentDefinitions object."""
        return self.metadata.name == other.metadata.name and self.spec == other.spec


@dataclass
class NetworkAnnotation:
    """NetworkAnnotation."""

    name: str
    interface: str

    dict = asdict


class KubernetesMultusError(Exception):
    """KubernetesMultusError."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class KubernetesClient:
    """Class containing all the Kubernetes specific calls."""

    def __init__(self, namespace: str):
        self.client = Client()
        self.namespace = namespace

    def delete_pod(self, pod_name: str) -> None:
        """Deleting given pod.

        Args:
            pod_name (str): Pod name

        """
        self.client.delete(Pod, pod_name, namespace=self.namespace)

    def pod_is_ready(
        self,
        pod_name: str,
        *,
        network_annotations: list[NetworkAnnotation],
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
    ) -> bool:
        """Returns whether pod has the requisite network annotation and NET_ADMIN capability.

        Args:
            pod_name: Pod name
            network_annotations: List of network annotations
            container_name: Container name
            cap_net_admin: Container requires NET_ADMIN capability
            privileged: Container requires privileged security context

        Returns:
            bool: Whether pod is ready.


        statefulset.spec.template.metadata.annotations
        pod.metadata.annotations

        statefulset.spec.template.spec.containers
        pod.spec.containers
        """
        try:
            pod = self.client.get(Pod, name=pod_name, namespace=self.namespace)
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesMultusError(f"Pod {pod_name} not found")
            return False
        return self._pod_is_patched(
            pod=pod,  # type: ignore[arg-type]
            network_annotations=network_annotations,
            container_name=container_name,
            cap_net_admin=cap_net_admin,
            privileged=privileged,
        )

    def network_attachment_definition_is_created(
        self, network_attachment_definition: NetworkAttachmentDefinition
    ) -> bool:
        """Returns whether a NetworkAttachmentDefinition is created.

        Args:
            network_attachment_definition: NetworkAttachmentDefinition

        Returns:
            bool: Whether the NetworkAttachmentDefinition is created
        """
        try:
            existing_nad = self.client.get(
                res=NetworkAttachmentDefinition,
                name=network_attachment_definition.metadata.name,
                namespace=self.namespace,
            )
            return existing_nad == network_attachment_definition
        except ApiError as e:
            if e.status.reason == "NotFound":
                logger.debug("NetworkAttachmentDefinition not found")
            elif e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesMultusError(
                    f"Unexpected outcome when retrieving NetworkAttachmentDefinition "
                    f"{network_attachment_definition.metadata.name}"
                )
            return False
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise KubernetesMultusError(
                    "NetworkAttachmentDefinition resource not found. "
                    "You may need to install Multus CNI."
                )
            else:
                raise KubernetesMultusError(
                    f"Unexpected outcome when retrieving NetworkAttachmentDefinition "
                    f"{network_attachment_definition.metadata.name}"
                )

    def create_network_attachment_definition(
        self, network_attachment_definition: GenericNamespacedResource
    ) -> None:
        """Creates a NetworkAttachmentDefinition.

        Args:
            network_attachment_definition: NetworkAttachmentDefinition object
        """
        try:
            self.client.create(obj=network_attachment_definition, namespace=self.namespace)  # type: ignore[call-overload]  # noqa: E501
        except ApiError:
            raise KubernetesMultusError(
                f"Could not create NetworkAttachmentDefinition "
                f"{network_attachment_definition.metadata.name}"  # type: ignore[union-attr]
            )
        logger.info(
            "NetworkAttachmentDefinition %s created", network_attachment_definition.metadata.name  # type: ignore[union-attr]  # noqa: E501, W505
        )

    def list_network_attachment_definitions(self) -> list[NetworkAttachmentDefinition]:
        """Lists NetworkAttachmentDefinitions in a given namespace.

        Returns:
            list[NetworkAttachmentDefinition]: List of NetworkAttachmentDefinitions
        """
        try:
            return list(
                self.client.list(res=NetworkAttachmentDefinition, namespace=self.namespace)
            )
        except ApiError:
            raise KubernetesMultusError("Could not list NetworkAttachmentDefinitions")

    def delete_network_attachment_definition(self, name: str) -> None:
        """Deletes network attachment definition based on name.

        Args:
            name: NetworkAttachmentDefinition name
        """
        try:
            self.client.delete(
                res=NetworkAttachmentDefinition, name=name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesMultusError(f"Could not delete NetworkAttachmentDefinition {name}")
        logger.info("NetworkAttachmentDefinition %s deleted", name)

    def patch_statefulset(
        self,
        name: str,
        network_annotations: list[NetworkAnnotation],
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
    ) -> None:
        """Patches a statefulset with Multus annotation and NET_ADMIN capability.

        Args:
            name: Statefulset name
            network_annotations: List of network annotations
            container_name: Container name
            cap_net_admin: Container requires NET_ADMIN capability
            privileged: Container requires privileged security context
        """
        if not network_annotations:
            logger.info("No network annotations were provided")
            return
        try:
            statefulset = self.client.get(res=StatefulSet, name=name, namespace=self.namespace)
        except ApiError:
            raise KubernetesMultusError(f"Could not get statefulset {name}")
        container = Container(name=container_name)
        if cap_net_admin:
            container.securityContext = SecurityContext(
                capabilities=Capabilities(
                    add=[
                        "NET_ADMIN",
                    ]
                )
            )
        if privileged:
            container.securityContext.privileged = True
        statefulset_delta = StatefulSet(
            spec=StatefulSetSpec(
                selector=statefulset.spec.selector,  # type: ignore[attr-defined]
                serviceName=statefulset.spec.serviceName,  # type: ignore[attr-defined]
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={
                            "k8s.v1.cni.cncf.io/networks": json.dumps(
                                [
                                    network_annotation.dict()
                                    for network_annotation in network_annotations
                                ]
                            )
                        }
                    ),
                    spec=PodSpec(containers=[container]),
                ),
            )
        )
        try:
            self.client.patch(
                res=StatefulSet,
                name=name,
                obj=statefulset_delta,
                patch_type=PatchType.APPLY,
                namespace=self.namespace,
                field_manager=self.__class__.__name__,
            )
        except ApiError:
            raise KubernetesMultusError(f"Could not patch statefulset {name}")
        logger.info("Multus annotation added to %s statefulset", name)

    def statefulset_is_patched(
        self,
        name: str,
        network_annotations: list[NetworkAnnotation],
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
    ) -> bool:
        """Returns whether the statefulset has the expected multus annotation.

        Args:
            name: Statefulset name.
            network_annotations: list of network annotations
            container_name: Container name
            cap_net_admin: Container requires NET_ADMIN capability
            privileged: Container requires privileged security context

        Returns:
            bool: Whether the statefulset has the expected multus annotation.
        """
        try:
            statefulset = self.client.get(res=StatefulSet, name=name, namespace=self.namespace)
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesMultusError(f"Could not get statefulset {name}")
            return False
        return self._pod_is_patched(
            container_name=container_name,
            cap_net_admin=cap_net_admin,
            privileged=privileged,
            network_annotations=network_annotations,
            pod=statefulset.spec.template,  # type: ignore[attr-defined]
        )

    def _pod_is_patched(
        self,
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
        network_annotations: list[NetworkAnnotation],
        pod: Union[PodTemplateSpec, Pod],
    ) -> bool:
        """Returns whether a pod is patched with network annotations and security context.

        Args:
            container_name: Container name
            cap_net_admin: Whether we expect "container name" to have cap_net_admin
            privileged: Whether we expect "container name" to be privileged
            network_annotations: List of network annotations
            pod: Kubernetes pod object.

        Returns:
            bool
        """
        if not self._annotations_contains_multus_networks(
            annotations=pod.metadata.annotations,
            network_annotations=network_annotations,
        ):
            return False
        if not self._container_security_context_is_set(
            containers=pod.spec.containers,
            container_name=container_name,
            cap_net_admin=cap_net_admin,
            privileged=privileged,
        ):
            return False
        return True

    def _annotations_contains_multus_networks(
        self, annotations: dict, network_annotations: list[NetworkAnnotation]
    ) -> bool:
        if "k8s.v1.cni.cncf.io/networks" not in annotations:
            return False
        try:
            if json.loads(annotations["k8s.v1.cni.cncf.io/networks"]) != [
                network_annotation.dict() for network_annotation in network_annotations
            ]:
                return False
        except JSONDecodeError:
            return False
        return True

    def _container_security_context_is_set(
        self,
        containers: list[Container],
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
    ) -> bool:
        """Returns whether container spec contains the expected security context.

        Args:
            containers: list of Containers
            container_name: Container name
            cap_net_admin: Whether we expect "container name" to have cap_net_admin
            privileged: Whether we expect "container name" to be privileged

        Returns:
            bool
        """
        for container in containers:
            if container.name == container_name:
                if cap_net_admin and "NET_ADMIN" not in container.securityContext.capabilities.add:
                    return False
                if privileged and not container.securityContext.privileged:
                    return False
        return True


class KubernetesMultusCharmLib(Object):
    """Class to be instantiated by charms requiring Multus networking."""

    def __init__(
        self,
        charm: CharmBase,
        network_attachment_definitions_func: Callable[[], list[NetworkAttachmentDefinition]],
        network_annotations: list[NetworkAnnotation],
        container_name: str,
        refresh_event: BoundEvent,
        cap_net_admin: bool = False,
        privileged: bool = False,
    ):
        """Constructor for the KubernetesMultusCharmLib.

        Args:
            charm: Charm object
            network_attachment_definitions_func: A callable to a function returning a list of
              `NetworkAttachmentDefinition` to be created.
            network_annotations: List of NetworkAnnotation.
            container_name: Container name
            cap_net_admin: Container requires NET_ADMIN capability
            privileged: Container requires privileged security context
            refresh_event: A BoundEvent which will be observed
                to configure_multus (e.g. NadConfigChangedEvent).
        """
        super().__init__(charm, "kubernetes-multus")
        self.kubernetes = KubernetesClient(namespace=self.model.name)
        self.network_attachment_definitions_func = network_attachment_definitions_func
        self.network_annotations = network_annotations
        self.container_name = container_name
        self.cap_net_admin = cap_net_admin
        self.privileged = privileged
        # Apply custom events
        self.framework.observe(refresh_event, self._configure_multus)
        self.framework.observe(charm.on.remove, self._on_remove)

    def _configure_multus(self, event: BoundEvent) -> None:
        """Creates network attachment definitions and patches statefulset.

        Args:
            event: EventBase
        """
        self._configure_network_attachment_definitions()
        if not self._statefulset_is_patched():
            self.kubernetes.patch_statefulset(
                name=self.model.app.name,
                network_annotations=self.network_annotations,
                container_name=self.container_name,
                cap_net_admin=self.cap_net_admin,
                privileged=self.privileged,
            )

    def _network_attachment_definition_created_by_charm(
        self, network_attachment_definition: NetworkAttachmentDefinition
    ) -> bool:
        """Returns whether a given NetworkAttachmentDefinitions was created by this charm."""
        labels = network_attachment_definition.metadata.labels
        if not labels:
            return False
        if "app.juju.is/created-by" not in labels:
            return False
        if labels["app.juju.is/created-by"] != self.model.app.name:
            return False
        return True

    def _configure_network_attachment_definitions(self):
        """Configures NetworkAttachmentDefinitions in Kubernetes.

        1. Goes through the list of existing NetworkAttachmentDefinitions in Kubernetes.
        - If it was created by this charm:
          - If it is in the list of NetworkAttachmentDefinitions to create, remove it from the
            list of NetworkAttachmentDefinitions to create
          - Else, delete it
        2. Goes through the list of NetworkAttachmentDefinitions to create and create them all
        3. Detects the NAD config changes and triggers pod restart
           if any there is any modification in existing NADs
        """
        network_attachment_definitions_to_create = self.network_attachment_definitions_func()
        nad_config_changed = False
        for (
            existing_network_attachment_definition
        ) in self.kubernetes.list_network_attachment_definitions():
            if self._network_attachment_definition_created_by_charm(
                existing_network_attachment_definition
            ):
                if (
                    existing_network_attachment_definition
                    not in network_attachment_definitions_to_create
                ):
                    self.kubernetes.delete_network_attachment_definition(
                        name=existing_network_attachment_definition.metadata.name
                    )
                    nad_config_changed = True
                else:
                    network_attachment_definitions_to_create.remove(
                        existing_network_attachment_definition
                    )
        for network_attachment_definition_to_create in network_attachment_definitions_to_create:
            self.kubernetes.create_network_attachment_definition(
                network_attachment_definition=network_attachment_definition_to_create
            )
        if nad_config_changed:
            # We want to trigger the pod restart once if there is a change in NADs
            # after all the NADs are configured.
            logger.warning("Restarting pod to make the new NAD configs effective.")
            self.delete_pod()

    def _network_attachment_definitions_are_created(self) -> bool:
        """Returns whether all network attachment definitions are created."""
        for network_attachment_definition in self.network_attachment_definitions_func():
            if not self.kubernetes.network_attachment_definition_is_created(
                network_attachment_definition=network_attachment_definition
            ):
                return False
        return True

    def _statefulset_is_patched(self) -> bool:
        """Returns whether statefuset is patched with network annotations and capabilities."""
        return self.kubernetes.statefulset_is_patched(
            name=self.model.app.name,
            network_annotations=self.network_annotations,
            container_name=self.container_name,
            cap_net_admin=self.cap_net_admin,
            privileged=self.privileged,
        )

    def _pod_is_ready(self) -> bool:
        """Returns whether pod is ready with network annotations and capabilities."""
        return self.kubernetes.pod_is_ready(
            pod_name=self._pod,
            network_annotations=self.network_annotations,
            container_name=self.container_name,
            cap_net_admin=self.cap_net_admin,
            privileged=self.privileged,
        )

    def is_ready(self) -> bool:
        """Returns whether Multus is ready.

        Validates that the network attachment definitions are created, that the statefulset is
        patched with the appropriate Multus annotations and capabilities and that the pod
        also contains the same annotations and capabilities.

        Returns:
            bool: Whether Multus is ready
        """
        nad_are_created = self._network_attachment_definitions_are_created()
        satefulset_is_patched = self._statefulset_is_patched()
        pod_is_ready = self._pod_is_ready()
        return nad_are_created and satefulset_is_patched and pod_is_ready

    @property
    def _pod(self) -> str:
        """Name of the unit's pod.

        Returns:
            str: A string containing the name of the current unit's pod.
        """
        return "-".join(self.model.unit.name.rsplit("/", 1))

    def _on_remove(self, event: RemoveEvent) -> None:
        """Deletes network attachment definitions.

        Args:
            event: RemoveEvent
        """
        for network_attachment_definition in self.network_attachment_definitions_func():
            if self.kubernetes.network_attachment_definition_is_created(
                network_attachment_definition=network_attachment_definition
            ):
                self.kubernetes.delete_network_attachment_definition(
                    name=network_attachment_definition.metadata.name  # type: ignore[union-attr]
                )

    def delete_pod(self) -> None:
        """Delete the pod."""
        self.kubernetes.delete_pod(self._pod)
