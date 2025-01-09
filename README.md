# SD-Core GNBSIM Operator (k8s)
[![CharmHub Badge](https://charmhub.io/sdcore-gnbsim-k8s/badge.svg)](https://charmhub.io/sdcore-gnbsim-k8s)

A Charmed Operator for SD-Core's gNodeB simulator (GNBSIM) component for K8s. 

## Usage

```bash
juju deploy sdcore-gnbsim-k8s --trust --channel=1.5/stable
juju run sdcore-gnbsim-k8s/leader start-simulation
```

## Image

- **gnbsim**: `ghcr.io/canonical/sdcore-gnbsim:1.6.0`

