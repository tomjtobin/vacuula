from __future__ import annotations

import logging
import threading

from vacuula_server.env import GEN3_LEGACY_PORT, GEN3_PORT, HOST_IP
from vacuula_server.handlers.router import RouterHandler
from vacuula_server.logger import LoggingThreadingHTTPServer
from vacuula_server.tls import create_ssl_context

logger = logging.getLogger(__name__)


def start():
    """Bind every required endpoint before starting any request threads."""
    context = create_ssl_context()
    ports = list(dict.fromkeys(port for port in (GEN3_PORT, GEN3_LEGACY_PORT) if port))
    servers = []
    try:
        for port in ports:
            try:
                server = LoggingThreadingHTTPServer((HOST_IP, port), RouterHandler)
            except OSError as error:
                raise OSError(
                    f"Cannot bind required Gen3 HTTPS listener {HOST_IP}:{port}. "
                    "Check port ownership and GEN3_PORT/GEN3_LEGACY_PORT; "
                    "GEN3_LEGACY_PORT=0 disables legacy compatibility."
                ) from error
            servers.append(server)
            server.socket = context.wrap_socket(server.socket, server_side=True)
    except BaseException:
        for server in servers:
            server.server_close()
        raise

    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info("Gen3 listening on https://%s:%d", HOST_IP, server.server_port)
    return servers
