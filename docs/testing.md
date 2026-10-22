# Testing storage, upgrades, and Home Assistant

## Server tests

With Python 3.14 and server dependencies installed:

```sh
python -m unittest discover -s server/tests -v
```

The Gen3 tests use generated PNGs, timestamp-shaped identifiers, a local HTTP
server, and a temporary SQLite database. They cover upload initiation, multipart
map/log upload, finalization, persistence and retrieval, including encoded colons
and traversal rejection. They are not hardware captures. The shared storage
tests additionally cover Gen4 writes, symlinks, atomic replacement and archive
limits. See [identifier evidence](../server/docs/identifiers.md).

## Complete image and upgrade tests

Build from the repository root, rather than overlaying source onto an installed
image. This validates dependency installation, frontend compilation, build
context/COPY rules, and the actual entrypoint:

```sh
docker build -t vacuula:test -f build/docker/Dockerfile .
VACUULA_TEST_IMAGE=vacuula:test python3 -m unittest discover -s tests/container -v
```

If your host requires sudo for Docker, set
`VACUULA_TEST_DOCKER='sudo -n docker'` for the test command. Tests create unique
disposable named volumes/containers, use no host networking, and never mount the
production volume. A legacy fixture creates an older Alembic schema, a robot
record, maps, and a certificate/private key with root-owned mode 0700/0600 data.
It is representative upgrade data, not a fixture copied from a user's backup.

The suite checks fresh startup, unattended ownership/schema upgrade, repeated
startup, partial preparation recovery, preservation of certificates/data,
post-start UID/capabilities, read-only-image operation, symlink handling, and
controlled failure for read-only volumes, missing privileges and hardlinks.

## Home Assistant coverage

The Docker suite includes `/server/data` and a separate read-only `/data` mount
with root-private `options.json`. It verifies configured API-port selection,
private temporary options and unchanged Supervisor-owned options. This simulates
the add-on's filesystem/options contract only. It does not run Supervisor or HA.

For full testing, follow Home Assistant's [app testing guide](https://contributors.home-assistant.io/apps/guides/testing/)
using its Supervisor development container or a disposable Home Assistant OS
installation. Test the actual stable and beta add-on definitions, including
protection mode and beta ingress, with the candidate image available to the
Supervisor. Merely installing Home Assistant Core in Docker is not this test.

Before taking this PR out of draft, record results for:

- Installing the previous add-on image, creating root-owned data, then upgrading
  through Supervisor with no terminal/chown/config repair commands.
- Robot/map/history retention, the same TLS certificate, and successful restart.
- Fresh install and a second upgrade/restart; interruption/recovery if feasible.
- Options, ingress for the beta add-on, Supervisor logs, and backup/restore.
- Actual Gen3 uploads/retrieval and a Gen4 action/run/map cycle. State clearly
  which hardware was available and which tests remain synthetic.

Use a disposable HA environment for this matrix. Supervisor may pull a published
image when `image:` is present; make sure it is testing the candidate you built,
not an unrelated registry tag. See [HA's configuration reference](https://contributors.home-assistant.io/apps/reference/configuration/).

## Reporting results

Give exact commands, commit/image digest, architecture, runtime, and results in
the PR description. Separate automated tests, full-image builds, filesystem-only
HA simulations, Supervisor tests, and physical device tests. Do not convert a
successful manually repaired installation into evidence of an unattended upgrade.
