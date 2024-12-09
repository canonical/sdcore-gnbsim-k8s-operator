# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import PropertyMock, patch

import pytest
from ops import testing

from charm import GNBSIMOperatorCharm


class GNBSUMUnitTestFixtures:
    patcher_k8s_service_patch = patch("charm.KubernetesServicePatch")
    patcher_k8s_multus = patch("charm.KubernetesMultusCharmLib")
    patcher_n2_requirer_amf_hostname = patch(
        "charm.N2Requires.amf_hostname", new_callable=PropertyMock
    )
    patcher_n2_requirer_amf_port = patch("charm.N2Requires.amf_port", new_callable=PropertyMock)
    patcher_publish_gnb_information = patch("charm.FivegCoreGnbRequires.publish_gnb_information")
    patcher_gnb_core_remote_tac = patch(
        "charm.FivegCoreGnbRequires.tac", new_callable=PropertyMock
    )
    patcher_gnb_core_remote_plmns = patch(
        "charm.FivegCoreGnbRequires.plmns", new_callable=PropertyMock
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
        self.mock_publish_gnb_information = (
            GNBSUMUnitTestFixtures.patcher_publish_gnb_information.start()
        )
        self.mock_gnb_core_remote_tac = (
            GNBSUMUnitTestFixtures.patcher_gnb_core_remote_tac.start()
        )
        self.mock_gnb_core_remote_plmns = (
            GNBSUMUnitTestFixtures.patcher_gnb_core_remote_plmns.start()
        )
        yield
        request.addfinalizer(self.teardown)

    @staticmethod
    def teardown() -> None:
        patch.stopall()

    @pytest.fixture(autouse=True)
    def context(self):
        self.ctx = testing.Context(
            charm_type=GNBSIMOperatorCharm,
        )
