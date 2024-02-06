resource "juju_application" "gnbsim" {
  name  = "gnbsim"
  model = var.model_name

  charm {
    name    = "sdcore-gnbsim-k8s"
    channel = var.channel
  }
  config = var.gnb-config
  units  = 1
  trust  = true
}

resource "juju_integration" "gnbsim-amf" {
  model = var.model_name

  application {
    name     = juju_application.gnbsim.name
    endpoint = "fiveg-n2"
  }

  application {
    name     = var.amf_application_name
    endpoint = "fiveg-n2"
  }
}

