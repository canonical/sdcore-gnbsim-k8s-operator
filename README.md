<div align="center">
  <img src="./icon.svg" alt="ONF Icon" width="200" height="200">
</div>
<br/>
<div align="center">
  <a href="https://charmhub.io/sdcore-gnbsim"><img src="https://charmhub.io/sdcore-gnbsim/badge.svg" alt="CharmHub Badge"></a>
  <a href="https://github.com/canonical/sdcore-gnbsim-operator/actions/workflows/publish-charm.yaml">
    <img src="https://github.com/canonical/sdcore-gnbsim-operator/actions/workflows/publish-charm.yaml/badge.svg?branch=main" alt=".github/workflows/publish-charm.yaml">
  </a>
  <br/>
  <br/>
  <h1>SD-Core GNBSIM Operator</h1>
</div>

A Charmed Operator for SD-Core's gNodeB simulator (GNBSIM) component. 

## Usage

```bash
juju deploy sdcore-gnbsim --trust --channel=edge
juju run sdcore-gnbsim/leader start-simulation
```

## Image

- **gnbsim**: `omecproject/5gc-gnbsim:main-1caccfc`
