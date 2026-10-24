# Gen3 upgrade ports and process shutdown

Gen3 robots configured by release 1.0.0 connect to HTTPS port 443. Later server
versions changed the default to `GEN3_PORT=335`; a successful database upgrade
does not move an existing robot to the new endpoint.

## Listener behavior

With Gen3 enabled, serve the same router and TLS certificate on both:

- `GEN3_PORT=335`: the current primary endpoint.
- `GEN3_LEGACY_PORT=443`: the additional legacy endpoint, enabled by default.

Both use `HOST_IP`. If the two values are equal, start one listener. Set
`GEN3_LEGACY_PORT=0` to disable the additional endpoint. `GEN3_ENABLED=false`
disables both. Environment variables override HA options. Stable and beta HA
schemas expose the primary and legacy ports; Compose documents both defaults.

Every configured Gen3 endpoint is required. Bind them synchronously before
starting request threads or the management listener. A conflict or permission
error closes any partially bound sockets and exits startup with an actionable
error instead of leaving a healthy-looking server with one missing endpoint.

If another service owns port 443 (for example HA Core HTTPS), default startup
will fail. Resolve the binding conflict, use a separate bind address/host, or
explicitly disable compatibility after updating affected robots. Moving the
compatibility listener to a different port does not automatically reconfigure
robots that still use 443. Both endpoints use the existing Gen3 router and TLS policy. They load the same
certificate and key.

## Shutdown behavior and limits

The main process handles SIGTERM and SIGINT through a shared stop event, closes
HTTP/Gen3 listeners, stops mDNS if started, restores previous signal handlers,
and exits normally. Docker's startup command uses `exec` after migrations so
signals reach the server at PID 1. The existing systemd service and HA `init`
setting are retained.

Listener shutdown has a shared three-second bound. An incomplete TLS handshake
can block the current accept loop; after that bound, remaining daemon workers
and Gen4 sockets close when the process exits. This is not a promise to drain
in-flight uploads, commands, or SSE clients to completion, and does not fix the
TLS accept-loop isolation issue discussed in PR #29. Database migration itself
is a separate process; termination during migration is not covered by these
server-shutdown guarantees.

## Regression checks

Build the full image and run isolated black-box tests:

```sh
docker build -t vacuula:compat-test -f build/docker/Dockerfile .
VACUULA_TEST_IMAGE=vacuula:compat-test python3 -m unittest discover -s tests -p test_upgrade_compat.py -v
```

Set `VACUULA_TEST_DOCKER='sudo -n docker'` if needed. Tests use disposable
containers, no external networking, temporary data, and real TLS sockets. They
check both default endpoints and identical certificates, disabling/customizing/
deduplicating legacy ports, disabled Gen3, invalid/conflicting options, HA options
precedence, occupied required ports and partial-bind cleanup, Docker PID 1
SIGTERM (including stalled TLS peers), ordinary-process SIGTERM/SIGINT, and
post-exit SQLite integrity. CI builds the image and runs the same checks.

These tests do not establish physical Gen3 compatibility, actual Supervisor
updates/ingress, or LXC/systemd deployment upgrades. Those remain draft-PR
validation work; a filesystem/options simulation is not a Supervisor test.
