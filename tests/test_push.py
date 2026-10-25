"""Notifications by Web Push: encryption a device can read, the signed VAPID header, devices, which kinds
are on, sending, and what the assistant sends."""

import base64
import json
import os
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from hobbes import jobs, push, secrets
from hobbes.assistant import tasks, watches

from .test_assistant import answer, use

APPLE = "https://web.push.apple.com/QGuQyavXutnMFOXd8Xp7aIZAT0Qo"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Device:
    """A browser's side of a subscription: its keys, and decrypting what arrives."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.public = self.key.public_key().public_bytes(serialization.Encoding.X962,
                                                         serialization.PublicFormat.UncompressedPoint)

    def decrypt(self, body: bytes) -> bytes:
        salt, (rs, idlen) = body[:16], struct.unpack(">IB", body[16:21])
        server = body[21:21 + idlen]
        assert rs == 4096 and idlen == 65
        shared = self.key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server))

        def hkdf(salt_, ikm, info, n):
            return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt_, info=info).derive(ikm)

        ikm = hkdf(self.auth, shared, b"WebPush: info\x00" + self.public + server, 32)
        cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
        nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
        plain = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
        assert plain.endswith(b"\x02")
        return plain[:-1]


@pytest.fixture
def sent(monkeypatch):
    """What reached the push services: (url, body, headers); answers with `status[0]`."""
    out: list = []
    status = [201]

    def transport(url, body, headers, timeout=15):
        out.append((url, body, headers))
        return status[0]

    monkeypatch.setattr(push, "transport", transport)
    out.append(status)  # the last item is the status to answer with
    return out


def test_a_device_can_read_what_is_sent(conn, sent):
    status = sent.pop()
    d = Device()
    dev = push.add_device(conn, APPLE, b64(d.public), b64(d.auth), "  iPhone  ")
    assert dev["label"] == "iPhone" and dev["host"] == "web.push.apple.com"
    assert json.loads(secrets.get(f"push.device.{dev['id']}"))["endpoint"] == APPLE  # in the Keychain, not the catalog
    assert APPLE not in json.dumps([dict(r) for r in conn.execute("SELECT * FROM push_devices")])

    assert push.send(conn, dev["id"], {"title": "Mumbai–Bangkok", "body": "Fare fell to ₹11,400"}) == "sent"
    url, body, headers = sent[-1]
    assert url == APPLE and headers["Content-Encoding"] == "aes128gcm" and headers["TTL"] == "86400"
    assert json.loads(d.decrypt(body)) == {"title": "Mumbai–Bangkok", "body": "Fare fell to ₹11,400"}
    assert push.devices(conn)[0]["last_ok_at"]

    # The VAPID header is a JWT for the push service's origin, signed with the dashboard's key.
    t, k = headers["Authorization"].removeprefix("vapid t=").split(", k=")
    assert k == push.public_key() and len(unb64(k)) == 65
    head, claims, sig = t.split(".")
    claims_ = json.loads(unb64(claims))
    assert claims_["aud"] == "https://web.push.apple.com"
    assert "localhost" not in claims_["sub"] and claims_["sub"].startswith(("https://", "mailto:"))  # Apple refuses it
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(k))
    raw = unb64(sig)
    public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                  f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))

    # A refusal keeps the push service's reason, so it can be put right.
    status[0] = (403, "BadJwtToken")
    assert push.send(conn, dev["id"], {"title": "x"}) == "failed"
    assert push.devices(conn)[0]["last_error"] == "The push service refused it (HTTP 403: BadJwtToken)."

    # A device the push service has forgotten is removed, keys and all.
    status[0] = 410
    assert push.send(conn, dev["id"], {"title": "x"}) == "gone"
    assert push.devices(conn) == [] and secrets.get(f"push.device.{dev['id']}") is None
    # Turned on again there, it's the same device back.
    assert push.add_device(conn, APPLE, b64(d.public), b64(d.auth), "iPhone")["id"] == dev["id"]


def test_only_known_push_services_and_valid_keys(conn):
    d = Device()
    for bad in ("http://web.push.apple.com/x", "https://evil.example/x", "https://192.168.1.2/x",
                "https://web.push.apple.com.evil.example/x"):
        with pytest.raises(ValueError, match="push service"):
            push.add_device(conn, bad, b64(d.public), b64(d.auth), "x")
    with pytest.raises(ValueError, match="keys"):
        push.add_device(conn, APPLE, b64(b"\x04" + b"0" * 64), b64(d.auth), "x")
    with pytest.raises(ValueError, match="keys"):
        push.add_device(conn, APPLE, b64(d.public), b64(b"short"), "x")
    assert push.add_device(conn, "https://fcm.googleapis.com/fcm/send/abc", b64(d.public), b64(d.auth), "Mac")


def test_kinds_and_queueing(conn, sent, monkeypatch):
    sent.pop()
    assert push.notify(conn, "done", "Done", "x") is False  # no device yet
    d = Device()
    push.add_device(conn, APPLE, b64(d.public), b64(d.auth), "iPhone")
    assert all(push.kinds(conn).values())
    assert push.notify(conn, "done", "Done: hotel", "Recommended: Casa Lisboa", "/assistant/task/1")
    push.set_kinds(conn, {"done": False, "nonsense": True})
    assert push.kinds(conn)["done"] is False and "nonsense" not in push.kinds(conn)
    assert push.notify(conn, "done", "Done", "x") is False
    assert jobs.run_one(conn)
    assert json.loads(Device.decrypt(d, sent[-1][1]))["url"] == "/assistant/task/1"

    monkeypatch.setattr(push, "transport", lambda *a, **k: (_ for _ in ()).throw(push.PushError("offline")))
    push.notify(conn, "changes", "Fare changed", "Now ₹9,800")
    jobs.run_one(conn)
    assert push.devices(conn)[0]["last_error"] == "offline"


def queued(conn) -> list[dict]:
    return [json.loads(r[0]) for r in conn.execute("SELECT payload FROM jobs WHERE kind = 'push.send' ORDER BY id")]


def drain(conn) -> None:
    while jobs.run_one(conn):
        pass


def test_what_the_assistant_sends(conn, sent, monkeypatch):
    d = Device()
    push.add_device(conn, APPLE, b64(d.public), b64(d.auth), "iPhone")
    use(monkeypatch, answer())
    task_id = tasks.create(conn, "Hotel near Lisbon")
    drain(conn)
    assert queued(conn)[-1] == {"kind": "done", "title": "Done: Hotel near Lisbon, 12–15 Nov",
                                "body": "Recommended: Casa Lisboa", "url": f"/assistant/task/{task_id}"}

    # A scheduled look with no change sends nothing; a change does.
    watches.watch(conn, task_id, "daily")
    before = len(queued(conn))
    use(monkeypatch, answer(changed=False, change=""))
    watches.look_now(conn, task_id)
    drain(conn)
    assert len(queued(conn)) == before
    use(monkeypatch, answer(changed=True, change="Now ₹6,100 a night"))
    watches.look_now(conn, task_id)
    drain(conn)
    assert queued(conn)[-1]["kind"] == "changes" and queued(conn)[-1]["body"] == "Now ₹6,100 a night"

    # A question, and a failure, are both "needs you".
    use(monkeypatch, answer(status="needs_you", question={"text": "Which dates?", "why": "x", "choices": ["A", "B"]}))
    tasks.message(conn, task_id, "Other dates")
    drain(conn)
    assert queued(conn)[-1]["kind"] == "needs_you" and queued(conn)[-1]["body"] == "Which dates?"
    monkeypatch.setenv("FAKE_CODEX_FAIL", "1")
    tasks.message(conn, task_id, "12–15")
    drain(conn)
    assert queued(conn)[-1]["kind"] == "needs_you" and queued(conn)[-1]["title"].startswith("Couldn't finish")


def test_push_through_the_api(client, conn):
    s = client.get("/api/push").json()
    assert len(unb64(s["public_key"])) == 65 and s["devices"] == []
    assert [k["kind"] for k in s["kinds"]] == list(push.KINDS) and all(k["on"] for k in s["kinds"])
    assert client.post("/api/push/test").status_code == 400

    d = Device()
    r = client.post("/api/push/devices", json={"endpoint": APPLE, "p256dh": b64(d.public), "auth": b64(d.auth),
                                               "label": "iPhone"})
    assert r.status_code == 200, r.text
    dev = r.json()["devices"][0]
    assert dev["label"] == "iPhone" and "endpoint" not in dev
    assert client.post("/api/push/devices", json={"endpoint": "https://evil.example/x", "p256dh": b64(d.public),
                                                  "auth": b64(d.auth)}).status_code == 400
    assert client.put("/api/push/kinds", json={"backups": False}).json()["kinds"][4] == \
        {"kind": "backups", "label": "A backup failed or didn't check out", "on": False}
    assert client.post("/api/push/test").status_code == 200
    assert client.delete(f"/api/push/devices/{dev['id']}").json()["devices"] == []
    assert client.delete(f"/api/push/devices/{dev['id']}").status_code == 404
