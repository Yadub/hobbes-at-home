"""Secrets (sign-in tokens, app passwords, personal details the assistant needs) live in the macOS
Keychain, never in the catalog or in files. HOBBES_SECRETS=memory keeps them in memory instead,
for tests and trial runs."""

from __future__ import annotations

import os

SERVICE = "hobbes-at-home"
_MEMORY: dict[str, str] = {}


def _memory() -> bool:
    return os.environ.get("HOBBES_SECRETS") == "memory"


def get(name: str) -> str | None:
    if _memory():
        return _MEMORY.get(name)
    import keyring

    return keyring.get_password(SERVICE, name)


def put(name: str, value: str) -> None:
    if _memory():
        _MEMORY[name] = value
        return
    import keyring

    keyring.set_password(SERVICE, name, value)


def forget(name: str) -> None:
    """Remove one secret, for when a connection is turned off. Missing is fine."""
    if _memory():
        _MEMORY.pop(name, None)
        return
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(SERVICE, name)
    except PasswordDeleteError:
        pass
