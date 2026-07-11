"""Lever — Multi-profession demo data seeder.

Run:  python seed.py
Re-seed: python seed.py --reset   (drops & recreates tables first)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from database import Base, SessionLocal, engine
from models import (
    ClientProfile, Dispute, Job, MechanicProfile,
    Message, Review, ServiceRequest, User, Vehicle,
)
from auth import hash_password


# ---------------------------------------------------------------------------
# Austin, TX area coordinates for realistic demo data
# ---------------------------------------------------------------------------
# North Austin:   ~30.38, -97.72
# South Austin:   ~30.22, -97.77
# East Austin:    ~30.26, -97.71
# West Austin:    ~30.30, -97.80
# Central Austin: ~30.27, -97.74
# Downtown:       ~30.265, -97.745
# Round Rock:     ~30.51, -97.68
# Cedar Park:     ~30.50, -97.82

COORDS = {
    "north_austin":   (30.3850, -97.7190),
    "south_austin":   (30.2150, -97.7700),
    "east_austin":    (30.2620, -97.7080),
    "west_austin":    (30.3010, -97.8020),
    "central_austin": (30.2740, -97.7430),
    "downtown":       (30.2672, -97.7431),
    "123_main_st":    (30.2650, -97.7420),   # Alice
    "456_oak_ave":    (30.2560, -97.7240),   # Bob
    "789_pine_rd":    (30.2980, -97.7530),   # Carol
}


# ---------------------------------------------------------------------------
# Seed data — Clients
# ---------------------------------------------------------------------------

CLIENTS = [
    {
        "email": "alice@demo.com",
        "password": "Alice123!",
        "profile": {"full_name": "Alice Johnson", "phone": "555-0101", "address": "123 Main St, Austin, TX 78701"},
        "vehicles": [
            {"make": "Toyota", "model": "Camry", "year": 2019, "color": "Blue", "license_plate": "TXA-1234", "mileage": 45000},
            {"make": "Honda", "model": "CR-V", "year": 2021, "color": "White", "license_plate": "TXA-5678", "mileage": 18000},
        ],
    },
    {
        "email": "bob@demo.com",
        "password": "Bob12345!",
        "profile": {"full_name": "Bob Martinez", "phone": "555-0202", "address": "456 Oak Ave, Austin, TX 78702"},
        "vehicles": [
            {"make": "Ford", "model": "F-150", "year": 2018, "color": "Red", "license_plate": "TXB-9012", "mileage": 72000},
        ],
    },
    {
        "email": "carol@demo.com",
        "password": "Carol123!",
        "profile": {"full_name": "Carol Williams", "phone": "555-0303", "address": "789 Pine Rd, Austin, TX 78703"},
        "vehicles": [
            {"make": "BMW", "model": "3 Series", "year": 2020, "color": "Black", "license_plate": "TXC-3456", "mileage": 31000},
        ],
    },
]

# ---------------------------------------------------------------------------
# Seed data — Providers (all professions)
# ---------------------------------------------------------------------------

PROVIDERS = [
    # --- Mechanics ---
    {
        "email": "mike@demo.com", "password": "Mike1234!", "profession": "mechanic",
        "profile": {
            "full_name": "Mike Chen", "phone": "555-0401",
            "bio": "ASE-certified master technician with 12 years experience. Specialise in Asian imports and hybrid/EV systems.",
            "specialties": ["Engine Repair", "Hybrid/EV", "Brakes", "Diagnostics"],
            "years_experience": 12, "hourly_rate": 85.0, "is_available": True,
            "location": "North Austin, TX", "service_radius_miles": 30,
            "latitude": COORDS["north_austin"][0], "longitude": COORDS["north_austin"][1],
        },
    },
    {
        "email": "sarah@demo.com", "password": "Sarah123!", "profession": "mechanic",
        "profile": {
            "full_name": "Sarah Nguyen", "phone": "555-0402",
            "bio": "Mobile mechanic covering the greater Austin area. Quick turnaround on brake, suspension, and A/C jobs.",
            "specialties": ["Brakes", "Suspension", "A/C & Heating", "Oil Change"],
            "years_experience": 7, "hourly_rate": 70.0, "is_available": True,
            "location": "South Austin, TX", "service_radius_miles": 40,
            "latitude": COORDS["south_austin"][0], "longitude": COORDS["south_austin"][1],
        },
    },
    {
        "email": "james@demo.com", "password": "James123!", "profession": "mechanic",
        "profile": {
            "full_name": "James Okafor", "phone": "555-0403",
            "bio": "European car specialist — BMW, Mercedes, Audi. Factory-trained with access to OEM diagnostic tools.",
            "specialties": ["European Cars", "Transmission", "Engine Repair", "Electrical"],
            "years_experience": 15, "hourly_rate": 110.0, "is_available": True,
            "location": "Central Austin, TX", "service_radius_miles": 25,
            "latitude": COORDS["central_austin"][0], "longitude": COORDS["central_austin"][1],
        },
    },
    # --- HVAC ---
    {
        "email": "david@demo.com", "password": "David123!", "profession": "hvac",
        "profile": {
            "full_name": "David Park", "phone": "555-0501",
            "bio": "EPA-certified HVAC technician. 10+ years in residential and light commercial systems.",
            "specialties": ["AC Repair", "Heating Repair", "Thermostat Setup", "Duct Cleaning"],
            "years_experience": 10, "hourly_rate": 95.0, "is_available": True,
            "location": "East Austin, TX", "service_radius_miles": 35,
            "latitude": COORDS["east_austin"][0], "longitude": COORDS["east_austin"][1],
        },
    },
    {
        "email": "maria@demo.com", "password": "Maria123!", "profession": "hvac",
        "profile": {
            "full_name": "Maria Gonzalez", "phone": "555-0502",
            "bio": "Specializing in energy-efficient HVAC installations and heat pump systems.",
            "specialties": ["AC Installation", "Heat Pump", "Indoor Air Quality", "Emergency Repair"],
            "years_experience": 8, "hourly_rate": 90.0, "is_available": True,
            "location": "West Austin, TX", "service_radius_miles": 30,
            "latitude": COORDS["west_austin"][0], "longitude": COORDS["west_austin"][1],
        },
    },
    # --- Electricians ---
    {
        "email": "kevin@demo.com", "password": "Kevin123!", "profession": "electrician",
        "profile": {
            "full_name": "Kevin Brooks", "phone": "555-0601",
            "bio": "Licensed master electrician. Residential and commercial wiring, panel upgrades, and EV charger installs.",
            "specialties": ["Wiring & Rewiring", "Panel Upgrade", "EV Charger Install", "Troubleshooting"],
            "years_experience": 14, "hourly_rate": 100.0, "is_available": True,
            "location": "North Austin, TX", "service_radius_miles": 25,
            "latitude": 30.3920, "longitude": -97.7250,
        },
    },
    {
        "email": "lisa@demo.com", "password": "Lisa1234!", "profession": "electrician",
        "profile": {
            "full_name": "Lisa Tran", "phone": "555-0602",
            "bio": "Smart home and lighting specialist. Making homes safer and more efficient.",
            "specialties": ["Lighting", "Smart Home", "Outlet Installation", "Code Compliance"],
            "years_experience": 6, "hourly_rate": 80.0, "is_available": True,
            "location": "South Austin, TX", "service_radius_miles": 30,
            "latitude": 30.2200, "longitude": -97.7650,
        },
    },
    # --- Construction ---
    {
        "email": "carlos@demo.com", "password": "Carlos12!", "profession": "construction",
        "profile": {
            "full_name": "Carlos Rivera", "phone": "555-0701",
            "bio": "Licensed general contractor. Kitchen and bathroom remodels, decks, and full home renovations.",
            "specialties": ["General Contracting", "Kitchen Remodel", "Bathroom Remodel", "Deck & Patio"],
            "years_experience": 18, "hourly_rate": 120.0, "is_available": True,
            "location": "Central Austin, TX", "service_radius_miles": 20,
            "latitude": 30.2800, "longitude": -97.7500,
        },
    },
    {
        "email": "tom@demo.com", "password": "Tom12345!", "profession": "construction",
        "profile": {
            "full_name": "Tom Anderson", "phone": "555-0702",
            "bio": "Framing, drywall, and painting specialist. Fast turnaround on interior projects.",
            "specialties": ["Framing", "Drywall", "Painting", "Flooring"],
            "years_experience": 9, "hourly_rate": 75.0, "is_available": True,
            "location": "East Austin, TX", "service_radius_miles": 35,
            "latitude": 30.2580, "longitude": -97.7020,
        },
    },
    # --- Car Wash ---
    {
        "email": "jasmine@demo.com", "password": "Jazz1234!", "profession": "carwash",
        "profile": {
            "full_name": "Jasmine Lee", "phone": "555-0801",
            "bio": "Professional mobile detailer. Ceramic coatings, paint correction, and full interior details.",
            "specialties": ["Full Detail", "Ceramic Coating", "Paint Correction", "Interior Cleaning"],
            "years_experience": 5, "hourly_rate": 65.0, "is_available": True,
            "location": "South Austin, TX", "service_radius_miles": 40,
            "latitude": 30.2100, "longitude": -97.7800,
        },
    },
    {
        "email": "marcus@demo.com", "password": "Marcus12!", "profession": "carwash",
        "profile": {
            "full_name": "Marcus Johnson", "phone": "555-0802",
            "bio": "Fleet washing and mobile car wash expert. Eco-friendly products and waterless wash options.",
            "specialties": ["Exterior Wash", "Fleet Washing", "Mobile Detailing", "Odor Removal"],
            "years_experience": 4, "hourly_rate": 55.0, "is_available": True,
            "location": "North Austin, TX", "service_radius_miles": 35,
            "latitude": 30.3780, "longitude": -97.7300,
        },
    },
]


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------

def seed(db):
    print("Seeding clients...")

    client_objs = []
    for c in CLIENTS:
        user = User(email=c["email"], password_hash=hash_password(c["password"]), role="client", email_verified=True)
        db.add(user)
        db.flush()
        db.add(ClientProfile(user_id=user.id, **c["profile"]))
        for v in c.get("vehicles", []):
            db.add(Vehicle(client_id=user.id, **v))
        client_objs.append(user)
        db.flush()

    print("Seeding providers (all professions)...")

    provider_objs = []
    for p in PROVIDERS:
        user = User(email=p["email"], password_hash=hash_password(p["password"]), role="mechanic", email_verified=True)
        db.add(user)
        db.flush()
        db.add(MechanicProfile(user_id=user.id, profession=p["profession"], **p["profile"]))
        provider_objs.append(user)
        db.flush()

    db.commit()

    # Re-query
    clients = [db.query(User).filter(User.email == c["email"]).first() for c in CLIENTS]
    alice_car = db.query(Vehicle).filter(Vehicle.client_id == clients[0].id).first()
    bob_truck = db.query(Vehicle).filter(Vehicle.client_id == clients[1].id).first()
    carol_bmw = db.query(Vehicle).filter(Vehicle.client_id == clients[2].id).first()

    providers_by_email = {p.email: p for p in [db.query(User).filter(User.email == pr["email"]).first() for pr in PROVIDERS]}

    print("Seeding service requests & jobs...")

    # --- COMPLETED MECHANIC JOB: Alice -> Mike ---
    sr1 = ServiceRequest(
        client_id=clients[0].id, vehicle_id=alice_car.id, profession_type="mechanic",
        title="Engine oil change + brake inspection",
        description="Due for 45k service. Check brake pads while you are at it.",
        location="123 Main St, Austin, TX", urgency="scheduled",
        scheduled_date=datetime.utcnow() - timedelta(days=14),
        budget_min=80.0, budget_max=150.0, status="completed",
        latitude=COORDS["123_main_st"][0], longitude=COORDS["123_main_st"][1],
    )
    db.add(sr1); db.flush()

    job1 = Job(
        request_id=sr1.id, mechanic_id=providers_by_email["mike@demo.com"].id,
        status="completed",
        mechanic_notes="Changed oil (5W-30 synthetic), replaced front brake pads. Rear pads at 40%.",
        final_price=135.0,
        started_at=datetime.utcnow() - timedelta(days=14, hours=2),
        completed_at=datetime.utcnow() - timedelta(days=14),
    )
    db.add(job1); db.flush()
    db.add(Message(job_id=job1.id, sender_id=clients[0].id, content="Hi Mike! Will you be able to check the rotors too?", is_read=True))
    db.add(Message(job_id=job1.id, sender_id=providers_by_email["mike@demo.com"].id, content="Absolutely, I'll do a full brake system inspection.", is_read=True))
    db.add(Review(job_id=job1.id, client_id=clients[0].id, mechanic_id=providers_by_email["mike@demo.com"].id, rating=5, comment="Mike was punctual, professional, and very thorough!"))

    mike_profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == providers_by_email["mike@demo.com"].id).first()
    mike_profile.total_jobs = 1; mike_profile.avg_rating = 5.0

    # --- ACTIVE MECHANIC JOB: Bob -> Sarah ---
    sr2 = ServiceRequest(
        client_id=clients[1].id, vehicle_id=bob_truck.id, profession_type="mechanic",
        title="Brake pads squealing - urgent fix needed",
        description="F-150 has a high-pitched squeal from the front left wheel when braking.",
        location="456 Oak Ave, Austin, TX", urgency="immediate",
        budget_min=150.0, budget_max=300.0, status="in_progress",
        latitude=COORDS["456_oak_ave"][0], longitude=COORDS["456_oak_ave"][1],
    )
    db.add(sr2); db.flush()
    job2 = Job(
        request_id=sr2.id, mechanic_id=providers_by_email["sarah@demo.com"].id,
        status="repairing", mechanic_notes="Front left caliper slightly seized. Replacing pads + caliper.",
        started_at=datetime.utcnow() - timedelta(hours=2),
    )
    db.add(job2); db.flush()
    db.add(Message(job_id=job2.id, sender_id=providers_by_email["sarah@demo.com"].id, content="On my way! ETA ~20 minutes."))
    db.add(Message(job_id=job2.id, sender_id=clients[1].id, content="Great, I'll leave the gate open for you."))

    # --- PENDING MECHANIC REQUEST: Carol ---
    db.add(ServiceRequest(
        client_id=clients[2].id, vehicle_id=carol_bmw.id, profession_type="mechanic",
        title="BMW 3 Series - check engine light + transmission jerk",
        description="CEL came on yesterday (code P0420). Jerk when shifting 2nd to 3rd. Need BMW specialist.",
        location="789 Pine Rd, Austin, TX", urgency="scheduled",
        scheduled_date=datetime.utcnow() + timedelta(days=2),
        budget_min=200.0, budget_max=800.0, status="pending",
        latitude=COORDS["789_pine_rd"][0], longitude=COORDS["789_pine_rd"][1],
    ))

    # --- PENDING HVAC REQUEST ---
    db.add(ServiceRequest(
        client_id=clients[0].id, profession_type="hvac",
        title="AC not cooling - blowing warm air",
        description="Central AC unit is running but blowing warm air. Thermostat set to 72 but house is at 82. Unit is 8 years old.",
        location="123 Main St, Austin, TX", urgency="immediate",
        budget_min=100.0, budget_max=500.0, status="pending",
        latitude=COORDS["123_main_st"][0], longitude=COORDS["123_main_st"][1],
    ))

    # --- PENDING ELECTRICIAN REQUEST ---
    db.add(ServiceRequest(
        client_id=clients[1].id, profession_type="electrician",
        title="Panel upgrade needed - breakers tripping",
        description="Main breaker keeps tripping when running AC and dryer at the same time. House built in 1985 with 100A panel.",
        location="456 Oak Ave, Austin, TX", urgency="scheduled",
        scheduled_date=datetime.utcnow() + timedelta(days=5),
        budget_min=1500.0, budget_max=3000.0, status="pending",
        latitude=COORDS["456_oak_ave"][0], longitude=COORDS["456_oak_ave"][1],
    ))

    # --- PENDING CONSTRUCTION REQUEST ---
    db.add(ServiceRequest(
        client_id=clients[2].id, profession_type="construction",
        title="Kitchen remodel - countertops and cabinets",
        description="Want to replace laminate countertops with quartz and reface existing cabinets. Kitchen is 12x14.",
        location="789 Pine Rd, Austin, TX", urgency="scheduled",
        scheduled_date=datetime.utcnow() + timedelta(days=10),
        budget_min=5000.0, budget_max=12000.0, status="pending",
        latitude=COORDS["789_pine_rd"][0], longitude=COORDS["789_pine_rd"][1],
    ))

    # --- PENDING CAR WASH REQUEST ---
    db.add(ServiceRequest(
        client_id=clients[0].id, vehicle_id=alice_car.id, profession_type="carwash",
        title="Full detail - interior and exterior",
        description="Toyota Camry needs a full detail. Dog hair in the back seat, some minor scratches on the hood.",
        location="123 Main St, Austin, TX", urgency="scheduled",
        budget_min=150.0, budget_max=300.0, status="pending",
        latitude=COORDS["123_main_st"][0], longitude=COORDS["123_main_st"][1],
    ))

    # --- DISPUTE on completed mechanic job ---
    sr5 = ServiceRequest(
        client_id=clients[1].id, vehicle_id=bob_truck.id, profession_type="mechanic",
        title="Alternator replacement",
        description="Headlights flickering, battery warning light.",
        location="456 Oak Ave, Austin, TX", urgency="scheduled", status="completed",
        latitude=COORDS["456_oak_ave"][0], longitude=COORDS["456_oak_ave"][1],
    )
    db.add(sr5); db.flush()
    job3 = Job(
        request_id=sr5.id, mechanic_id=providers_by_email["james@demo.com"].id,
        status="completed", mechanic_notes="Replaced alternator - OEM part.",
        final_price=450.0,
        started_at=datetime.utcnow() - timedelta(days=7),
        completed_at=datetime.utcnow() - timedelta(days=7) + timedelta(hours=3),
    )
    db.add(job3); db.flush()
    db.add(Dispute(
        job_id=job3.id, raised_by_id=clients[1].id,
        description="I was quoted $350 but was charged $450 without prior notice. Non-OEM alternator but charged OEM price.",
        status="reviewing", admin_notes="Awaiting invoice from provider.",
    ))

    db.commit()
    print("Seed complete.")
    print()
    print("  Demo credentials:")
    print("  -------------------------------------------------")
    print(f"  Admin        admin@lever.app          Admin123!")
    for c in CLIENTS:
        print(f"  Client       {c['email']:<30} {c['password']}")
    for p in PROVIDERS:
        label = p['profession'].ljust(12)
        print(f"  {label}   {p['email']:<30} {p['password']}")
    print("  -------------------------------------------------")
    print(f"  App URL:   http://0.0.0.0:8500")
    print(f"  API docs:  http://0.0.0.0:8500/docs")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lever demo data seeder")
    parser.add_argument("--reset", action="store_true", help="Drop all tables before seeding")
    args = parser.parse_args()

    if args.reset:
        print("Dropping all tables...")
        Base.metadata.drop_all(bind=engine)

    print("Creating tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing_count = db.query(User).filter(User.role == "client").count()
        if existing_count > 0 and not args.reset:
            print(f"Database already has {existing_count} client(s). Use --reset to re-seed.")
            sys.exit(0)
        seed(db)
    except Exception as e:
        db.rollback()
        print(f"SEED FAILED: {e}")
        raise
    finally:
        db.close()
