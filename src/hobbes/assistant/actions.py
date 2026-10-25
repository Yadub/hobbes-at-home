"""What the assistant would do next for the owner if it could: book an option, put a hold in the
calendar, send a message. This is the seam for later versions.

Version 1 only records these on a result, as "proposed", and shows them as next steps the owner takes
themselves with the links. Nothing here is ever performed: `PERFORMS` is False and there's no code
that acts on an action.

Later (see PLAN.md, "Bookings, honestly"), an action will be approved by the owner first (status
approved), then carried out by a separate runner with its own browser profile, up to the pay or send
button, with every step logged and a Stop button. That runner should take an action from a result
here, never anything a web page or email suggests.
"""

from __future__ import annotations

PERFORMS = False

KINDS = ("book", "buy", "hold", "remind", "send", "fill_form", "other")
NAMES = {"book": "Book", "buy": "Buy", "hold": "Hold", "remind": "Reminder", "send": "Send", "fill_form": "Fill in",
         "other": "Next step"}


def proposed(raw: list[dict], options: int, clean_link) -> list[dict]:
    """The actions an answer proposes, tidied: a known kind, the option it's about (1-based in the
    answer, 0-based here) and a link that is a real web address. Each is marked proposed."""
    out = []
    for a in raw[:5]:
        label = " ".join(str(a.get("label") or "").split())[:160]
        if not label:
            continue
        n = a.get("option")
        out.append({"kind": a.get("kind") if a.get("kind") in KINDS else "other", "label": label,
                    "option": n - 1 if isinstance(n, int) and 1 <= n <= options else None,
                    "link": clean_link(a.get("link")), "status": "proposed"})
    return out
