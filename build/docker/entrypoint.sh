#!/bin/sh
set -eu

# Preserve legacy low ports even with host networking. Discard root and every
# capability except binding low ports before migrations or application imports.
# Existing volumes must be migrated by the operator (see docs/security.md).
if [ "$(id -u)" = 0 ]; then
    exec setpriv --reuid=10001 --regid=10001 --clear-groups \
        --inh-caps=+net_bind_service --ambient-caps=+net_bind_service \
        --bounding-set=-all,+net_bind_service --no-new-privs "$@"
fi
exec "$@"
