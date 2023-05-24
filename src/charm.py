#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed operator for the 5G GNBSIM service."""

import logging

from ops.charm import CharmBase
from ops.main import main

logger = logging.getLogger(__name__)


class GNBSIMOperatorCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)


if __name__ == "__main__":
    main(GNBSIMOperatorCharm)
