# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import call, patch

import pytest
from ops import BoundEvent, testing

from tests.unit.lib.charms.sdcore_gnbsim.v0.test_charms.test_requirer_charm.src.charm import (
    WhateverCharm,
)

TEST_CHARM_PATH = "charms.sdcore_gnbsim_k8s.v0.fiveg_gnb_identity.GnbIdentityRequirerCharmEvents"
RELATION_NAME = "fiveg_gnb_identity"


class TestGnbIdentityRequires:
    patcher_gnb_identity = patch(f"{TEST_CHARM_PATH}.fiveg_gnb_identity_available")

    @pytest.fixture()
    def setUp(self) -> None:
        self.mock_gnb_identity = TestGnbIdentityRequires.patcher_gnb_identity.start()
        self.mock_gnb_identity.__class__ = BoundEvent

    def tearDown(self) -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def setup_harness(self, setUp, request):
        self.harness = testing.Harness(WhateverCharm)
        self.harness.begin()
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.tearDown)

    def test_given_relation_with_gnb_identity_provider_when_gnb_identity_available_event_then_gnb_identity_information_is_provided(  # noqa: E501
        self,
    ):
        test_gnb_name = "gnb0055"
        test_tac = 1234
        relation_id = self.harness.add_relation(
            relation_name=RELATION_NAME, remote_app="whatever-app"
        )
        self.harness.add_relation_unit(relation_id, "whatever-app/0")

        self.harness.update_relation_data(
            relation_id=relation_id,
            app_or_unit="whatever-app",
            key_values={"gnb_name": test_gnb_name, "tac": str(test_tac)},
        )

        calls = [
            call.emit(gnb_name=test_gnb_name, tac=str(test_tac)),
        ]
        self.mock_gnb_identity.assert_has_calls(calls)
