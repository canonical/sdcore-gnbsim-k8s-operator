# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from charms.sdcore_gnbsim.v0.fiveg_gnb_identity import GnbIdentityRequires
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus

logger = logging.getLogger(__name__)


class WhateverCharm(CharmBase):
    def __init__(self, *args):
        """Creates a new instance of this object for each event."""
        super().__init__(*args)
        self.fiveg_gnb_identity = GnbIdentityRequires(self, "fiveg_gnb_identity")

        self.framework.observe(
            self.fiveg_gnb_identity.on.fiveg_gnb_identity_available,
            self._on_fiveg_gnb_identity_available,
        )

    def _on_fiveg_gnb_identity_available(self, event):
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(WhateverCharm)
