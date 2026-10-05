"""Install the cert-manager certificate on GLKVM when Home Assistant requests it."""

import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import time
import urllib.parse

HOST = "glkvm.jetersen.dev"
TLS_DIR = Path("/etc/glkvm/tls")
PASSWORD_FILE = Path("/etc/glkvm/auth/password")
PIN_FILE = Path("/config/.glkvm-certificate-sha256")


def fingerprint(certificate):
    return hashlib.sha256(certificate).hexdigest()


def connect():
    """Verify normal PKI, or pin the last verified leaf if it has expired."""
    connection = http.client.HTTPSConnection(
        HOST, context=ssl.create_default_context(), timeout=4
    )
    try:
        connection.connect()
    except ssl.SSLCertVerificationError:
        connection.close()
        if not PIN_FILE.exists():
            raise
        connection = http.client.HTTPSConnection(
            HOST, context=ssl._create_unverified_context(), timeout=4
        )
        connection.connect()
        actual = fingerprint(connection.sock.getpeercert(binary_form=True))
        if actual != PIN_FILE.read_text().strip():
            connection.close()
            raise ssl.SSLError("KVM certificate does not match its saved identity")
    return connection


def request(connection, method, path, data=None, token=None):
    headers = {}
    if token:
        headers["token"] = token
    if isinstance(data, dict):
        data = json.dumps(data)
        headers["Content-Type"] = "application/json"
    elif data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    connection.request(method, path, body=data, headers=headers)
    response = connection.getresponse()
    payload = json.loads(response.read())
    if response.status != 200 or not payload.get("ok"):
        raise RuntimeError("KVM rejected the request")
    return payload["result"]


def save_pin(value):
    temporary = PIN_FILE.with_suffix(".tmp")
    temporary.write_text(value + "\n")
    temporary.replace(PIN_FILE)


def sync():
    cert_file, key_file = TLS_DIR / "tls.crt", TLS_DIR / "tls.key"
    # Check the certificate/key pair before connecting or sending credentials.
    ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_cert_chain(cert_file, key_file)
    certificate = cert_file.read_text()
    leaf = certificate.split("-----END CERTIFICATE-----", 1)[0]
    leaf += "-----END CERTIFICATE-----"
    desired = fingerprint(ssl.PEM_cert_to_DER_cert(leaf))
    connection = connect()
    try:
        actual = fingerprint(connection.sock.getpeercert(binary_form=True))
        if actual == desired:
            save_pin(actual)
            return "current"
        login = urllib.parse.urlencode(
            {"user": "admin", "passwd": PASSWORD_FILE.read_text().strip()}
        )
        token = request(connection, "POST", "/api/auth/login", login)["token"]
        request(
            connection,
            "POST",
            "/api/system/ssl_cert",
            {"ssl_cert": certificate, "ssl_key": key_file.read_text()},
            token,
        )
    finally:
        connection.close()
    # Nginx reloads asynchronously; verify the exact installed leaf with normal PKI.
    for _ in range(5):
        time.sleep(2)
        check = http.client.HTTPSConnection(
            HOST, context=ssl.create_default_context(), timeout=4
        )
        try:
            check.connect()
            if fingerprint(check.sock.getpeercert(binary_form=True)) == desired:
                save_pin(desired)
                return "updated"
        except (OSError, ssl.SSLError):
            pass
        finally:
            check.close()
    raise RuntimeError("Could not verify the installed certificate")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        print(json.dumps({"status": sync()}))
    except (ConnectionError, socket.gaierror, TimeoutError):
        print(json.dumps({"status": "offline"}))
    except Exception as error:
        if isinstance(error, OSError) and error.errno in {
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
        }:
            print(json.dumps({"status": "offline"}))
            sys.exit(0)
        # API bodies, passwords, private keys, and exception text must stay private.
        print(json.dumps({"status": "error", "reason": type(error).__name__}))
        sys.exit(1)
