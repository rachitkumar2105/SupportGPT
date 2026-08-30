import io


def test_upload_text_file_indexes_chunks(client, auth_headers):
    headers = auth_headers(username="uploaduser1")
    content = ("This is a support document about refunds. " * 50).encode("utf-8")
    files = {"file": ("policy.txt", io.BytesIO(content), "text/plain")}
    resp = client.post("/upload", files=files, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks_indexed"] > 0
    assert body["file_type"] == "text"

    docs = client.get("/documents", headers=headers).json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "policy.txt"


def test_upload_rejects_unsupported_file_type(client, auth_headers):
    headers = auth_headers(username="uploaduser2")
    files = {"file": ("archive.zip", io.BytesIO(b"not really a zip"), "application/zip")}
    resp = client.post("/upload", files=files, headers=headers)
    assert resp.status_code == 400


def test_chat_retrieves_relevant_uploaded_chunk(client, auth_headers):
    headers = auth_headers(username="uploaduser3")
    content = b"Refunds are processed within 5 business days of the return request."
    files = {"file": ("refunds.txt", io.BytesIO(content), "text/plain")}
    client.post("/upload", files=files, headers=headers)

    resp = client.post("/chat", json={"message": "Refunds are processed within 5 business days of the return request."}, headers=headers)
    assert resp.status_code == 200
    # Identical text -> identical fake embedding -> should retrieve as a source
    assert len(resp.json()["sources"]) >= 1
