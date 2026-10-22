import io
import os
import re
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="mkt-test-"))
os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp / 'test.db'}"),
    LOCAL_STORAGE_PATH=str(_tmp / "storage"),
    SECRET_KEY="test-secret-key-0123456789abcdef0123456789",
    LOGIN_RATE_LIMIT_PER_MINUTE="1000",
    FEATURE_PAID_LICENSING="true",
    PAYMENT_PROVIDER="fake",
    EARNINGS_HOLD_DAYS="14",
    MIN_PAYOUT_CENTS="1000",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Role, User, UserRole  # noqa: E402
from app.services import email  # noqa: E402
from app.services.payments import get_provider  # noqa: E402
from app.services.reference_data import seed_reference_data  # noqa: E402


def _reset_schema() -> None:
    if engine.dialect.name != "sqlite":
        Base.metadata.drop_all(engine)
    else:
        # Drop with FK checks off: self-referencing rows (e.g. earnings clawbacks)
        # would otherwise block SQLite's implicit DELETE during DROP TABLE.
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")
            for table in reversed(Base.metadata.sorted_tables):
                cur.execute(f'DROP TABLE IF EXISTS "{table.name}"')
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
        finally:
            raw.close()
    Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def fresh_db():
    _reset_schema()
    with SessionLocal() as db:
        seed_reference_data(db)
    limiter.reset()
    email.outbox().clear()
    get_provider.cache_clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register(client: TestClient, email_addr: str, verify: bool = True, password: str = "correct-horse-battery") -> TestClient:
    """Register a user, optionally verify the email. Session cookie stays on the client."""
    r = client.post("/api/v1/auth/register", json={
        "email": email_addr, "password": password, "display_name": email_addr.split("@")[0].title(),
        "accept_terms": True,
    })
    assert r.status_code == 201, r.text
    if verify:
        msg = next(m for m in reversed(email.outbox()) if m["to"] == email_addr.lower())
        token = re.search(r"token=([\w-]+)", msg["body"]).group(1)
        r = client.post("/api/v1/auth/verify-email", json={"token": token}, headers=CSRF)
        assert r.status_code == 200, r.text
    return client


CSRF = {"X-Requested-With": "fetch"}


def new_client() -> TestClient:
    return TestClient(app, headers=CSRF)


def make_role(email_addr: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email_addr))
        r = db.scalar(select(Role).where(Role.code == role))
        db.add(UserRole(user_id=user.id, role_id=r.id))
        user.token_version += 1
        db.commit()


def login(client: TestClient, email_addr: str, password: str = "correct-horse-battery") -> None:
    r = client.post("/api/v1/auth/login", json={"email": email_addr, "password": password})
    assert r.status_code == 200, r.text


def jpeg_bytes(size=(1200, 800), color=(200, 120, 40)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    for x in range(0, size[0], 40):
        img.paste((x % 255, 80, 160), (x, 0, x + 20, size[1]))
    img.save(buf, "JPEG")
    return buf.getvalue()


def become_creator(client: TestClient, handle: str, agreements=("model_a_nonexclusive", "model_c_free")) -> None:
    r = client.post("/api/v1/creators", json={"handle": handle, "display_name": handle.title(),
                                              "categories": ["photographer"], "city": "Jacksonville",
                                              "country_code": "us"})
    assert r.status_code == 201, r.text
    templates = {t["code"]: t for t in client.get("/api/v1/agreements/templates").json()}
    for code in agreements:
        t = templates[code]
        r = client.post("/api/v1/agreements/accept", json={
            "template_code": code, "template_version": t["version"], "body_sha256": t["body_sha256"],
            "signer_legal_name": "Test Creator", "rights_owner_name": "Test Creator", "i_agree": True,
        })
        assert r.status_code == 201, r.text


def upload_photo(client: TestClient, title="Sunset over downtown Jacksonville", size=(1200, 800), **extra) -> dict:
    data = {
        "title": title, "category": "aerial_drone", "keywords": "sunset, skyline, aerial",
        "rights_owner_name": "Test Creator", "is_original_author": "true", "accept_declaration": "true",
        "location_city": "Jacksonville", "location_country": "US",
    } | extra
    files = {"file": ("photo.jpg", jpeg_bytes(size), "image/jpeg")}
    r = client.post("/api/v1/media", data=data, files=files)
    assert r.status_code == 202, r.text
    return r.json()
