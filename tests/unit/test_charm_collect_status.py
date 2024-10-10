# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import tempfile

import pytest
from ops import ActiveStatus, BlockedStatus, WaitingStatus, testing

from tests.unit.fixtures import GNBSUMUnitTestFixtures


class TestCharmCollectUnitStatus(GNBSUMUnitTestFixtures):
    @pytest.mark.parametrize(
        "config_param",
        [
            ("usim-opc"),
            ("gnb-ip-address"),
            ("icmp-packet-destination"),
            ("imsi"),
            ("mcc"),
            ("mnc"),
            ("usim-key"),
            ("usim-sequence-number"),
            ("sd"),
            ("tac"),
            ("upf-subnet"),
            ("upf-gateway"),
        ],
    )
    def test_given_invalid_config_when_collect_unit_status_then_status_is_blocked(
        self, config_param
    ):
        state_in = testing.State(
            leader=True,
            config={config_param: ""},
        )

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == BlockedStatus(
            f"Configurations are invalid: ['{config_param}']"
        )

    def test_given_n2_relation_not_created_when_collect_unit_status_then_status_is_waiting(self):
        state_in = testing.State(
            leader=True,
        )

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == BlockedStatus("Waiting for N2 relation to be created")

    def test_given_cant_connect_to_workload_when_collect_unit_status_then_status_is_waiting(self):
        n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
        container = testing.Container(name="gnbsim", can_connect=False)
        state_in = testing.State(leader=True, relations=[n2_relation], containers=[container])

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == WaitingStatus("Waiting for container to be ready")

    def test_given_storage_not_attached_when_collect_unit_status_then_status_is_waiting(self):
        n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
        container = testing.Container(name="gnbsim", can_connect=True)
        state_in = testing.State(leader=True, relations=[n2_relation], containers=[container])

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == WaitingStatus("Waiting for storage to be attached")

    def test_given_multus_not_available_when_collect_unit_status_then_status_is_waiting(self):
        self.mock_k8s_multus.multus_is_available.return_value = False
        n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
        container = testing.Container(
            name="gnbsim",
            can_connect=True,
            mounts={
                "config": testing.Mount(
                    location="/etc/gnbsim",
                    source=tempfile.mkdtemp(),
                )
            },
        )
        state_in = testing.State(leader=True, relations=[n2_relation], containers=[container])

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == BlockedStatus("Multus is not installed or enabled")

    def test_given_multus_not_ready_when_collect_unit_status_then_status_is_waiting(self):
        self.mock_k8s_multus.multus_is_available.return_value = True
        self.mock_k8s_multus.is_ready.return_value = False
        n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
        container = testing.Container(
            name="gnbsim",
            can_connect=True,
            mounts={
                "config": testing.Mount(
                    location="/etc/gnbsim",
                    source=tempfile.mkdtemp(),
                )
            },
        )
        state_in = testing.State(leader=True, relations=[n2_relation], containers=[container])

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == WaitingStatus("Waiting for Multus to be ready")

    def test_given_n2_information_unavailable_when_collect_unit_status_then_status_is_waiting(
        self,
    ):
        self.mock_k8s_multus.multus_is_available.return_value = True
        self.mock_k8s_multus.is_ready.return_value = True
        self.mock_n2_requirer_amf_hostname.return_value = None
        self.mock_n2_requirer_amf_port.return_value = None
        n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
        container = testing.Container(
            name="gnbsim",
            can_connect=True,
            mounts={
                "config": testing.Mount(
                    location="/etc/gnbsim",
                    source=tempfile.mkdtemp(),
                )
            },
        )
        state_in = testing.State(leader=True, relations=[n2_relation], containers=[container])

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == WaitingStatus("Waiting for N2 information")

    def test_pre_requisites_met_when_collect_unit_status_then_status_is_active(self):
        self.mock_k8s_multus.multus_is_available.return_value = True
        self.mock_k8s_multus.is_ready.return_value = True
        self.mock_n2_requirer_amf_hostname.return_value = "amf"
        self.mock_n2_requirer_amf_port.return_value = 1234
        n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
        container = testing.Container(
            name="gnbsim",
            can_connect=True,
            mounts={
                "config": testing.Mount(
                    location="/etc/gnbsim",
                    source=tempfile.mkdtemp(),
                )
            },
        )
        state_in = testing.State(leader=True, relations=[n2_relation], containers=[container])

        state_out = self.ctx.run(self.ctx.on.collect_unit_status(), state_in)

        assert state_out.unit_status == ActiveStatus()
