# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Library used to leverage the Multus Kubernetes CNI in charms.

- On config-changed, it will:
  - Create the requested network attachment definitions
  - Patch the statefulset with the necessary annotations for the container to have interfaces
    that use those new network attachments.
- On charm removal, it will:
  - Delete the created network attachment definitions

## Usage

```python

from kubernetes_multus import (
    KubernetesMultusCharmLib,
    NetworkAttachmentDefinition,
    NetworkAnnotation
)

class YourCharm(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self._kubernetes_multus = KubernetesMultusCharmLib(
            charm=self,
            containers_requiring_net_admin_capability=[self._bessd_container_name],
            network_attachment_definitions=[
                NetworkAttachmentDefinition(
                    metadata=ObjectMeta(name=ACCESS_NETWORK_ATTACHMENT_DEFINITION_NAME),
                    spec=network_attachment_definition_spec,
                ),
                NetworkAttachmentDefinition(
                    metadata=ObjectMeta(name=CORE_NETWORK_ATTACHMENT_DEFINITION_NAME),
                    spec=network_attachment_definition_spec,
                ),
            ],
            network_annotations_func=self._network_annotations_from_config,
        )

    def _network_annotations_from_config(self) -> list[NetworkAnnotation]:
        return [
            NetworkAnnotation(
                name=ACCESS_NETWORK_ATTACHMENT_DEFINITION_NAME,
                interface=ACCESS_INTERFACE_NAME,
                ips=[self._get_access_network_ip_config()],
            ),
            NetworkAnnotation(
                name=CORE_NETWORK_ATTACHMENT_DEFINITION_NAME,
                interface=CORE_INTERFACE_NAME,
                ips=[self._get_core_network_ip_config()],
            ),
        ]
```
"""

import json
import logging
from dataclasses import asdict, dataclass
from json.decoder import JSONDecodeError
from typing import Callable, Optional

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
from ops.charm import CharmBase, EventBase, RemoveEvent
from ops.framework import Object

# The unique Charmhub library identifier, never change it
LIBID = "75283550e3474e7b8b5b7724d345e3c2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2


logger = logging.getLogger(__name__)

NetworkAttachmentDefinition = create_namespaced_resource(
    group="k8s.cni.cncf.io",
    version="v1",
    kind="NetworkAttachmentDefinition",
    plural="network-attachment-definitions",
)


@dataclass
class NetworkAnnotation:
    """NetworkAnnotation."""

    name: str
    interface: str
    ips: Optional[list] = None

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

    def pod_is_ready(
        self,
        pod_name: str,
        *,
        network_annotations: list[NetworkAnnotation],
        containers_requiring_net_admin_capability: list[str],
    ) -> bool:
        """Returns whether pod has the requisite network annotation and NET_ADMIN capability.

        Args:
            pod_name: Pod name
            network_annotations: List of network annotations
            containers_requiring_net_admin_capability: List of containers requiring NET_ADMIN
                capability

        Returns:
            bool: Whether pod is ready.
        """
        try:
            pod = self.client.get(Pod, name=pod_name, namespace=self.namespace)
        except ApiError:
            raise KubernetesMultusError(f"Pod {pod_name} not found")
        if "k8s.v1.cni.cncf.io/networks" not in pod.metadata.annotations:  # type: ignore[attr-defined]  # noqa: E501
            return False
        try:
            if json.loads(pod.metadata.annotations["k8s.v1.cni.cncf.io/networks"]) != [  # type: ignore[attr-defined]  # noqa: E501
                network_annotation.dict() for network_annotation in network_annotations
            ]:
                logger.info("Existing annotation are not identical to the expected ones")
                return False
        except JSONDecodeError:
            logger.info("Existing annotations are not a valid json.")
            return False
        for container in pod.spec.containers:  # type: ignore[attr-defined]
            if container.name in containers_requiring_net_admin_capability:
                if "NET_ADMIN" not in container.securityContext.capabilities.add:
                    return False
        return True

    def network_attachment_definition_is_created(self, name: str) -> bool:
        """Returns whether a NetworkAttachmentDefinition is created.

        Args:
            name: NetworkAttachmentDefinition name

        Returns:
            bool: Whether the NetworkAttachmentDefinition is created
        """
        try:
            self.client.get(
                res=NetworkAttachmentDefinition,
                name=name,
                namespace=self.namespace,
            )
            logger.info(f"NetworkAttachmentDefinition {name} already created")
            return True
        except ApiError as e:
            if e.status.reason != "NotFound":
                raise KubernetesMultusError(
                    f"Unexpected outcome when retrieving network attachment definition {name}"
                )
            logger.info(f"NetworkAttachmentDefinition {name} not yet created")
            return False
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise KubernetesMultusError(
                    "NetworkAttachmentDefinition resource not found. "
                    "You may need to install Multus CNI."
                )
            else:
                raise KubernetesMultusError(
                    f"Unexpected outcome when retrieving network attachment definition {name}"
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
            f"NetworkAttachmentDefinition {network_attachment_definition.metadata.name} created"  # type: ignore[union-attr]  # noqa: E501, W505
        )

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
        logger.info(f"NetworkAttachmentDefinition {name} deleted")

    def patch_statefulset(
        self,
        name: str,
        network_annotations: list[NetworkAnnotation],
        containers_requiring_net_admin_capability: list[str],
    ) -> None:
        """Patches a statefulset with Multus annotation and NET_ADMIN capability.

        Args:
            name: Statefulset name
            network_annotations: List of network annotations
            containers_requiring_net_admin_capability: Containers requiring NET_ADMIN capability
        """
        if not network_annotations:
            logger.info("No network annotations were provided")
            return
        try:
            statefulset = self.client.get(res=StatefulSet, name=name, namespace=self.namespace)
        except ApiError:
            raise KubernetesMultusError(f"Could not get statefulset {name}")
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
                    spec=PodSpec(
                        containers=[
                            Container(
                                name=container_name,
                                securityContext=SecurityContext(
                                    capabilities=Capabilities(
                                        add=[
                                            "NET_ADMIN",
                                        ]
                                    )
                                ),
                            )
                            for container_name in containers_requiring_net_admin_capability
                        ]
                    ),
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
        logger.info(f"Multus annotation added to {name} statefulset")

    def statefulset_is_patched(
        self,
        name: str,
        network_annotations: list[NetworkAnnotation],
        containers_requiring_net_admin_capability: list[str],
    ) -> bool:
        """Returns whether the statefulset has the expected multus annotation.

        Args:
            name: Statefulset name.
            network_annotations: list of network annotations
            containers_requiring_net_admin_capability: Containers requiring NET_ADMIN capability

        Returns:
            bool: Whether the statefulset has the expected multus annotation.
        """
        try:
            statefulset = self.client.get(res=StatefulSet, name=name, namespace=self.namespace)
        except ApiError:
            raise KubernetesMultusError(f"Could not get statefulset {name}")
        if "k8s.v1.cni.cncf.io/networks" not in statefulset.spec.template.metadata.annotations:  # type: ignore[attr-defined]  # noqa: E501
            logger.info("Multus annotation not yet added to statefulset")
            return False
        try:
            if json.loads(
                statefulset.spec.template.metadata.annotations["k8s.v1.cni.cncf.io/networks"]  # type: ignore[attr-defined]  # noqa: E501
            ) != [network_annotation.dict() for network_annotation in network_annotations]:
                logger.info("Existing annotation are not identical to the expected ones")
                return False
        except JSONDecodeError:
            logger.info("Existing annotations are not a valid json.")
            return False
        for container in statefulset.spec.template.spec.containers:  # type: ignore[attr-defined]
            if container.name in containers_requiring_net_admin_capability:
                if "NET_ADMIN" not in container.securityContext.capabilities.add:
                    logger.info(
                        f"The NET_ADMIN capability is not added to the container {container.name}"
                    )
                    return False
        logger.info("Multus annotation already added to statefulset")
        return True


class KubernetesMultusCharmLib(Object):
    """Class to be instantiated by charms requiring Multus networking."""

    def __init__(
        self,
        charm: CharmBase,
        network_attachment_definitions: list[GenericNamespacedResource],
        network_annotations_func: Callable[[], list[NetworkAnnotation]],
        containers_requiring_net_admin_capability: Optional[list[str]] = None,
    ):
        """Constructor for the KubernetesMultusCharmLib.

        Args:
            charm: Charm object
            network_attachment_definitions: List of `NetworkAttachmentDefinition` to be created.
            network_annotations_func: A callable to a function returning a list of
                NetworkAnnotation.
            containers_requiring_net_admin_capability: List of containers requiring the "NET_ADMIN"
                capability.
        """
        super().__init__(charm, "kubernetes-multus")
        self.kubernetes = KubernetesClient(namespace=self.model.name)
        self.network_attachment_definitions = network_attachment_definitions
        self.network_annotations_func = network_annotations_func
        self.containers_requiring_net_admin_capability = (
            containers_requiring_net_admin_capability
            if containers_requiring_net_admin_capability
            else []
        )
        self.framework.observe(charm.on.config_changed, self._configure_multus)
        self.framework.observe(charm.on.remove, self._on_remove)

    def _configure_multus(self, event: EventBase) -> None:
        """Creates network attachment definitions and patches statefulset.

        Args:
            event: EventBase
        """
        for network_attachment_definition in self.network_attachment_definitions:
            if not self.kubernetes.network_attachment_definition_is_created(
                name=network_attachment_definition.metadata.name  # type: ignore[union-attr]
            ):
                self.kubernetes.create_network_attachment_definition(
                    network_attachment_definition=network_attachment_definition
                )
        if not self._statefulset_is_patched():
            self.kubernetes.patch_statefulset(
                name=self.model.app.name,
                network_annotations=self.network_annotations_func(),
                containers_requiring_net_admin_capability=self.containers_requiring_net_admin_capability,  # noqa: E501
            )

    def _network_attachment_definitions_are_created(self) -> bool:
        """Returns whether all network attachment definitions are created."""
        for network_attachment_definition in self.network_attachment_definitions:
            if not self.kubernetes.network_attachment_definition_is_created(
                name=network_attachment_definition.metadata.name  # type: ignore[union-attr]
            ):
                return False
        return True

    def _statefulset_is_patched(self) -> bool:
        """Returns whether statefuset is patched with network annotations and capabilities."""
        return self.kubernetes.statefulset_is_patched(
            name=self.model.app.name,
            network_annotations=self.network_annotations_func(),
            containers_requiring_net_admin_capability=self.containers_requiring_net_admin_capability,  # noqa: E501
        )

    def _pod_is_ready(self) -> bool:
        """Returns whether pod is ready with network annotations and capabilities."""
        return self.kubernetes.pod_is_ready(
            containers_requiring_net_admin_capability=self.containers_requiring_net_admin_capability,  # noqa: E501
            pod_name=self._pod,
            network_annotations=self.network_annotations_func(),
        )

    def is_ready(self) -> bool:
        """Returns whether Multus is ready.

        Validates that the network attachment definitions are created, that the statefulset is
        patched with the appropriate Multus annotations and capabilities and that the pod
        also contains the same annotations and capabilities.

        Returns:
            bool: Whether Multus is ready
        """
        return (
            self._network_attachment_definitions_are_created()
            and self._statefulset_is_patched()  # noqa: W503
            and self._pod_is_ready()  # noqa: W503
        )

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
        for network_attachment_definition in self.network_attachment_definitions:
            if self.kubernetes.network_attachment_definition_is_created(
                name=network_attachment_definition.metadata.name  # type: ignore[union-attr]
            ):
                self.kubernetes.delete_network_attachment_definition(
                    name=network_attachment_definition.metadata.name  # type: ignore[union-attr]
                )
