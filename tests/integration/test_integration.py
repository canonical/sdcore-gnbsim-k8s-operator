#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
AMF_CHARM_NAME = "sdcore-amf-k8s"
AMF_CHARM_CHANNEL = "1.5/edge"
DB_CHARM_NAME = "mongodb-k8s"
DB_CHARM_CHANNEL = "6/edge"
NRF_CHARM_NAME = "sdcore-nrf-k8s"
NRF_CHARM_CHANNEL = "1.5/edge"
WEBUI_CHARM_NAME = "sdcore-webui-k8s"
WEBUI_CHARM_CHANNEL = "1.5/edge"
TLS_CHARM_NAME = "self-signed-certificates"
TLS_CHARM_CHANNEL = "latest/stable"
GRAFANA_AGENT_CHARM_NAME = "grafana-agent-k8s"
GRAFANA_AGENT_CHARM_CHANNEL = "latest/stable"
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

    await _deploy_mongodb(ops_test)
    await _deploy_tls_provider(ops_test)
    await _deploy_webui(ops_test)
    await _deploy_nrf(ops_test)
    await _deploy_amf(ops_test)
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
    await ops_test.model.integrate(relation1=f"{APP_NAME}:fiveg-n2", relation2=AMF_CHARM_NAME)
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
    await ops_test.model.remove_application(AMF_CHARM_NAME, block_until_done=True)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", timeout=TIMEOUT)


@pytest.mark.abort_on_fail
async def test_restore_amf_and_wait_for_active_status(ops_test: OpsTest, deploy):
    assert ops_test.model
    await _deploy_amf(ops_test)
    await ops_test.model.integrate(relation1=APP_NAME, relation2=AMF_CHARM_NAME)
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", timeout=TIMEOUT)


async def _deploy_amf(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.deploy(
        AMF_CHARM_NAME,
        application_name=AMF_CHARM_NAME,
        channel=AMF_CHARM_CHANNEL,
        trust=True,
    )
    await ops_test.model.integrate(relation1=AMF_CHARM_NAME, relation2=NRF_CHARM_NAME)
    await ops_test.model.integrate(relation1=AMF_CHARM_NAME, relation2=WEBUI_CHARM_NAME)
    await ops_test.model.integrate(relation1=AMF_CHARM_NAME, relation2=DB_CHARM_NAME)
    await ops_test.model.integrate(relation1=AMF_CHARM_NAME, relation2=TLS_CHARM_NAME)


async def _deploy_mongodb(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.deploy(
        DB_CHARM_NAME,
        application_name=DB_CHARM_NAME,
        channel=DB_CHARM_CHANNEL,
        trust=True,
    )


async def _deploy_tls_provider(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.deploy(
        TLS_CHARM_NAME,
        application_name=TLS_CHARM_NAME,
        channel=TLS_CHARM_CHANNEL,
    )


async def _deploy_grafana_agent(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.deploy(
        GRAFANA_AGENT_CHARM_NAME,
        application_name=GRAFANA_AGENT_CHARM_NAME,
        channel=GRAFANA_AGENT_CHARM_CHANNEL,
    )


async def _deploy_nrf(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.deploy(
        NRF_CHARM_NAME,
        application_name=NRF_CHARM_NAME,
        channel=NRF_CHARM_CHANNEL,
        trust=True,
    )
    await ops_test.model.integrate(relation1=NRF_CHARM_NAME, relation2=DB_CHARM_NAME)
    await ops_test.model.integrate(relation1=NRF_CHARM_NAME, relation2=TLS_CHARM_NAME)
    await ops_test.model.integrate(relation1=NRF_CHARM_NAME, relation2=WEBUI_CHARM_NAME)


async def _deploy_webui(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.deploy(
        WEBUI_CHARM_NAME,
        application_name=WEBUI_CHARM_NAME,
        channel=WEBUI_CHARM_CHANNEL,
    )
    await ops_test.model.integrate(
        relation1=f"{WEBUI_CHARM_NAME}:common_database", relation2=f"{DB_CHARM_NAME}"
    )
    await ops_test.model.integrate(
        relation1=f"{WEBUI_CHARM_NAME}:auth_database", relation2=f"{DB_CHARM_NAME}"
    )
