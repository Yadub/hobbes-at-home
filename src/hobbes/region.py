"""Where the owner lives and what they mostly eat, chosen in setup (and in Settings), so the AI's prompts fit
them: how meals are named and portioned, where branded food's labels are looked up, and the currency prices
are given in. Until it's chosen, the Mac's own region is used.
"""

from __future__ import annotations

import sqlite3
import subprocess
from typing import Any

from . import db

# Country code: (name in a sentence, currency, its symbol, large grocery sellers online)
COUNTRIES: dict[str, tuple[str, str, str, str]] = {
    "AE": ("the United Arab Emirates", "AED", "AED ", "Carrefour, Noon, Amazon.ae"),
    "AU": ("Australia", "AUD", "A$", "Woolworths, Coles"),
    "CA": ("Canada", "CAD", "C$", "Loblaws, Walmart.ca, Amazon.ca"),
    "DE": ("Germany", "EUR", "€", "REWE, Edeka, Amazon.de"),
    "ES": ("Spain", "EUR", "€", "Mercadona, Carrefour, Amazon.es"),
    "FR": ("France", "EUR", "€", "Carrefour, Auchan, Amazon.fr"),
    "GB": ("the United Kingdom", "GBP", "£", "Tesco, Sainsbury's, Ocado"),
    "IE": ("Ireland", "EUR", "€", "Tesco Ireland, SuperValu, Dunnes Stores"),
    "IN": ("India", "INR", "₹", "BigBasket, Blinkit, Zepto, Swiggy Instamart, Amazon.in"),
    "IT": ("Italy", "EUR", "€", "Esselunga, Carrefour, Amazon.it"),
    "NL": ("the Netherlands", "EUR", "€", "Albert Heijn, Jumbo"),
    "NZ": ("New Zealand", "NZD", "NZ$", "Countdown (Woolworths), New World"),
    "SG": ("Singapore", "SGD", "S$", "FairPrice, RedMart, Cold Storage"),
    "US": ("the United States", "USD", "$", "Walmart, Target, Instacart, Amazon"),
}
DEFAULT_COUNTRY = "US"

CUISINES = {
    "IN": "Indian home food (North and South Indian), and other food too",
}

# How the reading should name and portion food: Indian home food has its own measures (katori, phulka).
NAMING = {
    "IN": ('a clear, common name as an Indian home cook would say it, e.g. "Toor dal", "Phulka (roti)",\n'
           '  "Jeera rice", "Aloo gobi", "Curd (dahi)", "Masala dosa". For other food, its usual English name.'),
}
NAMING_DEFAULT = ('a clear, common name as a home cook would say it, e.g. "Spaghetti bolognese", "Greek yoghurt",\n'
                  '  "Scrambled eggs on toast", "Chicken caesar salad".')
PORTIONS = {
    "IN": ("Portion guide for Indian food: 1 katori of dal, sabzi or curd ≈ 150 g; 1 phulka ≈ 30 g, a thicker roti\n"
           "or chapati ≈ 40 g, a paratha ≈ 80 g; 1 cup of cooked rice ≈ 160 g; 1 idli ≈ 40 g; a plain dosa ≈ 100 g;\n"
           "1 tablespoon of ghee or oil ≈ 13 g."),
}
PORTIONS_DEFAULT = ("Portion guide: 1 cup of cooked rice or pasta ≈ 160 g; 1 slice of bread ≈ 35 g; 1 medium egg\n"
                    "≈ 50 g; 1 bowl of soup ≈ 300 g; 1 tablespoon of oil or butter ≈ 13 g.")
MEASURES = {"IN": '"1 katori", "2 phulkas", "1 cup", "1 medium banana"'}
MEASURES_DEFAULT = '"1 bowl", "2 slices", "1 cup", "1 medium banana"'


def mac_country() -> str | None:
    """The Mac's region (System Settings, General, Language & Region), as a country code."""
    try:
        r = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    code = r.stdout.strip().split("@")[0].split("_")[-1].upper()
    return code if len(code) == 2 and code.isalpha() else None


def get(conn: sqlite3.Connection) -> dict[str, Any]:
    code = (db.get_setting(conn, "region.country") or mac_country() or DEFAULT_COUNTRY).upper()
    name, currency, symbol, sellers = COUNTRIES.get(code, (code, "", "", ""))
    currency = db.get_setting(conn, "region.currency") or currency or "USD"
    if currency != COUNTRIES.get(code, ("", "", "", ""))[1]:
        symbol = next((c[2] for c in COUNTRIES.values() if c[1] == currency), currency + " ")
    cuisine = db.get_setting(conn, "region.cuisine") or CUISINES.get(code) or (
        f"the home food usual in {name}, and other food too" if code in COUNTRIES else "home food, and other food")
    return {"country_code": code, "country": name, "currency": currency, "symbol": symbol, "cuisine": cuisine,
            "sellers": sellers or "large grocery sellers online where they live", "chosen":
            db.get_setting(conn, "region.country") is not None}


def put(conn: sqlite3.Connection, country: str, cuisine: str | None = None, currency: str | None = None) -> None:
    code = country.strip().upper()
    if len(code) != 2 or not code.isalpha():
        raise ValueError("Give the country as its two-letter code, like GB, IN or US.")
    with db.write_lock(conn):
        db.set_setting(conn, "region.country", code)
        db.set_setting(conn, "region.cuisine", (cuisine or "").strip()[:200])
        db.set_setting(conn, "region.currency", (currency or "").strip().upper()[:3])


def fill(text: str, conn: sqlite3.Connection | None) -> str:
    """Put the owner's region into a prompt: {eats}, {naming}, {measures}, {portions}, {country}, {sellers},
    {currency} and {symbol}."""
    if conn is None:
        c = db.connect()
        try:
            r = get(c)
        finally:
            c.close()
    else:
        r = get(conn)
    code = r["country_code"]
    for key, value in (("{eats}", f"They mostly eat {r['cuisine']}."), ("{naming}", NAMING.get(code, NAMING_DEFAULT)),
                       ("{measures}", MEASURES.get(code, MEASURES_DEFAULT)),
                       ("{portions}", PORTIONS.get(code, PORTIONS_DEFAULT)), ("{country}", r["country"]),
                       ("{sellers}", r["sellers"]), ("{currency}", r["currency"]), ("{symbol}", r["symbol"])):
        text = text.replace(key, value)
    return text
