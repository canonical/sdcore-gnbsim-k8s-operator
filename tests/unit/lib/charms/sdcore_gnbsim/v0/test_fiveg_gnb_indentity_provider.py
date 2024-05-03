# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, patch

import pytest
from ops import testing
from test_charms.test_provider_charm.src.charm import WhateverCharm  # type: ignore[import]

TEST_CHARM_PATH = "test_charms.test_provider_charm.src.charm.WhateverCharm"
RELATION_NAME = "fiveg_gnb_identity"

class TestGnbIdentityProvides:
    patcher_gnb_name = patch(f"{TEST_CHARM_PATH}.TEST_GNB_NAME", new_callable=PropertyMock)
    patcher_tac = patch(f"{TEST_CHARM_PATH}.TEST_TAC", new_callable=PropertyMock)

    @pytest.fixture()
    def setUp(self) -> None:
        self.mock_gnb_name = TestGnbIdentityProvides.patcher_gnb_name.start()
        self.mock_tac = TestGnbIdentityProvides.patcher_tac.start()

    def tearDown(self) -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def harness(self, setUp, request):
        self.harness = testing.Harness(WhateverCharm)
        self.harness.begin()
        self.harness.set_leader(is_leader=True)
        yield self.harness
        self.harness.cleanup()
        request.addfinalizer(self.tearDown)

    def test_given_fiveg_gnb_identity_relation_when_relation_created_then_gnb_name_and_tac_are_published_in_the_relation_data(  # noqa: E501
        self
    ):
        test_gnb_name = "gnb004"
        test_tac = 2
        self.mock_gnb_name.return_value = test_gnb_name
        self.mock_tac.return_value = test_tac
        relation_id = self.harness.add_relation(
            relation_name=RELATION_NAME, remote_app="whatever-app"
        )
        self.harness.add_relation_unit(relation_id, "whatever-app/0")

        relation_data = self.harness.get_relation_data(
            relation_id=relation_id, app_or_unit=self.harness.charm.app
        )
        assert test_gnb_name == relation_data["gnb_name"]
        assert str(test_tac) == relation_data["tac"]

    def test_given_invalid_gnb_name_when_relation_created_then_value_error_is_raised(self):
        test_invalid_gnb_name = None
        test_tac = 2
        self.mock_gnb_name.return_value = test_invalid_gnb_name
        self.mock_tac.return_value = test_tac

        with pytest.raises(ValueError):
            relation_id = self.harness.add_relation(
                relation_name=RELATION_NAME, remote_app="whatever-app"
            )
            self.harness.add_relation_unit(relation_id, "whatever-app/0")

    def test_given_invalid_tac_when_relation_created_then_value_error_is_raised(self):
        test_gnb_name = "gnb005"
        test_invalid_tac = "0xffffff"
        self.mock_gnb_name.return_value = test_gnb_name
        self.mock_tac.return_value = test_invalid_tac

        with pytest.raises(ValueError):
            relation_id = self.harness.add_relation(
                relation_name=RELATION_NAME, remote_app="whatever-app"
            )
            self.harness.add_relation_unit(relation_id, "whatever-app/0")
