# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, patch

import pytest
import scenario

from charm import GNBSIMOperatorCharm


class GNBSUMUnitTestFixtures:
    patcher_k8s_service_patch = patch("charm.KubernetesServicePatch")
    patcher_k8s_multus = patch("charm.KubernetesMultusCharmLib")
    patcher_n2_requirer_amf_hostname = patch(
        "charm.N2Requires.amf_hostname", new_callable=PropertyMock
    )
    patcher_n2_requirer_amf_port = patch("charm.N2Requires.amf_port", new_callable=PropertyMock)
    patcher_gnb_identity_publish_information = patch(
        "charm.GnbIdentityProvides.publish_gnb_identity_information"
    )

    @pytest.fixture(autouse=True)
    def setup(self, request):
        self.mock_k8s_service_patch = GNBSUMUnitTestFixtures.patcher_k8s_service_patch.start()
        self.mock_k8s_multus = GNBSUMUnitTestFixtures.patcher_k8s_multus.start().return_value
        self.mock_n2_requirer_amf_hostname = (
            GNBSUMUnitTestFixtures.patcher_n2_requirer_amf_hostname.start()
        )
        self.mock_n2_requirer_amf_port = (
            GNBSUMUnitTestFixtures.patcher_n2_requirer_amf_port.start()
        )
        self.mock_gnb_identity_publish_information = (
            GNBSUMUnitTestFixtures.patcher_gnb_identity_publish_information.start()
        )
        yield
        request.addfinalizer(self.teardown)

    @staticmethod
    def teardown() -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = scenario.Context(
            charm_type=GNBSIMOperatorCharm,
        )
