"""The owner's region: how meals are read and named, where labels are looked up, and prices' currency."""

from hobbes import region
from hobbes.diet import drinks, meals


def test_default_until_chosen_then_the_owner_s(conn):
    r = region.get(conn)
    assert (r["country_code"], r["currency"], r["symbol"], r["chosen"]) == ("US", "USD", "$", False)
    assert "katori" not in region.fill(meals.PROMPT, conn)
    region.put(conn, "in")
    r = region.get(conn)
    assert (r["country"], r["currency"], r["symbol"], r["chosen"]) == ("India", "INR", "₹", True)
    text = region.fill(meals.PROMPT, conn)
    assert "They mostly eat Indian home food" in text and "1 katori" in text and "{" not in text.replace("{note}", "")


def test_own_cuisine_and_currency(conn):
    region.put(conn, "GB", cuisine="mostly vegetarian Mediterranean food", currency="eur")
    assert region.fill("{eats} {sellers} {symbol}", conn) == \
        "They mostly eat mostly vegetarian Mediterranean food. Tesco, Sainsbury's, Ocado €"


def test_typical_figures_for_where_they_live(conn):
    labels = [t["label"] for t in drinks.reference(conn)["caffeine"]["typical"]]
    assert labels == ["US adults who have caffeine"]
    region.put(conn, "IN")
    assert "Young adults in India" in [t["label"] for t in drinks.reference(conn)["caffeine"]["typical"]]


def test_through_the_api(client):
    assert client.get("/api/region").json()["chosen"] is False
    r = client.put("/api/region", json={"country": "AU", "cuisine": "", "currency": ""}).json()
    assert (r["country"], r["symbol"], r["chosen"]) == ("Australia", "A$", True)
    assert client.put("/api/region", json={"country": "Australia", "cuisine": "", "currency": ""}).status_code == 422
    assert {"code": "IN", "name": "India"} in client.get("/api/region").json()["countries"]
