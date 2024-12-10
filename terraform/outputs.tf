# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.gnbsim.name
}

output "requires" {
  value = {
    fiveg_core_gnb = "fiveg_core_gnb"
    fiveg_n2       = "fiveg-n2"
    logging        = "logging"
  }
}
