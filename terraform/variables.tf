variable "model_name" {
  description = "Name of Juju model to deploy application to."
  type        = string
  default     = ""
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "1.3/edge"
}

variable "gnb-config" {
  description = "Additional configuration for the GNBSIM"
  default     = {}
}

variable "amf_application_name" {
  description = "The name of the AMF application."
  type        = string
  default     = ""
}


