from fastapi.testclient import TestClient

from .conftest import OWNER

TAILNET = {"x-forwarded-for": "100.95.139.47", "host": "my-mac.tail1234.ts.net:8780"}


def test_owner_at_the_mac(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    assert r.json()["who"] == "this Mac"


def test_owner_through_tailscale(client):
    r = client.get("/api/meta", headers={**TAILNET, "tailscale-user-login": OWNER.upper()})
    assert r.status_code == 200
    assert r.json()["who"] == OWNER


def test_other_tailnet_account_is_refused(client):
    r = client.get("/api/meta", headers={**TAILNET, "tailscale-user-login": "someone-else@example.com"})
    assert r.status_code == 403
    page = client.get("/", headers={**TAILNET, "tailscale-user-login": "someone-else@example.com"})
    assert page.status_code == 403
    assert "private" in page.text


def test_forwarded_without_identity_is_refused(client):
    # a tagged device, or anything else tailscale serve forwards without a login
    assert client.get("/api/meta", headers=TAILNET).status_code == 403


def test_identity_header_from_a_direct_connection_is_ignored(app):
    # Only tailscale serve (on this Mac) can vouch for a login; a direct peer can't set it.
    with TestClient(app, client=("100.95.139.47", 50000)) as c:
        r = c.get("/api/meta", headers={"tailscale-user-login": OWNER, "host": "my-mac.tail1234.ts.net"})
        assert r.status_code == 403


def test_no_owner_known_means_only_the_mac(client, app):
    app.state.owner = None
    assert client.get("/api/meta", headers={**TAILNET, "tailscale-user-login": OWNER}).status_code == 403
    assert client.get("/api/meta").status_code == 200


def test_only_this_macs_names(client):
    assert client.get("/api/meta", headers={"host": "evil.example.com"}).status_code == 421
    assert client.get("/api/meta", headers={"host": "other-mac.tail9999.ts.net"}).status_code == 421
    assert client.get("/api/meta", headers={"host": "my-mac:8780"}).status_code == 200
    assert client.get("/api/meta", headers={"host": "100.111.210.99:8780"}).status_code == 200


def test_funnel_is_refused(client):
    r = client.get("/api/meta", headers={"tailscale-funnel-request": "?1"})
    assert r.status_code == 403


def test_changes_only_from_own_pages(client):
    other = {"origin": "https://evil.example.com"}
    assert client.post("/api/ai/check", headers=other, json={}).status_code == 403
    same = {"origin": "http://testserver"}
    assert client.post("/api/ai/check", headers=same, json={}).status_code == 200
    cross_site = {"sec-fetch-site": "cross-site"}
    assert client.post("/api/ai/check", headers=cross_site).status_code == 403


def test_form_posts_from_a_browser_need_the_own_header(client):
    files = {"photo": ("meal.jpg", b"\xff\xd8\xff", "image/jpeg")}
    browser = {"origin": "http://testserver"}
    # passes the guard with the header (the route doesn't take files, so it isn't a 403)
    assert client.post("/api/ai/check", headers={**browser, "x-hobbes": "1"}, files=files).status_code != 403
    assert client.post("/api/ai/check", headers=browser, files=files).status_code == 403
    plain = client.post("/api/ai/check", headers={**browser, "content-type": "text/plain"}, content=b"x")
    assert plain.status_code == 415


def test_unknown_api_is_404_not_the_app(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["detail"] == "No such API."


def test_security_headers(client):
    r = client.get("/api/meta")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
