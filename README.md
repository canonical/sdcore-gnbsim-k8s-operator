# SD-Core GNBSIM K8 Operator
[![CharmHub Badge](https://charmhub.io/sdcore-gnbsim-k8s/badge.svg)](https://charmhub.io/sdcore-gnbsim-k8s)

A Charmed K8s Operator for SD-Core's gNodeB simulator (GNBSIM) component. 

## Usage

```bash
juju deploy sdcore-gnbsim-k8s --trust --channel=edge
juju run sdcore-gnbsim-k8s/leader start-simulation
```

## Image

- **gnbsim**: `ghcr.io/canonical/sdcore-gnbsim:1.3`
