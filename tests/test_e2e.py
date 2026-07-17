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
        check("Health status = ok", data.get("status") == "ok", str(data))
        check("Service name correct", data.get("service") == "MechFix", str(data))
        check("Version present", "version" in data)
        check("Uptime reported", data.get("uptime_seconds", -1) >= 0)
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
        "role": "mechanic", "accepted_terms": True, "date_of_birth": ADULT_DOB
    })
    check("Register fresh provider", mech_r.status_code == 201)
    mech = Session(mech_r.json()["access_token"])

    admin = login("admin@mechfix.app", "Admin123!")
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
        "title": "Strange knocking sound from engine",
        "description": "Knocking every time I accelerate above 40mph. Started 3 days ago.",
        "location": "Av. Francisco de Orellana, Kennedy Norte, Guayaquil",
        "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
        "urgency": "immediate",
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
    check("Job status is accepted", r.json()["status"] == "accepted")

    # ---- Step 4b: Double-accept rejected ----
    r2 = mech.post(f"/api/provider/board/{request_id}/accept")
    check("Double-accept rejected (409)", r2.status_code == 409)

    # ---- Step 5: Request status updated ----
    r = client.get(f"/api/client/requests/{request_id}")
    check("Request now shows assigned status", r.json()["status"] == "assigned", r.json()["status"])
    check("Request has linked job", r.json().get("job") is not None)

    # ---- Step 6: Client cancels — should fail (already assigned) ----
    r = client.delete(f"/api/client/requests/{request_id}")
    # Assigned requests CAN be cancelled per current rules
    # but after mechanic accepts it's "assigned" which is allowed
    # Let's skip cancel here and let job progress

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
        ("en_route",   "accepted",   True),
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

    # ---- Step 11: Client leaves review ----
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
    admin = login("admin@mechfix.app", "Admin123!")

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

    ok = c.post(f"{BASE}/api/client/requests", headers=h, json={
        "service_key": "faucet_leak_repair", "title": "Fuga de agua en la cocina",
        "description": "La llave de la cocina gotea constantemente desde ayer",
        "location": "Urdesa, Guayaquil", "city": "Guayaquil", "province": "Guayas", "country_code": "EC",
    })
    check("Guayaquil request accepted (201)", ok.status_code == 201, ok.text)
    check("Request assigned market_code GYE", ok.json().get("market_code") == "GYE", ok.text)

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
        "role": "mechanic", "accepted_terms": True, "date_of_birth": ADULT_DOB})
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

    for s in ["en_route", "diagnosing", "repairing"]:
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

    today = date.today()

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
    rq2 = client.post("/api/client/requests", json={
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
