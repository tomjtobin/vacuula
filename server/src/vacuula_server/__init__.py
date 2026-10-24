from __future__ import annotations

import logging
import signal
import threading
import time
from vacuula_server.constants import APP_VERSION
from vacuula_server.db import check_db_is_up_to_date
from vacuula_server.env import GEN3_ENABLED, GEN4_ENABLED, MDNS_ENABLED
import vacuula_server.gen3.init 
import vacuula_server.gen4.init
import vacuula_server.handlers.init
from vacuula_server.handlers.setup import MDNSAdvertiser, ensure_ssl_certificate
from vacuula_server.logger import setup_logging

# welcome to the source code for vacuula. sorry for it being a mess, a cleanup effort is on the way.
# the big unexpected differances between the robot generations and wanting to release something as fast as
# possible has resulted in this. Please don't judge to hard lol
# some major todos i have in mind that i come to think of writing this:
# - better logging system for what is going on

setup_logging()
logger = logging.getLogger(__name__)

def main():
    stopping = threading.Event()
    servers = []
    mdns = None

    def request_shutdown(signum, frame):
        stopping.set()

    previous_handlers = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, request_shutdown)
        logger.info("Starting Vacuula Server %s", APP_VERSION)
        check_db_is_up_to_date()
        ensure_ssl_certificate()
        # Bind synchronously so a required endpoint failure fails the process.
        if GEN3_ENABLED:
            servers.extend(vacuula_server.gen3.init.start())
        servers.append(vacuula_server.handlers.init.start())
        if GEN4_ENABLED:
            threading.Thread(target=vacuula_server.gen4.init.start, daemon=True).start()
        if MDNS_ENABLED:
            mdns = MDNSAdvertiser()
            mdns.start()
        stopping.wait()
    finally:
        logger.info("Server stopping")
        try:
            # An incomplete TLS accept can block serve_forever (see PR #29).
            # Bound listener shutdown without waiting forever for daemon workers.
            deadline = time.monotonic() + 3
            closers = [threading.Thread(target=server.shutdown, daemon=True) for server in servers]
            for closer in closers:
                closer.start()
            for closer in closers:
                closer.join(max(0, deadline - time.monotonic()))
            for server in servers:
                server.server_close()
            if any(closer.is_alive() for closer in closers):
                logger.warning("Listener shutdown timed out; remaining daemon connections close on process exit")
            if mdns is not None:
                mdns.stop()
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
