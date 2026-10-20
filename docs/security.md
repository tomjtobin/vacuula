# Local network deployment and storage safety

This change contains robot uploads and map files within their storage directories
and reduces the privileges used by the Docker runtime. Native apps and the web
app keep their existing API and SSE contracts.

Robot-provided storage identifiers must be single path components containing
ASCII letters, digits, underscores, hyphens, and dots (maximum 128 characters,
starting with a letter, digit, underscore, or hyphen). Storage rejects symlinks
and replaces output files atomically. Gen3 log uploads are saved as `upload.bin`;
the supplied filename no longer determines the destination. Gen3 map archives
accept flat regular files, including the standard `./` prefix, up to 128 members
and 64 MiB expanded contents. Links, devices, duplicate files, and directory
traversal are rejected before any member is published. These limits do not
provide general traffic or storage quotas.

The Docker entrypoint briefly starts as root solely to drop privileges with
`setpriv`. Migrations and Python run as UID/GID **10001:10001**, with only
`CAP_NET_BIND_SERVICE` retained to support legacy low ports with host networking.
The bounding set also discards the startup capabilities. The Compose example
enables no-new-privileges, a read-only image filesystem, a bounded temporary
filesystem, memory/CPU/PID limits, and bounded Docker logs. Adjust resource
limits for your maps/hardware. The application data volume remains writable.
Docker resource limits also require matching host kernel/cgroup support; inspect
`docker info` rather than assuming a requested limit is enforced.

For a fresh named volume, Docker copies the image directory ownership. For an
existing installation, stop the service and back up the data volume, preserving
ownership and permissions, before updating. As root in a maintenance container,
change ownership of the data directory and its contents to `10001:10001` (do not
follow symlinks or change ownership of anything outside this volume). The
entrypoint deliberately does not recursively change permissions at every boot.
Custom bind mounts must also permit UID 10001 to access the required files.
TLS keys should remain mode 0600. Mount only trusted data volumes.

When invoking maintenance commands, remember that the image entrypoint drops
privileges too. Use a separately authorized root maintenance container for
volume ownership migration. A rollback can use the previous root-running image
with the migrated volume; restoring an older backup discards newer data.

Host networking is retained for robot discovery and legacy protocol compatibility.

Run the storage tests with Python 3.14 and the server dependencies installed:

```sh
python -m unittest discover -s server/tests -v
```

Tests cover traversal, absolute paths, existing symlinks, atomic replacement,
archive member types/limits, the Gen3 upload-init response, Gen4 map writes, and
HTTP route validation. Gen3 hardware compatibility needs a real robot test;
fixtures alone cannot establish it.
