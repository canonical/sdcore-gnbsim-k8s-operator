# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm Library used to leverage the Multus Kubernetes CNI in charms.

## Usage

```python

from typing import List

from charms.kubernetes_charm_libraries.v0.multus import (
    KubernetesMultusCharmLib,
    NetworkAnnotation,
    NetworkAttachmentDefinition,
)
from ops import RemoveEvent
from ops.charm import CharmBase
from ops.framework import EventBase
from ops.main import main


class YourCharm(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self._kubernetes_multus = KubernetesMultusCharmLib(
            cap_net_admin=True,
            namespace=self.model.name,
            statefulset_name=self.model.app.name,
            pod_name="-".join(self.model.unit.name.rsplit("/", 1)),
            container_name=self._bessd_container_name,
            network_annotations=self._generate_network_annotations(),
            network_attachment_definitions=self._network_attachment_definitions_from_config(),
            privileged=True,
        )

        self.framework.observe(self.on.update_status, self._on_update_status)

    def _on_update_status(self, event: EventBase):
        self._kubernetes_multus.configure()

    def _on_remove(self, _: RemoveEvent) -> None:
        self._kubernetes_multus.remove()

    def _generate_network_annotations(self) -> List[NetworkAnnotation]:
        return [
            NetworkAnnotation(
                name=ACCESS_NETWORK_ATTACHMENT_DEFINITION_NAME,
                interface_name=ACCESS_INTERFACE_NAME,
                bridge_name=ACCESS_INTERFACE_BRIDGE_NAME,
            ),
            NetworkAnnotation(
                name=CORE_NETWORK_ATTACHMENT_DEFINITION_NAME,
                interface_name=CORE_INTERFACE_NAME,
                bridge_name=CORE_INTERFACE_BRIDGE_NAME,
            ),
        ]

    def _network_attachment_definitions_from_config(self) -> List[NetworkAttachmentDefinition]:
        return [
            NetworkAttachmentDefinition(
                name=ACCESS_NETWORK_ATTACHMENT_DEFINITION_NAME,
                cni_type="macvlan",
                network_name=self.config["access_network_name"],
            ),
            NetworkAttachmentDefinition(
                name=CORE_NETWORK_ATTACHMENT_DEFINITION_NAME,
                cni_type="macvlan",
                network_name=self.config["core_network_name"],
            ),
        ]
```
"""

import json
import logging
from dataclasses import asdict, dataclass
from json.decoder import JSONDecodeError
from typing import List, Optional, Union

import httpx
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError
from lightkube.generic_resource import (
    GenericNamespacedResource,
    create_namespaced_resource,
)
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

# The unique Charmhub library identifier, never change it
LIBID = "75283550e3474e7b8b5b7724d345e3c2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 17


logger = logging.getLogger(__name__)

_NetworkAttachmentDefinition = create_namespaced_resource(
    group="k8s.cni.cncf.io",
    version="v1",
    kind="NetworkAttachmentDefinition",
    plural="network-attachment-definitions",
)


class NetworkAttachmentDefinition(_NetworkAttachmentDefinition):
    """Object to represent Kubernetes Multus NetworkAttachmentDefinition."""

    def __eq__(self, other):
        """Validate equality between two NetworkAttachmentDefinitions object."""
        assert self.metadata
        return self.metadata.name == other.metadata.name and self.spec == other.spec


@dataclass
class NetworkAnnotation:
    """NetworkAnnotation."""

    NETWORK_ANNOTATION_RESOURCE_KEY = "k8s.v1.cni.cncf.io/networks"

    name: str
    interface: str
    mac: Optional[str] = None
    ips: Optional[List[str]] = None

    def dict(self) -> dict:
        """Return a NetworkAnnotation in the form of a dictionary.

        Returns:
            dict: Dictionary representation of the NetworkAnnotation
        """
        return {key: value for key, value in asdict(self).items() if value}


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
        """Delete given pod.

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
        """Return whether pod has the requisite network annotation and NET_ADMIN capability.

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
            pod=pod,
            network_annotations=network_annotations,
            container_name=container_name,
            cap_net_admin=cap_net_admin,
            privileged=privileged,
        )

    def network_attachment_definition_is_created(
        self, network_attachment_definition: NetworkAttachmentDefinition
    ) -> bool:
        """Return whether a NetworkAttachmentDefinition is created.

        Args:
            network_attachment_definition: NetworkAttachmentDefinition

        Returns:
            bool: Whether the NetworkAttachmentDefinition is created
        """
        assert network_attachment_definition.metadata
        assert network_attachment_definition.metadata.name
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
        """Create a NetworkAttachmentDefinition.

        Args:
            network_attachment_definition: NetworkAttachmentDefinition object
        """
        assert network_attachment_definition.metadata
        assert network_attachment_definition.metadata.name
        try:
            self.client.create(  # type: ignore[call-overload]
                obj=network_attachment_definition,
                namespace=self.namespace,
            )
        except ApiError:
            raise KubernetesMultusError(
                f"Could not create NetworkAttachmentDefinition "
                f"{network_attachment_definition.metadata.name}"
            )
        logger.info(
            "NetworkAttachmentDefinition %s created",
            network_attachment_definition.metadata.name,
        )

    def list_network_attachment_definitions(self) -> list[NetworkAttachmentDefinition]:
        """List NetworkAttachmentDefinitions in a given namespace.

        Returns:
            list[NetworkAttachmentDefinition]: List of NetworkAttachmentDefinitions
        """
        try:
            return list(
                self.client.list(
                    res=NetworkAttachmentDefinition, namespace=self.namespace
                )
            )
        except ApiError:
            raise KubernetesMultusError("Could not list NetworkAttachmentDefinitions")

    def delete_network_attachment_definition(self, name: str) -> None:
        """Delete network attachment definition based on name.

        Args:
            name: NetworkAttachmentDefinition name
        """
        try:
            self.client.delete(
                res=NetworkAttachmentDefinition, name=name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesMultusError(
                f"Could not delete NetworkAttachmentDefinition {name}"
            )
        logger.info("NetworkAttachmentDefinition %s deleted", name)

    def patch_statefulset(
        self,
        name: str,
        network_annotations: list[NetworkAnnotation],
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
    ) -> None:
        """Patch a statefulset with Multus annotation and NET_ADMIN capability.

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
            statefulset = self.client.get(
                res=StatefulSet, name=name, namespace=self.namespace
            )
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
            container.securityContext.privileged = True  # type: ignore[union-attr]
        statefulset_delta = StatefulSet(
            spec=StatefulSetSpec(
                selector=statefulset.spec.selector,  # type: ignore[union-attr]
                serviceName=statefulset.spec.serviceName,  # type: ignore[union-attr]
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={
                            NetworkAnnotation.NETWORK_ANNOTATION_RESOURCE_KEY: json.dumps(
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

    def unpatch_statefulset(
        self,
        name: str,
        container_name: str,
    ) -> None:
        """Remove annotations, security privilege and NET_ADMIN capability from stateful set.

        Args:
            name: Statefulset name
            container_name: Container name
        """
        try:
            statefulset = self.client.get(
                res=StatefulSet, name=name, namespace=self.namespace
            )
        except ApiError:
            raise KubernetesMultusError(f"Could not get statefulset {name}")

        container = Container(name=container_name)
        container.securityContext = SecurityContext(
            capabilities=Capabilities(
                drop=[
                    "NET_ADMIN",
                ]
            )
        )
        container.securityContext.privileged = False  # type: ignore[reportOptionalMemberAccess]
        statefulset_delta = StatefulSet(
            spec=StatefulSetSpec(
                selector=statefulset.spec.selector,  # type: ignore[union-attr]
                serviceName=statefulset.spec.serviceName,  # type: ignore[union-attr]
                template=PodTemplateSpec(
                    metadata=ObjectMeta(
                        annotations={
                            NetworkAnnotation.NETWORK_ANNOTATION_RESOURCE_KEY: "[]"
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
            raise KubernetesMultusError(
                f"Could not remove patches from statefulset {name}"
            )
        logger.info("Multus annotation removed from %s statefulset", name)

    def statefulset_is_patched(
        self,
        name: str,
        network_annotations: list[NetworkAnnotation],
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
    ) -> bool:
        """Return whether the statefulset has the expected multus annotation.

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
            statefulset = self.client.get(
                res=StatefulSet, name=name, namespace=self.namespace
            )
        except ApiError as e:
            if e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesMultusError(f"Could not get statefulset {name}")
            return False
        if not statefulset.spec:
            return False
        return self._pod_is_patched(
            container_name=container_name,
            cap_net_admin=cap_net_admin,
            privileged=privileged,
            network_annotations=network_annotations,
            pod=statefulset.spec.template,
        )

    def _pod_is_patched(
        self,
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
        network_annotations: list[NetworkAnnotation],
        pod: Union[PodTemplateSpec, Pod],
    ) -> bool:
        """Return whether a pod is patched with network annotations and security context.

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
            annotations=pod.metadata.annotations,  # type: ignore[reportOptionalMemberAccess]
            network_annotations=network_annotations,
        ):
            return False
        if not self._container_security_context_is_set(
            containers=pod.spec.containers,  # type: ignore[reportOptionalMemberAccess]
            container_name=container_name,
            cap_net_admin=cap_net_admin,
            privileged=privileged,
        ):
            return False
        return True

    @staticmethod
    def _annotations_contains_multus_networks(
        annotations: dict, network_annotations: list[NetworkAnnotation]
    ) -> bool:
        if NetworkAnnotation.NETWORK_ANNOTATION_RESOURCE_KEY not in annotations:
            return False
        try:
            if json.loads(
                annotations[NetworkAnnotation.NETWORK_ANNOTATION_RESOURCE_KEY]
            ) != [
                network_annotation.dict() for network_annotation in network_annotations
            ]:
                return False
        except JSONDecodeError:
            return False
        return True

    @staticmethod
    def _container_security_context_is_set(
        containers: list[Container],
        container_name: str,
        cap_net_admin: bool,
        privileged: bool,
    ) -> bool:
        """Return whether container spec contains the expected security context.

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
                if (
                    cap_net_admin
                    and "NET_ADMIN" not in container.securityContext.capabilities.add  # type: ignore[operator,union-attr]
                ):
                    return False
                if privileged and not container.securityContext.privileged:  # type: ignore[union-attr]
                    return False
        return True

    def multus_is_available(self) -> bool:
        """Check whether Multus is enabled leveraging existence of NAD custom resource.

        Returns:
            bool: Whether Multus is enabled
        """
        try:
            list(
                self.client.list(
                    res=NetworkAttachmentDefinition, namespace=self.namespace
                )
            )
        except ApiError as e:
            if e.status.reason == "NotFound":
                logger.debug("NetworkAttachmentDefinition resource not found")
            elif e.status.reason == "Unauthorized":
                logger.debug("kube-apiserver not ready yet")
            else:
                raise KubernetesMultusError(
                    "Unexpected outcome when checking for Multus availability"
                )
            return False
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            else:
                raise KubernetesMultusError(
                    "Unexpected outcome when checking for Multus availability"
                )
        return True


class KubernetesMultusCharmLib:
    """Class to be instantiated by charms requiring Multus networking."""

    def __init__(
        self,
        network_attachment_definitions: List[NetworkAttachmentDefinition],
        network_annotations: List[NetworkAnnotation],
        namespace: str,
        statefulset_name: str,
        pod_name: str,
        container_name: str,
        cap_net_admin: bool = False,
        privileged: bool = False,
    ):
        """Create instance of the KubernetesMultusCharmLib.

        Args:
            network_attachment_definitions: list of `NetworkAttachmentDefinition` to be created.
            network_annotations: List of `NetworkAnnotation` to be added to the container.
            namespace: Kubernetes namespace
            statefulset_name: Statefulset name
            pod_name: Pod name
            container_name: Container name
            cap_net_admin: Container requires NET_ADMIN capability
            privileged: Container requires privileged security context
        """
        self.namespace = namespace
        self.statefulset_name = statefulset_name
        self.pod_name = pod_name
        self.kubernetes = KubernetesClient(namespace=self.namespace)
        self.network_attachment_definitions = network_attachment_definitions
        self.network_annotations = network_annotations
        self.container_name = container_name
        self.cap_net_admin = cap_net_admin
        self.privileged = privileged

    def configure(self) -> None:
        """Create network attachment definitions and patches statefulset."""
        self._configure_network_attachment_definitions()
        if not self._statefulset_is_patched():
            self.kubernetes.patch_statefulset(
                name=self.statefulset_name,
                network_annotations=self.network_annotations,
                container_name=self.container_name,
                cap_net_admin=self.cap_net_admin,
                privileged=self.privileged,
            )

    def _network_attachment_definition_created_by_charm(
        self, network_attachment_definition: NetworkAttachmentDefinition
    ) -> bool:
        """Return whether a given NetworkAttachmentDefinitions was created by this charm."""
        labels = network_attachment_definition.metadata.labels  # type: ignore[reportOptionalMemberAccess]
        if not labels:
            return False
        if "app.juju.is/created-by" not in labels:
            return False
        if labels["app.juju.is/created-by"] != self.statefulset_name:
            return False
        return True

    def _configure_network_attachment_definitions(self):
        """Configure NetworkAttachmentDefinitions in Kubernetes.

        1. Goes through the list of existing NetworkAttachmentDefinitions in Kubernetes.
        - If it was created by this charm:
          - If it is in the list of NetworkAttachmentDefinitions to create, remove it from the
            list of NetworkAttachmentDefinitions to create
          - Else, delete it
        2. Goes through the list of NetworkAttachmentDefinitions to create and create them all
        3. Detects the NAD config changes and triggers pod restart
           if any there is any modification in existing NADs
        """
        network_attachment_definitions_to_create = self.network_attachment_definitions
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
                    if not existing_network_attachment_definition.metadata:
                        logger.warning("NetworkAttachmentDefinition has no metadata")
                        continue
                    if not existing_network_attachment_definition.metadata.name:
                        logger.warning("NetworkAttachmentDefinition has no name")
                        continue
                    self.kubernetes.delete_network_attachment_definition(
                        name=existing_network_attachment_definition.metadata.name
                    )
                    nad_config_changed = True
                else:
                    network_attachment_definitions_to_create.remove(
                        existing_network_attachment_definition
                    )
        for (
            network_attachment_definition_to_create
        ) in network_attachment_definitions_to_create:
            self.kubernetes.create_network_attachment_definition(
                network_attachment_definition=network_attachment_definition_to_create
            )
        if nad_config_changed:
            # We want to trigger the pod restart once if there is a change in NADs
            # after all the NADs are configured.
            logger.warning("Restarting pod to make the new NAD configs effective.")
            self.delete_pod()

    def _network_attachment_definitions_are_created(self) -> bool:
        """Return whether all network attachment definitions are created."""
        for network_attachment_definition in self.network_attachment_definitions:
            if not self.kubernetes.network_attachment_definition_is_created(
                network_attachment_definition=network_attachment_definition
            ):
                return False
        return True

    def _statefulset_is_patched(self) -> bool:
        """Return whether statefuset is patched with network annotations and capabilities."""
        return self.kubernetes.statefulset_is_patched(
            name=self.statefulset_name,
            network_annotations=self.network_annotations,
            container_name=self.container_name,
            cap_net_admin=self.cap_net_admin,
            privileged=self.privileged,
        )

    def _pod_is_ready(self) -> bool:
        """Return whether pod is ready with network annotations and capabilities."""
        return self.kubernetes.pod_is_ready(
            pod_name=self.pod_name,
            network_annotations=self.network_annotations,
            container_name=self.container_name,
            cap_net_admin=self.cap_net_admin,
            privileged=self.privileged,
        )

    def is_ready(self) -> bool:
        """Return whether Multus is ready.

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

    def remove(self) -> None:
        """Delete network attachment definitions and removes patch."""
        self.kubernetes.unpatch_statefulset(
            name=self.statefulset_name,
            container_name=self.container_name,
        )
        for network_attachment_definition in self.network_attachment_definitions:
            if self.kubernetes.network_attachment_definition_is_created(
                network_attachment_definition=network_attachment_definition
            ):
                self.kubernetes.delete_network_attachment_definition(
                    name=network_attachment_definition.metadata.name  # type: ignore[union-attr]
                )

    def delete_pod(self) -> None:
        """Delete the pod."""
        self.kubernetes.delete_pod(self.pod_name)

    def multus_is_available(self) -> bool:
        """Check whether Multus is enabled leveraging existence of NAD custom resource.

        Returns:
            bool: Whether Multus is enabled
        """
        return self.kubernetes.multus_is_available()
