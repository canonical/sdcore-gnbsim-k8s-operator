#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
AMF_CHARM_NAME = "sdcore-amf"
DB_CHARM_NAME = "mongodb-k8s"
NRF_CHARM_NAME = "sdcore-nrf"
TLS_PROVIDER_CHARM_NAME = "self-signed-certificates"


@pytest.fixture(scope="module")
@pytest.mark.abort_on_fail
async def build_and_deploy(ops_test):
    """Build the charm-under-test and deploy it."""
    charm = await ops_test.build_charm(".")
    resources = {
        "gnbsim-image": METADATA["resources"]["gnbsim-image"]["upstream-source"],
    }
    await ops_test.model.deploy(
        charm,
        resources=resources,
        application_name=APP_NAME,
        trust=True,
    )
    await ops_test.model.deploy(
        AMF_CHARM_NAME,
        application_name=AMF_CHARM_NAME,
        channel="edge",
        trust=True,
    )

    await ops_test.model.deploy(
        DB_CHARM_NAME,
        application_name=DB_CHARM_NAME,
        channel="5/edge",
        trust=True,
    )
    await ops_test.model.deploy(
        NRF_CHARM_NAME,
        application_name=NRF_CHARM_NAME,
        channel="edge",
        trust=True,
    )

    await ops_test.model.deploy(
        TLS_PROVIDER_CHARM_NAME, application_name=TLS_PROVIDER_CHARM_NAME, channel="beta"
    )


@pytest.mark.abort_on_fail
async def test_deploy_charm_and_wait_for_blocked_status(
    ops_test,
    build_and_deploy,
):
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status="blocked",
        timeout=1000,
    )


@pytest.mark.abort_on_fail
async def test_relate_and_wait_for_active_status(
    ops_test,
    build_and_deploy,
):
    await ops_test.model.add_relation(
        relation1=f"{NRF_CHARM_NAME}:database", relation2=f"{DB_CHARM_NAME}"
    )
    await ops_test.model.add_relation(
        relation1=f"{AMF_CHARM_NAME}:database", relation2=f"{DB_CHARM_NAME}"
    )
    await ops_test.model.add_relation(relation1=AMF_CHARM_NAME, relation2=TLS_PROVIDER_CHARM_NAME)
    await ops_test.model.add_relation(relation1=NRF_CHARM_NAME, relation2=TLS_PROVIDER_CHARM_NAME)
    await ops_test.model.add_relation(relation1=AMF_CHARM_NAME, relation2=NRF_CHARM_NAME)
    await ops_test.model.add_relation(relation1=f"{APP_NAME}:fiveg-n2", relation2=AMF_CHARM_NAME)
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        raise_on_error=False,
        status="active",
        timeout=1000,
    )
