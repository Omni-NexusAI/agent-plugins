"""Stdlib fake inference endpoints: routes, auth, redirects, delays, TLS, request log.

Used by the Phase 0 characterization of the host search and by the discovery tests, so both exercise
real sockets (the production code path) instead of mocks.
"""
from __future__ import annotations

import datetime
import json
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from . import endpoint_payloads


@dataclass
class Route:
    body: object = None
    status: int = 200
    headers: dict = field(default_factory=dict)
    delay: float = 0.0
    raw: bytes | None = None  # send these exact bytes instead of JSON


def redirect(location: str, status: int = 302) -> Route:
    return Route(status=status, headers={"Location": location}, body={})


class FakeEndpoint:
    """routes: path -> payload (dict/list), Route, or callable(request_record) -> Route/payload."""

    def __init__(self, routes: dict | str, *, token: str | None = None, tls: tuple[str, str] | None = None,
                 delay: float = 0.0, forbid: Callable[[dict], bool] | None = None):
        self.routes = dict(endpoint_payloads.KINDS[routes]()) if isinstance(routes, str) else dict(routes)
        self.token = token
        self.tls = tls
        self.delay = delay
        self.forbid = forbid
        self.requests: list[dict] = []
        self.release = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FakeEndpoint/1"

            def log_message(self, *args):
                pass

            def _write(self, status: int, payload: bytes, headers: dict | None = None):
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    for key, value in (headers or {}).items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(payload)
                except (ConnectionError, OSError):
                    pass

            def do_GET(self):  # noqa: N802
                parts = urlsplit(self.path)
                record = {"method": "GET", "path": parts.path, "query": parts.query,
                          "headers": {k.lower(): v for k, v in self.headers.items()}}
                owner.requests.append(record)
                if owner.delay:
                    time.sleep(owner.delay)
                if owner.forbid and owner.forbid(record):
                    return self._write(403, b'{"error":"forbidden"}')
                if owner.token:
                    auth = record["headers"].get("authorization", "")
                    if auth != f"Bearer {owner.token}" and record["headers"].get("x-api-key") != owner.token:
                        return self._write(401, b'{"error":{"message":"Invalid API key"}}')
                route = owner.routes.get(parts.path)
                if callable(route):
                    route = route(record)
                if route is None:
                    return self._write(404, b'{"error":"not found"}')
                if not isinstance(route, Route):
                    route = Route(body=route)
                if route.delay:
                    owner.release.wait(route.delay)
                payload = route.raw if route.raw is not None else json.dumps(route.body).encode()
                self._write(route.status, payload, route.headers)

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):  # untrusted-TLS clients abort handshakes: not interesting
                pass

        self.httpd = Server(("127.0.0.1", 0), Handler)
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*tls)
            self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)  # fast shutdown

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"{'https' if self.tls else 'http'}://127.0.0.1:{self.port}"

    def start(self) -> "FakeEndpoint":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def make_self_signed(directory: str | Path) -> tuple[str, str] | None:
    """Create a self-signed localhost certificate (cryptography, else openssl). Returns (cert, key) or None."""
    directory = Path(directory)
    cert, key = directory / "cert.pem", directory / "key.pem"
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import ipaddress

        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
                       .not_valid_after(now + datetime.timedelta(days=1))
                       .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                       .sign(private, hashes.SHA256()))
        cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        return str(cert), str(key)
    except ImportError:
        pass
    openssl = shutil.which("openssl")
    if not openssl:
        return None
    result = subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1",
                             "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], capture_output=True)
    return (str(cert), str(key)) if result.returncode == 0 else None


class TempCert:
    """Context manager yielding (cert, key) paths or None when no TLS tooling exists."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        return make_self_signed(self.tmp.name)

    def __exit__(self, *exc):
        self.tmp.cleanup()
