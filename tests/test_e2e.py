"""
MechFix — End-to-end integration test suite.

Tests the full orchestration between client, mechanic, and admin.
Runs against the LIVE server (http://127.0.0.1:8500) — start it first.

Usage:
    pip install requests pytest  (or use .venv\Scripts\pip)
    .venv\Scripts\pytest tests/test_e2e.py -v

Or run standalone:
    .venv\Scripts\python tests/test_e2e.py
"""
from __future__ import annotations

import sys
import uuid
import requests
import traceback

# Windows pipes default to cp1252 — failure details contain "→"/emoji, and a
# crashed print must never mask a real test failure.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8500"
# Registration now requires a date of birth (18+ policy — see age.py).
ADULT_DOB = "1990-01-01"
PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"

# ──────────────────────────────────────────────
# Test runner helpers
# ──────────────────────────────────────────────

results = []

def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    label = f"  {tag} {name}"
    if not condition and detail:
        label += f"\n         → {detail}"
    print(label)
    results.append((name, condition))
    return condition

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ──────────────────────────────────────────────
# HTTP helper
# ──────────────────────────────────────────────

class Session:
    def __init__(self, token: str = None):
        self.token = token

    def headers(self):
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def get(self, path, **kw):
        return requests.get(BASE + path, headers=self.headers(), **kw)

    def post(self, path, json=None, **kw):
        return requests.post(BASE + path, json=json, headers=self.headers(), **kw)

    def patch(self, path, json=None, **kw):
        return requests.patch(BASE + path, json=json, headers=self.headers(), **kw)

    def put(self, path, json=None, **kw):
        return requests.put(BASE + path, json=json, headers=self.headers(), **kw)

    def delete(self, path, **kw):
        return requests.delete(BASE + path, headers=self.headers(), **kw)


anon = Session()


def login(email: str, password: str) -> Session:
    r = anon.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    data = r.json()
    s = Session(data["access_token"])
    s.role = data["role"]
    s.user_id = data["user_id"]
    return s


# ──────────────────────────────────────────────
# TEST 1: Health & server reachability
# ──────────────────────────────────────────────

def test_server_health():
    section("1. Server Health")
    try:
        r = anon.get("/health")
        check("Server is reachable", r.status_code == 200)
        data = r.json()
        # "degraded" is acceptable in local dev (no SMTP); the database must be up.
        check("Health status ok/degraded", data.get("status") in ("ok", "degraded"), str(data))
        check("Database reachable", data.get("database_ok") is True, str(data))
        check("Service name correct", data.get("app") == "Lever", str(data))
        check("Version present", "version" in data)
    except requests.ConnectionError:
        check("Server is reachable", False, f"Cannot connect to {BASE} — is it running?")
        print("\n  Start with: start.bat or .venv\\Scripts\\python -m uvicorn app:app --port 8500")
        sys.exit(1)


# ──────────────────────────────────────────────
# TEST 2: Auth flows
# ──────────────────────────────────────────────

def test_auth():
    section("2. Authentication")
    uid = str(uuid.uuid4())[:8]

    # Registration
    r = anon.post("/api/auth/register", json={
        "email": f"testclient_{uid}@test.com",
        "password": "Test1234!",
        "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    check("Client registration returns 201", r.status_code == 201, r.text)
    token_data = r.json()
    check("Registration returns JWT", "access_token" in token_data)
    check("Role is client", token_data.get("role") == "client")

    # Duplicate registration rejected
    r2 = anon.post("/api/auth/register", json={
        "email": f"testclient_{uid}@test.com",
        "password": "Test1234!",
        "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    check("Duplicate registration rejected (409)", r2.status_code == 409, r2.text)

    # Weak password rejected
    r3 = anon.post("/api/auth/register", json={
        "email": f"weak_{uid}@test.com",
        "password": "weak",
        "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    check("Weak password rejected (422)", r3.status_code == 422, r3.text)

    # Login
    r4 = anon.post("/api/auth/login", json={
        "email": f"testclient_{uid}@test.com",
        "password": "Test1234!"
    })
    check("Login returns 200", r4.status_code == 200, r4.text)

    # Wrong password
    r5 = anon.post("/api/auth/login", json={
        "email": f"testclient_{uid}@test.com",
        "password": "WrongPass1!"
    })
    check("Wrong password rejected (401)", r5.status_code == 401)

    # Role guard — client tries mechanic endpoint
    client_sess = Session(token_data["access_token"])
    r6 = client_sess.get("/api/provider/board")
    check("Client denied provider endpoint (403)", r6.status_code == 403)

    # Role guard — unauthenticated request
    r7 = anon.get("/api/client/profile")
    check("Unauthenticated request denied (401)", r7.status_code == 401)


# ──────────────────────────────────────────────
# TEST 3: Full client → mechanic → admin flow
# ──────────────────────────────────────────────

def test_full_orchestration():
    section("3. Full Orchestration Flow")

    # ---- Login all three roles ----
    uid = str(uuid.uuid4())[:8]
    client_r = anon.post("/api/auth/register", json={
        "email": f"client_{uid}@test.com",
        "password": "Client123!",
        "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    check("Register fresh client", client_r.status_code == 201)
    client = Session(client_r.json()["access_token"])

    mech_r = anon.post("/api/auth/register", json={
        "email": f"mech_{uid}@test.com",
        "password": "Mech1234!",
        "role": "mechanic", "profession": "plumbing",
        "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    check("Register fresh provider", mech_r.status_code == 201)
    mech = Session(mech_r.json()["access_token"])

    admin = login("admin@lever.app", "Admin123!")
    check("Admin login", admin.role == "admin")

    print(f"\n  {INFO} Client ID={client_r.json()['user_id']}  Mechanic ID={mech_r.json()['user_id']}\n")

    # ---- Step 1: Client adds a vehicle ----
    r = client.post("/api/client/vehicles", json={
        "make": "Honda",
        "model": "Civic",
        "year": 2020,
        "mileage": 30000,
        "color": "Silver"
    })
    check("Client adds vehicle (201)", r.status_code == 201, r.text)
    vehicle_id = r.json()["id"]

    # ---- Step 2: Client creates service request ----
    r = client.post("/api/client/requests", json={
        "title": "Fuga fuerte bajo el fregadero",
        "description": "Fuga de agua constante bajo el fregadero de la cocina desde ayer.",
        "location": "Av. Francisco de Orellana, Kennedy Norte, Guayaquil",
        "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
        "urgency": "immediate",
        "profession_type": "plumbing",
        "vehicle_id": vehicle_id,
        "budget_max": 400.0,
    })
    check("Client creates service request (201)", r.status_code == 201, r.text)
    request_id = r.json()["id"]
    check("Request status is pending", r.json()["status"] == "pending")

    # ---- Step 3: Provider goes online and sees it on board ----
    mech.post("/api/provider/go-online")  # Must be online to see board
    r = mech.get("/api/provider/board")
    check("Provider sees request on board", r.status_code == 200)
    board_ids = [item["id"] for item in r.json()]
    check("New request appears on board", request_id in board_ids, f"Expected {request_id} in {board_ids}")

    # ---- Step 4: Provider accepts ----
    r = mech.post(f"/api/provider/board/{request_id}/accept")
    check("Provider accepts request (201)", r.status_code == 201, r.text)
    job_id = r.json()["id"]
    check("Job starts EN ROUTE on accept (simplified flow)", r.json()["status"] == "en_route")
    check("Arrival window set on accept", r.json().get("arrival_deadline") is not None)

    # ---- Step 4b: Double-accept rejected ----
    r2 = mech.post(f"/api/provider/board/{request_id}/accept")
    check("Double-accept rejected (409)", r2.status_code == 409)

    # ---- Step 5: Request status updated ----
    r = client.get(f"/api/client/requests/{request_id}")
    check("Request now shows assigned status", r.json()["status"] == "assigned", r.json()["status"])
    check("Request has linked job", r.json().get("job") is not None)

    # ---- Step 6: (no cancel here) ----
    # Cancelling an assigned request is allowed and now cancels the Job and
    # frees the professional — covered by test 18. Here the job must keep
    # running so the rest of the flow can progress.

    # ---- Step 7: Messaging ----
    r = client.post(f"/api/messages/job/{job_id}", json={"content": "Hi! How long will it take?"})
    check("Client sends message (201)", r.status_code == 201, r.text)
    msg_id = r.json()["id"]

    r = mech.post(f"/api/messages/job/{job_id}", json={"content": "About 2 hours. I'm on my way."})
    check("Provider sends reply (201)", r.status_code == 201, r.text)

    r = client.get(f"/api/messages/job/{job_id}")
    check("Client reads both messages", r.status_code == 200 and len(r.json()) == 2)

    # ---- Step 8: Job status progression (en_route → diagnosing → repairing → completed) ----
    transitions = [
        ("diagnosing", "en_route",   True),
        ("repairing",  "diagnosing", True),
    ]
    for new_status, from_status, should_pass in transitions:
        r = mech.patch(f"/api/provider/jobs/{job_id}/status", json={"status": new_status})
        check(f"Job transitions {from_status} -> {new_status}", r.status_code == 200, r.text)

    # ---- Step 8b: Invalid transition (en_route from repairing) ----
    r = mech.patch(f"/api/provider/jobs/{job_id}/status", json={"status": "en_route"})
    check("Invalid transition rejected (400)", r.status_code == 400, r.text)

    # ---- Step 9: Complete job with notes + price ----
    r = mech.patch(f"/api/provider/jobs/{job_id}/status", json={
        "status": "completed",
        "mechanic_notes": "Replaced spark plugs. Knocking resolved.",
        "final_price": 185.0
    })
    check("Provider completes job (200)", r.status_code == 200, r.text)
    check("Job status = completed", r.json()["status"] == "completed")
    check("Final price recorded", r.json()["final_price"] == 185.0)

    # ---- Step 10: Service request auto-completes ----
    r = client.get(f"/api/client/requests/{request_id}")
    check("Request auto-completes when job done", r.json()["status"] == "completed")

    # ---- Step 11: review requires client confirmation first ----
    r0 = client.post(f"/api/client/jobs/{job_id}/review", json={"rating": 4, "comment": "x"})
    check("Review blocked before client confirms (400)",
          r0.status_code == 400 and "CONFIRM_COMPLETION_FIRST" in r0.text, r0.text)
    rc = client.post(f"/api/client/jobs/{job_id}/confirm-completion")
    check("Client confirms completion (200)", rc.status_code == 200, rc.text)
    rc2 = client.post(f"/api/client/jobs/{job_id}/confirm-completion")
    check("Duplicate confirmation rejected (409)", rc2.status_code == 409, rc2.text)
    r = client.post(f"/api/client/jobs/{job_id}/review", json={
        "rating": 4,
        "comment": "Quick and professional. Would use again."
    })
    check("Client leaves review (201)", r.status_code == 201, r.text)
    check("Review rating correct", r.json()["rating"] == 4)

    # ---- Step 11b: Duplicate review rejected ----
    r2 = client.post(f"/api/client/jobs/{job_id}/review", json={"rating": 5, "comment": "Again"})
    check("Duplicate review rejected (409)", r2.status_code == 409)

    # ---- Step 12: Provider avg rating updated ----
    r = mech.get("/api/provider/profile")
    check("Provider total_jobs incremented", r.json()["total_jobs"] >= 1)

    # ---- Step 13: Raise a dispute ----
    r = client.post(f"/api/disputes/job/{job_id}", json={
        "description": "The mechanic said he would use OEM parts but used aftermarket spark plugs."
    })
    check("Client raises dispute (201)", r.status_code == 201, r.text)
    dispute_id = r.json()["id"]
    check("Dispute status = open", r.json()["status"] == "open")

    # ---- Step 13b: Duplicate dispute rejected ----
    r2 = client.post(f"/api/disputes/job/{job_id}", json={"description": "Again raising the same dispute about the parts issue"})
    check("Duplicate dispute rejected (409)", r2.status_code == 409)

    # ---- Step 14: Admin sees dispute ----
    r = admin.get("/api/admin/disputes")
    dispute_ids = [d["id"] for d in r.json()]
    check("Admin sees new dispute", dispute_id in dispute_ids)

    # ---- Step 15: Admin resolves dispute ----
    r = admin.patch(f"/api/admin/disputes/{dispute_id}", json={
        "status": "resolved",
        "admin_notes": "Verified receipts — aftermarket parts used. Refunded $40."
    })
    check("Admin resolves dispute (200)", r.status_code == 200, r.text)
    check("Dispute status = resolved", r.json()["status"] == "resolved")
    check("Admin notes saved", "aftermarket" in r.json()["admin_notes"])

    # ---- Step 16: Admin dashboard reflects activity ----
    r = admin.get("/api/admin/stats")
    stats = r.json()
    check("Admin stats endpoint works", r.status_code == 200)
    check("Completed jobs counted", stats["completed_jobs"] >= 1)

    print(f"\n  {INFO} Orchestration job_id={job_id} dispute_id={dispute_id}")


# ──────────────────────────────────────────────
# TEST 4: Client flows
# ──────────────────────────────────────────────

def test_client_flows():
    section("4. Client-Specific Flows")
    client = login("alice@demo.com", "Alice123!")

    # Profile CRUD
    r = client.get("/api/client/profile")
    check("Get client profile (200)", r.status_code == 200)
    check("Profile has full_name", "full_name" in r.json())

    r = client.patch("/api/client/profile", json={"phone": "555-9999"})
    check("Update profile (200)", r.status_code == 200)
    check("Phone updated", r.json()["phone"] == "555-9999")

    # Vehicle operations
    r = client.get("/api/client/vehicles")
    check("List vehicles (200)", r.status_code == 200)
    check("Has at least 1 vehicle", len(r.json()) >= 1)

    # Create + delete vehicle
    r = client.post("/api/client/vehicles", json={
        "make": "Test", "model": "Car", "year": 2022, "mileage": 0
    })
    check("Add vehicle (201)", r.status_code == 201)
    new_vid = r.json()["id"]

    r = client.delete(f"/api/client/vehicles/{new_vid}")
    check("Delete vehicle (200)", r.status_code == 200)

    # Browse providers
    r = client.get("/api/client/providers")
    check("Browse providers (200)", r.status_code == 200)
    check("At least one provider visible", len(r.json()) >= 1)

    # Budget validation
    r = client.post("/api/client/requests", json={
        "title": "Engine check",
        "description": "Something is wrong with my engine, needs diagnosis",
        "location": "123 Test St",
        "urgency": "scheduled",
        "budget_min": 500.0,
        "budget_max": 100.0,  # min > max — should fail
    })
    check("Budget min > max rejected (422)", r.status_code == 422, r.text)


# ──────────────────────────────────────────────
# TEST 5: Mechanic flows
# ──────────────────────────────────────────────

def test_mechanic_flows():
    section("5. Provider-Specific Flows")
    mech = login("sarah@demo.com", "Sarah123!")

    # Profile
    r = mech.get("/api/provider/profile")
    check("Get provider profile (200)", r.status_code == 200)
    check("Has specialties list", isinstance(r.json().get("specialties"), list))

    # Toggle availability
    current = r.json()["is_available"]
    r = mech.patch("/api/provider/profile", json={"is_available": not current})
    check("Toggle availability (200)", r.status_code == 200)
    check("Availability toggled", r.json()["is_available"] == (not current))
    mech.patch("/api/provider/profile", json={"is_available": current})  # restore

    # Go online / offline
    r = mech.post("/api/provider/go-online")
    check("Go online (200)", r.status_code == 200)
    check("is_online = True", r.json().get("is_online") == True)

    r = mech.post("/api/provider/go-offline")
    check("Go offline (200)", r.status_code == 200)
    check("is_online = False", r.json().get("is_online") == False)

    # Heartbeat
    mech.post("/api/provider/go-online")
    r = mech.post("/api/provider/heartbeat")
    check("Heartbeat (200)", r.status_code == 200)
    check("Heartbeat returns online", r.json().get("is_online") == True)
    mech.post("/api/provider/go-offline")  # restore

    # Job list
    r = mech.get("/api/provider/jobs")
    check("List my jobs (200)", r.status_code == 200)

    # Reviews
    r = mech.get("/api/provider/reviews")
    check("List reviews (200)", r.status_code == 200)


# ──────────────────────────────────────────────
# TEST 6: Admin flows
# ──────────────────────────────────────────────

def test_admin_flows():
    section("6. Admin-Specific Flows")
    admin = login("admin@lever.app", "Admin123!")

    # Stats
    r = admin.get("/api/admin/stats")
    check("Get platform stats (200)", r.status_code == 200)
    expected_fields = ["total_users","total_clients","total_mechanics",
                       "open_requests","active_jobs","completed_jobs","open_disputes"]
    for f in expected_fields:
        check(f"Stats has '{f}'", f in r.json())

    # User list
    r = admin.get("/api/admin/users")
    check("List users (200)", r.status_code == 200)
    check("Returns paginated result", "total" in r.json() and "items" in r.json())

    # Filter by role
    r = admin.get("/api/admin/users?role=mechanic")
    check("Filter users by role (200)", r.status_code == 200)
    all_mechanics = all(u["role"] == "mechanic" for u in r.json()["items"])
    check("All returned users are mechanics", all_mechanics, str(r.json()["items"][:2]))

    # Admin can't deactivate self
    r = admin.patch(f"/api/admin/users/{admin.user_id}", json={"is_active": False})
    check("Admin can't deactivate own account (400)", r.status_code == 400, r.text)

    # Non-admin can't access admin stats
    client = login("alice@demo.com", "Alice123!")
    r = client.get("/api/admin/stats")
    check("Non-admin denied stats (403)", r.status_code == 403)


# ──────────────────────────────────────────────
# TEST 7: Message isolation
# ──────────────────────────────────────────────

def test_message_isolation():
    section("7. Message Security & Isolation")

    # Create two completely separate client/mechanic pairs
    uid = str(uuid.uuid4())[:8]

    c1_r = anon.post("/api/auth/register", json={
        "email": f"c1_{uid}@test.com", "password": "C1234567!", "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    c2_r = anon.post("/api/auth/register", json={
        "email": f"c2_{uid}@test.com", "password": "C2234567!", "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    m1_r = anon.post("/api/auth/register", json={
        "email": f"m1_{uid}@test.com", "password": "M1234567!", "role": "mechanic", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    c1 = Session(c1_r.json()["access_token"])
    c2 = Session(c2_r.json()["access_token"])
    m1 = Session(m1_r.json()["access_token"])

    # c1 creates request, m1 accepts → job_a
    sr = c1.post("/api/client/requests", json={
        "title": "Test isolation request",
        "description": "This is a test to verify message isolation between job participants",
        "location": "Urdesa Central, Guayaquil",
        "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
        "urgency": "scheduled",
    })
    m1.post("/api/provider/go-online")
    job_a_r = m1.post(f"/api/provider/board/{sr.json()['id']}/accept")
    job_a = job_a_r.json()["id"]

    # c1 sends message
    c1.post(f"/api/messages/job/{job_a}", json={"content": "Private message from c1"})

    # c2 tries to read job_a messages — should be denied
    r = c2.get(f"/api/messages/job/{job_a}")
    check("Non-participant denied job messages (403)", r.status_code == 403, r.text)

    # c2 tries to send to job_a — should be denied
    r = c2.post(f"/api/messages/job/{job_a}", json={"content": "Intruder message"})
    check("Non-participant denied message send (403)", r.status_code == 403, r.text)

    # Unread count only counts own unread
    r = m1.get("/api/messages/unread-count")
    check("Unread count endpoint works", r.status_code == 200 and "unread" in r.json())


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def test_guayaquil_market():
    """Guayaquil-only launch: market config + authoritative service-area
    enforcement on request creation."""
    print(f"\n{INFO} TEST: Guayaquil market restriction")

    # Public market endpoint reports Guayaquil active.
    r = requests.get(f"{BASE}/api/market")
    check("Active market endpoint (200)", r.status_code == 200, r.text)
    check("Active market is Guayaquil", r.json().get("city") == "Guayaquil", r.text)
    check("Market code is GYE", r.json().get("code") == "GYE")

    # Advisory location check.
    r = requests.post(f"{BASE}/api/market/check-location", json={"city": "Guayaquil"})
    check("Guayaquil city supported", r.json().get("supported") is True, r.text)
    r = requests.post(f"{BASE}/api/market/check-location", json={"city": "Quito"})
    check("Quito city not supported", r.json().get("supported") is False, r.text)
    r = requests.post(f"{BASE}/api/market/check-location", json={"latitude": -2.19, "longitude": -79.88})
    check("Guayaquil coords supported", r.json().get("supported") is True, r.text)
    r = requests.post(f"{BASE}/api/market/check-location", json={"latitude": -0.18, "longitude": -78.47})
    check("Quito coords not supported", r.json().get("supported") is False, r.text)

    # Real enforcement on request creation.
    uid = uuid.uuid4().hex[:8]
    c = requests.Session()
    reg = c.post(f"{BASE}/api/auth/register", json={
        "email": f"gye_{uid}@test.com", "password": "Passw0rd!", "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB,
    })
    tok = reg.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # Out-of-area probes FIRST: the one-active-request rule (409) would
    # otherwise short-circuit these once the valid request below exists.
    bad = c.post(f"{BASE}/api/client/requests", headers=h, json={
        "service_key": "faucet_leak_repair", "title": "Fuga de agua en la cocina",
        "description": "La llave de la cocina gotea constantemente desde ayer",
        "location": "Quito", "city": "Quito", "province": "Pichincha", "country_code": "EC",
    })
    check("Non-Guayaquil request rejected (422)", bad.status_code == 422, bad.text)
    check("Rejection reason is out-of-area", "GUAYAQUIL" in bad.text.upper(), bad.text)

    # Client can't smuggle in a market_code — server assigns it.
    tamper = c.post(f"{BASE}/api/client/requests", headers=h, json={
        "service_key": "faucet_leak_repair", "title": "Fuga de agua en la cocina",
        "description": "La llave de la cocina gotea constantemente desde ayer",
        "location": "Quito", "city": "Quito", "market_code": "GYE",
    })
    check("Client-supplied market_code cannot bypass (422)", tamper.status_code == 422, tamper.text)

    ok = c.post(f"{BASE}/api/client/requests", headers=h, json={
        "service_key": "faucet_leak_repair", "title": "Fuga de agua en la cocina",
        "description": "La llave de la cocina gotea constantemente desde ayer",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
    })
    check("Guayaquil request accepted (201)", ok.status_code == 201, ok.text)
    check("Request assigned market_code GYE", ok.json().get("market_code") == "GYE", ok.text)


def run_all():
    print("\n" + "="*60)
    print("  MechFix Integration Test Suite")
    print(f"  Target: {BASE}")
    print("="*60)

    tests = [
        test_server_health,
        test_auth,
        test_full_orchestration,
        test_client_flows,
        test_mechanic_flows,
        test_admin_flows,
        test_message_isolation,
        test_guayaquil_market,
        test_customer_ratings,
        test_email_case_insensitive,
        test_minimum_age,
        test_multi_profession_matching,
        test_pricing_estimates,
        test_app_set_pricing,
        test_redispatch_on_go_online,
        test_one_at_a_time,
        test_dispatch_lifecycle,
        test_client_cancel_releases_provider,
        test_worker_set_pricing,
        test_choose_professional,
        test_hourly_metering,
        test_admin_operations,
        test_device_registration,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            print(f"\n  {FAIL} Test function crashed: {test_fn.__name__}")
            traceback.print_exc()

    # Summary
    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    failed = total - passed
    print(f"\n{'='*60}")
    print(f"  RESULTS:  {passed}/{total} passed", end="")
    if failed:
        print(f"  |  {failed} FAILED", end="")
    print(f"\n{'='*60}")

    if failed:
        print("\n  Failed checks:")
        for name, ok in results:
            if not ok:
                print(f"    - {name}")
        sys.exit(1)
    else:
        print("\n  All tests passed.")


def test_customer_ratings():
    section("9. Customer ratings + reputation (two-way)")
    uid = str(uuid.uuid4())[:8]

    cr = anon.post("/api/auth/register", json={
        "email": f"crat_{uid}@test.com", "password": "Client123!",
        "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    check("Register client", cr.status_code == 201, cr.text)
    client = Session(cr.json()["access_token"])

    mr = anon.post("/api/auth/register", json={
        "email": f"mrat_{uid}@test.com", "password": "Mech1234!",
        "role": "mechanic", "profession": "plumbing",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    check("Register mechanic A", mr.status_code == 201, mr.text)
    mech = Session(mr.json()["access_token"])

    mr2 = anon.post("/api/auth/register", json={
        "email": f"mrat2_{uid}@test.com", "password": "Mech1234!",
        "role": "mechanic", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    other_mech = Session(mr2.json()["access_token"])

    rq = client.post("/api/client/requests", json={
        "title": "Fuga de agua en la cocina",
        "description": "Hay una fuga bajo el fregadero desde ayer.",
        "location": "Urdesa Central, Guayaquil",
        "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
        "urgency": "immediate", "budget_max": 100.0, "profession_type": "plumbing"})
    check("Create request (201)", rq.status_code == 201, rq.text)
    request_id = rq.json()["id"]

    mech.post("/api/provider/go-online")
    acc = mech.post(f"/api/provider/board/{request_id}/accept")
    check("Mechanic accepts (201)", acc.status_code == 201, acc.text)
    job_id = acc.json()["id"]

    early = mech.post(f"/api/provider/jobs/{job_id}/rate-customer", json={"rating": 5})
    check("Rate before completion rejected (400)",
          early.status_code == 400 and "JOB_NOT_ELIGIBLE" in early.text, early.text)

    for s in ["diagnosing", "repairing"]:
        mech.patch(f"/api/provider/jobs/{job_id}/status", json={"status": s})
    comp = mech.patch(f"/api/provider/jobs/{job_id}/status",
                      json={"status": "completed", "final_price": 80.0})
    check("Complete job (200)", comp.status_code == 200, comp.text)

    rep0 = client.get("/api/client/reputation")
    check("Reputation reachable (200)", rep0.status_code == 200, rep0.text)
    check("No rating yet -> average null + count 0",
          rep0.json().get("average_rating") is None and rep0.json().get("rating_count") == 0, rep0.text)

    bad = other_mech.post(f"/api/provider/jobs/{job_id}/rate-customer", json={"rating": 5})
    check("Non-assigned mechanic rejected (403)",
          bad.status_code == 403 and "PROFESSIONAL_NOT_ASSIGNED" in bad.text, bad.text)

    invalid = mech.post(f"/api/provider/jobs/{job_id}/rate-customer", json={"rating": 6})
    check("Rating > 5 rejected (422)", invalid.status_code == 422, invalid.text)

    rate = mech.post(f"/api/provider/jobs/{job_id}/rate-customer",
                     json={"rating": 5, "comment": "Cliente puntual y claro."})
    check("Mechanic rates customer (201)", rate.status_code == 201, rate.text)

    dup = mech.post(f"/api/provider/jobs/{job_id}/rate-customer", json={"rating": 4})
    check("Duplicate customer rating rejected (409)",
          dup.status_code == 409 and "ALREADY_EXISTS" in dup.text, dup.text)

    rep = client.get("/api/client/reputation").json()
    check("Reputation count = 1", rep.get("rating_count") == 1, str(rep))
    check("Reputation average = 5.0", rep.get("average_rating") == 5.0, str(rep))
    check("Completed job count >= 1", rep.get("completed_job_count", 0) >= 1, str(rep))
    check("Recent ratings hide professional identity",
          all("mechanic_id" not in rr and "professional_id" not in rr for rr in rep.get("recent_ratings", [])), str(rep))

    cr2 = anon.post("/api/auth/register", json={
        "email": f"crat_b_{uid}@test.com", "password": "Client123!",
        "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client_b = Session(cr2.json()["access_token"])
    repb = client_b.get("/api/client/reputation").json()
    check("Other client's reputation empty (isolation)", repb.get("rating_count") == 0, str(repb))


def test_email_case_insensitive():
    section("10. Case-insensitive email")
    uid = str(uuid.uuid4())[:8]
    email_lower = f"case_{uid}@test.com"
    r = anon.post("/api/auth/register", json={
        "email": email_lower, "password": "Client123!", "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    check("Register lowercase email (201)", r.status_code == 201, r.text)
    dup = anon.post("/api/auth/register", json={
        "email": email_lower.upper(), "password": "Client123!", "role": "client", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    check("Duplicate with different case rejected (409)", dup.status_code == 409, dup.text)
    li = anon.post("/api/auth/login", json={"email": email_lower.upper(), "password": "Client123!"})
    check("Login with uppercase email works (200)",
          li.status_code == 200 and bool(li.json().get("access_token")), li.text)


def test_minimum_age():
    section("11. Minimum age (18+) enforcement")
    from datetime import date, timedelta
    uid = str(uuid.uuid4())[:8]

    def reg(suffix, dob, role="client"):
        body = {"email": f"age_{suffix}_{uid}@test.com", "password": "Client123!",
                "role": role, "accepted_terms": True}
        if dob is not None:
            body["date_of_birth"] = dob
        return anon.post("/api/auth/register", json=body)

    # The 18+ policy evaluates "today" in America/Guayaquil (age.py). The
    # machine's local/UTC date can differ by a day around midnight (e.g.
    # 00:00–05:00 UTC is still the previous day in Guayaquil), so boundary
    # cases MUST be computed on the Guayaquil clock. Ecuador has no DST.
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    today = _dt.now(_tz(_td(hours=-5))).date()

    def dob_for_age(years, days_offset=0):
        try:
            b = today.replace(year=today.year - years)
        except ValueError:
            b = date(today.year - years, 3, 1)
        return (b + timedelta(days=days_offset)).isoformat()

    # ---- Boundary ----
    r = reg("today18", dob_for_age(18))
    check("Turns 18 TODAY -> allowed (201)", r.status_code == 201, r.text)

    r = reg("tomorrow18", dob_for_age(18, 1))
    check("Turns 18 TOMORROW -> rejected (403)",
          r.status_code == 403 and "MINIMUM_AGE_REQUIREMENT_NOT_MET" in r.text, r.text)

    r = reg("yesterday18", dob_for_age(18, -1))
    check("Turned 18 YESTERDAY -> allowed (201)", r.status_code == 201, r.text)

    r = reg("child", dob_for_age(10))
    check("10-year-old rejected (403)",
          r.status_code == 403 and "MINIMUM_AGE_REQUIREMENT_NOT_MET" in r.text, r.text)

    # ---- Provider channel: underage must not reach professional onboarding ----
    r = reg("minorpro", dob_for_age(15), role="mechanic")
    check("Underage PROVIDER rejected (403)",
          r.status_code == 403 and "MINIMUM_AGE_REQUIREMENT_NOT_MET" in r.text, r.text)

    # ---- Invalid input ----
    r = reg("nodob", None)
    check("Missing date_of_birth rejected (422)", r.status_code == 422, r.text)

    r = reg("future", (today + timedelta(days=1)).isoformat())
    check("Future DOB rejected", r.status_code in (403, 422), r.text)

    r = reg("badcal", "2000-02-31")
    check("Impossible calendar date (31 Feb) rejected (422)", r.status_code == 422, r.text)

    r = reg("nontext", "not-a-date")
    check("Non-date text rejected (422)", r.status_code == 422, r.text)

    r = reg("ancient", "0001-01-01")
    check("Absurdly old DOB rejected", r.status_code in (403, 422), r.text)

    # ---- Bypass attempts: client-supplied adult flags are ignored ----
    r = anon.post("/api/auth/register", json={
        "email": f"age_flag_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "isAdult": True, "age": 30})
    check("isAdult/age flags cannot replace DOB (422)", r.status_code == 422, r.text)

    r = anon.post("/api/auth/register", json={
        "email": f"age_flag2_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": dob_for_age(12), "isAdult": True})
    check("isAdult=true does not override a minor's DOB (403)",
          r.status_code == 403 and "MINIMUM_AGE_REQUIREMENT_NOT_MET" in r.text, r.text)

    # ---- DOB must not leak back in the error ----
    r = reg("leak", dob_for_age(9))
    check("Underage error does not echo the DOB", dob_for_age(9) not in r.text, r.text)


def test_multi_profession_matching():
    section("12. Multi-profession + exact-service matching")
    uid = str(uuid.uuid4())[:8]
    PLUMB = "pipe_leak_repair"      # plumbing service (no enhanced verification)
    ELEC = "outlet_replacement"     # electrical service

    # An ELECTRICIAN who explicitly enables a PLUMBING service.
    er = anon.post("/api/auth/register", json={
        "email": f"elec_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "electrical", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    check("Register electrician", er.status_code == 201, er.text)
    elec = Session(er.json()["access_token"])

    # Multi-profession WRITE: an electrician can now configure a plumbing service.
    r = elec.put("/api/provider/services", json={"services": [{"service_key": PLUMB}]})
    check("Electrician can enable a PLUMBING service (cross-profession)", r.status_code == 200, r.text)

    # A second electrician who only enabled an ELECTRICAL service.
    er2 = anon.post("/api/auth/register", json={
        "email": f"elec2_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "electrical", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    elec2 = Session(er2.json()["access_token"])
    elec2.put("/api/provider/services", json={"services": [{"service_key": ELEC}]})

    elec.post("/api/provider/go-online")
    elec2.post("/api/provider/go-online")

    # Client submits a PLUMBING request (backend derives profession from service).
    cr = anon.post("/api/auth/register", json={
        "email": f"cli_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    rq = client.post("/api/client/requests", json={
        "title": "Fuga en tubería de la cocina",
        "description": "Hay una fuga en la tubería bajo el fregadero.",
        "location": "Urdesa Central, Guayaquil",
        "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
        "urgency": "immediate", "service_key": PLUMB})
    check("Plumbing request created (201)", rq.status_code == 201, rq.text)
    check("Backend derived profession = plumbing",
          rq.json().get("profession_type") == "plumbing", rq.json().get("profession_type"))
    request_id = rq.json()["id"]

    # The electrician who ENABLED the plumbing service SEES it (cross-profession).
    board = elec.get("/api/provider/board")
    ids = [x["id"] for x in board.json()]
    check("Electrician-with-plumbing SEES the plumbing request", request_id in ids, str(ids))

    # The electrician who did NOT enable it does not see it (exact service).
    board2 = elec2.get("/api/provider/board")
    ids2 = [x["id"] for x in board2.json()]
    check("Electrician-without-it does NOT see the plumbing request", request_id not in ids2, str(ids2))

    # And can ACCEPT it despite the profession mismatch.
    acc = elec.post(f"/api/provider/board/{request_id}/accept")
    check("Cross-profession accept succeeds (201)", acc.status_code == 201, acc.text)

    # Paused service -> no longer eligible.
    uid2 = str(uuid.uuid4())[:8]
    pr = anon.post("/api/auth/register", json={
        "email": f"paus_{uid2}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "electrical", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    paused = Session(pr.json()["access_token"])
    paused.put("/api/provider/services", json={"services": [{"service_key": PLUMB}]})
    paused.patch(f"/api/provider/services/{PLUMB}", json={"is_active": False})
    paused.post("/api/provider/go-online")
    # One-request-at-a-time: the first client still has an active job, so the
    # second probe request comes from a fresh client.
    cr2 = anon.post("/api/auth/register", json={
        "email": f"cli2_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client_b = Session(cr2.json()["access_token"])
    rq2 = client_b.post("/api/client/requests", json={
        "title": "Otra fuga en tubería",
        "description": "Segunda fuga distinta bajo el lavabo del baño.",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "service_key": PLUMB})
    board3 = paused.get("/api/provider/board")
    check("Paused service -> request not on board",
          rq2.json()["id"] not in [x["id"] for x in board3.json()], board3.text)


def test_pricing_estimates():
    section("13. Reference pricing (Guayaquil labor rates)")
    r = anon.get("/api/catalog")
    check("Catalog reachable", r.status_code == 200, r.text[:200])
    services = r.json().get("services", [])
    with_est = [s for s in services if s.get("estimate_min") is not None]
    check("Catalog services carry estimates", len(with_est) > 250, f"{len(with_est)}/{len(services)}")
    check("All estimates sane (0 < min <= max)",
          all(0 < s["estimate_min"] <= s["estimate_max"] for s in with_est))

    # Board rows carry the estimate so providers see payment without a budget.
    uid = str(uuid.uuid4())[:8]
    mr = anon.post("/api/auth/register", json={
        "email": f"pr_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "plumbing", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    mech = Session(mr.json()["access_token"])
    cr = anon.post("/api/auth/register", json={
        "email": f"cl_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    client.post("/api/client/requests", json={
        "title": "Fuga sin presupuesto",
        "description": "Fuga en tubería, sin presupuesto definido.",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "service_key": "pipe_leak_repair"})
    mech.post("/api/provider/go-online")
    board = mech.get("/api/provider/board").json()
    mine = [b for b in board if b["title"] == "Fuga sin presupuesto"]
    check("Board row has estimate when client set no budget",
          bool(mine) and mine[0].get("estimate_min") is not None, str(mine[:1]))


def test_app_set_pricing():
    section("14. Lever sets the price (no negotiation)")
    uid = str(uuid.uuid4())[:8]
    SVC = "pipe_leak_repair"

    cr = anon.post("/api/auth/register", json={
        "email": f"apc_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    mr = anon.post("/api/auth/register", json={
        "email": f"apm_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "plumbing", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    mech = Session(mr.json()["access_token"])

    # Client tries to set their own budget — the server must OVERRIDE it with
    # the app price snapshot.
    rq = client.post("/api/client/requests", json={
        "title": "Fuga con presupuesto propio",
        "description": "El cliente intenta fijar su propio precio.",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "service_key": SVC,
        "budget_min": 1.0, "budget_max": 2.0})
    check("Request created (201)", rq.status_code == 201, rq.text)
    body = rq.json()
    check("Server overrode client budget with app price",
          body.get("budget_max") is not None and body.get("budget_max") > 2.0,
          f"budget={body.get('budget_min')}-{body.get('budget_max')}")
    price_min, price_max = body["budget_min"], body["budget_max"]

    # Provider accepts, then tries to bill outside the app-set range.
    mech.post("/api/provider/go-online")
    acc = mech.post(f"/api/provider/board/{body['id']}/accept")
    check("Accept (201)", acc.status_code == 201, acc.text)
    job_id = acc.json()["id"]
    for s in ["diagnosing", "repairing"]:
        mech.patch(f"/api/provider/jobs/{job_id}/status", json={"status": s})

    over = mech.patch(f"/api/provider/jobs/{job_id}/status",
                      json={"status": "completed", "final_price": price_max + 500})
    check("Final price above app range rejected (400)",
          over.status_code == 400 and "FINAL_PRICE_OUT_OF_RANGE" in over.text, over.text)

    ok = mech.patch(f"/api/provider/jobs/{job_id}/status",
                    json={"status": "completed", "final_price": price_min})
    check("Final price within app range accepted (200)", ok.status_code == 200, ok.text)


def test_redispatch_on_go_online():
    section("15. Pending request offered when a provider comes ONLINE")
    uid = str(uuid.uuid4())[:8]
    cr = anon.post("/api/auth/register", json={
        "email": f"rdc_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    mr = anon.post("/api/auth/register", json={
        "email": f"rdm_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "plumbing", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    mech = Session(mr.json()["access_token"])

    # Request created while the provider is OFFLINE — previously this sat
    # silently on the board forever.
    rq = client.post("/api/client/requests", json={
        "title": "Fuga creada sin nadie en línea",
        "description": "Nadie estaba conectado cuando se creó esta solicitud.",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "service_key": "pipe_leak_repair"})
    check("Request created (201)", rq.status_code == 201, rq.text)
    req_id = rq.json()["id"]

    r0 = mech.get("/api/provider/offer")
    check("No offer while offline", r0.status_code == 200 and r0.json().get("offer") is None, r0.text)

    # Going online must trigger an immediate offer for the waiting request.
    go = mech.post("/api/provider/go-online")
    check("Go online (200)", go.status_code == 200, go.text)
    r1 = mech.get("/api/provider/offer")
    off = r1.json().get("offer") if r1.status_code == 200 else None
    # Queue is FIFO: on a shared/dirty DB an OLDER pending plumbing request may
    # be offered first — the behavior under test is that go-online produces an
    # offer at all (one at a time), not which request wins the queue.
    check("Pending request offered on go-online", bool(off), r1.text[:300])
    if off and off.get("request_id") != req_id:
        print(f"  {INFO} FIFO queue offered older pending request "
              f"#{off.get('request_id')} before ours (#{req_id})")
    check("Offer carries decision details (pay + window)",
          bool(off) and off.get("budget_max") is not None and off.get("window_seconds", 0) >= 60,
          str(off)[:200])


def test_one_at_a_time():
    section("16. One request / one job at a time")
    uid = str(uuid.uuid4())[:8]
    c1r = anon.post("/api/auth/register", json={
        "email": f"oaa_c1_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client1 = Session(c1r.json()["access_token"])
    c2r = anon.post("/api/auth/register", json={
        "email": f"oaa_c2_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client2 = Session(c2r.json()["access_token"])
    mr = anon.post("/api/auth/register", json={
        "email": f"oaa_m_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "painting", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    mech = Session(mr.json()["access_token"])
    mech.post("/api/provider/go-online")

    def make_request(sess, title):
        return sess.post("/api/client/requests", json={
            "title": title, "description": "Prueba de una solicitud a la vez.",
            "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
            "country_code": "EC", "urgency": "immediate", "profession_type": "painting"})

    # Client: only ONE active request allowed
    ra = make_request(client1, "Pintar sala — solicitud A")
    check("Client creates request A (201)", ra.status_code == 201, ra.text)
    req_a = ra.json()["id"]
    rb = make_request(client1, "Pintar cocina — bloqueada")
    check("Second active request blocked (409 ACTIVE_REQUEST_EXISTS)",
          rb.status_code == 409 and "ACTIVE_REQUEST_EXISTS" in rb.text, rb.text)

    # A different client is unaffected
    rc = make_request(client2, "Pintar dormitorio — solicitud B")
    check("Other client can still create (201)", rc.status_code == 201, rc.text)
    req_b = rc.json()["id"]

    # Provider: only ONE unfinished job allowed
    acc = mech.post(f"/api/provider/board/{req_a}/accept")
    check("Provider accepts job A (201)", acc.status_code == 201, acc.text)
    job_a = acc.json()["id"]
    acc2 = mech.post(f"/api/provider/board/{req_b}/accept")
    check("Second accept blocked (409 ACTIVE_JOB_EXISTS)",
          acc2.status_code == 409 and "ACTIVE_JOB_EXISTS" in acc2.text, acc2.text)

    # Finish job A: en_route → prepping (start) → completed
    s1 = mech.patch(f"/api/provider/jobs/{job_a}/status", json={"status": "prepping"})
    check("Start work (200)", s1.status_code == 200, s1.text)
    s2 = mech.patch(f"/api/provider/jobs/{job_a}/status", json={"status": "completed"})
    check("Complete job (200)", s2.status_code == 200, s2.text)

    # Both sides unblock the moment the job is done
    rd = make_request(client1, "Pintar sala — nueva tras completar")
    check("Client can request again after completion (201)", rd.status_code == 201, rd.text)
    off = mech.get("/api/provider/offer").json().get("offer")
    check("Freed-up provider is offered pending work again", bool(off), str(off)[:200])


def _wait_offer(sess, want_request_id=None, tries=12, delay=0.5):
    """Poll GET /offer briefly — dispatch on creation is scheduled onto the
    server's event loop, so the offer appears a beat after the 201."""
    import time
    for _ in range(tries):
        r = sess.get("/api/provider/offer")
        off = r.json().get("offer") if r.status_code == 200 else None
        if off and (want_request_id is None or off.get("request_id") == want_request_id):
            return off
        time.sleep(delay)
    return None


def _offer_of(sess, req_id):
    """This provider's live offer, only if it's for req_id."""
    o = sess.get("/api/provider/offer").json().get("offer")
    return o if (o and o.get("request_id") == req_id) else None


def _shed_stale_offers(sess, tries=6):
    """Dirty shared DB: pending requests left behind by older runs can hand a
    provider an offer the moment they go online. Decline them (the decline
    cooldown stops immediate re-offers) until the slate is clean — call this
    BEFORE creating the request the test actually cares about."""
    import time
    for _ in range(tries):
        o = sess.get("/api/provider/offer").json().get("offer")
        if not o:
            return
        sess.post("/api/provider/offer/decline")
        time.sleep(0.3)


def test_dispatch_lifecycle():
    section("17. Dispatch lifecycle: offer on creation, decline rotation")
    # Uses the "events" profession — no seed data and no other test touches it,
    # so the fresh pair below are the only candidates (dispatch is rating-first,
    # and a leftover same-profession provider would win the first offer).
    uid = str(uuid.uuid4())[:8]
    p1r = anon.post("/api/auth/register", json={
        "email": f"dl_p1_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "events", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    p1 = Session(p1r.json()["access_token"])
    p2r = anon.post("/api/auth/register", json={
        "email": f"dl_p2_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "events", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    p2 = Session(p2r.json()["access_token"])
    p1.post("/api/provider/go-online")
    p2.post("/api/provider/go-online")
    _shed_stale_offers(p1)
    _shed_stale_offers(p2)

    cr = anon.post("/api/auth/register", json={
        "email": f"dl_c_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    rq = client.post("/api/client/requests", json={
        "title": "Meseros para evento familiar",
        "description": "Necesito dos meseros para un evento familiar el fin de semana.",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "profession_type": "events"})
    check("Request created (201)", rq.status_code == 201, rq.text)
    req_id = rq.json()["id"]

    # Dispatch must fire on CREATION (not only on go-online) — this was the
    # threadpool/event-loop bug: the offer never existed at all. WHICH of the
    # two gets it first can vary on a dirty DB, so assert the MECHANICS:
    # exactly one holds the live offer, and declining hands it to the other.
    import time
    first = second = None
    for _ in range(12):
        o1, o2 = _offer_of(p1, req_id), _offer_of(p2, req_id)
        if o1 or o2:
            first, second = (p1, p2) if o1 else (p2, p1)
            check("Only ONE provider holds the live offer", not (o1 and o2),
                  f"p1={bool(o1)} p2={bool(o2)}")
            break
        time.sleep(0.5)
    check("Offer created on request creation reaches a provider", first is not None,
          "no offer within 6s")
    if first is None:
        return

    # Decline advances the queue immediately — and must return 200, not 500.
    _shed_stale_offers(second)   # second must be FREE to receive the rotation
    dec = first.post("/api/provider/offer/decline")
    check("Decline returns 200", dec.status_code == 200, dec.text)
    check("Decliner's offer is gone", _offer_of(first, req_id) is None, "")
    off2 = _wait_offer(second, req_id)
    check("Offer rotates to the other provider after decline", bool(off2), str(off2))

    acc = second.post(f"/api/provider/board/{req_id}/accept")
    check("Second provider accepts (201)", acc.status_code == 201, acc.text)

    # Leave nothing behind that could steal the first offer on a future run.
    p1.post("/api/provider/go-offline")
    p2.post("/api/provider/go-offline")


def test_client_cancel_releases_provider():
    section("18. Client cancellation frees the professional + notifies them")
    uid = str(uuid.uuid4())[:8]
    pr = anon.post("/api/auth/register", json={
        "email": f"cc_p_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "beauty", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    prov = Session(pr.json()["access_token"])
    prov.post("/api/provider/go-online")
    _shed_stale_offers(prov)
    cr = anon.post("/api/auth/register", json={
        "email": f"cc_c_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])

    def make(title):
        return client.post("/api/client/requests", json={
            "title": title, "description": "Corte de cabello a domicilio, por favor.",
            "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
            "country_code": "EC", "urgency": "immediate", "profession_type": "beauty"})

    # Cancel while the offer is LIVE → offer disappears + provider notified.
    r1 = make("Corte a domicilio — se cancelará")
    check("Request 1 created (201)", r1.status_code == 201, r1.text)
    off = _wait_offer(prov, r1.json()["id"])
    check("Provider holds the live offer", bool(off), str(off))
    cx = client.delete(f"/api/client/requests/{r1.json()['id']}")
    check("Client cancels pending request (200)", cx.status_code == 200, cx.text)
    off_after = prov.get("/api/provider/offer").json().get("offer")
    check("Cancelled request's offer is withdrawn",
          not (off_after and off_after.get("request_id") == r1.json()["id"]), str(off_after))
    notifs = prov.get("/api/notifications").json()
    check("Provider notified of the cancellation",
          any(n.get("title") == "Solicitud cancelada" for n in notifs), str(notifs)[:300])

    # Cancel an ASSIGNED request → the job cancels and the professional is
    # free to take new work (one-job-at-a-time must not wedge them).
    r2 = make("Corte a domicilio — asignado y cancelado")
    check("Request 2 created after cancelling 1 (201)", r2.status_code == 201, r2.text)
    acc = prov.post(f"/api/provider/board/{r2.json()['id']}/accept")
    check("Provider accepts (201)", acc.status_code == 201, acc.text)
    job_id = acc.json()["id"]
    cx2 = client.delete(f"/api/client/requests/{r2.json()['id']}")
    check("Client cancels assigned request (200)", cx2.status_code == 200, cx2.text)
    jb = prov.get(f"/api/provider/jobs/{job_id}")
    check("Job is cancelled with the request",
          jb.status_code == 200 and jb.json().get("status") == "cancelled", jb.text[:200])
    notifs2 = prov.get("/api/notifications").json()
    check("Provider told the client cancelled the job",
          any(n.get("title") == "Trabajo cancelado por el cliente" for n in notifs2), str(notifs2)[:300])

    r3 = make("Corte a domicilio — tras liberarse")
    check("Client can request again (201)", r3.status_code == 201, r3.text)
    acc3 = prov.post(f"/api/provider/board/{r3.json()['id']}/accept")
    check("Freed provider can accept again — not wedged (201)", acc3.status_code == 201, acc3.text)
    prov.post("/api/provider/go-offline")   # keep future runs deterministic


def test_worker_set_pricing():
    section("19. Worker-set pricing: own rate, quoted total, enforcement")
    uid = str(uuid.uuid4())[:8]
    pr = anon.post("/api/auth/register", json={
        "email": f"wsp_p_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "moving", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    prov = Session(pr.json()["access_token"])

    bad = prov.patch("/api/provider/profile", json={"hourly_rate": 2})
    check("Rate below the honesty floor rejected (400)",
          bad.status_code == 400 and "HOURLY_RATE_OUT_OF_RANGE" in bad.text, bad.text)
    bad2 = prov.patch("/api/provider/profile", json={"hourly_rate": 500})
    check("Absurd rate rejected (400)", bad2.status_code == 400, bad2.text)
    ok = prov.patch("/api/provider/profile", json={"hourly_rate": 12})
    check("Valid rate saved (200)", ok.status_code == 200 and ok.json().get("hourly_rate") == 12, ok.text)
    prov.post("/api/provider/go-online")
    _shed_stale_offers(prov)

    cr = anon.post("/api/auth/register", json={
        "email": f"wsp_c_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    rq = client.post("/api/client/requests", json={
        "title": "Mudanza pequeña de estudio",
        "description": "Pocas cajas y un escritorio para mudar dentro de la ciudad.",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "service_key": "small_move"})
    check("Request created (201)", rq.status_code == 201, rq.text)
    req_id = rq.json()["id"]

    # small_move = 120–360 min; rate 12/h → quote 24–72 (the popup's pay)
    off = _wait_offer(prov, req_id)
    check("Offer carries the provider's OWN quote + rate",
          bool(off) and off.get("hourly_rate") == 12 and off.get("quote_max") is not None,
          str(off)[:250])
    check("Quote = rate × duration (24–72)",
          bool(off) and off.get("quote_min") == 24 and off.get("quote_max") == 72,
          f"{(off or {}).get('quote_min')}–{(off or {}).get('quote_max')}")

    acc = prov.post(f"/api/provider/board/{req_id}/accept")
    check("Accept snapshots the quote onto the job",
          acc.status_code == 201 and acc.json().get("quoted_min") == 24
          and acc.json().get("quoted_max") == 72, acc.text[:300])
    job_id = acc.json()["id"]

    det = client.get(f"/api/client/requests/{req_id}").json()
    check("Client sees the professional's rate + track record",
          det.get("professional_hourly_rate") == 12 and det.get("professional_jobs") is not None,
          str({k: det.get(k) for k in ("professional_hourly_rate", "professional_jobs")}))

    s1 = prov.patch(f"/api/provider/jobs/{job_id}/status", json={"status": "working"})
    check("Start work (200)", s1.status_code == 200, s1.text)
    over = prov.patch(f"/api/provider/jobs/{job_id}/status",
                      json={"status": "completed", "final_price": 100.0})
    check("Final price above the quote rejected (400)",
          over.status_code == 400 and "FINAL_PRICE_OUT_OF_RANGE" in over.text, over.text)
    done = prov.patch(f"/api/provider/jobs/{job_id}/status",
                      json={"status": "completed", "final_price": 50.0})
    check("Final price inside the quote accepted (200)",
          done.status_code == 200 and done.json().get("final_price") == 50.0, done.text[:200])

    prov.post("/api/provider/go-offline")   # keep future runs deterministic


def test_choose_professional():
    section("20. Client chooses a professional (Phase 2)")
    uid = str(uuid.uuid4())[:8]
    # Two business_support providers with different rates.
    p1r = anon.post("/api/auth/register", json={
        "email": f"ch_p1_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "business_support", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    p1 = Session(p1r.json()["access_token"])
    p1_id = p1r.json()["user_id"]
    p2r = anon.post("/api/auth/register", json={
        "email": f"ch_p2_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "business_support", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    p2 = Session(p2r.json()["access_token"])
    p2_id = p2r.json()["user_id"]
    p1.patch("/api/provider/profile", json={"hourly_rate": 8})
    p2.patch("/api/provider/profile", json={"hourly_rate": 15})
    p1.post("/api/provider/go-online"); _shed_stale_offers(p1)
    p2.post("/api/provider/go-online"); _shed_stale_offers(p2)

    cr = anon.post("/api/auth/register", json={
        "email": f"ch_c_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])

    # Browse: both cards with their OWN rates/quotes + trust fields.
    # (Pick a business_support service straight from the live catalog.)
    cat = anon.get("/api/catalog").json().get("services", [])
    bs = [s for s in cat if s.get("category") == "business_support" and s.get("estimate_min") is not None]
    check("Catalog has business_support services", len(bs) > 0, str(len(bs)))
    if not bs:
        return
    svc_key = bs[0]["key"]
    r = client.get(f"/api/client/providers/for-service?service_key={svc_key}")
    check("Browse endpoint returns providers (200)", r.status_code == 200, r.text[:200])
    cards = {c["user_id"]: c for c in r.json().get("providers", [])}
    check("Both fresh providers are listed", p1_id in cards and p2_id in cards,
          str(list(cards.keys()))[:120])
    c2 = cards.get(p2_id) or {}
    check("Card carries own rate, quote and trust fields",
          c2.get("hourly_rate") == 15 and c2.get("quote_max") is not None
          and "total_jobs" in c2 and "verified" in c2, str(c2)[:250])
    check("Reference range included for honesty anchor",
          r.json().get("reference_max") is not None, r.text[:150])

    # Hire p2 directly — the offer must reach ONLY p2, flagged as direct.
    rq = client.post("/api/client/requests", json={
        "title": "Trámite bancario urgente",
        "description": "Necesito ayuda con un trámite en el centro de la ciudad.",
        "location": "Centro, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "service_key": svc_key,
        "preferred_provider_id": p2_id})
    check("Direct request created (201)", rq.status_code == 201, rq.text)
    req_id = rq.json()["id"]
    off2 = _wait_offer(p2, req_id)
    check("Chosen professional receives the offer, marked direct",
          bool(off2) and off2.get("direct") is True, str(off2)[:250])
    check("The OTHER professional gets nothing", _offer_of(p1, req_id) is None, "")

    # Nobody else can snipe it from the board either.
    snipe = p1.post(f"/api/provider/board/{req_id}/accept")
    check("Other professional blocked from accepting (403)",
          snipe.status_code == 403 and "RESERVED_FOR_CHOSEN_PROVIDER" in snipe.text, snipe.text)
    board1 = p1.get("/api/provider/board")
    check("Reserved request hidden from other boards",
          req_id not in [x["id"] for x in board1.json()], str([x["id"] for x in board1.json()])[:120])

    # Chosen pro declines → client can BROADCAST to everyone; p1 gets it.
    dec = p2.post("/api/provider/offer/decline")
    check("Chosen professional declines (200)", dec.status_code == 200, dec.text)
    check("Not offered to others while still reserved", _offer_of(p1, req_id) is None, "")
    bc = client.post(f"/api/client/requests/{req_id}/broadcast")
    check("Broadcast fallback (200)", bc.status_code == 200, bc.text)
    off1 = _wait_offer(p1, req_id)
    check("After broadcast the other professional is offered", bool(off1), str(off1)[:200])
    acc = p1.post(f"/api/provider/board/{req_id}/accept")
    check("Accept after broadcast (201)", acc.status_code == 201, acc.text)

    p1.post("/api/provider/go-offline")
    p2.post("/api/provider/go-offline")


def test_hourly_metering():
    section("21. Metered hourly billing + overtime approvals (Phase 3)")
    uid = str(uuid.uuid4())[:8]
    pr = anon.post("/api/auth/register", json={
        "email": f"hm_p_{uid}@test.com", "password": "Mech1234!", "role": "mechanic",
        "profession": "moving", "accepted_terms": True, "date_of_birth": ADULT_DOB})
    prov = Session(pr.json()["access_token"])
    prov.patch("/api/provider/profile", json={"hourly_rate": 12})
    prov.post("/api/provider/go-online")
    _shed_stale_offers(prov)
    cr = anon.post("/api/auth/register", json={
        "email": f"hm_c_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])

    rq = client.post("/api/client/requests", json={
        "title": "Mudanza medida por horas",
        "description": "Cajas y muebles pequeños, cobro medido por tiempo.",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas",
        "country_code": "EC", "urgency": "immediate", "service_key": "small_move"})
    check("Request created (201)", rq.status_code == 201, rq.text)
    req_id = rq.json()["id"]
    acc = prov.post(f"/api/provider/board/{req_id}/accept")
    check("Accept snapshots the RATE for metered billing",
          acc.status_code == 201 and acc.json().get("hourly_rate_snapshot") == 12, acc.text[:250])
    job_id = acc.json()["id"]

    # Start-confirmation only makes sense once the clock is running.
    early = client.post(f"/api/client/jobs/{job_id}/confirm-start")
    check("Confirm-start before work starts rejected (400)", early.status_code == 400, early.text)
    s1 = prov.patch(f"/api/provider/jobs/{job_id}/status", json={"status": "working"})
    check("Start work — the app clock starts (200)",
          s1.status_code == 200 and s1.json().get("started_at") is not None, s1.text[:200])
    cs = client.post(f"/api/client/jobs/{job_id}/confirm-start")
    check("Client countersigns the start (200)", cs.status_code == 200, cs.text)
    cs2 = client.post(f"/api/client/jobs/{job_id}/confirm-start")
    check("Duplicate start confirmation rejected (409)", cs2.status_code == 409, cs2.text)

    # Overtime: pro asks, ONLY the client's approval raises the cap.
    badmin = prov.post(f"/api/provider/jobs/{job_id}/request-extra-time", json={"minutes": 45})
    check("Non-standard extra-time amount rejected (422)", badmin.status_code == 422, badmin.text)
    xt = prov.post(f"/api/provider/jobs/{job_id}/request-extra-time", json={"minutes": 60})
    check("Extra-time request recorded (200)",
          xt.status_code == 200 and xt.json().get("extra_minutes_requested") == 60, xt.text[:200])
    dup = prov.post(f"/api/provider/jobs/{job_id}/request-extra-time", json={"minutes": 30})
    check("Second request while pending rejected (409)", dup.status_code == 409, dup.text)
    deny = client.post(f"/api/client/jobs/{job_id}/extra-time", json={"approve": False})
    check("Client can DENY — nothing extra bills",
          deny.status_code == 200 and deny.json().get("extra_minutes_approved") == 0, deny.text)
    xt2 = prov.post(f"/api/provider/jobs/{job_id}/request-extra-time", json={"minutes": 60})
    check("Pro can ask again after a denial (200)", xt2.status_code == 200, xt2.text[:150])
    ok = client.post(f"/api/client/jobs/{job_id}/extra-time", json={"approve": True})
    check("Approval raises the authorized time",
          ok.status_code == 200 and ok.json().get("extra_minutes_approved") == 60, ok.text)

    # Billing: cap = quote_max 72 + 1h × 12 = 84; floor = quote_min 24.
    over = prov.patch(f"/api/provider/jobs/{job_id}/status",
                      json={"status": "completed", "final_price": 100.0})
    check("Price above the raised cap still rejected (400)",
          over.status_code == 400 and "FINAL_PRICE_OUT_OF_RANGE" in over.text, over.text)
    done = prov.patch(f"/api/provider/jobs/{job_id}/status", json={"status": "completed"})
    body = done.json() if done.status_code == 200 else {}
    check("No price sent → the METER is the price (200)", done.status_code == 200, done.text[:250])
    check("Seconds of work billed at the call-out floor (quoted_min 24)",
          body.get("final_price") == 24 and body.get("billed_minutes") is not None,
          f"final_price={body.get('final_price')} billed_minutes={body.get('billed_minutes')}")

    det = client.get(f"/api/client/requests/{req_id}").json()
    check("Client sees the metered result",
          (det.get("job") or {}).get("final_price") == 24
          and (det.get("job") or {}).get("hourly_rate_snapshot") == 12, str(det.get("job"))[:250])

    prov.post("/api/provider/go-offline")


def test_admin_operations():
    section("22. Admin operations health view")
    admin = login("admin@lever.app", "Admin123!")
    r = admin.get("/api/admin/operations")
    check("Operations endpoint (200)", r.status_code == 200, r.text[:200])
    body = r.json() if r.status_code == 200 else {}
    check("Has counts + all four lists",
          "counts" in body and all(k in body for k in
          ("stuck_requests", "overdue_arrivals", "awaiting_confirmation", "stale_offers")),
          str(body.get("counts")))
    check("Exposes the auto-confirm window",
          isinstance(body.get("auto_confirm_hours"), int), str(body.get("auto_confirm_hours")))

    uid = str(uuid.uuid4())[:8]
    cr = anon.post("/api/auth/register", json={
        "email": f"ao_c_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    rd = client.get("/api/admin/operations")
    check("Non-admin denied (403)", rd.status_code == 403, rd.text[:120])


def test_device_registration():
    section("23. Push device registration")
    uid = str(uuid.uuid4())[:8]
    cr = anon.post("/api/auth/register", json={
        "email": f"dev_{uid}@test.com", "password": "Client123!", "role": "client",
        "accepted_terms": True, "date_of_birth": ADULT_DOB})
    client = Session(cr.json()["access_token"])
    tok = f"fake-fcm-token-{uid}-abcdefghijkl"

    r = client.post("/api/devices/register", json={"token": tok, "platform": "android"})
    check("Register device (200)", r.status_code == 200, r.text)
    r2 = client.post("/api/devices/register", json={"token": tok, "platform": "android"})
    check("Re-register same token is idempotent (200)", r2.status_code == 200, r2.text)
    short = client.post("/api/devices/register", json={"token": "x", "platform": "android"})
    check("Too-short token rejected (422)", short.status_code == 422, short.text)
    badp = client.post("/api/devices/register", json={"token": tok, "platform": "nintendo"})
    check("Bad platform rejected (422)", badp.status_code == 422, badp.text)
    un = client.post("/api/devices/unregister", json={"token": tok})
    check("Unregister device (200)", un.status_code == 200, un.text)
    anon_r = anon.post("/api/devices/register", json={"token": tok, "platform": "android"})
    check("Unauthenticated registration denied (401)", anon_r.status_code == 401, anon_r.text)


if __name__ == "__main__":
    run_all()


# ──────────────────────────────────────────────
# pytest compatibility
# ──────────────────────────────────────────────

def test_pytest_health():     test_server_health()
def test_pytest_auth():       test_auth()
def test_pytest_flow():       test_full_orchestration()
def test_pytest_client():     test_client_flows()
def test_pytest_mechanic():   test_mechanic_flows()
def test_pytest_admin():      test_admin_flows()
def test_pytest_isolation():  test_message_isolation()
def test_pytest_guayaquil():  test_guayaquil_market()
def test_pytest_customer_ratings(): test_customer_ratings()
def test_pytest_email_ci():   test_email_case_insensitive()
def test_pytest_minimum_age(): test_minimum_age()
def test_pytest_multi_profession(): test_multi_profession_matching()
def test_pytest_pricing(): test_pricing_estimates()
def test_pytest_app_set_pricing(): test_app_set_pricing()
def test_pytest_redispatch(): test_redispatch_on_go_online()
def test_pytest_one_at_a_time(): test_one_at_a_time()
def test_pytest_dispatch_lifecycle(): test_dispatch_lifecycle()
def test_pytest_cancel_releases(): test_client_cancel_releases_provider()
def test_pytest_worker_set_pricing(): test_worker_set_pricing()
def test_pytest_choose_professional(): test_choose_professional()
def test_pytest_hourly_metering(): test_hourly_metering()
def test_pytest_admin_operations(): test_admin_operations()
def test_pytest_device_registration(): test_device_registration()
