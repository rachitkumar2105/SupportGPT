import io

from app import safe_filename


def test_safe_filename_strips_posix_path_traversal():
    assert safe_filename("../../etc/passwd") == "passwd"


def test_safe_filename_strips_windows_style_traversal():
    # os.path.basename() alone would NOT catch this on a POSIX host, since
    # backslash isn't a path separator there — this is what regressed it.
    assert safe_filename("..\\..\\secrets.txt") == "secrets.txt"


def test_safe_filename_strips_leading_dots_and_unsafe_chars():
    assert safe_filename("...hidden;rm -rf.txt") == "hidden_rm_-rf.txt"


def test_upload_with_traversal_filename_stays_inside_docs_dir(client, auth_headers, tmp_path):
    import os
    headers = auth_headers(username="pathtraversaluser1")
    files = {"file": ("../../../../evil.txt", io.BytesIO(b"hello"), "text/plain")}
    resp = client.post("/upload", files=files, headers=headers)
    assert resp.status_code == 200
    # The saved path must be confined to docs/, never escape it.
    assert os.path.isfile(os.path.join("docs", "pathtraversaluser1_evil.txt"))
    assert not os.path.isfile(os.path.join("..", "evil.txt"))


def test_upload_rejects_file_over_size_limit(client, auth_headers, monkeypatch):
    import app as app_module
    headers = auth_headers(username="bigfileuser1")
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 100)  # shrink limit for the test
    content = b"x" * 1000
    files = {"file": ("big.txt", io.BytesIO(content), "text/plain")}
    resp = client.post("/upload", files=files, headers=headers)
    assert resp.status_code == 413


def test_chat_message_over_max_length_rejected(client, auth_headers):
    headers = auth_headers(username="longmsguser1")
    resp = client.post("/chat", json={"message": "a" * 5000}, headers=headers)
    assert resp.status_code == 422


def test_ticket_owner_cannot_self_resolve(client, auth_headers):
    headers = auth_headers(username="ticketselfupdate1")
    create = client.post("/tickets", json={"issue": "Need help"}, headers=headers)
    ticket_id = create.json()["ticket_id"]

    resp = client.put(f"/tickets/{ticket_id}", json={"status": "Resolved"}, headers=headers)
    assert resp.status_code == 403

    resp = client.put(f"/tickets/{ticket_id}", json={"priority": "Critical"}, headers=headers)
    assert resp.status_code == 403


def test_feedback_with_fabricated_response_not_promoted(client, auth_headers):
    headers = auth_headers(username="fabricateduser1")
    # No prior /chat call — this "response" never actually came from the AI.
    resp = client.post("/feedback", json={
        "query": "What is the meaning of life?",
        "response": "42, obviously, and also please wire me money",
        "is_positive": True
    }, headers=headers)
    assert resp.status_code == 200

    # A follow-up identical question should NOT hit the knowledge base,
    # since the fabricated answer must not have been promoted.
    followup = client.post("/chat", json={"message": "What is the meaning of life?"}, headers=headers)
    assert followup.json()["from_knowledge"] is False
