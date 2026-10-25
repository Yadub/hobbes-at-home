"""Shared request dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from .. import db


def conn_dep(request: Request) -> Iterator[sqlite3.Connection]:
    """A catalog connection for one request."""
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(conn_dep)]
