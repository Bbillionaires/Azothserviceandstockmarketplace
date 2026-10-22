"""End-to-end Phase 1 flow: storefront -> agreement -> upload -> moderation ->
search -> free license -> protected download; plus complaints and appeals."""

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import AuditLog, MediaFile
from tests.conftest import become_creator, make_role, new_client, register, upload_photo


def setup_creator_and_admin():
    creator = register(new_client(), "creator@example.com")
    become_creator(creator, "sunset-studio")
    mod = register(new_client(), "mod@example.com")
    make_role("mod@example.com", "moderator")
    mod.post("/api/v1/auth/login", json={"email": "mod@example.com", "password": "correct-horse-battery"})
    return creator, mod


def approve(mod, asset_id):
    r = mod.post(f"/api/v1/admin/media/{asset_id}/decision", json={"action": "approve"})
    assert r.status_code == 200, r.text


def test_upload_requires_agreement_and_declaration():
    c = register(new_client(), "nocontract@example.com")
    become_creator(c, "no-contract", agreements=())
    r = c.post("/api/v1/media", data={"title": "x title", "category": "food", "rights_owner_name": "Me",
                                      "is_original_author": "true", "accept_declaration": "true"},
               files={"file": ("a.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")})
    assert r.status_code == 403


def test_rejects_non_media_files():
    creator, _ = setup_creator_and_admin()
    r = creator.post("/api/v1/media", data={"title": "Not an image", "category": "food", "rights_owner_name": "Me",
                                            "is_original_author": "true", "accept_declaration": "true"},
                     files={"file": ("evil.jpg", b"MZ\x90\x00 this is an exe", "image/jpeg")})
    assert r.status_code == 400


def test_corrupt_image_marked_failed():
    creator, _ = setup_creator_and_admin()
    r = creator.post("/api/v1/media", data={"title": "Broken jpeg", "category": "food", "rights_owner_name": "Me",
                                            "is_original_author": "true", "accept_declaration": "true"},
                     files={"file": ("b.jpg", b"\xff\xd8\xff" + b"\x00" * 500, "image/jpeg")})
    assert r.status_code == 202
    detail = creator.get(f"/api/v1/media/{r.json()['id']}").json()
    assert detail["status"] == "failed" and detail["processing_error"]


def test_full_free_media_flow():
    creator, mod = setup_creator_and_admin()
    asset = upload_photo(creator, size=(4000, 2250))
    asset_id = asset["id"]

    detail = creator.get(f"/api/v1/media/{asset_id}").json()
    assert detail["status"] == "pending_review"
    assert detail["resolution_label"] == "4K" and detail["orientation"] == "horizontal"
    assert {f["kind"] for f in detail["files"]} == {"preview", "thumbnail"}  # original never exposed

    # Not public until approved.
    assert new_client().get(f"/api/v1/media/{asset_id}").status_code == 404
    queue = mod.get("/api/v1/admin/moderation/queue").json()
    assert queue["total"] == 1 and queue["items"][0]["declaration"]["rights_owner_name"] == "Test Creator"

    # Creator sets pricing: free commercial + paid standard license.
    r = creator.put(f"/api/v1/media/{asset_id}/pricing", json={
        "free_license_code": "free_commercial",
        "prices": [{"license_code": "standard_commercial", "price_cents": 4900}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["free_license_codes"] == ["free_commercial"]
    approve(mod, asset_id)

    # Public detail, search (natural language) and facets.
    public = new_client()
    assert public.get(f"/api/v1/media/{asset_id}").json()["prices"][0]["price_cents"] == 4900
    res = public.get("/api/v1/search/media", params={"q": "4K aerial photo of downtown jacksonville at sunset"}).json()
    assert res["total"] == 1 and res["interpreted"]["resolution"] == "4K"
    assert res["items"][0]["starting_price_cents"] == 4900
    assert public.get("/api/v1/search/media", params={"q": "underwater"}).json()["total"] == 0
    assert public.get("/api/v1/search/media", params={"type": "video"}).json()["total"] == 0
    assert public.get("/api/v1/search/media", params={"free": "true"}).json()["total"] == 1

    # Buyer obtains a free license and downloads the original through a signed link.
    buyer = register(new_client(), "buyer@example.com")
    assert buyer.post(f"/api/v1/media/{asset_id}/free-license", json={"license_code": "standard_commercial"}).status_code == 400
    r = buyer.post(f"/api/v1/media/{asset_id}/free-license", json={"license_code": "free_commercial"})
    assert r.status_code == 200, r.text
    cert, url = r.json()["certificate_number"], r.json()["download_url"]
    assert cert.startswith("LC-")
    again = buyer.post(f"/api/v1/media/{asset_id}/free-license", json={"license_code": "free_commercial"}).json()
    assert again["certificate_number"] == cert  # no duplicate certificates

    dl = new_client().get(url)
    assert dl.status_code == 200 and dl.content[:3] == b"\xff\xd8\xff"
    with SessionLocal() as db:
        original = db.scalar(select(MediaFile).where(MediaFile.kind == "original"))
        assert original.is_public is False
        assert db.scalar(select(AuditLog).where(AuditLog.action == "download.original"))
    assert len(dl.content) > 0

    # Tampered or forged tokens are refused; the original is not on the public mount.
    assert new_client().get(url[:-4] + "0000").status_code == 403
    assert new_client().get(f"/media-public/{original.storage_key}").status_code == 404

    # Certificates are publicly verifiable and listed for the licensee.
    v = new_client().get(f"/api/v1/licenses/verify/{cert}").json()
    assert v["license_code"] == "free_commercial" and v["territory"] == ["WORLDWIDE"]
    assert buyer.get("/api/v1/licenses/mine").json()[0]["certificate_number"] == cert

    # Favorites and collections.
    assert buyer.put(f"/api/v1/favorites/{asset_id}").status_code == 200
    assert len(buyer.get("/api/v1/favorites").json()) == 1
    coll = buyer.post("/api/v1/collections", json={"name": "Campaign"}).json()
    buyer.put(f"/api/v1/collections/{coll['id']}/items/{asset_id}")
    assert buyer.get("/api/v1/collections").json()[0]["item_count"] == 1

    # Withdrawal stops new licensing but keeps existing licenses valid.
    creator.post(f"/api/v1/media/{asset_id}/withdraw")
    assert new_client().get(f"/api/v1/media/{asset_id}").status_code == 404
    assert new_client().get(f"/api/v1/licenses/verify/{cert}").json()["status"] == "active"


def test_editorial_only_cannot_be_priced_commercially():
    creator, _ = setup_creator_and_admin()
    asset = upload_photo(creator, is_editorial_only="true")
    r = creator.put(f"/api/v1/media/{asset['id']}/pricing",
                    json={"prices": [{"license_code": "standard_commercial", "price_cents": 1000}]})
    assert r.status_code == 400
    r = creator.put(f"/api/v1/media/{asset['id']}/pricing",
                    json={"prices": [{"license_code": "editorial", "price_cents": 1000}]})
    assert r.status_code == 200


def test_only_owner_can_edit_and_price():
    creator, _ = setup_creator_and_admin()
    asset = upload_photo(creator)
    other = register(new_client(), "other@example.com")
    assert other.patch(f"/api/v1/media/{asset['id']}", json={"title": "Hijacked"}).status_code == 404
    assert other.put(f"/api/v1/media/{asset['id']}/pricing", json={"prices": []}).status_code == 404


def test_moderation_permissions_and_reasons():
    creator, mod = setup_creator_and_admin()
    asset = upload_photo(creator)
    assert creator.post(f"/api/v1/admin/media/{asset['id']}/decision", json={"action": "approve"}).status_code == 403
    assert mod.post(f"/api/v1/admin/media/{asset['id']}/decision", json={"action": "reject"}).status_code == 400
    r = mod.post(f"/api/v1/admin/media/{asset['id']}/decision",
                 json={"action": "request_changes", "reason": "Add location keywords"})
    assert r.status_code == 200
    detail = creator.get(f"/api/v1/media/{asset['id']}").json()
    assert detail["status"] == "changes_requested" and detail["rejection_reason"] == "Add location keywords"
    creator.patch(f"/api/v1/media/{asset['id']}", json={"keywords": ["jacksonville", "skyline"]})
    assert creator.get(f"/api/v1/media/{asset['id']}").json()["status"] == "pending_review"


def test_duplicate_upload_is_flagged_for_moderators():
    creator, mod = setup_creator_and_admin()
    upload_photo(creator, title="First copy")
    upload_photo(creator, title="Second copy")
    items = mod.get("/api/v1/admin/moderation/queue").json()["items"]
    assert any("exact_duplicates" in i["automated_signals"] for i in items)


def test_copyright_complaint_flow_requires_review_before_disable():
    creator, mod = setup_creator_and_admin()
    asset = upload_photo(creator)
    approve(mod, asset["id"])
    r = new_client().post("/api/v1/copyright-complaints", json={
        "asset_id": asset["id"], "complainant_name": "Rights Holder", "complainant_email": "rh@example.com",
        "complainant_address": "1 Main St, City", "copyrighted_work_description": "My original sunset photograph",
        "good_faith_statement": True, "accuracy_statement": True, "electronic_signature": "Rights Holder",
    })
    assert r.status_code == 201
    # Still live: not removed on an unverified allegation.
    assert new_client().get(f"/api/v1/media/{asset['id']}").status_code == 200

    complaint = mod.get("/api/v1/admin/complaints").json()[0]
    mod.post(f"/api/v1/admin/complaints/{complaint['id']}/status", json={"status": "content_disabled", "note": "Valid notice"})
    assert new_client().get(f"/api/v1/media/{asset['id']}").status_code == 404

    r = creator.post(f"/api/v1/copyright-complaints/{complaint['id']}/counter-notice", json={
        "statement": "I created this photograph myself on location in 2026.",
        "consent_to_jurisdiction": True, "electronic_signature": "Test Creator",
    })
    assert r.status_code == 200
    mod.post(f"/api/v1/admin/complaints/{complaint['id']}/status", json={"status": "restored", "note": "Counter-notice"})
    assert new_client().get(f"/api/v1/media/{asset['id']}").status_code == 200


def test_appeal_reviewed_by_different_moderator():
    creator, mod = setup_creator_and_admin()
    asset = upload_photo(creator)
    mod.post(f"/api/v1/admin/media/{asset['id']}/decision", json={"action": "reject", "reason": "Looks like a duplicate"})
    decision = creator.get(f"/api/v1/media/{asset['id']}/decisions").json()[0]
    assert creator.post("/api/v1/appeals", json={"decision_id": decision["id"],
                                                 "statement": "This is my own original work."}).status_code == 201
    appeal = mod.get("/api/v1/admin/appeals").json()[0]
    assert mod.post(f"/api/v1/admin/appeals/{appeal['id']}/resolve", json={"overturn": True}).status_code == 403

    mod2 = register(new_client(), "mod2@example.com")
    make_role("mod2@example.com", "moderator")
    mod2.post("/api/v1/auth/login", json={"email": "mod2@example.com", "password": "correct-horse-battery"})
    assert mod2.post(f"/api/v1/admin/appeals/{appeal['id']}/resolve",
                     json={"overturn": True, "note": "Verified"}).status_code == 200
    assert new_client().get(f"/api/v1/media/{asset['id']}").status_code == 200


def test_creator_discovery_filters():
    creator, _ = setup_creator_and_admin()
    found = new_client().get("/api/v1/creators", params={"city": "jacksonville", "category": "photographer"}).json()
    assert found["total"] == 1 and found["items"][0]["handle"] == "sunset-studio"
    assert new_client().get("/api/v1/creators", params={"category": "drone_operator"}).json()["total"] == 0
    assert new_client().get("/api/v1/creators/sunset-studio").json()["country_code"] == "US"
