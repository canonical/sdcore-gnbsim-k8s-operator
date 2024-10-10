# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import tempfile

import pytest
from ops import testing
from ops.testing import ActionFailed

from tests.unit.fixtures import GNBSUMUnitTestFixtures


class TestCharmStartSimulationAction(GNBSUMUnitTestFixtures):
    def test_given_config_file_not_written_when_start_simulation_then_action_fails(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
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
                containers={container},
            )

            with pytest.raises(ActionFailed) as exc_info:
                self.ctx.run(self.ctx.on.action("start-simulation"), state_in)

            assert exc_info.value.message == "Config file is not written"

    def test_given_less_than_5_profiles_passed_when_start_simulation_then_action_returns_with_success_false(  # noqa: E501
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
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
                        command_prefix=["/bin/gnbsim", "--cfg", "/etc/gnbsim/gnb.conf"],
                        return_code=0,
                        stderr="Profile Status: PASS\nProfile Status: PASS\nProfile Status: FAILED\nProfile Status: PASS\nProfile Status: PASS\n",  # noqa: E501
                    )
                },
            )
            state_in = testing.State(
                leader=True,
                containers={container},
            )

            with open("tests/unit/expected_config.yaml", "r") as f:
                config_file = f.read()

            with open(f"{temp_dir}/gnb.conf", "w") as f:
                f.write(config_file)

            self.ctx.run(self.ctx.on.action("start-simulation"), state_in)

            assert self.ctx.action_results
            assert self.ctx.action_results["success"] == "false"
            assert self.ctx.action_results["info"] == "4/5 profiles passed"

    def test_given_5_profiles_passed_when_start_simulation_then_action_returns_with_success(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
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
                        command_prefix=["/bin/gnbsim", "--cfg", "/etc/gnbsim/gnb.conf"],
                        return_code=0,
                        stderr="Profile Status: PASS\nProfile Status: PASS\nProfile Status: PASS\nProfile Status: PASS\nProfile Status: PASS\n",  # noqa: E501
                    )
                },
            )
            state_in = testing.State(
                leader=True,
                containers={container},
            )

            with open("tests/unit/expected_config.yaml", "r") as f:
                config_file = f.read()

            with open(f"{temp_dir}/gnb.conf", "w") as f:
                f.write(config_file)

            self.ctx.run(self.ctx.on.action("start-simulation"), state_in)

            assert self.ctx.action_results
            assert self.ctx.action_results["success"] == "true"
            assert self.ctx.action_results["info"] == "5/5 profiles passed"
