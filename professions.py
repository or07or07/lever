"""Lever — Professions registry.

To add a new profession:
  1. Add an entry to PROFESSIONS dict below
  2. Add a `prof.<key>` translation in frontend/index.html, a
     `badge-prof-<key>` CSS color, and a profColors entry for the map
  3. The UI, API, and job board automatically adapt

Each profession defines:
  - label:        Display name shown in UI (English fallback — the frontend
                  overrides with the bilingual `prof.<key>` translation)
  - icon:         Emoji icon for badges/cards
  - description:  Short description for marketing/info
  - specialties:  Default specialty options for provider profiles
  - service_noun: What a single service unit is called
  - vehicle_required: Whether service requests require a vehicle record
  - job_statuses: Ordered status flow for jobs (first = default after accept).
                  IMPORTANT: only values already present in models.py's
                  job_status_enum may be used here — adding a new status
                  requires a PostgreSQL enum migration, not just an edit.

Historical note: the original five professions (mechanic, hvac, electrician,
construction, carwash) were replaced with this broader 12-category catalog.
Migration 0006 remaps existing rows: mechanic/carwash → automotive,
hvac → appliance_repair, electrician → electrical; construction kept its key.
"""

PROFESSIONS = {
    "home_cleaning": {
        "label": "Home Cleaning",
        "icon": "\U0001f9f9",  # broom
        "description": "Regular cleaning, deep cleaning, move-in cleaning, window cleaning",
        "specialties": [
            "Limpieza Regular", "Limpieza Profunda", "Limpieza de Mudanza",
            "Limpieza de Ventanas", "Limpieza de Oficinas", "Planchado y Lavandería",
        ],
        "service_noun": "cleaning",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "working", "completed", "cancelled"],
    },
    "handyman": {
        "label": "Handyman",
        "icon": "\U0001f6e0️",  # hammer and wrench
        "description": "Furniture assembly, shelf installation, curtain installation, minor repairs",
        "specialties": [
            "Ensamblaje de Muebles", "Instalación de Estanterías", "Instalación de Cortinas",
            "Reparaciones Menores", "Colgado de Cuadros y TV", "Cambio de Cerraduras",
        ],
        "service_noun": "job",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "assessing", "working", "completed", "cancelled"],
    },
    "plumbing": {
        "label": "Plumbing",
        "icon": "\U0001f6b0",  # potable water
        "description": "Repair leaking faucets, unclog sinks, replace toilet parts, install fixtures",
        "specialties": [
            "Reparación de Fugas", "Destape de Cañerías", "Reparación de Inodoros",
            "Instalación de Grifería", "Instalación de Sanitarios", "Calefones",
        ],
        "service_noun": "repair",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "diagnosing", "repairing", "completed", "cancelled"],
    },
    "electrical": {
        "label": "Electrical Work",
        "icon": "⚡",  # lightning
        "description": "Install lights, replace outlets, troubleshoot minor electrical problems",
        "specialties": [
            "Instalación de Luminarias", "Cambio de Tomacorrientes", "Diagnóstico de Fallas",
            "Instalación de Ventiladores", "Cableado", "Tableros Eléctricos",
        ],
        "service_noun": "electrical job",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "inspecting", "working", "completed", "cancelled"],
    },
    "painting": {
        "label": "Painting & Drywall",
        "icon": "\U0001f3a8",  # palette
        "description": "Paint rooms, repair holes, install or finish drywall",
        "specialties": [
            "Pintura de Interiores", "Pintura de Exteriores", "Reparación de Huecos",
            "Instalación de Drywall", "Acabados de Drywall", "Empaste",
        ],
        "service_noun": "job",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "prepping", "working", "completed", "cancelled"],
    },
    "construction": {
        "label": "Construction Labor",
        "icon": "\U0001f3d7️",  # building construction
        "description": "Masonry, tile installation, cement work, demolition assistance",
        "specialties": [
            "Albañilería", "Instalación de Cerámica", "Trabajo en Cemento",
            "Ayuda en Demolición", "Mampostería", "Enlucido",
        ],
        "service_noun": "project",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "assessing", "working", "completed", "cancelled"],
    },
    "gardening": {
        "label": "Gardening",
        "icon": "\U0001f331",  # seedling
        "description": "Cut grass, clear yards, trim plants, basic landscaping",
        "specialties": [
            "Corte de Césped", "Limpieza de Terrenos", "Poda de Plantas",
            "Jardinería Básica", "Diseño de Jardines", "Fumigación de Plantas",
        ],
        "service_noun": "job",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "working", "completed", "cancelled"],
    },
    "appliance_repair": {
        "label": "Appliance Repair",
        "icon": "\U0001f50c",  # electric plug
        "description": "Refrigerators, washing machines, stoves and air conditioners",
        "specialties": [
            "Refrigeradoras", "Lavadoras", "Cocinas y Hornos",
            "Aires Acondicionados", "Secadoras", "Microondas",
        ],
        "service_noun": "repair",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "diagnosing", "repairing", "completed", "cancelled"],
    },
    "tech_support": {
        "label": "Technology Support",
        "icon": "\U0001f4bb",  # laptop
        "description": "Computer repair, Wi-Fi setup, cameras, printers, cellphone repair",
        "specialties": [
            "Reparación de Computadoras", "Configuración de Wi-Fi", "Cámaras de Seguridad",
            "Impresoras", "Reparación de Celulares", "Instalación de Software",
        ],
        "service_noun": "service",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "diagnosing", "repairing", "completed", "cancelled"],
    },
    "beauty": {
        "label": "Beauty at Home",
        "icon": "\U0001f487",  # haircut
        "description": "Haircuts, barbering, nails, makeup and hairstyling",
        "specialties": [
            "Cortes de Cabello", "Barbería", "Uñas",
            "Maquillaje", "Peinados", "Tratamientos Capilares",
        ],
        "service_noun": "session",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "working", "completed", "cancelled"],
    },
    "automotive": {
        "label": "Automotive Services",
        "icon": "\U0001f697",  # car
        "description": "Battery replacement, diagnostics, oil changes, washing and detailing",
        "specialties": [
            "Cambio de Batería", "Diagnóstico Automotriz", "Cambio de Aceite",
            "Lavado y Detailing", "Frenos", "Llantas",
        ],
        "service_noun": "service",
        "vehicle_required": True,
        "job_statuses": ["accepted", "en_route", "diagnosing", "repairing", "completed", "cancelled"],
    },
    "moving": {
        "label": "Moving Assistance",
        "icon": "\U0001f4e6",  # package
        "description": "Loading, unloading, furniture moving and small deliveries",
        "specialties": [
            "Carga y Descarga", "Mudanza de Muebles", "Entregas Pequeñas",
            "Embalaje", "Fletes", "Transporte de Electrodomésticos",
        ],
        "service_noun": "move",
        "vehicle_required": False,
        "job_statuses": ["accepted", "en_route", "working", "completed", "cancelled"],
    },
}

# Convenience: list of valid profession keys
PROFESSION_KEYS = list(PROFESSIONS.keys())

# Regex pattern for Pydantic validation
PROFESSION_PATTERN = "^(" + "|".join(PROFESSION_KEYS) + ")$"

# Fallback when a provider registers without picking a profession.
DEFAULT_PROFESSION = "handyman"

# Old profession keys → new ones. Used by migration 0006 to remap existing
# rows, and kept here as the single documented source of that mapping.
LEGACY_PROFESSION_MAP = {
    "mechanic": "automotive",
    "carwash": "automotive",
    "hvac": "appliance_repair",
    "electrician": "electrical",
    # "construction" kept its key
}


def get_profession(key: str) -> dict:
    """Return profession config by key, or raise ValueError."""
    if key not in PROFESSIONS:
        raise ValueError(f"Unknown profession: {key}. Valid: {PROFESSION_KEYS}")
    return PROFESSIONS[key]


def get_specialties(profession_key: str) -> list[str]:
    """Return specialty options for a profession."""
    return get_profession(profession_key)["specialties"]


def get_job_statuses(profession_key: str) -> list[str]:
    """Return valid job statuses for a profession.

    Falls back to a generic flow for unknown/legacy keys so an unmigrated
    row can't crash job-detail rendering."""
    if profession_key not in PROFESSIONS:
        return ["accepted", "en_route", "working", "completed", "cancelled"]
    return PROFESSIONS[profession_key]["job_statuses"]
