# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import pytest
from ops import testing
from ops.charm import ActionEvent, CharmBase

from lib.charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity import GnbIdentityProvides


class DummyFivegGNBIdentityProviderCharm(CharmBase):
    """Dummy charm implementing the provider side of the fiveg_gnb_identity interface."""

    def __init__(self, *args):
        super().__init__(*args)
        self.gnb_identity_provider = GnbIdentityProvides(self, "fiveg_gnb_identity")
        self.framework.observe(
            self.on.publish_gnb_identity_information_action,
            self._on_publish_gnb_identity_information_action,
        )

    def _on_publish_gnb_identity_information_action(self, event: ActionEvent):
        relation_id = event.params.get("relation-id")
        gnb_name = event.params.get("gnb-name")
        tac = event.params.get("tac")
        assert relation_id
        assert gnb_name
        assert tac
        self.gnb_identity_provider.publish_gnb_identity_information(
            relation_id=int(relation_id), gnb_name=gnb_name, tac=tac
        )


class TestFiveGGNBIdentityProvider:
    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = testing.Context(
            charm_type=DummyFivegGNBIdentityProviderCharm,
            meta={
                "name": "gnb-identity-provider-charm",
                "provides": {"fiveg_gnb_identity": {"interface": "fiveg_gnb_identity"}},
            },
            actions={
                "publish-gnb-identity-information": {
                    "params": {
                        "relation-id": {"type": "string"},
                        "gnb-name": {"type": "string"},
                        "tac": {"type": "string"},
                    },
                },
            },
        )

    def test_given_unit_is_leader_and_data_is_valid_when_set_fiveg_gnb_identity_information_then_data_is_in_application_databag(  # noqa: E501
        self,
    ):
        fiveg_gnb_identity_relation = testing.Relation(
            endpoint="fiveg_gnb_identity",
            interface="fiveg_gnb_identity",
        )
        state_in = testing.State(
            leader=True,
            relations=[fiveg_gnb_identity_relation],
        )

        params = {
            "relation-id": str(fiveg_gnb_identity_relation.id),
            "gnb-name": "my-gnb-name",
            "tac": "1",
        }

        state_out = self.ctx.run(
            self.ctx.on.action("publish-gnb-identity-information", params=params), state_in
        )

        relation = state_out.get_relation(fiveg_gnb_identity_relation.id)
        assert relation.local_app_data["gnb_name"] == "my-gnb-name"
        assert relation.local_app_data["tac"] == "1"

    def test_given_invalid_gnb_name_when_relation_created_then_value_error_is_raised(self):
        fiveg_gnb_identity_relation = testing.Relation(
            endpoint="fiveg_gnb_identity",
            interface="fiveg_gnb_identity",
        )
        state_in = testing.State(
            leader=True,
            relations=[fiveg_gnb_identity_relation],
        )

        params = {
            "relation-id": str(fiveg_gnb_identity_relation.id),
            "gnb-name": "",
            "tac": "1",
        }

        with pytest.raises(Exception):
            self.ctx.run(
                self.ctx.on.action("publish-gnb-identity-information", params=params), state_in
            )
