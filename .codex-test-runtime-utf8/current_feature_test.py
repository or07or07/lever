from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from urllib.parse import quote

import requests
import websockets


BASE = "http://127.0.0.1:8500"
MAIL_LOG = os.path.join(os.path.dirname(__file__), "emails.jsonl")
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" :: {detail}" if detail and not condition else ""))
    return condition


class API:
    def __init__(self, token: str | None = None):
        self.token = token

    def request(self, method: str, path: str, payload=None):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return requests.request(method, BASE + path, json=payload, headers=headers, timeout=20)

    def get(self, path): return self.request("GET", path)
    def post(self, path, payload=None): return self.request("POST", path, payload)
    def patch(self, path, payload=None): return self.request("PATCH", path, payload)
    def delete(self, path, payload=None): return self.request("DELETE", path, payload)


def register(email: str, role: str, profession: str | None = None, password="Start123!"):
    payload = {
        "email": email,
        "password": password,
        "role": role,
        "accepted_terms": True,
        "date_of_birth": "1990-01-01",
    }
    if profession:
        payload["profession"] = profession
    return API().post("/api/auth/register", payload)


def login(email: str, password: str):
    response = API().post("/api/auth/login", {"email": email, "password": password})
    if response.status_code != 200:
        raise RuntimeError(f"Login failed {response.status_code}: {response.text}")
    return API(response.json()["access_token"]), response.json()


def wait_for_code(email_address: str, subject_fragment: str, after_count: int = 0) -> str:
    deadline = time.time() + 15
    while time.time() < deadline:
        if os.path.exists(MAIL_LOG):
            with open(MAIL_LOG, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
            for row in rows[after_count:]:
                if email_address in row.get("to", []) and subject_fragment.lower() in row.get("subject", "").lower():
                    matches = re.findall(r"(?<!\d)\d{6}(?!\d)", row.get("body", ""))
                    if matches:
                        return matches[0]
        time.sleep(0.2)
    raise RuntimeError(f"No captured {subject_fragment} email for {email_address}")


def mail_count() -> int:
    if not os.path.exists(MAIL_LOG):
        return 0
    with open(MAIL_LOG, encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


async def websocket_roundtrip(job_id: int, client_token: str, provider_token: str):
    client_url = f"ws://127.0.0.1:8500/ws/messages/{job_id}?token={quote(client_token)}"
    provider_url = f"ws://127.0.0.1:8500/ws/messages/{job_id}?token={quote(provider_token)}"
    async with websockets.connect(client_url) as client_ws, websockets.connect(provider_url) as provider_ws:
        await client_ws.send(json.dumps({"content": "Mensaje WebSocket en tiempo real"}))
        client_received = json.loads(await asyncio.wait_for(client_ws.recv(), 5))
        provider_received = json.loads(await asyncio.wait_for(provider_ws.recv(), 5))
        return client_received, provider_received


def main():
    uid = uuid.uuid4().hex[:10]
    client_email = f"codex-client-{uid}@example.com"
    provider_email = f"codex-provider-{uid}@example.com"
    intruder_email = f"codex-intruder-{uid}@example.com"

    # Registration, email verification, age enforcement, and password reset.
    before = mail_count()
    client_reg = register(client_email, "client")
    check("Client registration", client_reg.status_code == 201, client_reg.text)
    client_data = client_reg.json()
    client = API(client_data["access_token"])
    check("Registration starts unverified", client_data.get("email_verified") is False, str(client_data))
    verification_code = wait_for_code(client_email, "Verify Your Email", before)
    wrong = client.post("/api/auth/verify-email", {"code": "000000"})
    check("Wrong verification code rejected", wrong.status_code == 200 and wrong.json().get("success") is False, wrong.text)
    verified = client.post("/api/auth/verify-email", {"code": verification_code})
    check("Email verification succeeds", verified.status_code == 200 and verified.json().get("email_verified") is True, verified.text)

    underage = API().post("/api/auth/register", {
        "email": f"codex-minor-{uid}@example.com", "password": "Minor123!", "role": "client",
        "accepted_terms": True, "date_of_birth": "2015-01-01",
    })
    check("Underage registration blocked", underage.status_code == 403, underage.text)

    before = mail_count()
    reset_request = API().post("/api/auth/reset-password-request", {"email": client_email})
    check("Password reset request accepted", reset_request.status_code == 200 and reset_request.json().get("success") is True, reset_request.text)
    reset_code = wait_for_code(client_email, "Password Reset Code", before)
    reset = API().post("/api/auth/reset-password-verify", {
        "email": client_email, "code": reset_code, "new_password": "Changed123!",
    })
    check("Password reset succeeds", reset.status_code == 200 and reset.json().get("success") is True, reset.text)
    old_login = API().post("/api/auth/login", {"email": client_email, "password": "Start123!"})
    check("Old password invalidated", old_login.status_code == 401, old_login.text)
    client, client_login = login(client_email.upper(), "Changed123!")
    check("New password and case-insensitive login work", client_login.get("role") == "client", str(client_login))

    nonexistent = API().post("/api/auth/reset-password-request", {"email": f"missing-{uid}@example.com"})
    check("Password reset prevents account enumeration", nonexistent.status_code == 200 and nonexistent.json() == reset_request.json(), nonexistent.text)

    # Correctly typed plumbing provider.
    before = mail_count()
    provider_reg = register(provider_email, "mechanic", "plumbing", "Provider123!")
    check("Plumbing provider registration", provider_reg.status_code == 201 and provider_reg.json().get("profession") == "plumbing", provider_reg.text)
    provider_data = provider_reg.json()
    provider = API(provider_data["access_token"])
    provider_code = wait_for_code(provider_email, "Verify Your Email", before)
    provider_verify = provider.post("/api/auth/verify-email", {"code": provider_code})
    check("Provider email verification", provider_verify.status_code == 200, provider_verify.text)

    profile_update = provider.patch("/api/provider/profile", {
        "full_name": "Codex Plumber", "is_available": True, "location": "Guayaquil",
    })
    check("Provider profile update", profile_update.status_code == 200, profile_update.text)
    online = provider.post("/api/provider/go-online")
    check("Provider goes online", online.status_code == 200 and online.json().get("is_online") is True, online.text)

    request = client.post("/api/client/requests", {
        "service_key": "faucet_leak_repair",
        "title": "Fuga de agua para prueba integral",
        "description": "La llave de la cocina gotea constantemente y requiere reparación profesional.",
        "location": "Urdesa Central, Guayaquil",
        "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
        "urgency": "immediate", "budget_max": 120,
    })
    check("Customer booking created", request.status_code == 201 and request.json().get("profession_type") == "plumbing", request.text)
    request_id = request.json()["id"]
    board = provider.get("/api/provider/board")
    check("Matching request appears on provider board", board.status_code == 200 and request_id in [item["id"] for item in board.json()], board.text)
    accepted = provider.post(f"/api/provider/board/{request_id}/accept")
    check("Provider accepts matching request", accepted.status_code == 201 and accepted.json().get("status") == "accepted", accepted.text)
    job_id = accepted.json()["id"]

    client_notifications = client.get("/api/notifications")
    provider_notifications = provider.get("/api/notifications")
    check("Acceptance creates customer notification", client_notifications.status_code == 200 and len(client_notifications.json()) >= 1, client_notifications.text)
    check("Acceptance creates provider notification", provider_notifications.status_code == 200 and len(provider_notifications.json()) >= 1, provider_notifications.text)

    first_message = client.post(f"/api/messages/job/{job_id}", {"content": "¿Cuándo puede llegar?"})
    reply = provider.post(f"/api/messages/job/{job_id}", {"content": "Estoy en camino."})
    thread = client.get(f"/api/messages/job/{job_id}")
    check("REST chat sends and reads both messages", first_message.status_code == 201 and reply.status_code == 201 and len(thread.json()) == 2, thread.text)

    client_token = client.token
    provider_token = provider.token
    client_ws, provider_ws = asyncio.run(websocket_roundtrip(job_id, client_token, provider_token))
    check("WebSocket chat broadcasts to customer", client_ws.get("type") == "message" and client_ws.get("content") == "Mensaje WebSocket en tiempo real", str(client_ws))
    check("WebSocket chat broadcasts to provider", provider_ws.get("type") == "message" and provider_ws.get("content") == "Mensaje WebSocket en tiempo real", str(provider_ws))

    intruder_reg = register(intruder_email, "client", password="Intruder123!")
    intruder = API(intruder_reg.json()["access_token"])
    denied_read = intruder.get(f"/api/messages/job/{job_id}")
    denied_send = intruder.post(f"/api/messages/job/{job_id}", {"content": "Should not work"})
    check("Non-participant cannot read chat", denied_read.status_code == 403, denied_read.text)
    check("Non-participant cannot send chat", denied_send.status_code == 403, denied_send.text)

    report = provider.post("/api/reports", {
        "entity_type": "message", "entity_id": first_message.json()["id"], "category": "other",
        "description": "Automated moderation workflow test",
    })
    check("Provider can report a job message", report.status_code == 201 and report.json().get("reported_user_id") == client_data["user_id"], report.text)

    blocked = client.post("/api/blocks", {"blocked_user_id": provider_data["user_id"]})
    blocked_client_send = client.post(f"/api/messages/job/{job_id}", {"content": "Blocked send"})
    blocked_provider_send = provider.post(f"/api/messages/job/{job_id}", {"content": "Blocked reply"})
    block_list = client.get("/api/blocks")
    check("Customer can block provider", blocked.status_code == 201 and len(block_list.json()) == 1, blocked.text)
    check("Block prevents messaging in both directions", blocked_client_send.status_code == 403 and blocked_provider_send.status_code == 403, f"{blocked_client_send.text} | {blocked_provider_send.text}")
    unblocked = client.delete(f"/api/blocks/{provider_data['user_id']}")
    resumed = client.post(f"/api/messages/job/{job_id}", {"content": "Messaging restored"})
    check("Unblock restores messaging", unblocked.status_code == 204 and resumed.status_code == 201, f"{unblocked.text} | {resumed.text}")

    for target in ["en_route", "diagnosing", "repairing"]:
        transition = provider.patch(f"/api/provider/jobs/{job_id}/status", {"status": target})
        check(f"Plumbing workflow -> {target}", transition.status_code == 200 and transition.json().get("status") == target, transition.text)
    completed = provider.patch(f"/api/provider/jobs/{job_id}/status", {
        "status": "completed", "mechanic_notes": "Fuga reparada", "final_price": 85,
    })
    check("Provider completes job", completed.status_code == 200 and completed.json().get("status") == "completed", completed.text)

    review = client.post(f"/api/client/jobs/{job_id}/review", {"rating": 5, "comment": "Excelente servicio"})
    customer_rating = provider.post(f"/api/provider/jobs/{job_id}/rate-customer", {"rating": 5, "comment": "Cliente puntual"})
    reputation = client.get("/api/client/reputation")
    check("Customer rates provider", review.status_code == 201 and review.json().get("rating") == 5, review.text)
    check("Provider rates customer", customer_rating.status_code == 201 and customer_rating.json().get("rating") == 5, customer_rating.text)
    check("Customer reputation updates", reputation.status_code == 200 and reputation.json().get("rating_count", 0) >= 1, reputation.text)

    dispute = client.post(f"/api/disputes/job/{job_id}", {"description": "Automated dispute workflow test with enough descriptive detail."})
    check("Customer raises dispute", dispute.status_code == 201 and dispute.json().get("status") == "open", dispute.text)

    admin, admin_login = login("admin@mechfix.app", "Admin123!")
    report_id = report.json()["id"]
    reports = admin.get("/api/admin/reports?status=open")
    report_resolved = admin.patch(f"/api/admin/reports/{report_id}", {"status": "resolved", "admin_notes": "Reviewed in automated test"})
    check("Admin sees moderation report", reports.status_code == 200 and report_id in [item["id"] for item in reports.json()], reports.text)
    check("Admin resolves moderation report", report_resolved.status_code == 200 and report_resolved.json().get("status") == "resolved", report_resolved.text)

    dispute_id = dispute.json()["id"]
    dispute_resolved = admin.patch(f"/api/admin/disputes/{dispute_id}", {"status": "resolved", "admin_notes": "Resolved in automated test"})
    check("Admin resolves dispute", dispute_resolved.status_code == 200 and dispute_resolved.json().get("status") == "resolved", dispute_resolved.text)

    verification = admin.patch(f"/api/admin/users/{provider_data['user_id']}", {"verification_level": "enhanced"})
    check("Admin grants enhanced provider verification", verification.status_code == 200 and verification.json().get("verification_level") == "enhanced", verification.text)

    mark_read = client.post("/api/notifications/mark-all-read")
    unread = client.get("/api/notifications/count")
    check("Notifications can be marked read", mark_read.status_code == 200 and unread.json().get("unread_count") == 0, f"{mark_read.text} | {unread.text}")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\nCURRENT FEATURE RESULTS: {passed}/{len(RESULTS)} passed")
    if passed != len(RESULTS):
        print("Failures:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"- {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
