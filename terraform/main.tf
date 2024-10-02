# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

resource "juju_application" "gnbsim" {
  name  = var.app_name
  model = var.model

  charm {
    name     = "sdcore-gnbsim-k8s"
    channel  = var.channel
    revision = var.revision
  }

  config      = var.config
  constraints = var.constraints
  resources   = var.resources
  trust       = true
  units       = var.units
}
