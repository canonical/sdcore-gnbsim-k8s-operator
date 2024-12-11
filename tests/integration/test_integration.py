#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
import textwrap
from pathlib import Path

import pytest
import requests
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
AMF_MOCK = "amf-mock"
NMS_MOCK = "nms-mock"
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


async def _deploy_amf_mock(ops_test: OpsTest):
    fiveg_n2_lib_url = "https://github.com/canonical/sdcore-amf-k8s-operator/raw/main/lib/charms/sdcore_amf_k8s/v0/fiveg_n2.py"
    fiveg_n2_lib = requests.get(fiveg_n2_lib_url, timeout=10).text
    any_charm_src_overwrite = {
        "fiveg_n2.py": fiveg_n2_lib,
        "any_charm.py": textwrap.dedent(
            """\
        from fiveg_n2 import N2Provides
        from any_charm_base import AnyCharmBase
        from ops.framework import EventBase
        N2_RELATION_NAME = "provide-fiveg-n2"

        class AnyCharm(AnyCharmBase):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.n2_provider = N2Provides(self, N2_RELATION_NAME)
                self.framework.observe(
                    self.on[N2_RELATION_NAME].relation_changed,
                    self.fiveg_n2_relation_changed,
                )

            def fiveg_n2_relation_changed(self, event: EventBase) -> None:
                fiveg_n2_relations = self.model.relations.get(N2_RELATION_NAME)
                if not fiveg_n2_relations:
                    logger.info("No %s relations found.", N2_RELATION_NAME)
                    return
                self.n2_provider.set_n2_information(
                    amf_ip_address="1.2.3.4",
                    amf_hostname="amf-external.sdcore.svc.cluster.local",
                    amf_port=38412,
                )
        """
        ),
    }
    assert ops_test.model
    await ops_test.model.deploy(
        "any-charm",
        application_name=AMF_MOCK,
        channel="beta",
        config={
            "src-overwrite": json.dumps(any_charm_src_overwrite),
            "python-packages": "pytest-interface-tester"
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
        "any_charm.py": textwrap.dedent(
            """\
        from fiveg_core_gnb import FivegCoreGnbProvides, PLMNConfig
        from any_charm_base import AnyCharmBase
        from ops.framework import EventBase
        CORE_GNB_RELATION_NAME = "provide-fiveg-core-gnb"

        class AnyCharm(AnyCharmBase):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._fiveg_core_gnb_provider = FivegCoreGnbProvides(self, CORE_GNB_RELATION_NAME)
                self.framework.observe(
                    self.on[CORE_GNB_RELATION_NAME].relation_changed,
                    self.fiveg_core_gnb_relation_changed,
                )

            def fiveg_core_gnb_relation_changed(self, event: EventBase):
                core_gnb_relations = self.model.relations.get(CORE_GNB_RELATION_NAME)
                if not core_gnb_relations:
                    logger.info("No %s relations found.", CORE_GNB_RELATION_NAME)
                    return
                for relation in core_gnb_relations:
                    self._fiveg_core_gnb_provider.publish_gnb_config_information(
                        relation_id=relation.id,
                        tac=1,
                        plmns=[PLMNConfig(mcc="001", mnc="01", sst=1, sd=1056816)],
                    )
        """
        ),
    }
    assert ops_test.model
    await ops_test.model.deploy(
        "any-charm",
        application_name=NMS_MOCK,
        channel="beta",
        config={
            "src-overwrite": json.dumps(any_charm_src_overwrite),
            "python-packages": "pytest-interface-tester"
        },
    )
