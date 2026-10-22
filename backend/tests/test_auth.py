import pyotp

from app.services import email
from tests.conftest import CSRF, new_client, register


def test_register_verify_login_me():
    c = new_client()
    register(c, "Alice@Example.com")
    me = c.get("/api/v1/auth/me").json()
    assert me["email"] == "alice@example.com"
    assert me["email_verified"] is True
    assert me["roles"] == ["buyer"]

    other = new_client()
    r = other.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200
    bearer = r.json()["access_token"]
    plain = new_client()
    plain.cookies.clear()
    assert plain.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bearer}"}).status_code == 200


def test_duplicate_email_and_bad_password():
    c = new_client()
    register(c, "bob@example.com")
    assert new_client().post("/api/v1/auth/register", json={
        "email": "BOB@example.com", "password": "another-password", "display_name": "Bob", "accept_terms": True,
    }).status_code == 409
    r = new_client().post("/api/v1/auth/login", json={"email": "bob@example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_terms_must_be_accepted():
    r = new_client().post("/api/v1/auth/register", json={
        "email": "x@example.com", "password": "long-enough-pass", "display_name": "X", "accept_terms": False,
    })
    assert r.status_code == 422


def test_cookie_writes_require_csrf_header():
    c = new_client()
    register(c, "carol@example.com")
    r = c.post("/api/v1/collections", json={"name": "Moodboard"}, headers={"X-Requested-With": ""})
    assert r.status_code == 403
    assert c.post("/api/v1/collections", json={"name": "Moodboard"}).status_code == 201


def test_unverified_user_cannot_open_storefront():
    c = new_client()
    register(c, "dave@example.com", verify=False)
    r = c.post("/api/v1/creators", json={"handle": "dave-shoots", "display_name": "Dave"})
    assert r.status_code == 403


def test_mfa_enrollment_and_login():
    c = new_client()
    register(c, "erin@example.com")
    secret = c.post("/api/v1/auth/mfa/setup").json()["secret"]
    assert c.post("/api/v1/auth/mfa/enable", json={"code": "000000"}).status_code == 400
    assert c.post("/api/v1/auth/mfa/enable", json={"code": pyotp.TOTP(secret).now()}).status_code == 200

    fresh = new_client()
    r = fresh.post("/api/v1/auth/login", json={"email": "erin@example.com", "password": "correct-horse-battery"})
    assert r.json()["mfa_required"] is True
    pending = {"Authorization": f"Bearer {r.json()['access_token']}"} | CSRF
    assert fresh.get("/api/v1/auth/me", headers=pending).status_code == 401  # pending token is not a session
    r = fresh.post("/api/v1/auth/mfa/verify", json={"code": pyotp.TOTP(secret).now()}, headers=pending)
    assert r.status_code == 200
    assert fresh.get("/api/v1/auth/me").json()["mfa_enabled"] is True


def test_password_reset_invalidates_sessions():
    c = new_client()
    register(c, "frank@example.com")
    assert new_client().post("/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"}).status_code == 200
    new_client().post("/api/v1/auth/password-reset/request", json={"email": "frank@example.com"})
    token = email.outbox()[-1]["body"].split("token=")[1].split()[0]
    r = new_client().post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "brand-new-password"})
    assert r.status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401  # old session revoked
    assert new_client().post("/api/v1/auth/password-reset/confirm",
                             json={"token": token, "new_password": "x" * 12}).status_code == 400  # single use


def test_login_rate_limited():
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.login_rate_limit_per_minute
    settings.login_rate_limit_per_minute = 3
    try:
        c = new_client()
        codes = [c.post("/api/v1/auth/login", json={"email": "z@example.com", "password": "nope-nope-nope"}).status_code
                 for _ in range(4)]
        assert codes[-1] == 429
    finally:
        settings.login_rate_limit_per_minute = original
