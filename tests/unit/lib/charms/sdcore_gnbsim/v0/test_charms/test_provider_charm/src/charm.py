# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from charms.sdcore_gnbsim.v0.fiveg_gnb_identity import GnbIdentityProvides
from ops.charm import CharmBase
from ops.main import main

logger = logging.getLogger(__name__)


class WhateverCharm(CharmBase):
    TEST_GNB_NAME = ""
    TEST_TAC = ""

    def __init__(self, *args):
        """Creates a new instance of this object for each event."""
        super().__init__(*args)
        self.gnb_identity_provider = GnbIdentityProvides(self, "fiveg_gnb_identity")

        self.framework.observe(
            self.gnb_identity_provider.on.fiveg_gnb_identity_request,
            self._on_fiveg_gnb_identity_request,
        )

    def _on_fiveg_gnb_identity_request(self, event):
        self.gnb_identity_provider.publish_gnb_identity_information(
            relation_id=event.relation_id, gnb_name=self.TEST_GNB_NAME, tac=self.TEST_TAC
        )


if __name__ == "__main__":
    main(WhateverCharm)
