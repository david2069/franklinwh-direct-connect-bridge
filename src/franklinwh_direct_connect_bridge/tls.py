"""The HTTPS port's certificate (#457 phase 2).

Your own certificate when ``ssl_certfile`` and ``ssl_keyfile`` are set (on the add-on a bare
file name is looked up in Home Assistant's ``/ssl`` folder), else a self-signed one kept in
``DATA_DIR/tls``. The self-signed certificate is its own CA (so a phone can install and
trust it), is valid for 825 days (the longest iOS accepts) and is made again 30 days
before it runs out, or when the bridge's addresses change.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import socket
from pathlib import Path

from . import environment

log = logging.getLogger(__name__)

VALID_DAYS = 825
RENEW_DAYS = 30
SSL_DIR = "/ssl"

#: What the HTTPS listener is doing, for Settings → Admin → Security.
status: dict = {"port": 0, "running": False, "error": "", "source": "", "certfile": ""}
#: The running HTTPS server (uvicorn), set by cli.https_server.
server = None


def running() -> bool:
    return bool(server is not None and server.started and not server.should_exit)


def _dir() -> Path:
    return Path(environment.DATA_DIR) / "tls"


def _resolve(name: str) -> Path:
    p = Path(name)
    if not p.is_absolute() and environment.IS_HA_ADDON:
        p = Path(SSL_DIR) / p
    return p


def local_names() -> tuple[list[str], list[str]]:
    """The names and addresses the bridge is likely reached at: its host name, localhost,
    loopback and the address of its default route."""
    names = sorted({socket.gethostname(), "localhost"} - {""})
    ips = {"127.0.0.1", "::1"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))      # no packet is sent; picks the outgoing address
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return names, sorted(ips)


def _load(certfile: Path):
    from cryptography import x509
    return x509.load_pem_x509_certificate(certfile.read_bytes())


def _sans(cert) -> tuple[set[str], set[str]]:
    from cryptography import x509
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return set(), set()
    return (set(ext.get_values_for_type(x509.DNSName)),
            {str(a) for a in ext.get_values_for_type(x509.IPAddress)})


def make_self_signed(certfile: Path, keyfile: Path, names: list[str], ips: list[str],
                     now: dt.datetime | None = None) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = now or dt.datetime.now(dt.timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FranklinWH Direct Connect Bridge")])
    san = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True,
                                         crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False,
                                         decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    certfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    keyfile.chmod(0o600)
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ensure_cert(settings, now: dt.datetime | None = None) -> tuple[str, str, str]:
    """``(certfile, keyfile, source)``: ``own`` or ``self-signed``. Raises ValueError when
    your own certificate is set but can't be read."""
    if settings.ssl_certfile or settings.ssl_keyfile:
        if not settings.ssl_certfile or not settings.ssl_keyfile:
            raise ValueError("set both ssl_certfile and ssl_keyfile, or neither")
        cert, key = _resolve(settings.ssl_certfile), _resolve(settings.ssl_keyfile)
        for what, p in (("certificate", cert), ("key", key)):
            if not p.is_file():
                raise ValueError(f"the {what} file {p} does not exist")
        return str(cert), str(key), "own"
    now = now or dt.datetime.now(dt.timezone.utc)
    cert, key = _dir() / "bridge.crt", _dir() / "bridge.key"
    names, ips = local_names()
    reason = ""
    if not cert.is_file() or not key.is_file():
        reason = "none yet"
    else:
        try:
            c = _load(cert)
            if c.not_valid_after_utc - now < dt.timedelta(days=RENEW_DAYS):
                reason = "it expires soon"
            elif not (set(names) <= _sans(c)[0] and set(ips) <= _sans(c)[1]):
                reason = "the bridge's addresses changed"
        except ValueError:
            reason = "it could not be read"
    if reason:
        make_self_signed(cert, key, names, ips, now)
        log.info("HTTPS: made a self-signed certificate (%s)", reason)
    return str(cert), str(key), "self-signed"


def describe(certfile: str) -> dict:
    """The certificate as Settings shows it: SHA-256 fingerprint, valid until, names."""
    from cryptography.hazmat.primitives import hashes
    try:
        c = _load(Path(certfile))
    except (OSError, ValueError) as e:
        return {"error": f"could not read the certificate: {e}"}
    fp = c.fingerprint(hashes.SHA256()).hex().upper()
    dns, ips = _sans(c)
    return {"fingerprint_sha256": ":".join(fp[i:i + 2] for i in range(0, len(fp), 2)),
            "not_after": c.not_valid_after_utc.strftime("%Y-%m-%d"),
            "names": sorted(dns) + sorted(ips)}
