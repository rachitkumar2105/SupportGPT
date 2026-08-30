def test_chat_requires_auth(client):
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_chat_empty_message_rejected(client, auth_headers):
    headers = auth_headers(username="chatuser1")
    resp = client.post("/chat", json={"message": "   "})
    resp = client.post("/chat", json={"message": "   "}, headers=headers)
    assert resp.status_code == 400


def test_chat_happy_path_returns_mocked_response(client, auth_headers):
    headers = auth_headers(username="chatuser2")
    resp = client.post("/chat", json={"message": "What is your return policy?"}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "This is a mocked AI response."
    assert "sources" in body
    assert body["sources"] == []  # no documents uploaded yet


def test_chat_with_no_documents_has_no_relevant_context(client, auth_headers):
    headers = auth_headers(username="chatuser3")
    resp = client.post("/chat", json={"message": "anything"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["from_knowledge"] is False


def test_ticket_auto_created_on_issue_keyword(client, auth_headers):
    headers = auth_headers(username="chatuser4")
    client.post("/chat", json={"message": "I have an issue with my last order"}, headers=headers)
    tickets = client.get("/tickets", headers=headers).json()
    assert len(tickets) >= 1


def test_feedback_promotes_positive_answer_to_knowledge_base(client, auth_headers):
    headers = auth_headers(username="chatuser5")
    chat_resp = client.post("/chat", json={"message": "How do I reset my password?"}, headers=headers)
    answer = chat_resp.json()["response"]

    fb_resp = client.post("/feedback", json={
        "query": "How do I reset my password?",
        "response": answer,
        "is_positive": True
    }, headers=headers)
    assert fb_resp.status_code == 200

    # A semantically identical follow-up should now hit the curated knowledge base
    followup = client.post("/chat", json={"message": "How do I reset my password?"}, headers=headers)
    assert followup.status_code == 200
    assert followup.json()["from_knowledge"] is True
