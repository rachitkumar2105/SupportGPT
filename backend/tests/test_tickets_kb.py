from datetime import datetime

from tests.conftest import authed, make_client


def _ticket(customer):
    r = customer.post("/api/tickets", json={"subject": "Cannot export notes", "body": "Export button spins forever"})
    assert r.status_code == 201, r.text
    return r.json()


def test_agent_workflow_and_visibility(customer, agent):
    t = _ticket(customer)
    tid = t["id"]
    # internal note invisible to customer
    agent.post(f"/api/tickets/{tid}/messages", json={"body": "checking logs", "internal": True})
    r = agent.post(f"/api/tickets/{tid}/messages", json={"body": "Can you try the JSON export?", "ai_assisted": True})
    body = r.json()
    assert body["status"] == "pending" and body["first_response_at"] and body["assignee"]["name"] == "Demo Agent"
    cust_view = customer.get(f"/api/tickets/{tid}").json()
    assert all(m["kind"] != "note" for m in cust_view["messages"])
    assert any(m["kind"] == "note" for m in agent.get(f"/api/tickets/{tid}").json()["messages"])
    # customer reply reopens
    assert customer.post(f"/api/tickets/{tid}/messages", json={"body": "still broken"}).json()["status"] == "open"
    # customers can't add internal notes or patch
    assert customer.post(f"/api/tickets/{tid}/messages", json={"body": "x", "internal": True}).status_code == 403
    assert customer.patch(f"/api/tickets/{tid}", json={"status": "resolved"}).status_code == 403


def test_priority_change_recomputes_sla(customer, agent):
    t = _ticket(customer)
    r = agent.patch(f"/api/tickets/{t['id']}", json={"priority": "urgent"}).json()
    created = datetime.fromisoformat(r["created_at"])
    due = datetime.fromisoformat(r["sla_due_at"])
    assert abs((due - created).total_seconds() - 3600) < 5


def test_csat_only_after_resolution_and_once(customer, agent):
    t = _ticket(customer)
    assert customer.post(f"/api/tickets/{t['id']}/csat", json={"score": 5}).status_code == 409
    agent.patch(f"/api/tickets/{t['id']}", json={"status": "resolved"})
    assert customer.post(f"/api/tickets/{t['id']}/csat", json={"score": 6}).status_code == 422
    assert customer.post(f"/api/tickets/{t['id']}/csat", json={"score": 4, "comment": "quick"}).json()["csat"] == 4
    assert customer.post(f"/api/tickets/{t['id']}/csat", json={"score": 5}).status_code == 409


def test_customer_cannot_see_others_tickets(customer):
    t = _ticket(customer)
    other = make_client()
    authed(
        other,
        other.post(
            "/api/auth/signup", json={"name": "O", "email": "other@example.com", "password": "long-enough-pw-9"}
        ),
    )
    assert other.get(f"/api/tickets/{t['id']}").status_code == 404
    assert all(x["id"] != t["id"] for x in other.get("/api/tickets?status=all").json())


def test_assign_only_to_staff(customer, agent):
    t = _ticket(customer)
    me = customer.get("/api/auth/me").json()
    assert agent.patch(f"/api/tickets/{t['id']}", json={"assignee_id": me["id"]}).status_code == 422


def test_ai_draft(customer, agent, fake_llm):
    fake_llm.complete_text = "Hi Asha, try exporting as JSON [1]."
    t = _ticket(customer)
    r = agent.post(f"/api/tickets/{t['id']}/draft")
    assert r.status_code == 200 and r.json()["text"].startswith("Hi Asha") and r.json()["sources"]
    assert customer.post(f"/api/tickets/{t['id']}/draft").status_code == 403


def test_queue_filters(customer, agent):
    _ticket(customer)
    assert agent.get("/api/tickets?priority=urgent").status_code == 200
    assert agent.get("/api/tickets?status=bogus").status_code == 422


def test_kb_upload_validation_and_delete(admin):
    md = b"# Holiday hours\n\nSupport is closed on 25 December and replies resume on 26 December at 9am CET."
    r = admin.post("/api/kb/documents", files={"file": ("../../etc/holiday_hours.md", md, "text/markdown")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["title"] == "holiday hours" and doc["chunk_count"] == 1
    assert admin.post("/api/kb/documents", files={"file": ("again.md", md)}).status_code == 409
    assert (
        admin.post("/api/kb/documents", files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + bytes(range(256)))}).status_code
        == 415
    )
    assert admin.post("/api/kb/documents", files={"file": ("big.md", b"a" * (10 * 1024 * 1024 + 1))}).status_code == 413
    assert admin.post("/api/kb/documents", files={"file": ("fake.pdf", b"%PDF-1.4 garbage")}).status_code == 422
    v_before = admin.get("/api/admin/analytics").json()["kb"]["kb_version"]
    assert admin.delete(f"/api/kb/documents/{doc['id']}").status_code == 204
    assert admin.get("/api/admin/analytics").json()["kb"]["kb_version"] == v_before + 1
    actions = [a["action"] for a in admin.get("/api/admin/audit").json()]
    assert "kb.upload" in actions and "kb.delete" in actions


def test_retrieval_inspector(agent):
    r = agent.post("/api/kb/search", json={"query": "E-402 error", "k": 3}).json()
    assert set(r["results"]) == {"hybrid", "dense", "bm25"}
    assert r["results"]["bm25"][0]["doc_slug"] == "sync-troubleshooting"


def test_eval_endpoint(agent):
    r = agent.post("/api/admin/eval")
    assert r.status_code == 200
    m = r.json()["metrics"]
    assert m["n_answerable"] == 54 and m["n_out_of_scope"] == 14
    assert set(m["retrieval"]) == {"hybrid", "dense", "bm25"}
    assert agent.get("/api/admin/eval").json()[0]["id"] == r.json()["id"]


def test_analytics_excludes_sample_data(admin):
    a = admin.get("/api/admin/analytics").json()
    assert "deflection_rate" in a and len(a["series"]) == 14


def test_public_quality_after_eval(agent):
    from tests.conftest import make_client

    agent.post("/api/admin/eval")
    q = make_client().get("/api/public/quality").json()["latest"]
    assert q["n_answerable"] == 54 and "hybrid" in q["retrieval"] and "hybrid_misses" not in q
