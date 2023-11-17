# SD-Core GNBSIM Operator (k8s)
[![CharmHub Badge](https://charmhub.io/sdcore-gnbsim/badge.svg)](https://charmhub.io/sdcore-gnbsim)

A Charmed Operator for SD-Core's gNodeB simulator (GNBSIM) component. 

## Usage

```bash
juju deploy sdcore-gnbsim --trust --channel=edge
juju run sdcore-gnbsim/leader start-simulation
```

## Image

- **gnbsim**: `ghcr.io/canonical/sdcore-gnbsim:1.3`
