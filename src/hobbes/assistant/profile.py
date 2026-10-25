"""The owner's profile: plain facts the assistant reads before every job (home airport, seat, budgets,
who usually travels with them), and the suggestions it makes for it.

The facts are the owner's own: they can see and edit all of them, and every edit or removal can be
undone. A fact marked secret (a passport or loyalty number) keeps its value in the Keychain, never in
the catalog, and is never sent to the AI: the assistant is only told that it exists, by name.

Suggestions come from the assistant ("prefers aisle seats") and change nothing until the owner adds
them. Anything that looks like an ID number is never suggested.
"""

from __future__ import annotations

import re
import sqlite3

from .. import changes, db, secrets

TOPICS = ("travel", "stays", "budget", "payments", "bookings", "food", "people", "ids", "other")
TOPIC_NAMES = {"travel": "Travel", "stays": "Hotels", "budget": "Budgets", "payments": "Cards and rewards",
               "bookings": "Where to book", "food": "Food", "people": "People", "ids": "Loyalty and IDs",
               "other": "Other"}

# Facts worth having, offered on the profile page until they're filled in: (topic, label, example, secret).
PROMPTS: list[tuple[str, str, str, bool]] = [
    ("travel", "Home airport", "London Heathrow (LHR)", False),
    ("travel", "Preferred airlines", "Any full-service airline; not low-cost for long flights", False),
    ("travel", "Seat", "Aisle, near the front", False),
    ("travel", "Luggage", "One cabin bag", False),
    ("stays", "Hotel style", "Small and quiet, good breakfast", False),
    ("stays", "Hotel must-haves", "Fast Wi-Fi, a pool", False),
    ("budget", "Hotel budget", "Up to 150 a night", False),
    ("budget", "Flight budget", "Economy; premium economy over 6 hours", False),
    ("payments", "Cards", "Which card to use, and any travel portal that gives more", False),
    ("bookings", "Travel sites", "Booking.com, Skyscanner, Google Flights", False),
    ("bookings", "Restaurant bookings", "OpenTable, the restaurant's own site", False),
    ("food", "Food preferences", "Vegetarian; loves Thai food", False),
    ("people", "Travel companions", "My partner; sometimes my parents", False),
    ("ids", "Loyalty programmes", "An airline's programme, Marriott Bonvoy", False),
    ("ids", "Passport number", "", True),
]

MAX_LABEL = 60
MAX_VALUE = 500
_ID_LIKE = re.compile(r"\d[\d\s-]{5,}\d")


def _secret_name(fact_id: int) -> str:
    return f"assistant.fact.{fact_id}"


def _clean(text: str | None, limit: int) -> str:
    return " ".join((text or "").split())[:limit]


def _fact(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "topic": r["topic"] if r["topic"] in TOPICS else "other", "label": r["label"],
            "value": "" if r["secret"] else r["value"], "secret": bool(r["secret"]), "updated_at": r["updated_at"]}


def facts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM assistant_facts WHERE deleted_at IS NULL ORDER BY id").fetchall()
    order = {t: i for i, t in enumerate(TOPICS)}
    return sorted((_fact(r) for r in rows), key=lambda f: order[f["topic"]])


def prompts(conn: sqlite3.Connection) -> list[dict]:
    """The suggested facts the owner hasn't filled in yet."""
    have = {f["label"].lower() for f in facts(conn)}
    return [{"topic": t, "label": label, "example": example, "secret": secret}
            for t, label, example, secret in PROMPTS if label.lower() not in have]


def _check(topic: str, label: str) -> None:
    if topic not in TOPICS:
        raise ValueError("Unknown topic.")
    if not label:
        raise ValueError("Give it a name, like Home airport.")


def add(conn: sqlite3.Connection, *, topic: str, label: str, value: str, secret: bool = False) -> dict:
    label, value = _clean(label, MAX_LABEL), (value or "").strip()[:MAX_VALUE]
    _check(topic, label)
    if not value:
        raise ValueError("Write what it is.")
    now = db.now()
    with db.write_lock(conn):
        cur = conn.execute("INSERT INTO assistant_facts (topic, label, value, secret, created_at, updated_at) "
                           "VALUES (?, ?, ?, ?, ?, ?)", (topic, label, "" if secret else value, int(secret), now, now))
        fact_id = cur.lastrowid
        assert fact_id is not None
        if secret:
            _put_secret(fact_id, value)
        row = changes.row(conn, "assistant_facts", fact_id)
        assert row
        # Adding is undone by removing, so it's recorded the same way.
        change_id = changes.record(conn, "fact.add", "assistant_facts", fact_id, {**row, "deleted_at": now}, row)
    return {"fact_id": fact_id, "change_id": change_id}


def _put_secret(fact_id: int, value: str) -> None:
    try:
        secrets.put(_secret_name(fact_id), value)
    except Exception:
        raise ValueError("The Keychain couldn't be reached, so the secret wasn't saved.") from None


def edit(conn: sqlite3.Connection, fact_id: int, *, topic: str | None = None, label: str | None = None,
         value: str | None = None) -> dict:
    """Change a fact. Recorded for Undo, except a secret's value, which lives only in the Keychain."""
    with db.write_lock(conn):
        before = changes.row(conn, "assistant_facts", fact_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such fact.")
        new = dict(before)
        if topic is not None:
            new["topic"] = topic
        if label is not None:
            new["label"] = _clean(label, MAX_LABEL)
        _check(new["topic"], new["label"])
        secret_changed = False
        if value is not None:
            value = value.strip()[:MAX_VALUE]
            if not value:
                raise ValueError("Write what it is, or remove it.")
            if before["secret"]:
                _put_secret(fact_id, value)
                secret_changed = True
            else:
                new["value"] = value
        if all(new[k] == before[k] for k in ("topic", "label", "value")):
            return {"fact_id": fact_id, "change_id": None, "secret_changed": secret_changed}
        new["updated_at"] = db.now()
        conn.execute("UPDATE assistant_facts SET topic = ?, label = ?, value = ?, updated_at = ? WHERE id = ?",
                     (new["topic"], new["label"], new["value"], new["updated_at"], fact_id))
        change_id = changes.record(conn, "fact.edit", "assistant_facts", fact_id, before, new)
    return {"fact_id": fact_id, "change_id": change_id, "secret_changed": secret_changed}


def remove(conn: sqlite3.Connection, fact_id: int) -> dict:
    """Hide a fact (Undo brings it back). A secret stays in the Keychain so Undo can restore it."""
    with db.write_lock(conn):
        before = changes.row(conn, "assistant_facts", fact_id)
        if not before or before["deleted_at"]:
            raise LookupError("There's no such fact.")
        now = db.now()
        conn.execute("UPDATE assistant_facts SET deleted_at = ? WHERE id = ?", (now, fact_id))
        change_id = changes.record(conn, "fact.delete", "assistant_facts", fact_id, before,
                                   {**before, "deleted_at": now})
    return {"fact_id": fact_id, "change_id": change_id}


def for_prompt(conn: sqlite3.Connection) -> str:
    """The profile as the AI sees it. Secret values are left out; only their names are given."""
    shared, kept = [], []
    for f in facts(conn):
        if f["secret"]:
            kept.append(f["label"])
        else:
            shared.append(f"- {TOPIC_NAMES[f['topic']]} · {f['label']}: {f['value']}")
    text = "\n".join(shared) if shared else "(Nothing yet. Use sensible defaults and say what you assumed.)"
    if kept:
        text += ("\nKept private in the owner's Keychain and not shared with you: " + ", ".join(kept)
                 + ". Never ask for these; if a step needs one, say the owner will need it.")
    return text


# ---------------------------------------------------------------- suggestions from the assistant

def _suggestion(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    current = conn.execute("SELECT value, secret FROM assistant_facts WHERE deleted_at IS NULL AND lower(label) = ? "
                           "ORDER BY id DESC LIMIT 1", (r["label"].lower(),)).fetchone()
    return {"id": r["id"], "task_id": r["task_id"], "topic": r["topic"] if r["topic"] in TOPICS else "other",
            "label": r["label"], "value": r["value"], "why": r["why"],
            "replaces": current["value"] if current and not current["secret"] else None}


def suggestions(conn: sqlite3.Connection, task_id: int | None = None) -> list[dict]:
    """Open suggestions, newest first (one task's, or all)."""
    sql = "SELECT * FROM assistant_suggestions WHERE status = 'open'"
    args: tuple = ()
    if task_id is not None:
        sql, args = sql + " AND task_id = ?", (task_id,)
    return [_suggestion(conn, r) for r in conn.execute(sql + " ORDER BY id DESC", args)]


def suggest(conn: sqlite3.Connection, task_id: int, items: list[dict], limit: int = 3) -> int:
    """Store what the assistant thinks it learned. Skips anything already in the profile, already
    suggested or dismissed before, about a secret, or that looks like an ID number."""
    added = 0
    for item in items:
        if added >= limit:
            break
        topic = item.get("topic") if item.get("topic") in TOPICS else "other"
        label, value = _clean(item.get("label"), MAX_LABEL), _clean(item.get("value"), 200)
        why = _clean(item.get("why"), 200)
        if not label or not value or _ID_LIKE.search(value):
            continue
        same = conn.execute("SELECT value, secret FROM assistant_facts WHERE deleted_at IS NULL AND lower(label) = ?",
                            (label.lower(),)).fetchall()
        if any(r["secret"] or r["value"].lower() == value.lower() for r in same):
            continue
        if conn.execute("SELECT 1 FROM assistant_suggestions WHERE lower(label) = ? AND lower(value) = ? "
                        "AND status IN ('open', 'dismissed')", (label.lower(), value.lower())).fetchone():
            continue
        conn.execute("INSERT INTO assistant_suggestions (task_id, topic, label, value, why, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (task_id, topic, label, value, why, db.now()))
        added += 1
    return added


def _open_suggestion(conn: sqlite3.Connection, suggestion_id: int) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM assistant_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not r:
        raise LookupError("There's no such suggestion.")
    if r["status"] != "open":
        raise ValueError("That suggestion has already been dealt with.")
    return r


def accept(conn: sqlite3.Connection, suggestion_id: int) -> dict:
    """Put a suggestion into the profile: it replaces the value of a fact with the same name, or adds
    one. Undo puts the profile back."""
    r = _open_suggestion(conn, suggestion_id)
    current = conn.execute("SELECT id, secret FROM assistant_facts WHERE deleted_at IS NULL AND lower(label) = ? "
                           "ORDER BY id DESC LIMIT 1", (r["label"].lower(),)).fetchone()
    if current and current["secret"]:
        raise ValueError("That's kept in the Keychain; change it on the profile page.")
    if current:
        done = edit(conn, current["id"], value=r["value"])
    else:
        done = add(conn, topic=r["topic"] if r["topic"] in TOPICS else "other", label=r["label"], value=r["value"])
    conn.execute("UPDATE assistant_suggestions SET status = 'accepted', fact_id = ?, decided_at = ? WHERE id = ?",
                 (done["fact_id"], db.now(), suggestion_id))
    return {"fact_id": done["fact_id"], "change_id": done["change_id"]}


def dismiss(conn: sqlite3.Connection, suggestion_id: int) -> dict:
    with db.write_lock(conn):
        _open_suggestion(conn, suggestion_id)
        before = changes.row(conn, "assistant_suggestions", suggestion_id)
        assert before
        now = db.now()
        conn.execute("UPDATE assistant_suggestions SET status = 'dismissed', decided_at = ? WHERE id = ?",
                     (now, suggestion_id))
        change_id = changes.record(conn, "suggestion.dismiss", "assistant_suggestions", suggestion_id, before,
                                   {**before, "status": "dismissed", "decided_at": now})
    return {"change_id": change_id}
