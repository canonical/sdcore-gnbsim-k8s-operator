# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for the ip-router integration

This library contains the Requires and Provides classes for interactions through the 
ip-router interface

## Getting Started

From a charm directory, fetch the library using `charmcraft`:

```shell
charmcraft fetch-lib charms.ip_router_interface.v0.ip_router_interface
```

### Provider charm
This example provider charm is all we need to listen to ip-router requirer requests.
The ip-router provider fulfills the routing function for multiple charms that are
requirers of the ip-router interface. For that reason, this charm will continuously
track and update all of the connected requirers and the networks and routes they've 
requested, which it does in a routing table. As new charms are connected and disconnected
to the relation, this routing table is automatically adds and removes the dependent
networks.

The library handles the listening and synchronization for all of the ip-router network
requests internally, which means as the charm author you don't need to worry about any
of the business logic of validating or orchestrating the relation network.

You can also listen to the `routing_table_updated` event that is emitted after the 
tables are synced.


```python
import logging, json
import ops
from charms.ip_router_interface.v0.ip_router_interface import *

class SimpleIPRouteProviderCharm(ops.CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.RouterProvider = RouterProvides(charm=self)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.RouterProvider.on.routing_table_updated, self._routing_table_updated)
        self.framework.observe(self.on.get_routing_table_action, self._action_get_routing_table)

    def _on_install(self, event: ops.InstallEvent):
        self.unit.status = ops.ActiveStatus("Ready to Provide")

    def _routing_table_updated(self, event: RoutingTableUpdatedEvent):
        routing_table = event.routing_table

        # Process the networks however you like
        implement_networks(all_networks)
        
        
    def _action_get_routing_table(self, event: ops.ActionEvent):
        all_networks = self.RouterProvider.get_flattened_routing_table()
        event.set_results({"msg": json.dumps(all_networks)})
    


if __name__ == "__main__":  # pragma: nocover
    ops.main(SimpleIPRouteProviderCharm)  # type: ignore
```

### Requirer charm
This example requirer charm shows the two available actions as a host in the network:
* get the latest list of all networks available from the provider
* request a network to be assigned to the requirer charm

The ip-router requirer allows a foolproof, typechecked, secure and safe way to 
interact with the router that handles validation and format of the network 
request, so you can focus on more important things. The library also provides a
way to list out all of the available networks. This list is not cached, and comes
directly from the provider.

```python
import logging, json
import ops

from charms.ip_router_interface.v0.ip_router_interface import *

class SimpleIPRouteRequirerCharm(ops.CharmBase):

    def __init__(self, *args):
        super().__init__(*args)
        self.RouterRequirer = RouterRequires(charm=self)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.ip_router_relation_joined, self._on_relation_joined)
        self.framework.observe(self.RouterRequirer.on.routing_table_updated, self._routing_table_updated)

        self.framework.observe(self.on.get_all_networks_action, self._action_get_all_networks)
        self.framework.observe(self.on.request_network_action, self._action_request_network)

    def _on_install(self, event: ops.InstallEvent):
        self.unit.status = ops.ActiveStatus("Ready to Provide")

    def _on_relation_joined(self, event: ops.RelationJoinedEvent):
        self.unit.status = ops.ActiveStatus("Ready to Require")

    def _routing_table_updated(self, event: RoutingTableUpdatedEvent):
        # Get and process all of the available networks when they're updated
        all_networks = self.RouterRequirer.get_all_networks()

    def _action_get_all_networks(self, event: ops.ActionEvent):
        # Get and process all of the available networks any time you like
        all_networks = self.RouterRequirer.get_all_networks()
        event.set_results({"msg": json.dumps(all_networks)})

    def _action_request_network(self, event: ops.ActionEvent):
        # Request a new network as required in the required format
        self.RouterRequirer.request_network(event.params["network"])

        event.set_results({"msg": "ok"})


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(SimpleIPRouteRequirerCharm)  # type: ignore
```

You can relate both charms by running:

```bash
juju integrate <ip-router provider charm> <ip-router requirer charm>
```
"""  # noqa: D405, D410, D411, D214, D416

# The unique Charmhub library identifier, never change it
LIBID = "8bed752769244d9ba01c61d5647683cf"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 3

from ipaddress import IPv4Address, IPv4Network
from typing import Dict, List, Union, TypeAlias
from ops.framework import Object, EventSource, EventBase, ObjectEvents
from ops.charm import CharmBase
from ops import RelationChangedEvent, RelationDepartedEvent, Relation
import logging, json

logger = logging.getLogger(__name__)

Network: TypeAlias = Dict[
    str,  # 'network' | 'gateway' | 'routes'
    Union[
        IPv4Address,  # gateway, ex: '192.168.250.1'
        IPv4Network,  # network, ex: '192.168.250.0/24'
        List[  # List of routes
            Dict[
                str,  # 'destination' | 'gateway'
                Union[
                    IPv4Address,  # gateway, ex: '192.168.250.3'
                    IPv4Network,  # destination, ex: '172.250.0.0/16'
                ],
            ]
        ],
    ],
]

RoutingTable: TypeAlias = Dict[
    str,  # Name of the application
    List[Network],  # All networks for this application
]


class RoutingTableUpdatedEvent(EventBase):
    """
    Charm event for when a host registers a route to an existing interface in the router
    """

    def __init__(self, handle, routing_table=None):
        super().__init__(handle)
        self.routing_table = routing_table

    def snapshot(self):
        return {"data": self.routing_table}

    def restore(self, snapshot):
        self.routing_table = snapshot["data"]


class RouterProviderCharmEvents(ObjectEvents):
    routing_table_updated = EventSource(RoutingTableUpdatedEvent)


class RouterRequirerCharmEvents(ObjectEvents):
    routing_table_updated = EventSource(RoutingTableUpdatedEvent)


def _validate_network(network_request: Network, existing_routing_table: RoutingTable):
    """Validates the network configuration created by the ip-router requirer

    The requested network must have all of the required keys as indicated in the
    Network type ('gateway' and 'network'), the gateway has to be located within
    the network, and all of the routes need to have a path through the top level
    network. The requested network must also be previously unassigned by the
    provider.

    Args:
        network_request:
            An object of type `Network` that will be validated.
        new_networks:
            The rest of the networks to check if this one is mutually
            exclusive to the rest of the subnets.

    Raises:
        ValueError:
            Reasons could be that the gateway is not within the network,
            there is no route to the destination, the network is already
            taken or the same network is requested twice.
        KeyError:
            Missing required key
    """
    if "gateway" not in network_request:
        raise KeyError("Key 'gateway' not found.")

    if "network" not in network_request:
        raise KeyError("Key 'network' not found.")

    gateway = IPv4Address(network_request.get("gateway"))
    network = IPv4Network(network_request.get("network"))

    if gateway not in network:
        ValueError("Chosen gateway not within given network.")

    for route in network_request.get("routes", []):
        if "gateway" not in route:
            raise KeyError("Key 'gateway' not found in route.")

        if "destination" not in route:
            raise KeyError("Key 'destination' not found in route.")
        route_gateway = IPv4Address(route["gateway"])
        if route_gateway not in network:
            raise ValueError("There is no route to this destination from the network.")

    for existing_network_list in existing_routing_table.values():
        for existing_network in existing_network_list:
            old_subnet = IPv4Network(existing_network["network"])
            new_subnet = IPv4Network(network_request["network"])

            if old_subnet.subnet_of(new_subnet) or old_subnet.supernet_of(new_subnet):
                raise ValueError("This network has been defined in a previous entry.")


def _network_name_taken(name: str, relations: List[Relation]) -> bool:
    count = 0
    for relation in relations:
        if name == relation.data[relation.app].get("network-name"):
            count += 1

    if count > 1:
        logger.error(
            "There are multiple relations with the name (%s). Please change one or provide a custom network name.",
            name,
        )
        return True
    return False


class RouterProvides(Object):
    """This class is used to manage the routing table of the router provider.

    It's capabilities are to:
    * Build a Routing Table from all of the databags of the requirers with their
    declared networks.
    * Synchronize the databags of all requiring units with the aforementioned
    routing table.
    * Send events indicating a change in this table.

    Attributes:
        charm:
            The Charm object that instantiates this class.
        relationship_name:
            The name used for the relationship implementing the ip-router interface.
            All requirers that integrate to this name are grouped into one routing table.
            "ip-router" by default.
    """

    on = RouterProviderCharmEvents()

    def __init__(self, charm: CharmBase, relation_name: str = "ip-router"):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self.framework.observe(
            charm.on[relation_name].relation_changed, self._router_relation_changed
        )
        self.framework.observe(
            charm.on[relation_name].relation_departed, self._router_relation_departed
        )

    def _router_relation_changed(self, event: RelationChangedEvent):
        """Resync the databags since there could have been a change in networks."""
        if not self.charm.unit.is_leader():
            return
        self._sync_routing_tables()
        new_table = self.get_routing_table()
        self.on.routing_table_updated.emit({"networks": new_table})

    def _router_relation_departed(self, event: RelationDepartedEvent):
        """If an application has completely departed the relation, remove it
        from the routing table.
        """
        if not self.charm.unit.is_leader():
            return
        self._sync_routing_tables()
        new_table = self.get_routing_table()
        self.on.routing_table_updated.emit({"networks": new_table})

    def get_routing_table(self) -> RoutingTable:
        """Build the routing table from all of the related databags. Relations
        that don't have missing or invalid network requests will be ignored.
        """
        router_relations = self.model.relations[self.relation_name]
        final_routing_table: RoutingTable = {}
        for relation in router_relations:
            new_network_name = relation.data[relation.app].get("network-name", None)
            new_network_request: List[Network] = json.loads(
                relation.data[relation.app].get("networks", "{}")
            )

            if (
                not new_network_name
                or not new_network_request
                or _network_name_taken(new_network_name, router_relations)
            ):
                continue

            final_routing_table[new_network_name] = []

            for network in new_network_request:
                try:
                    _validate_network(network, final_routing_table)
                except (ValueError, KeyError) as e:
                    logger.error(
                        "Exception (%s) occurred with network %s. Skipping this entry.",
                        e.args[0],
                        network,
                    )
                else:
                    final_routing_table[new_network_name].append(network)
                    logger.debug(
                        "Added (%s) from app:(%s) with relation-name:(%s)",
                        new_network_request,
                        relation.app.name,
                        new_network_name,
                    )

        logger.debug("Generated rt: %s", final_routing_table)
        return final_routing_table

    def get_flattened_routing_table(self) -> List[Network]:
        """Returns a read-only routing table that's flattened to fit the specification.
        The routing table is in the form of
        {
            app1_name: list_of_networks_1,
            app2_name: list_of_networks_2,
            ...
        }

        A flattened table looks like
        [
            *list_of_networks_1,
            *list_of_networks_2,
            ...
        ]

        Returns:
            A list of objects of type `Network`
        """
        internal_routing_table = self.get_routing_table()
        final_routing_table: List[Network] = []
        for networks in internal_routing_table.values():
            final_routing_table.extend(networks)
        logger.debug("Flattened RT to %s", final_routing_table)
        return final_routing_table

    def _sync_routing_tables(self) -> None:
        """Syncs the internal routing table with all of the requirer's app databags"""
        routing_table = self.get_routing_table()
        for relation in self.model.relations[self.relation_name]:
            relation.data[self.charm.app].update({"networks": json.dumps(routing_table)})
        logger.info("Resynchronized routing tables with %s", routing_table)


class RouterRequires(Object):
    """ip-router requirer class to be instantiated by charms that require routing

    This class provides methods to request a new network, and read the available
    network from the router providers. These should be used exclusively to
    interact with the relation.

    Attributes:
        charm: The Charm object that instantiates this class.
    """

    on = RouterRequirerCharmEvents()

    def __init__(self, charm: CharmBase, relation_name: str = "ip-router"):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self.framework.observe(
            charm.on[relation_name].relation_changed, self._router_relation_changed
        )

    def _router_relation_changed(self, event: RelationChangedEvent):
        new_table = self.get_routing_table()
        self.on.routing_table_updated.emit({"networks": new_table})

    def request_network(
        self, requested_networks: List[Network], custom_network_name: str = None
    ) -> None:
        """Requests a new network interface from the ip-router provider

        The interfaces must be valid according to `_network_is_valid`. Multiple
        calls to this function will replace the previously requested networks,
        so all of the networks required must be given with each call.

        Arguments:
            networks:
                A list containing the desired networks of the type `Network`.
            custom_network_name:
                A string to use as the name of the network. Defaults to the relation
                name.

        Raises:
            RuntimeError:
                No ip-router relation exists yet or validation of one
            or more of the networks failed.
        """
        if not self.charm.unit.is_leader():
            return

        ip_router_relations = self.model.relations.get(self.relation_name)
        if len(ip_router_relations) == 0:
            raise RuntimeError("No ip-router relation exists yet.")

        try:
            existing_routing_table = self.get_routing_table()
            for i, network_request in enumerate(requested_networks):
                other_requested_networks = requested_networks[i + 1 :]
                _validate_network(network_request, existing_routing_table)
                _validate_network(
                    network_request, {"other-requested-networks": other_requested_networks}
                )
        except (ValueError, KeyError) as e:
            logger.error(
                "Exception (%s) occurred with network request. No routes were added.", e.args[0]
            )
            raise

        for relation in ip_router_relations:
            network_name = custom_network_name if custom_network_name else relation.name
            relation.data[self.charm.app].update({"networks": json.dumps(requested_networks)})
            relation.data[self.charm.app].update({"network-name": network_name})
        logger.debug(
            "Requested new network from the routers %s",
            str([r.name for r in ip_router_relations]),
        )

    def get_routing_table(self) -> RoutingTable:
        """Fetches combined routing tables made available by ip-router providers

        Returns:
            An object of type `RoutingTable` as defined in this file.
        """
        if not self.charm.unit.is_leader():
            return

        router_relations = self.model.relations.get(self.relation_name)
        validated_routing_table: RoutingTable = {}
        for relation in router_relations:
            if relation_data := relation.data[relation.app].get("networks"):
                routing_table_from_databag: RoutingTable = json.loads(relation_data)
                if not isinstance(routing_table_from_databag, dict):
                    logger.error(
                        "The router's routing table has been misconfigured. Can't build routing table."
                    )
                    return {}
                for network_name, networks in routing_table_from_databag.items():
                    validated_routing_table[network_name] = []
                    for network in networks:
                        try:
                            _validate_network(network, validated_routing_table)
                        except (ValueError, KeyError) as e:
                            logger.warning(
                                "Malformed network detected in the databag:\nNetwork: (%s)\nError: (%s)",
                                network,
                                e.args[0],
                            )
                        else:
                            validated_routing_table[network_name].append(network)
                logger.debug(
                    "Read networks from app: (%s) and relation: (%s)",
                    relation.app.name,
                    self.relation_name,
                )
        return validated_routing_table

    def get_all_networks(self) -> List[Network]:
        """Fetches combined routing tables made available by ip-router providers

        Returns:
            A list of objects of type `Network`. This list contains networks
            from all ip-router providers that are integrated with the charm.
        """
        if not self.charm.unit.is_leader():
            return

        router_relations = self.model.relations.get(self.relation_name)
        all_networks = []
        for relation in router_relations:
            if relation_data := relation.data[relation.app].get("networks"):
                routing_table_from_databag: RoutingTable = json.loads(relation_data)
                if not isinstance(routing_table_from_databag, dict):
                    logger.error(
                        "The router's routing table has been misconfigured. Can't build routing table."
                    )
                    return
                for _, networks in routing_table_from_databag.items():
                    for network in networks:
                        try:
                            _validate_network(network, {"existing-networks": all_networks})
                        except (ValueError, KeyError) as e:
                            logger.warning(
                                "Malformed network detected in the databag:\nNetwork: (%s)\nError: (%s)",
                                network,
                                e.args[0],
                            )
                        else:
                            all_networks.append(network)
                logger.debug(
                    "Read networks from app: (%s) and relation: (%s)",
                    relation.app.name,
                    self.relation_name,
                )
        return all_networks