# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import PropertyMock, patch

from ops import testing
from test_charms.test_provider_charm.src.charm import WhateverCharm  # type: ignore[import]

TEST_CHARM_PATH = "test_charms.test_provider_charm.src.charm.WhateverCharm"


class TestGnbIdentityProvides(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = testing.Harness(WhateverCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.relation_name = "fiveg_gnb_identity"
        self.harness.set_leader(is_leader=True)

    @patch(f"{TEST_CHARM_PATH}.TEST_GNB_NAME", new_callable=PropertyMock)
    @patch(f"{TEST_CHARM_PATH}.TEST_TAC", new_callable=PropertyMock)
    def test_given_fiveg_gnb_identity_relation_when_relation_created_then_gnb_name_and_tac_are_published_in_the_relation_data(  # noqa: E501
        self, patched_test_tac, patched_test_gnb_name
    ):
        test_gnb_name = "gnb004"
        test_tac = 2
        patched_test_gnb_name.return_value = test_gnb_name
        patched_test_tac.return_value = test_tac
        relation_id = self.harness.add_relation(
            relation_name=self.relation_name, remote_app="whatever-app"
        )
        self.harness.add_relation_unit(relation_id, "whatever-app/0")

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app
        )
        self.assertEqual(test_gnb_name, relation_data["gnb_name"])
        self.assertEqual(str(test_tac), relation_data["tac"])

    @patch(f"{TEST_CHARM_PATH}.TEST_GNB_NAME", new_callable=PropertyMock)
    @patch(f"{TEST_CHARM_PATH}.TEST_TAC", new_callable=PropertyMock)
    def test_given_invalid_gnb_name_when_relation_created_then_value_error_is_raised(
        self, patched_test_tac, patched_test_gnb_name
    ):
        test_invalid_gnb_name = None
        test_tac = 2
        patched_test_gnb_name.return_value = test_invalid_gnb_name
        patched_test_tac.return_value = test_tac

        with self.assertRaises(ValueError):
            relation_id = self.harness.add_relation(
                relation_name=self.relation_name, remote_app="whatever-app"
            )
            self.harness.add_relation_unit(relation_id, "whatever-app/0")

    @patch(f"{TEST_CHARM_PATH}.TEST_GNB_NAME", new_callable=PropertyMock)
    @patch(f"{TEST_CHARM_PATH}.TEST_TAC", new_callable=PropertyMock)
    def test_given_invalid_tac_when_relation_created_then_value_error_is_raised(
        self, patched_test_tac, patched_test_gnb_name
    ):
        test_gnb_name = "gnb005"
        test_invalid_tac = "0xffffff"
        patched_test_gnb_name.return_value = test_gnb_name
        patched_test_tac.return_value = test_invalid_tac

        with self.assertRaises(ValueError):
            relation_id = self.harness.add_relation(
                relation_name=self.relation_name, remote_app="whatever-app"
            )
            self.harness.add_relation_unit(relation_id, "whatever-app/0")
