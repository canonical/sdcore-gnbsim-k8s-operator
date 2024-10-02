# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import pytest
import scenario
from ops.charm import CharmBase

from lib.charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity import (
    GnbIdentityAvailableEvent,
    GnbIdentityRequires,
)


class DummyFivegGNBIdentityRequirerCharm(CharmBase):
    """Dummy charm implementing the requirer side of the fiveg_gnb_identity interface."""

    def __init__(self, *args):
        super().__init__(*args)
        self.gnb_identity_requirer = GnbIdentityRequires(self, "fiveg_gnb_identity")


class TestFiveGGNBIdentityProvider:
    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=DummyFivegGNBIdentityRequirerCharm,
            meta={
                "name": "gnb-identity-requirer-charm",
                "requires": {"fiveg_gnb_identity": {"interface": "fiveg_gnb_identity"}},
            },
        )

    def test_given_valid_relation_data_when_relation_changed_then_gnb_identity_available_event_is_emitted(  # noqa: E501
        self,
    ):
        fiveg_gnb_identity_relation = scenario.Relation(
            endpoint="fiveg_gnb_identity",
            interface="fiveg_gnb_identity",
            remote_app_data={
                "tac": "1",
                "gnb_name": "gnb",
            },
        )
        state_in = scenario.State(
            leader=True,
            relations=[fiveg_gnb_identity_relation],
        )

        self.ctx.run(self.ctx.on.relation_changed(fiveg_gnb_identity_relation), state_in)

        assert len(self.ctx.emitted_events) == 2
        assert isinstance(self.ctx.emitted_events[1], GnbIdentityAvailableEvent)
        assert self.ctx.emitted_events[1].gnb_name == "gnb"
        assert self.ctx.emitted_events[1].tac == "1"

    def test_given_invalid_relation_data_when_relation_changed_then_gnb_identity_available_event_not_emitted(  # noqa: E501
        self,
    ):
        fiveg_gnb_identity_relation = scenario.Relation(
            endpoint="fiveg_gnb_identity",
            interface="fiveg_gnb_identity",
            remote_app_data={
                "tac": "1",
            },
        )
        state_in = scenario.State(
            leader=True,
            relations=[fiveg_gnb_identity_relation],
        )

        self.ctx.run(self.ctx.on.relation_changed(fiveg_gnb_identity_relation), state_in)

        assert len(self.ctx.emitted_events) == 1
