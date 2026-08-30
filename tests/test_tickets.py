def test_create_ticket_and_list(client, auth_headers):
    headers = auth_headers(username="ticketuser1")
    resp = client.post("/tickets", json={"issue": "Payment failed", "priority": "High"}, headers=headers)
    assert resp.status_code == 200
    ticket_id = resp.json()["ticket_id"]

    tickets = client.get("/tickets", headers=headers).json()
    assert any(t["id"] == ticket_id for t in tickets)


def test_create_ticket_invalid_priority_rejected(client, auth_headers):
    headers = auth_headers(username="ticketuser2")
    resp = client.post("/tickets", json={"issue": "Something broke", "priority": "Super Urgent"}, headers=headers)
    assert resp.status_code == 422


def test_update_ticket_invalid_status_rejected(client, auth_headers):
    headers = auth_headers(username="ticketuser3")
    create = client.post("/tickets", json={"issue": "Login broken", "priority": "Medium"}, headers=headers)
    ticket_id = create.json()["ticket_id"]

    resp = client.put(f"/tickets/{ticket_id}", json={"status": "NotARealStatus"}, headers=headers)
    assert resp.status_code == 422


def test_customer_cannot_update_others_ticket(client, auth_headers):
    owner_headers = auth_headers(username="ticketowner1")
    create = client.post("/tickets", json={"issue": "Billing question"}, headers=owner_headers)
    ticket_id = create.json()["ticket_id"]

    other_headers = auth_headers(username="ticketstranger1")
    resp = client.put(f"/tickets/{ticket_id}", json={"status": "Resolved"}, headers=other_headers)
    assert resp.status_code == 403
