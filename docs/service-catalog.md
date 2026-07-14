# Lever — Service Catalog

**Source of truth:** `services_catalog.py` (version-controlled structured data,
per the decision in `service-catalog-ux-audit.md` §9). Categories live in
`professions.py`. No service data is hard-coded in frontend screens — the
frontend consumes `GET /api/catalog`.

## Hierarchy

```
Category (16, professions.py)  ← browse grid; carries icon, job-status flow, badge styling
└── Service (297, services_catalog.py)  ← what a customer books
    └── Questions (per-category QUESTION_SETS)  ← drive the dynamic request form
```

v1 keeps Profession ≡ Category. The 16: home_cleaning, handyman, plumbing,
electrical, painting, construction, gardening, appliance_repair, tech_support,
beauty, automotive, moving, home_security, pets, events, business_support.

## Service record fields

`key`, `category`, `profession`, `name_es`/`name_en` (es-EC first),
`description_es`/`description_en`, `icon`, `booking_type` (`instant`|`estimate`),
`emergency_capable` (bool), `pricing_type` (`fixed`|`starting_at`|`hourly`|
`per_m2`|`per_room`|`per_item`|`inspection_fee`|`estimate_required`),
`duration_min`/`duration_max` (minutes), `materials_possible`,
`photos_requested`, `risk_level` (`low`|`medium`|`high`),
`verification_required` (`none`|`enhanced`), `keywords` (es-EC synonyms),
`questions`, `sort_order`, `is_active`.

Category-level defaults (`CATEGORY_DEFAULTS`) + per-service overrides keep the
data compact. Compliance flags per the owner's spec: high-risk electrical/
construction/security ⇒ `verification_required: enhanced` (enforcement lands
with provider verification, Phase 3 / decision D5); beauty limited to
non-invasive; pets exclude veterinary; business support excludes regulated
professional services.

## API

- `GET /api/catalog` — categories + all active services, both languages,
  `Cache-Control: public, max-age=300`. Public (guests browse pre-auth).
- `GET /api/catalog/search?q=&lang=` — accent-insensitive scored match over
  names, keywords, descriptions. Spec synonyms verified: “llave de agua” →
  faucet repair, “tubería rota” → leak repair, “computadora lenta” → computer
  diagnosis, “no tengo internet” → Wi-Fi troubleshooting, “lavadora no
  prende” → washer diagnosis.
- `POST /api/client/requests` accepts optional `service_key` + `answers`
  (migration `0007`). The server derives `profession_type` from the service —
  the client cannot mismatch them. `service_key=NULL` = legacy free-text
  request; everything existing keeps working.

## Adding/changing services

Edit `services_catalog.py`, keep names concise es-EC, run
`py -c "from services_catalog import ALL_SERVICES"` to validate, commit.
Frontend picks changes up on next `/api/catalog` fetch (5-min cache).
