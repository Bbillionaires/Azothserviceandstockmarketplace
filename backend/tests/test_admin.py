from tests.conftest import become_creator, make_role, new_client, register


def finance_client():
    c = register(new_client(), "cfo@example.com")
    make_role("cfo@example.com", "finance_admin")
    c.post("/api/v1/auth/login", json={"email": "cfo@example.com", "password": "correct-horse-battery"})
    return c


def test_revenue_rules_are_versioned_not_edited():
    c = finance_client()
    rules = c.get("/api/v1/admin/revenue-rules").json()
    a1 = next(r for r in rules if r["code"] == "model_a_nonexclusive")
    assert (a1["version"], a1["creator_bps"]) == (1, 5000)
    r = c.post("/api/v1/admin/revenue-rules", json={
        "code": "model_a_nonexclusive", "revenue_model": "nonexclusive", "creator_bps": 5500,
        "affiliate_bps_of_platform": 1000, "net_revenue_deductions": ["taxes_collected"], "notes": "Promo",
    })
    assert r.status_code == 201 and r.json()["version"] == 2
    versions = [x for x in c.get("/api/v1/admin/revenue-rules").json() if x["code"] == "model_a_nonexclusive"]
    assert {(v["version"], v["creator_bps"]) for v in versions} == {(1, 5000), (2, 5500)}


def test_invalid_rule_rejected():
    c = finance_client()
    r = c.post("/api/v1/admin/revenue-rules", json={
        "code": "x_rule", "revenue_model": "nonexclusive", "creator_bps": 5000, "net_revenue_deductions": ["bogus"],
    })
    assert r.status_code == 400


def test_royalty_preview_uses_stored_rule():
    c = finance_client()
    rule = next(r for r in c.get("/api/v1/admin/revenue-rules").json() if r["code"] == "model_b_exclusive")
    r = c.post("/api/v1/admin/royalty-preview", json={"rule_id": rule["id"], "gross_cents": 10000,
                                                      "is_initial_exclusive_transaction": True})
    assert r.json()["creator_pool_cents"] == 6500


def test_non_finance_users_cannot_manage_rules():
    c = register(new_client(), "user@example.com")
    assert c.get("/api/v1/admin/revenue-rules").status_code == 403
    mod = register(new_client(), "mod@example.com")
    make_role("mod@example.com", "moderator")
    mod.post("/api/v1/auth/login", json={"email": "mod@example.com", "password": "correct-horse-battery"})
    assert mod.get("/api/v1/admin/revenue-rules").status_code == 403
    assert mod.get("/api/v1/admin/stats").status_code == 200


def test_exclusive_agreement_cannot_be_click_accepted():
    c = register(new_client(), "creator@example.com")
    become_creator(c, "excl-test", agreements=())
    t = next(t for t in c.get("/api/v1/agreements/templates").json() if t["code"] == "model_b_exclusive")
    assert t["available_to_sign"] is False
    r = c.post("/api/v1/agreements/accept", json={
        "template_code": t["code"], "template_version": t["version"], "body_sha256": t["body_sha256"],
        "signer_legal_name": "X Y", "rights_owner_name": "X Y", "i_agree": True,
    })
    assert r.status_code == 400


def test_agreement_hash_must_match_displayed_text():
    c = register(new_client(), "creator2@example.com")
    become_creator(c, "hash-test", agreements=())
    t = next(t for t in c.get("/api/v1/agreements/templates").json() if t["code"] == "model_a_nonexclusive")
    r = c.post("/api/v1/agreements/accept", json={
        "template_code": t["code"], "template_version": t["version"], "body_sha256": "0" * 64,
        "signer_legal_name": "X Y", "rights_owner_name": "X Y", "i_agree": True,
    })
    assert r.status_code == 409


def test_admin_role_management_revokes_sessions():
    admin = register(new_client(), "admin@example.com")
    make_role("admin@example.com", "admin")
    admin.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "correct-horse-battery"})
    target = register(new_client(), "target@example.com")
    uid = target.get("/api/v1/auth/me").json()["id"]
    r = admin.post(f"/api/v1/admin/users/{uid}/roles", json={"role": "moderator", "grant": True})
    assert "moderator" in r.json()["roles"]
    assert target.get("/api/v1/auth/me").status_code == 401
    r = admin.post(f"/api/v1/admin/users/{uid}/status", json={"status": "suspended", "reason": "spam"})
    assert r.json()["status"] == "suspended"
    assert new_client().post("/api/v1/auth/login", json={"email": "target@example.com",
                                                         "password": "correct-horse-battery"}).status_code == 403
