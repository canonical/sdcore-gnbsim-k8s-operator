#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
from pathlib import Path

import pytest
import requests
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
FIVEG_CORE_GNB_MOCK_PATH = "./tests/integration/fiveg_core_gnb_mock_charm.py"
FIVEG_N2_MOCK_PATH = "./tests/integration/fiveg_n2_mock_charm.py"
AMF_MOCK = "amf-mock"
NMS_MOCK = "nms-mock"
GRAFANA_AGENT_CHARM_NAME = "grafana-agent-k8s"
GRAFANA_AGENT_CHARM_CHANNEL = "1/stable"
TIMEOUT = 5 * 60


@pytest.fixture(scope="module")
@pytest.mark.abort_on_fail
async def deploy(ops_test: OpsTest, request):
    """Deploy required components."""
    assert ops_test.model
    charm = Path(request.config.getoption("--charm_path")).resolve()
    resources = {
        "gnbsim-image": METADATA["resources"]["gnbsim-image"]["upstream-source"],
    }
    await ops_test.model.deploy(
        charm,
        resources=resources,
        application_name=APP_NAME,
        trust=True,
    )
    await _deploy_nms_mock(ops_test)
    await _deploy_amf_mock(ops_test)
    await _deploy_grafana_agent(ops_test)


@pytest.mark.abort_on_fail
async def test_deploy_charm_and_wait_for_blocked_status(ops_test: OpsTest, deploy):
    assert ops_test.model
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=TIMEOUT,
    )


@pytest.mark.abort_on_fail
async def test_relate_and_wait_for_active_status(ops_test: OpsTest, deploy):
    assert ops_test.model
    await ops_test.model.integrate(relation1=f"{APP_NAME}:fiveg-n2", relation2=AMF_MOCK)
    await ops_test.model.integrate(relation1=f"{APP_NAME}:fiveg_core_gnb", relation2=NMS_MOCK)
    await ops_test.model.integrate(
        relation1=f"{APP_NAME}:logging", relation2=GRAFANA_AGENT_CHARM_NAME
    )
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        raise_on_error=False,
        status="active",
        timeout=TIMEOUT,
    )


@pytest.mark.abort_on_fail
async def test_remove_amf_and_wait_for_blocked_status(ops_test: OpsTest, deploy):
    assert ops_test.model
    await ops_test.model.remove_application(AMF_MOCK, block_until_done=True)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=TIMEOUT)


@pytest.mark.abort_on_fail
async def test_restore_amf_and_wait_for_active_status(ops_test: OpsTest, deploy):
    assert ops_test.model
    await _deploy_amf_mock(ops_test)
    await ops_test.model.integrate(relation1=f"{APP_NAME}:fiveg-n2", relation2=AMF_MOCK)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=TIMEOUT)


@pytest.mark.abort_on_fail
async def test_remove_nms_and_wait_for_blocked_status(ops_test: OpsTest, deploy):
    assert ops_test.model
    await ops_test.model.remove_application(NMS_MOCK, block_until_done=True)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=TIMEOUT)


@pytest.mark.abort_on_fail
async def test_restore_nms_and_wait_for_active_status(ops_test: OpsTest, deploy):
    assert ops_test.model
    await _deploy_nms_mock(ops_test)
    await ops_test.model.integrate(relation1=f"{APP_NAME}:fiveg_core_gnb", relation2=NMS_MOCK)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=TIMEOUT)


async def _deploy_amf_mock(ops_test: OpsTest):
    fiveg_n2_lib_url = "https://github.com/canonical/sdcore-amf-k8s-operator/raw/main/lib/charms/sdcore_amf_k8s/v0/fiveg_n2.py"
    fiveg_n2_lib = requests.get(fiveg_n2_lib_url, timeout=10).text
    any_charm_src_overwrite = {
        "fiveg_n2.py": fiveg_n2_lib,
        "any_charm.py": Path(FIVEG_N2_MOCK_PATH).read_text(),
    }
    assert ops_test.model
    await ops_test.model.deploy(
        "any-charm",
        application_name=AMF_MOCK,
        channel="beta",
        config={
            "src-overwrite": json.dumps(any_charm_src_overwrite),
            "python-packages": "ops==2.17.1\npytest-interface-tester"
        },
    )


async def _deploy_grafana_agent(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.deploy(
        GRAFANA_AGENT_CHARM_NAME,
        application_name=GRAFANA_AGENT_CHARM_NAME,
        channel=GRAFANA_AGENT_CHARM_CHANNEL,
    )


async def _deploy_nms_mock(ops_test: OpsTest):
    fiveg_core_gnb_lib_url = "https://github.com/canonical/sdcore-nms-k8s-operator/raw/main/lib/charms/sdcore_nms_k8s/v0/fiveg_core_gnb.py"
    fiveg_core_gnb_lib = requests.get(fiveg_core_gnb_lib_url, timeout=10).text
    any_charm_src_overwrite = {
        "fiveg_core_gnb.py": fiveg_core_gnb_lib,
        "any_charm.py": Path(FIVEG_CORE_GNB_MOCK_PATH).read_text(),
    }
    assert ops_test.model
    await ops_test.model.deploy(
        "any-charm",
        application_name=NMS_MOCK,
        channel="beta",
        config={
            "src-overwrite": json.dumps(any_charm_src_overwrite),
            "python-packages": "ops==2.17.0\npytest-interface-tester"
        },
    )
