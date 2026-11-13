"""Network guard for Python test processes started by `ds.py run-tests`.

Loaded automatically through `sitecustomize` (run-tests puts this directory on
PYTHONPATH). It blocks outbound connections to anything except loopback and
explicitly allowed hosts. Limitation: only sockets created through Python's
`socket` module are covered; native drivers (libpq, some SDKs) bypass it, which
is why run-tests also applies OS sandboxing where available and records which
enforcement was active.
"""

import ipaddress
import os
import socket

_MODE = os.environ.get("DEVSKILLS_NET_MODE", "")


class NetworkBlockedError(ConnectionRefusedError):
    """Raised instead of opening a connection the test profile does not allow."""


def _install_guard() -> None:
    allowed_names = {
        name.strip().lower() for name in os.environ.get("DEVSKILLS_NET_ALLOW", "").split(",") if name.strip()
    }
    allowed_ips: set = set()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo

    def is_allowed_host(host) -> bool:
        if host is None:
            return True
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        text = str(host).strip("[]").lower()
        if text in ("localhost", "") or text in allowed_names:
            return True
        try:
            address = ipaddress.ip_address(text.split("%", 1)[0])
        except ValueError:
            return False
        return address.is_loopback or text in allowed_ips

    def check_address(sock, address) -> None:
        if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
            return
        host = address[0] if isinstance(address, tuple) and address else address
        if not is_allowed_host(host):
            raise NetworkBlockedError(
                f"devskills network guard blocked a connection to {host!r} (mode={_MODE}). "
                "Use a simulator/fake, or ask the user to allow a sandbox host."
            )

    def guarded_connect(self, address):
        check_address(self, address)
        return original_connect(self, address)

    def guarded_connect_ex(self, address):
        check_address(self, address)
        return original_connect_ex(self, address)

    def guarded_sendto(self, data, *args):
        address = args[-1] if args else None
        if address is not None:
            check_address(self, address)
        return original_sendto(self, data, *args)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not is_allowed_host(host):
            raise socket.gaierror(socket.EAI_NONAME, f"devskills network guard: lookup of {host!r} blocked")
        results = original_getaddrinfo(host, *args, **kwargs)
        if host is not None and str(host).lower() in allowed_names:
            # Connections go to resolved IPs, so remember the addresses of allowed names.
            for _family, _type, _proto, _canon, sockaddr in results:
                allowed_ips.add(str(sockaddr[0]).lower())
        return results

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.socket.sendto = guarded_sendto
    socket.getaddrinfo = guarded_getaddrinfo
    socket.NetworkBlockedError = NetworkBlockedError


if _MODE in ("deny", "local", "allow-listed"):
    _install_guard()
