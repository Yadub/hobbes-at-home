"""Notifications (under /api/push): the key a browser subscribes with, the owner's devices, and which kinds
of notification are on. See push.py."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import push
from .web.deps import Conn

router = APIRouter()


class PushDevice(BaseModel):
    id: int
    label: str
    host: str = Field(description="The push service, e.g. web.push.apple.com.")
    endpoint_hash: str = Field(description="sha256 of its push address, so a page can tell it's this device.")
    created_at: str
    last_ok_at: str | None
    last_error: str | None


class PushKind(BaseModel):
    kind: str
    label: str
    on: bool


class PushSettings(BaseModel):
    public_key: str = Field(description="The dashboard's VAPID key, for pushManager.subscribe.")
    kinds: list[PushKind]
    devices: list[PushDevice]


class PushDeviceIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2000)
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=10, max_length=100)
    label: str = Field("", max_length=80)


def _settings(conn: Conn) -> dict:
    on = push.kinds(conn)
    return {"public_key": push.public_key(),
            "kinds": [{"kind": k, "label": label, "on": on[k]} for k, label in push.KINDS.items()],
            "devices": push.devices(conn)}


def _wake(request: Request) -> None:
    worker = getattr(request.app.state, "worker", None)
    if worker:
        worker.wake()


@router.get("/api/push", response_model=PushSettings)
def get_push(conn: Conn) -> Any:
    return _settings(conn)


@router.post("/api/push/devices", response_model=PushSettings)
def add_device(conn: Conn, body: PushDeviceIn) -> Any:
    try:
        push.add_device(conn, body.endpoint, body.p256dh, body.auth, body.label)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return _settings(conn)


@router.delete("/api/push/devices/{device_id}", response_model=PushSettings)
def remove_device(conn: Conn, device_id: int) -> Any:
    try:
        push.remove_device(conn, device_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    return _settings(conn)


@router.put("/api/push/kinds", response_model=PushSettings)
def set_kinds(conn: Conn, body: dict[str, bool]) -> Any:
    push.set_kinds(conn, body)
    return _settings(conn)


@router.post("/api/push/test", response_model=PushSettings)
def test(request: Request, conn: Conn) -> Any:
    """Send a test notification to every device."""
    if not push.notify(conn, "test", "Hobbes at Home", "Notifications are working.", "/settings/notifications"):
        raise HTTPException(400, "No device has notifications turned on.")
    _wake(request)
    return _settings(conn)
