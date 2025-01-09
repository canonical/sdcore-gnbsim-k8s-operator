from any_charm_base import AnyCharmBase  # type: ignore[import]
from fiveg_n2 import N2Provides  # type: ignore[import]
from ops.framework import EventBase, logger

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
