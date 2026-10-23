"""Job queue (RQ/Redis), shared rate limits, direct uploads, email provider, CAPTCHA."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.core import jobs
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.rate_limit import limiter
from app.models import UploadSession
from app.services import email
from tests.conftest import become_creator, jpeg_bytes, new_client, register

MEDIA_META = {"title": "Direct upload skyline", "category": "aerial_drone", "keywords": ["skyline"],
              "rights_owner_name": "Test Creator", "is_original_author": True, "accept_declaration": True}


@pytest.fixture
def redis_queue():
    settings = get_settings()
    settings.redis_url = "fakeredis://"
    jobs.redis_connection.cache_clear()
    yield jobs.redis_connection()
    jobs.redis_connection().flushall()
    settings.redis_url = None
    jobs.redis_connection.cache_clear()


def creator():
    c = register(new_client(), "creator@example.com")
    become_creator(c, "direct-cam")
    return c


def direct_upload(client, data: bytes, purpose="media", target=None, name="photo.jpg", ctype="image/jpeg"):
    r = client.post("/api/v1/uploads", json={"purpose": purpose, "target_id": target, "filename": name,
                                             "size_bytes": len(data), "content_type": ctype})
    assert r.status_code == 201, r.text
    session = r.json()
    assert session["upload_url"].endswith("/blob")  # local storage target
    assert client.put(session["upload_url"], content=data, headers=session["headers"]).status_code == 204
    return session["id"]


def test_media_processing_runs_on_rq_worker(redis_queue):
    from rq import SimpleWorker

    c = creator()
    r = c.post("/api/v1/media", data={"title": "Queued photo", "category": "food", "rights_owner_name": "Me",
                                      "is_original_author": "true", "accept_declaration": "true"},
               files={"file": ("p.jpg", jpeg_bytes(), "image/jpeg")})
    asset_id = r.json()["id"]
    assert c.get(f"/api/v1/media/{asset_id}").json()["status"] == "processing"  # waiting for a worker
    assert jobs.queue().count == 1
    SimpleWorker([jobs.queue()], connection=redis_queue).work(burst=True)
    assert c.get(f"/api/v1/media/{asset_id}").json()["status"] == "pending_review"


def test_rate_limits_shared_through_redis(redis_queue):
    for _ in range(3):
        limiter.check("shared-test", 3)
    with pytest.raises(Exception) as exc:
        limiter.check("shared-test", 3)
    assert getattr(exc.value, "status_code", None) == 429
    assert any(k.startswith(b"rl:shared-test") for k in redis_queue.scan_iter("rl:*"))


def test_direct_upload_media_flow_and_session_rules():
    c = creator()
    upload_id = direct_upload(c, jpeg_bytes((2400, 1600)))
    r = c.post("/api/v1/media/from-upload", json=MEDIA_META | {"upload_id": upload_id})
    assert r.status_code == 202, r.text
    detail = c.get(f"/api/v1/media/{r.json()['id']}").json()
    assert detail["status"] == "pending_review" and detail["width"] == 2400
    # A session can be used once.
    assert c.post("/api/v1/media/from-upload", json=MEDIA_META | {"upload_id": upload_id}).status_code == 409
    # Other users can't use someone else's upload.
    other = register(new_client(), "other@example.com")
    become_creator(other, "other-cam")
    upload_id = direct_upload(c, jpeg_bytes())
    assert other.post("/api/v1/media/from-upload", json=MEDIA_META | {"upload_id": upload_id}).status_code == 404
    # Non-media bytes are rejected after upload.
    bad = direct_upload(c, b"MZ\x90\x00not an image", name="x.jpg")
    assert c.post("/api/v1/media/from-upload", json=MEDIA_META | {"upload_id": bad}).status_code == 400
    # Expired sessions are refused.
    expiring = direct_upload(c, jpeg_bytes())
    with SessionLocal() as db:
        db.execute(update(UploadSession).where(UploadSession.id == uuid.UUID(expiring))
                   .values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()
    assert c.post("/api/v1/media/from-upload", json=MEDIA_META | {"upload_id": expiring}).status_code == 410
    # Not uploaded yet.
    r = c.post("/api/v1/uploads", json={"purpose": "media", "filename": "a.jpg", "size_bytes": 10,
                                        "content_type": "image/jpeg"})
    assert c.post("/api/v1/media/from-upload", json=MEDIA_META | {"upload_id": r.json()["id"]}).status_code == 400


def test_upload_size_limits():
    c = creator()
    too_big = get_settings().max_image_upload_mb * 1024 * 1024 + 1
    r = c.post("/api/v1/uploads", json={"purpose": "media", "filename": "a.jpg", "size_bytes": too_big,
                                        "content_type": "image/jpeg"})
    assert r.status_code == 400
    r = c.post("/api/v1/uploads", json={"purpose": "media", "filename": "a.jpg", "size_bytes": 10,
                                        "content_type": "image/jpeg"}).json()
    settings = get_settings()
    original = settings.max_image_upload_mb
    with SessionLocal() as db:
        db.execute(update(UploadSession).where(UploadSession.id == uuid.UUID(r["id"])).values(max_size=100))
        db.commit()
    try:
        assert c.put(r["upload_url"], content=b"x" * 500).status_code == 413
    finally:
        settings.max_image_upload_mb = original


def test_gallery_and_deliverable_direct_uploads():
    from tests.test_production import booked_project, fund

    client, drone, project_id = booked_project()
    m1 = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["id"]
    # Unfunded milestone: no upload session.
    r = drone.post("/api/v1/uploads", json={"purpose": "deliverable", "target_id": m1, "filename": "cut.mov",
                                            "size_bytes": 100, "content_type": "video/quicktime"})
    assert r.status_code == 409
    fund(client, m1)
    upload_id = direct_upload(drone, b"\x00\x00\x00\x14ftypqt  " + b"y" * 2000, purpose="deliverable", target=m1,
                              name="final cut.mov", ctype="video/quicktime")
    r = drone.post(f"/api/v1/milestones/{m1}/deliverables/from-upload", json={"upload_id": upload_id, "note": "v1"})
    assert r.status_code == 201, r.text
    d = client.get(f"/api/v1/projects/{project_id}").json()["milestones"][0]["deliverables"][0]
    assert d["filename"] == "final cut.mov" and d["scan_status"] == "not_scanned"  # scanner disabled in tests
    link = client.post(f"/api/v1/deliverables/{d['id']}/link").json()["url"]
    assert new_client().get(link).content.startswith(b"\x00\x00\x00\x14ftyp")
    # Session for a different milestone can't be used here.
    assert client.post("/api/v1/uploads", json={"purpose": "deliverable", "target_id": m1, "filename": "x",
                                                "size_bytes": 1}).status_code == 404

    g = drone.post("/api/v1/galleries", json={"title": "Direct gallery"}).json()
    upload_id = direct_upload(drone, jpeg_bytes(), purpose="gallery_item", target=g["id"])
    r = drone.post(f"/api/v1/galleries/{g['id']}/items/from-upload", json={"upload_id": upload_id})
    assert r.status_code == 202
    assert drone.get(f"/api/v1/galleries/{g['id']}").json()["items"][0]["status"] == "ready"


def test_resend_email_backend(monkeypatch):
    import httpx

    sent = {}

    class Resp:
        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, json=json)
        return Resp()

    monkeypatch.setattr(httpx, "post", fake_post)
    settings = get_settings()
    settings.email_backend, settings.resend_api_key = "resend", "re_test"
    try:
        email.send("someone@example.com", "Hello", "Body text")
    finally:
        settings.email_backend, settings.resend_api_key = "console", None
    assert sent["url"] == "https://api.resend.com/emails"
    assert sent["headers"]["Authorization"] == "Bearer re_test"
    assert sent["json"]["to"] == ["someone@example.com"] and sent["json"]["text"] == "Body text"


def test_turnstile_captcha_on_registration(monkeypatch):
    import httpx

    class Resp:
        def __init__(self, ok):
            self.ok = ok

        def json(self):
            return {"success": self.ok}

    monkeypatch.setattr(httpx, "post", lambda url, data=None, timeout=None: Resp(data["response"] == "good-token"))
    settings = get_settings()
    settings.turnstile_secret_key = "secret"
    body = {"email": "bot@example.com", "password": "correct-horse-battery", "display_name": "Bot", "accept_terms": True}
    try:
        assert new_client().post("/api/v1/auth/register", json=body).status_code == 400
        assert new_client().post("/api/v1/auth/register", json=body | {"captcha_token": "bad"}).status_code == 400
        assert new_client().post("/api/v1/auth/register", json=body | {"captcha_token": "good-token"}).status_code == 201
        r = new_client().post("/api/v1/auth/password-reset/request", json={"email": "bot@example.com"})
        assert r.status_code == 400
    finally:
        settings.turnstile_secret_key = None
