# SD-Core GNBSIM K8s Terraform Module

This SD-Core GNBSIM K8s Terraform module aims to deploy the [sdcore-gnbsim-k8s charm](https://charmhub.io/sdcore-gnbsim-k8s) via Terraform.

## Getting Started

### Prerequisites

The following software and tools needs to be installed and should be running in the local environment. Please [set up your environment](https://discourse.charmhub.io/t/set-up-your-development-environment-with-microk8s-for-juju-terraform-provider/13109) before deployment.

- `microk8s`
- `juju 3.x`
- `terrafom`

The `sdcore-gnbsim-ks8` application requires the integrations with the following application.

- `sdcore-amf-k8s`

### Deploy the sdcore-gnbsim-k8s charm using Terraform

Make sure that `storage` and `multus` plugins are enabled for Microk8s:

```console
sudo microk8s enable hostpath-storage multus
```

Add a Juju model:

```console
juju add-model <model-name>
```

Initialise the provider:

```console
terraform init
```

Fill the mandatory config options in the `terraform.tfvars` file:

```yaml
# Mandatory Config Options
model_name           = "put your model-name here"
amf_application_name = "put your AMF app name here"
```

Create the Terraform Plan:

```console
terraform plan -var-file="terraform.tfvars" 
```

Deploy the resources:

```console
terraform apply -auto-approve 
```

### Check the Output

Run `juju switch <juju model>` to switch to the target Juju model and observe the status of the applications.

```console
juju status --relations
```

### Clean up

Destroy the deployment:

```console
terraform destroy -auto-approve
```
