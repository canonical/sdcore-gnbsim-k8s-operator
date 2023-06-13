# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


"""Library for the `fiveg_n2` relation.

This library contains the Requires and Provides classes for handling the `fiveg_n2`
interface.

The purpose of this library is to relate a charm claiming
to be able to provide or consume information on connectivity to the N2 plane.

## Getting Started
From a charm directory, fetch the library using `charmcraft`:

```shell
charmcraft fetch-lib charms.sdcore_amf.v0.fiveg_n2
```

Add the following libraries to the charm's `requirements.txt` file:
- pydantic
- pytest-interface-tester

### Requirer charm
The requirer charm is the one requiring the N2 information.

Example:
```python

from ops.charm import CharmBase
from ops.main import main

from charms.sdcore_amf.v0.fiveg_n2 import N2InformationAvailableEvent, N2Requires

logger = logging.getLogger(__name__)


class DummyFivegN2Requires(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.n2_requirer = N2Requires(self, "fiveg-n2")
        self.framework.observe(
            self.n2_requirer.on.n2_information_available, self._on_n2_information_available
        )

    def _on_n2_information_available(self, event: N2InformationAvailableEvent):
        amf_ip_address = event.amf_ip_address
        amf_hostname = event.amf_hostname
        amf_port = event.amf_port
        <do something with the amf IP, hostname and port>


if __name__ == "__main__":
    main(DummyFivegN2Requires)
```

### Provider charm
The provider charm is the one providing the information about the N2 interface.

Example:
```python

from ops.charm import CharmBase, RelationJoinedEvent
from ops.main import main

from charms.sdcore_amf.v0.fiveg_n2 import N2Provides


class DummyFivegN2ProviderCharm(CharmBase):

    HOST = "amf"
    PORT = 38412
    IP_ADDRESS = "192.168.70.132"

    def __init__(self, *args):
        super().__init__(*args)
        self.n2_provider = N2Provides(self, "fiveg-n2")
        self.framework.observe(
            self.on.fiveg_n2_relation_joined, self._on_fiveg_n2_relation_joined
        )

    def _on_fiveg_n2_relation_joined(self, event: RelationJoinedEvent):
        if self.unit.is_leader():
            self.n2_provider.set_n2_information(
                amf_ip_address=self.IP_ADDRESS,
                amf_hostname=self.HOST,
                amf_port=self.PORT,
            )


if __name__ == "__main__":
    main(DummyFivegN2ProviderCharm)
```

"""

import logging
from typing import Dict, Optional

from interface_tester.schema_base import DataBagSchema  # type: ignore[import]
from ops.charm import CharmBase, CharmEvents, RelationChangedEvent
from ops.framework import EventBase, EventSource, Handle, Object
from ops.model import Relation
from pydantic import BaseModel, Field, IPvAnyAddress, ValidationError

# The unique Charmhub library identifier, never change it
LIBID = "3bb439930da24fd09631af74f70ea394"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft push-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

logger = logging.getLogger(__name__)
"""Schemas definition for the provider and requirer sides of the `fiveg_n2` interface.
It exposes two interfaces.schema_base.DataBagSchema subclasses called:
- ProviderSchema
- RequirerSchema
Examples:
    ProviderSchema:
        unit: <empty>
        app: {
            "amf_ip_address": "192.168.70.132"
            "amf_hostname": "amf",
            "amf_port": 38412
        }
    RequirerSchema:
        unit: <empty>
        app:  <empty>
"""


class ProviderAppData(BaseModel):
    """Provider app data for fiveg_n2."""

    amf_ip_address: IPvAnyAddress = Field(
        description="IP Address to reach the AMF's N2 interface.", examples=["192.168.70.132"]
    )
    amf_hostname: str = Field(
        description="Hostname to reach the AMF's N2 interface.", examples=["amf"]
    )
    amf_port: int = Field(description="Port to reach the AMF's N2 interface.", examples=[38412])


class ProviderSchema(DataBagSchema):
    """Provider schema for fiveg_n2."""

    app: ProviderAppData


def data_is_valid(data: dict) -> bool:
    """Returns whether data is valid.

    Args:
        data (dict): Data to be validated.

    Returns:
        bool: True if data is valid, False otherwise.
    """
    try:
        ProviderSchema(app=data)
        return True
    except ValidationError as e:
        logger.error("Invalid data: %s", e)
        return False


class N2InformationAvailableEvent(EventBase):
    """Charm event emitted when N2 information is available. It carries the AMF hostname."""

    def __init__(self, handle: Handle, amf_ip_address: str, amf_hostname: str, amf_port: int):
        """Init."""
        super().__init__(handle)
        self.amf_ip_address = amf_ip_address
        self.amf_hostname = amf_hostname
        self.amf_port = amf_port

    def snapshot(self) -> dict:
        """Returns snapshot."""
        return {
            "amf_ip_address": self.amf_ip_address,
            "amf_hostname": self.amf_hostname,
            "amf_port": self.amf_port,
        }

    def restore(self, snapshot: dict) -> None:
        """Restores snapshot."""
        self.amf_ip_address = snapshot["amf_ip_address"]
        self.amf_hostname = snapshot["amf_hostname"]
        self.amf_port = snapshot["amf_port"]


class N2RequirerCharmEvents(CharmEvents):
    """List of events that the N2 requirer charm can leverage."""

    n2_information_available = EventSource(N2InformationAvailableEvent)


class N2Requires(Object):
    """Class to be instantiated by the N2 requirer charm."""

    on = N2RequirerCharmEvents()

    def __init__(self, charm: CharmBase, relation_name: str):
        """Init."""
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_relation_changed)

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handler triggered on relation changed event.

        Args:
            event (RelationChangedEvent): Juju event.

        Returns:
            None
        """
        if remote_app_relation_data := self._get_remote_app_relation_data(event.relation):
            self.on.n2_information_available.emit(
                amf_ip_address=remote_app_relation_data["amf_ip_address"],
                amf_hostname=remote_app_relation_data["amf_hostname"],
                amf_port=remote_app_relation_data["amf_port"],
            )

    @property
    def amf_ip_address(self) -> Optional[str]:
        """Returns AMF IP address.

        Returns:
            str: AMF IP address.
        """
        if remote_app_relation_data := self._get_remote_app_relation_data():
            return remote_app_relation_data.get("amf_ip_address")
        return None

    @property
    def amf_hostname(self) -> Optional[str]:
        """Returns AMF hostname.

        Returns:
            str: AMF hostname.
        """
        if remote_app_relation_data := self._get_remote_app_relation_data():
            return remote_app_relation_data.get("amf_hostname")
        return None

    @property
    def amf_port(self) -> Optional[int]:
        """Returns the port used to connect to the AMF host.

        Returns:
            int: AMF port.
        """
        if remote_app_relation_data := self._get_remote_app_relation_data():
            return int(remote_app_relation_data.get("amf_port"))  # type: ignore[arg-type]
        return None

    def _get_remote_app_relation_data(
        self, relation: Optional[Relation] = None
    ) -> Optional[Dict[str, str]]:
        """Get relation data for the remote application.

        Args:
            Relation: Juju relation object (optional).

        Returns:
            Dict: Relation data for the remote application
            or None if the relation data is invalid.
        """
        relation = relation or self.model.get_relation(self.relation_name)
        if not relation:
            logger.error("No relation: %s", self.relation_name)
            return None
        if not relation.app:
            logger.warning("No remote application in relation: %s", self.relation_name)
            return None
        remote_app_relation_data = dict(relation.data[relation.app])
        if not data_is_valid(remote_app_relation_data):
            logger.error("Invalid relation data: %s", remote_app_relation_data)
            return None
        return remote_app_relation_data


class N2Provides(Object):
    """Class to be instantiated by the charm providing the N2 data."""

    def __init__(self, charm: CharmBase, relation_name: str):
        """Init."""
        super().__init__(charm, relation_name)
        self.relation_name = relation_name
        self.charm = charm

    def set_n2_information(self, amf_ip_address: str, amf_hostname: str, amf_port: int) -> None:
        """Sets the hostname and the ngapp port in the application relation data.

        Args:
            amf_ip_address (str): AMF IP address.
            amf_hostname (str): AMF hostname.
            amf_port (int): AMF NGAPP port.

        Returns:
            None
        """
        if not self.charm.unit.is_leader():
            raise RuntimeError("Unit must be leader to set application relation data.")
        relations = self.model.relations[self.relation_name]
        if not relations:
            raise RuntimeError(f"Relation {self.relation_name} not created yet.")
        if not data_is_valid(
            {"amf_ip_address": amf_ip_address, "amf_hostname": amf_hostname, "amf_port": amf_port}
        ):
            raise ValueError("Invalid relation data")
        for relation in relations:
            relation.data[self.charm.app].update(
                {
                    "amf_ip_address": amf_ip_address,
                    "amf_hostname": amf_hostname,
                    "amf_port": str(amf_port),
                }
            )
