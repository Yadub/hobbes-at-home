"""Notifications on the owner's devices, by Web Push: the iPhone (the dashboard added to its Home Screen),
or a browser on a laptop.

A device turns them on in Settings: the page subscribes with the browser and sends its push address and
keys, which are kept in the Keychain (`push.device.<id>`); the catalog keeps a label and a hash of the
address. Each message is encrypted for the device (RFC 8291) and signed with the dashboard's own key
(VAPID, RFC 8292; the private key is in the Keychain as `push.vapid`), so the push service (Apple's, for an
iPhone) carries it without being able to read it. Messages go only to the known push services (HOSTS).

What sends one: `notify(conn, kind, ...)`, which queues a `push.send` job when that kind is switched on
and a device is set up. The owner switches each kind on or off (KINDS), and each device off.

Browsers allow push only on HTTPS pages, and an iPhone only from the Home Screen app.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import os
import sqlite3
import struct
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import db, jobs, secrets
from .web import net

KINDS = {
    "changes": "A watched job changed",
    "routines": "A routine has new results",
    "needs_you": "A job needs your answer or couldn't finish",
    "done": "A job you started is done",
    "backups": "A backup failed or didn't check out",
}
HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com")
HOST_SUFFIXES = (".notify.windows.com", ".push.apple.com")
SEND_KIND = "push.send"
TTL = 24 * 3600
VAPID_KEY = "push.vapid"


class PushError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---------------------------------------------------------------- the dashboard's own key

def _vapid() -> ec.EllipticCurvePrivateKey:
    pem = secrets.get(VAPID_KEY)
    if pem:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key
    key = ec.generate_private_key(ec.SECP256R1())
    secrets.put(VAPID_KEY, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()).decode())
    return key


def public_key() -> str:
    """The key a browser subscribes with (base64url, uncompressed point)."""
    return _b64(_point(_vapid().public_key()))


@functools.cache
def subject() -> str:
    """Who the push services can contact about these messages (VAPID's "sub"): the dashboard's https address
    on the tailnet. Apple refuses a mailto: at localhost."""
    name = net.info().get("name")
    return f"https://{name}" if name else "mailto:owner@example.com"


def vapid_header(endpoint: str, now: float | None = None) -> str:
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600),
              "sub": subject()}
    signing = (_b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
               + _b64(json.dumps(claims, separators=(",", ":")).encode()))
    key = _vapid()
    r, s = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={_b64(_point(key.public_key()))}"


# ---------------------------------------------------------------- encryption (aes128gcm)

def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(p256dh: bytes, auth: bytes, plaintext: bytes, *, salt: bytes | None = None,
            key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """One message for one device: RFC 8291's single record, with its header."""
    salt = salt or os.urandom(16)
    key = key or ec.generate_private_key(ec.SECP256R1())
    ua = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    ours = _point(key.public_key())
    ikm = _hkdf(auth, key.exchange(ec.ECDH(), ua), b"WebPush: info\x00" + p256dh + ours, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)
    return salt + struct.pack(">IB", 4096, len(ours)) + ours + body


# ---------------------------------------------------------------- devices

def check_host(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host in HOSTS or host.endswith(HOST_SUFFIXES)):
        raise ValueError("That isn't a push service the dashboard sends to.")
    return host


def _hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def devices(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r["id"], "label": r["label"], "host": r["host"], "endpoint_hash": r["endpoint_hash"],
             "created_at": r["created_at"], "last_ok_at": r["last_ok_at"], "last_error": r["last_error"]}
            for r in conn.execute("SELECT * FROM push_devices WHERE removed_at IS NULL ORDER BY id")]


def add_device(conn: sqlite3.Connection, endpoint: str, p256dh: str, auth: str, label: str) -> dict:
    host = check_host(endpoint)
    try:
        if len(_unb64(p256dh)) != 65 or len(_unb64(auth)) != 16:
            raise ValueError
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _unb64(p256dh))
    except ValueError:
        raise ValueError("The browser's push keys aren't valid.") from None
    label = " ".join(label.split())[:40] or "This device"
    with db.write_lock(conn):
        device_id = conn.execute(
            "INSERT INTO push_devices (label, endpoint_hash, host, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (endpoint_hash) DO UPDATE SET label = excluded.label, removed_at = NULL, last_error = NULL "
            "RETURNING id", (label, _hash(endpoint), host, db.now())).fetchone()[0]
    secrets.put(f"push.device.{device_id}", json.dumps({"endpoint": endpoint, "p256dh": p256dh, "auth": auth}))
    return next(d for d in devices(conn) if d["id"] == device_id)


def remove_device(conn: sqlite3.Connection, device_id: int, why: str | None = None) -> None:
    cur = conn.execute("UPDATE push_devices SET removed_at = ?, last_error = coalesce(?, last_error) WHERE id = ? "
                       "AND removed_at IS NULL", (db.now(), why, device_id))
    if not cur.rowcount:
        raise LookupError("There's no such device.")
    secrets.forget(f"push.device.{device_id}")


# ---------------------------------------------------------------- what's switched on

def kinds(conn: sqlite3.Connection) -> dict[str, bool]:
    saved = json.loads(db.get_setting(conn, "push.kinds") or "{}")
    return {k: bool(saved.get(k, True)) for k in KINDS}


def set_kinds(conn: sqlite3.Connection, changes: dict[str, bool]) -> dict[str, bool]:
    now = kinds(conn) | {k: bool(v) for k, v in changes.items() if k in KINDS}
    db.set_setting(conn, "push.kinds", json.dumps(now))
    return now


def notify(conn: sqlite3.Connection, kind: str, title: str, body: str, url: str = "/") -> bool:
    """Queue a notification for every device, if this kind is on and there's a device. Safe to call inside
    a write lock (it only adds a job)."""
    if kind != "test" and not kinds(conn).get(kind):
        return False
    if conn.execute("SELECT 1 FROM push_devices WHERE removed_at IS NULL").fetchone() is None:
        return False
    jobs.enqueue(conn, SEND_KIND, {"kind": kind, "title": title[:80], "body": body[:240], "url": url})
    return True


# ---------------------------------------------------------------- sending

def transport(url: str, body: bytes, headers: dict[str, str], timeout: float = 15) -> int | tuple[int, str]:
    """One POST to a push service: its status, and its reason when it refused. Replaced in tests."""
    if os.environ.get("HOBBES_OFFLINE") == "1":
        raise PushError("offline")
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        try:
            text = e.read(2000).decode(errors="replace")
            reason = json.loads(text).get("reason") or text if text.startswith("{") else text
        except (OSError, ValueError, AttributeError):
            reason = ""
        return e.code, " ".join(str(reason).split())[:200]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PushError(f"The push service couldn't be reached ({e}).") from None


def send(conn: sqlite3.Connection, device_id: int, message: dict) -> str:
    """Send one message to one device: "sent", "gone" (the device was removed), or "failed"."""
    raw = secrets.get(f"push.device.{device_id}")
    if not raw:
        remove_device(conn, device_id, "Its keys are missing; turn notifications on again there.")
        return "gone"
    sub = json.loads(raw)
    check_host(sub["endpoint"])
    payload = json.dumps(message, ensure_ascii=False).encode()
    body = encrypt(_unb64(sub["p256dh"]), _unb64(sub["auth"]), payload)
    headers = {"Authorization": vapid_header(sub["endpoint"]), "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "TTL": str(TTL), "Urgency": "normal"}
    try:
        answer = transport(sub["endpoint"], body, headers)
    except PushError as e:
        conn.execute("UPDATE push_devices SET last_error = ? WHERE id = ?", (str(e), device_id))
        return "failed"
    status, reason = answer if isinstance(answer, tuple) else (answer, "")
    if status in (200, 201, 202):
        conn.execute("UPDATE push_devices SET last_ok_at = ?, last_error = NULL WHERE id = ?", (db.now(), device_id))
        return "sent"
    if status in (404, 410):
        remove_device(conn, device_id, "The push service said this device has gone; turn notifications on again "
                                       "there.")
        return "gone"
    conn.execute("UPDATE push_devices SET last_error = ? WHERE id = ?",
                 (f"The push service refused it (HTTP {status}{': ' + reason if reason else ''}).", device_id))
    return "failed"


@jobs.handler(SEND_KIND)
def send_job(conn: sqlite3.Connection, payload: dict) -> dict[str, Any]:
    message = {"title": payload.get("title") or "Hobbes at Home", "body": payload.get("body") or "",
               "url": payload.get("url") or "/", "tag": payload.get("kind") or ""}
    out: dict[str, int] = {}
    for d in devices(conn):
        result = send(conn, d["id"], message)
        out[result] = out.get(result, 0) + 1
    return out
