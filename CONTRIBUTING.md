# Contributing

To make contributions to this charm, you'll need a working [Juju development setup](https://juju.is/docs/sdk/dev-setup).

You can use the environments created by `tox` for development:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

## Testing

This project uses `tox` for managing test environments. There are some pre-configured environments
that can be used for linting and formatting code when you're preparing contributions to the charm:

```shell
tox -e lint          # code style
tox -e static        # static analysis
tox -e unit          # unit tests
tox -e integration   # integration tests
```

## Build
Building charms is done using charmcraft (official documentation [here](https://juju.is/docs/sdk/publishing)). You can install charmcraft using `snap`:

```bash
sudo snap install charmcraft --channel=classic
```

Initialize LXD:

```bash
lxd init --auto
```

Go to the charm directory and run:

```bash
charmcraft pack
```
