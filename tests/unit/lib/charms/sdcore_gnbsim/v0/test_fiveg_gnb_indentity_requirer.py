# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import call, patch

from ops import testing
from test_charms.test_requirer_charm.src.charm import WhateverCharm  # type: ignore[import]

TEST_CHARM_PATH = "charms.sdcore_gnbsim.v0.fiveg_gnb_identity.GnbIdentityRequirerCharmEvents"


class TestGnbIdentityRequires(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = testing.Harness(WhateverCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.relation_name = "fiveg_gnb_identity"

    @patch(f"{TEST_CHARM_PATH}.fiveg_gnb_identity_available")
    def test_given_relation_with_gnb_identity_provider_when_gnb_identity_available_event_then_gnb_identity_information_is_provided(  # noqa: E501
        self, patched_gnb_identity_available_event
    ):
        test_gnb_name = "gnb0055"
        test_tac = 1234
        relation_id = self.harness.add_relation(
            relation_name=self.relation_name, remote_app="whatever-app"
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
        patched_gnb_identity_available_event.assert_has_calls(calls)
