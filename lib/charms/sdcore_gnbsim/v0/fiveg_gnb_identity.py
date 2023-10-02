# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for the `fiveg_gnb_identity` relation.

This library contains the Requires and Provides classes for handling the `fiveg_gnb_identity`
interface.

The purpose of this library is to provide a way for gNodeB's to share their identity with the charms which require this information.

To get started using the library, you need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.sdcore_gnbsim.v0.fiveg_gnb_identity
```

Add the following libraries to the charm's `requirements.txt` file:
- pydantic
- pytest-interface-tester

Charms providing the `fiveg_gnb_identity` relation should use `GnbIdentityProvides`.
Typical usage of this class would look something like:

    ```python
    ...
    from charms.sdcore_gnbsim.v0.fiveg_gnb_identity import GnbIdentityProvides
    ...

    class SomeProviderCharm(CharmBase):

        def __init__(self, *args):
            ...
            self.gnb_identity_provider = GnbIdentityProvides(charm=self, relation_name="fiveg_gnb_identity")
            ...
            self.framework.observe(self.gnb_identity_provider.on.fiveg_gnb_identity_request, self._on_fiveg_gnb_identity_request)

        def _on_fiveg_gnb_identity_request(self, event):
            ...
            self.gnb_identity_provider.publish_gnb_identity_information(
                relation_id=event.relation_id,
                gnb_name=name,
                tac=tac,
            )
    ```

    And a corresponding section in charm's `metadata.yaml`:
    ```
    provides:
        fiveg_gnb_identity:  # Relation name
            interface: fiveg_gnb_identity  # Relation interface
    ```

Charms that require the `fiveg_gnb_identity` relation should use `GnbIdentityRequires`.
Typical usage of this class would look something like:

    ```python
    ...
    from charms.sdcore_gnbsim.v0.fiveg_gnb_identity import GnbIdentityRequires
    ...

    class SomeRequirerCharm(CharmBase):

        def __init__(self, *args):
            ...
            self.fiveg_gnb_identity = GnbIdentityRequires(charm=self, relation_name="fiveg_gnb_identity")
            ...
            self.framework.observe(self.fiveg_gnb_identity.on.fiveg_gnb_identity_available, 
                self._on_fiveg_gnb_identity_available)

        def _on_fiveg_gnb_identity_available(self, event):
            gnb_name = event.gnb_name,
            tac = event.tac,
            # Do something with the gNB's name and TAC.
    ```

    And a corresponding section in charm's `metadata.yaml`:
    ```
    requires:
        fiveg_gnb_identity:  # Relation name
            interface: fiveg_gnb_identity  # Relation interface
    ```
"""

import logging

from interface_tester.schema_base import DataBagSchema  # type: ignore[import]
from ops.charm import CharmBase, CharmEvents, RelationChangedEvent, RelationJoinedEvent
from ops.framework import EventBase, EventSource, Handle, Object
from pydantic import BaseModel, Field, ValidationError

# The unique Charmhub library identifier, never change it
LIBID = "ca9a66c5806e47e7b2750e8cdf696b80"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

PYDEPS = ["pydantic", "pytest-interface-tester"]


logger = logging.getLogger(__name__)

"""Schemas definition for the provider and requirer sides of the `fiveg_gnb_identity` interface.
It exposes two interfaces.schema_base.DataBagSchema subclasses called:
- ProviderSchema
- RequirerSchema

Examples:
    ProviderSchema:
        unit: <empty>
        app: {
            "gnb_name": "gnb001",
            "tac": 1
        }
    RequirerSchema:
        unit: <empty>
        app:  <empty>
"""


class FivegGnbIdentityProviderAppData(BaseModel):
    """Provider app data for fiveg_gnb_identity."""

    gnb_name: str = Field(
        description="Name of the gnB.",
        examples=["gnb001"]
    )
    tac: int = Field(
        description="Tracking Area Code",
        examples=[1]
    )

class ProviderSchema(DataBagSchema):
    """Provider schema for fiveg_gnb_identity."""

    app: FivegGnbIdentityProviderAppData


def data_matches_provider_schema(data: dict) -> bool:
    """Returns whether data matches provider schema.

    Args:
        data (dict): Data to be validated.

    Returns:
        bool: True if data matches provider schema, False otherwise.
    """
    try:
        ProviderSchema(app=data)
        return True
    except ValidationError as e:
        logger.error("Invalid data: %s", e)
        return False


class FivegGnbIdentityRequestEvent(EventBase):
    """Dataclass for the `fiveg_gnb_identity` request event."""

    def __init__(self, handle: Handle, relation_id: int):
        """Sets relation id.
        
        Args:
            handle (Handle): Juju framework handle.
            relation_id : ID of the relation.
        """
        super().__init__(handle)
        self.relation_id = relation_id

    def snapshot(self) -> dict:
        """Returns event data.
        
        Returns:
            (dict): contains the relation ID.
        """
        return {
            "relation_id": self.relation_id,
        }

    def restore(self, snapshot: dict) -> None:
        """Restores event data.
        
        Args:
            snapshot (dict): contains the relation ID.
        """
        self.relation_id = snapshot["relation_id"]


class GnbIdentityProviderCharmEvents(CharmEvents):
    """Custom events for the GnbIdentityProvider."""

    fiveg_gnb_identity_request = EventSource(FivegGnbIdentityRequestEvent)


class GnbIdentityProvides(Object):
    """Class to be instantiated by provider of the `fiveg_gnb_identity`."""

    on = GnbIdentityProviderCharmEvents()

    def __init__(self, charm: CharmBase, relation_name: str):
        """Observes relation joined event.

        Args:
            charm: Juju charm
            relation_name (str): Relation name
        """
        self.relation_name = relation_name
        self.charm = charm
        super().__init__(charm, relation_name)
        self.framework.observe(charm.on[relation_name].relation_joined, self._on_relation_joined)

    def publish_gnb_identity_information(
        self, relation_id: int, gnb_name: str, tac: int
    ) -> None:
        """Sets gNodeB's name and TAC in the relation data.

        Args:
            relation_id (str): Relation ID
            gnb_name (str): name of the gNodeB.
            tac (int): Tracking Area Code.
        """
        if not data_matches_provider_schema(
            data={"gnb_name": gnb_name, "tac": tac}
        ):
            raise ValueError(f"Invalid gnb identity data: {gnb_name}, {tac}")
        relation = self.model.get_relation(
            relation_name=self.relation_name, relation_id=relation_id
        )
        if not relation:
            raise RuntimeError(f"Relation {self.relation_name} not created yet.")
        relation.data[self.charm.app]["gnb_name"] = gnb_name
        relation.data[self.charm.app]["tac"] = str(tac)

    def _on_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Triggered whenever a requirer charm joins the relation.

        Args:
            event (RelationJoinedEvent): Juju event
        """
        self.on.fiveg_gnb_identity_request.emit(relation_id=event.relation.id)


class GnbIdentityAvailableEvent(EventBase):
    """Dataclass for the `fiveg_gnb_identity` available event."""

    def __init__(self, handle: Handle, gnb_name: str, tac: str):
        """Sets gNodeB's name and TAC."""
        super().__init__(handle)
        self.gnb_name = gnb_name
        self.tac = tac

    def snapshot(self) -> dict:
        """Returns event data."""
        return {
            "gnb_name": self.gnb_name,
            "tac": self.tac,
        }

    def restore(self, snapshot: dict) -> None:
        """Restores event data.
        
        Args:
            snapshot (dict): contains information to be restored.
        """
        self.gnb_name = snapshot["gnb_name"]
        self.tac = snapshot["tac"]


class GnbIdentityRequirerCharmEvents(CharmEvents):
    """Custom events for the GnbIdentityRequirer."""

    fiveg_gnb_identity_available = EventSource(GnbIdentityAvailableEvent)


class GnbIdentityRequires(Object):
    """Class to be instantiated by requirer of the `fiveg_gnb_identity`."""

    on = GnbIdentityRequirerCharmEvents()

    def __init__(self, charm: CharmBase, relation_name: str):
        """Observes relation joined and relation changed events.

        Args:
            charm: Juju charm
            relation_name (str): Relation name
        """
        self.relation_name = relation_name
        self.charm = charm
        super().__init__(charm, relation_name)
        self.framework.observe(charm.on[relation_name].relation_joined, self._on_relation_changed)
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_relation_changed)

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Triggered everytime there's a change in relation data.

        Args:
            event (RelationChangedEvent): Juju event
        """
        relation_data = event.relation.data
        gnb_name = relation_data[event.app].get("gnb_name")  # type: ignore[index]
        tac = relation_data[event.app].get("tac")  # type: ignore[index]
        if gnb_name and tac:
            self.on.fiveg_gnb_identity_available.emit(gnb_name=gnb_name, tac=tac)