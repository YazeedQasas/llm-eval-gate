"""Block network access for the duration of a replay run.

The gate is meant to be offline. Rather than trust that, `no_network()` swaps out the
socket constructors so any attempt to connect raises `NetworkBlocked`.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager


class NetworkBlocked(RuntimeError):
    pass


@contextmanager
def no_network() -> Iterator[None]:
    def blocked(*_args, **_kwargs):
        raise NetworkBlocked("network access attempted during an offline evalgate run")

    saved = (socket.socket, socket.create_connection, socket.getaddrinfo)
    socket.socket = blocked  # type: ignore[misc,assignment]
    socket.create_connection = blocked  # type: ignore[assignment]
    socket.getaddrinfo = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket, socket.create_connection, socket.getaddrinfo = saved  # type: ignore[misc]
