# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.gnbsim.name
}

output "requires" {
  value = {
    fiveg_n2 = "fiveg-n2"
    logging  = "logging"
  }
}

output "provides" {
  value = {
    fiveg_gnb_identity = "fiveg_gnb_identity"
  }
}
