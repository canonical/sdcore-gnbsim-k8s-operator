# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import tempfile

import scenario

from tests.unit.fixtures import GNBSUMUnitTestFixtures


class TestCharmConfigure(GNBSUMUnitTestFixtures):
    def test_given_config_file_not_pushed_when_configure_then_config_file_is_pushed(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.mock_k8s_multus.multus_is_available.return_value = True
            self.mock_k8s_multus.is_ready.return_value = True
            self.mock_n2_requirer_amf_hostname.return_value = "amf"
            self.mock_n2_requirer_amf_port.return_value = 38412
            n2_relation = scenario.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
            container = scenario.Container(
                name="gnbsim",
                can_connect=True,
                mounts={
                    "config": scenario.Mount(
                        location="/etc/gnbsim",
                        source=temp_dir,
                    )
                },
                execs={
                    scenario.Exec(
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
            state_in = scenario.State(
                leader=True,
                relations=[n2_relation],
                containers=[container],
            )

            self.ctx.run(self.ctx.on.update_status(), state_in)

            with open(f"{temp_dir}/gnb.conf", "r") as f:
                actual_config_file = f.read()

            with open("tests/unit/expected_config.yaml", "r") as f:
                expected_config_file = f.read()

            assert actual_config_file == expected_config_file

    def test_given_gnb_identity_relation_when_configure_then_gnb_information_is_provided(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.mock_k8s_multus.multus_is_available.return_value = True
            self.mock_k8s_multus.is_ready.return_value = True
            self.mock_n2_requirer_amf_hostname.return_value = "amf"
            self.mock_n2_requirer_amf_port.return_value = 38412
            n2_relation = scenario.Relation(endpoint="fiveg-n2", interface="fiveg_n2")
            gnb_identity_relation = scenario.Relation(
                endpoint="fiveg_gnb_identity", interface="fiveg_gnb_identity"
            )
            container = scenario.Container(
                name="gnbsim",
                can_connect=True,
                mounts={
                    "config": scenario.Mount(
                        location="/etc/gnbsim",
                        source=temp_dir,
                    )
                },
                execs={
                    scenario.Exec(
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
            state_in = scenario.State(
                leader=True,
                relations=[n2_relation, gnb_identity_relation],
                containers=[container],
                model=scenario.Model(name="my-model"),
                config={"tac": "2"},
            )

            self.ctx.run(self.ctx.on.update_status(), state_in)

            self.mock_gnb_identity_publish_information.assert_called_once_with(
                relation_id=gnb_identity_relation.id,
                gnb_name="my-model-gnbsim-sdcore-gnbsim-k8s",
                tac=2,
            )
