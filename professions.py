"""Lever — Professions registry.

To add a new profession:
  1. Add an entry to PROFESSIONS dict below
  2. Run seed.py --reset to populate demo data
  3. The UI, API, and job board automatically adapt

Each profession defines:
  - label:        Display name shown in UI
  - icon:         Emoji icon for badges/cards
  - description:  Short description for marketing/info
  - specialties:  Default specialty options for provider profiles
  - service_noun: What a single service unit is called (e.g., "repair", "installation")
  - vehicle_required: Whether service requests require a vehicle record
  - job_statuses: Ordered status flow for jobs (first = default after accept)
"""

PROFESSIONS = {
    "mechanic": {
        "label": "Mechanic",
        "icon": "\U0001f527",  # wrench
        "description": "Auto repair, maintenance, and diagnostics",
        "specialties": [
            "Engine Repair", "Brakes", "Transmission", "Oil Change",
            "A/C & Heating", "Suspension", "Electrical", "Diagnostics",
            "Hybrid/EV", "European Cars", "Body Work", "Tires & Alignment",
        ],
        "service_noun": "repair",
        "vehicle_required": True,
        "job_statuses": ["accepted", "en_route", "diagnosing", "repairing", "completed", "cancelled"],
    },
    "hvac": {
        "label": "HVAC Technician",
        "icon": "\u2744\ufe0f",  # snowflake
        "description": "Heating, ventilation, and air conditioning services",
        "specialties": [
            "AC Installation", "AC Repair", "Heating Installation", "Heating Repair",
            "Duct Cleaning", "Thermostat Setup", "Refrigerant Recharge",
            "Ventilation", "Heat Pump", "Boiler Service", "Indoor Air Quality",
            "Emergency Repair",
        ],
        "service_noun": "service call",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "inspecting", "servicing", "completed", "cancelled"],
    },
    "electrician": {
        "label": "Electrician",
        "icon": "\u26a1",  # lightning
        "description": "Electrical installation, repair, and safety inspections",
        "specialties": [
            "Wiring & Rewiring", "Panel Upgrade", "Outlet Installation",
            "Lighting", "Ceiling Fan Install", "EV Charger Install",
            "Generator Installation", "Troubleshooting", "Code Compliance",
            "Smart Home", "Commercial Electrical", "Emergency Repair",
        ],
        "service_noun": "electrical job",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "inspecting", "working", "completed", "cancelled"],
    },
    "construction": {
        "label": "Construction Professional",
        "icon": "\U0001f3d7\ufe0f",  # building construction
        "description": "General construction, remodeling, and renovation",
        "specialties": [
            "General Contracting", "Framing", "Drywall", "Painting",
            "Flooring", "Roofing", "Concrete & Masonry", "Carpentry",
            "Kitchen Remodel", "Bathroom Remodel", "Deck & Patio",
            "Demolition", "Siding", "Window & Door Install",
        ],
        "service_noun": "project",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "assessing", "working", "completed", "cancelled"],
    },
    "carwash": {
        "label": "Car Wash Professional",
        "icon": "\U0001f6bf",  # shower (closest to wash)
        "description": "Mobile car washing, detailing, and paint correction",
        "specialties": [
            "Exterior Wash", "Interior Cleaning", "Full Detail",
            "Ceramic Coating", "Paint Correction", "Wax & Polish",
            "Engine Bay Cleaning", "Headlight Restoration", "Odor Removal",
            "Leather Conditioning", "Fleet Washing", "Mobile Detailing",
        ],
        "service_noun": "detail",
        "vehicle_required": True,
        "job_statuses": ["accepted", "en_route", "prepping", "washing", "completed", "cancelled"],
    },
}

# Convenience: list of valid profession keys
PROFESSION_KEYS = list(PROFESSIONS.keys())

# Regex pattern for Pydantic validation
PROFESSION_PATTERN = "^(" + "|".join(PROFESSION_KEYS) + ")$"


def get_profession(key: str) -> dict:
    """Return profession config by key, or raise ValueError."""
    if key not in PROFESSIONS:
        raise ValueError(f"Unknown profession: {key}. Valid: {PROFESSION_KEYS}")
    return PROFESSIONS[key]


def get_specialties(profession_key: str) -> list[str]:
    """Return specialty options for a profession."""
    return get_profession(profession_key)["specialties"]


def get_job_statuses(profession_key: str) -> list[str]:
    """Return valid job statuses for a profession."""
    return get_profession(profession_key)["job_statuses"]
