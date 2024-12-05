# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import os
import tempfile

from charms.sdcore_nms_k8s.v0.fiveg_core_gnb import PLMNConfig
from ops import testing

from tests.unit.fixtures import GNBSUMUnitTestFixtures


class TestCharmConfigure(GNBSUMUnitTestFixtures):
    def test_given_config_file_not_pushed_when_configure_then_config_file_is_pushed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.mock_k8s_multus.multus_is_available.return_value = True
            self.mock_k8s_multus.is_ready.return_value = True
            self.mock_n2_requirer_amf_hostname.return_value = "amf"
            self.mock_n2_requirer_amf_port.return_value = 38412
            self.mock_gnb_core_remote_tac.return_value = 1
            plmns = [PLMNConfig(mcc="001", mnc="01", sst=1, sd=102030)]
            self.mock_gnb_core_remote_plmns.return_value = plmns
            core_gnb_relation = testing.Relation(
                endpoint="fiveg_core_gnb", interface="fiveg_core_gnb"
            )
            n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
            container = testing.Container(
                name="gnbsim",
                can_connect=True,
                mounts={
                    "config": testing.Mount(
                        location="/etc/gnbsim",
                        source=temp_dir,
                    )
                },
                execs={
                    testing.Exec(
                        command_prefix=[
                            "ip",
                            "route",
                            "replace",
                            "192.168.252.0/24",
                            "via",
                            "192.168.251.1",
                        ]
                    )
                },
            )
            state_in = testing.State(
                leader=True,
                relations=[n2_relation, core_gnb_relation],
                containers=[container],
            )

            self.ctx.run(self.ctx.on.update_status(), state_in)

            with open(f"{temp_dir}/gnb.conf", "r") as f:
                actual_config_file = f.read()

            with open("tests/unit/expected_config.yaml", "r") as f:
                expected_config_file = f.read()

            assert actual_config_file == expected_config_file


    def test_given_core_gnb_relation_relation_when_configure_then_gnb_information_is_provided(
        self
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.mock_k8s_multus.multus_is_available.return_value = True
            self.mock_k8s_multus.is_ready.return_value = True
            self.mock_n2_requirer_amf_hostname.return_value = "amf"
            self.mock_n2_requirer_amf_port.return_value = 38412
            self.mock_gnb_core_remote_tac.return_value = 1
            self.mock_gnb_core_remote_plmns.return_value = None
            n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
            core_gnb_relation = testing.Relation(
                endpoint="fiveg_core_gnb", interface="fiveg_core_gnb"
            )
            container = testing.Container(
                name="gnbsim",
                can_connect=True,
                mounts={
                    "config": testing.Mount(
                        location="/etc/gnbsim",
                        source=temp_dir,
                    )
                },
                execs={
                    testing.Exec(
                        command_prefix=[
                            "ip",
                            "route",
                            "replace",
                            "192.168.252.0/24",
                            "via",
                            "192.168.251.1",
                        ]
                    )
                },
            )
            state_in = testing.State(
                leader=True,
                relations=[n2_relation, core_gnb_relation],
                containers=[container],
                model=testing.Model(name="my-model"),
            )

            self.ctx.run(self.ctx.on.update_status(), state_in)

            self.mock_publish_gnb_information.assert_called_once_with(
                gnb_name="my-model-gnbsim-sdcore-gnbsim-k8s"
            )

    def test_given_core_gnb_information_unavailable_when_configure_then_config_file_is_not_pushed(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.mock_k8s_multus.multus_is_available.return_value = True
            self.mock_k8s_multus.is_ready.return_value = True
            self.mock_n2_requirer_amf_hostname.return_value = "amf"
            self.mock_n2_requirer_amf_port.return_value = 38412
            self.mock_gnb_core_remote_tac.return_value = None
            self.mock_gnb_core_remote_plmns.return_value = None
            core_gnb_relation = testing.Relation(
                endpoint="fiveg_core_gnb", interface="fiveg_core_gnb"
            )
            n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
            container = testing.Container(
                name="gnbsim",
                can_connect=True,
                mounts={
                    "config": testing.Mount(
                        location="/etc/gnbsim",
                        source=temp_dir,
                    )
                },
                execs={
                    testing.Exec(
                        command_prefix=[
                            "ip",
                            "route",
                            "replace",
                            "192.168.252.0/24",
                            "via",
                            "192.168.251.1",
                        ]
                    )
                },
            )
            state_in = testing.State(
                leader=True,
                relations=[n2_relation, core_gnb_relation],
                containers=[container],
            )

            self.ctx.run(self.ctx.on.update_status(), state_in)

            assert not os.path.exists(f"{temp_dir}/gnb.conf")

    def test_given_core_gnb_relation_unavailable_when_configure_then_config_file_is_not_pushed(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.mock_k8s_multus.multus_is_available.return_value = True
            self.mock_k8s_multus.is_ready.return_value = True
            self.mock_n2_requirer_amf_hostname.return_value = "amf"
            self.mock_n2_requirer_amf_port.return_value = 38412
            self.mock_gnb_core_remote_tac.return_value = 1
            self.mock_gnb_core_remote_plmns.return_value = [PLMNConfig(mcc="001", mnc="01", sst=1)]
            n2_relation = testing.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
            container = testing.Container(
                name="gnbsim",
                can_connect=True,
                mounts={
                    "config": testing.Mount(
                        location="/etc/gnbsim",
                        source=temp_dir,
                    )
                },
                execs={
                    testing.Exec(
                        command_prefix=[
                            "ip",
                            "route",
                            "replace",
                            "192.168.252.0/24",
                            "via",
                            "192.168.251.1",
                        ]
                    )
                },
            )
            state_in = testing.State(
                leader=True,
                relations=[n2_relation],
                containers=[container],
            )

            self.ctx.run(self.ctx.on.update_status(), state_in)

            assert not os.path.exists(f"{temp_dir}/gnb.conf")


    # TEST MULTIPLE PLMNS
    # TEST PLMN SD ABSENT
