"""Lever — reference pricing engine (Guayaquil, Ecuador).

Produces an HONEST, backend-owned price estimate per catalog service:

    estimate = profession hourly rate × the service's real duration range,
               floored by a minimum call-out ("visita mínima")

The output is explicitly REFERENCE guidance ("precio referencial") shown to
customers before requesting and to professionals in job offers. The final
price is always agreed between customer and professional. Lever currently
charges NO commission, so the amount the client pays is the amount the
professional receives — the UI states this rather than inventing fees.

Where the rates come from (documented so they can be challenged/updated):
- Baseline: Ecuador's 2026 Salario Básico Unificado is US$482/month — an
  official hourly value of US$3.01 (Ministerio del Trabajo, tripartite
  consensus, Dec 2025). Independent trades bill above that hourly floor
  because jobs are short, irregular, and carry travel + tool costs.
- Market evidence (Ecuador service platforms / trade guides, 2025-26):
  plumbers & electricians commonly bill US$10-20/hour, with complex electrical
  work quoted US$25-40/hour; call-out ("visita") fees around US$10; cleaning
  ≈ US$15-25 per 4-hour session (≈ US$4-6/hour).
- Guayaquil rates track slightly below Quito's; ranges below sit inside the
  evidenced band rather than at its top.
- They are deliberately RANGES, versioned (PRICING_POLICY_VERSION) and kept in
  one place so the owner can review/adjust without touching any other code.

CIA Triad:
  Integrity:    single source of truth; estimates precomputed from the catalog's
                own duration data; nothing computed client-side.
  Availability: pure stdlib, precomputed at import (O(297) multiplications).
  Honesty:      never called "net"/"final"; labelled referential everywhere.
"""
from __future__ import annotations

from typing import Optional

PRICING_POLICY_VERSION = "GYE-2026-07.v2"
CURRENCY = "USD"

# USD per hour of work, per profession — Guayaquil reference ranges.
LABOR_RATES: dict[str, tuple[float, float]] = {
    "home_cleaning":    (4.0, 6.0),
    "handyman":         (6.0, 10.0),
    "plumbing":         (10.0, 18.0),
    "electrical":       (10.0, 18.0),
    "painting":         (5.0, 9.0),
    "construction":     (5.0, 10.0),
    "gardening":        (5.0, 9.0),
    "appliance_repair": (9.0, 16.0),
    "tech_support":     (8.0, 14.0),
    "beauty":           (6.0, 12.0),
    "automotive":       (9.0, 16.0),
    "moving":           (6.0, 10.0),
    "home_security":    (8.0, 14.0),
    "pets":             (4.0, 8.0),
    "events":           (6.0, 12.0),
    "business_support": (6.0, 12.0),
}
_DEFAULT_RATE = (5.0, 10.0)

# Minimum call-out ("visita mínima") — short jobs never estimate below this.
MIN_VISIT: dict[str, float] = {
    "plumbing": 10, "electrical": 10, "appliance_repair": 10, "automotive": 10,
    "home_security": 10, "tech_support": 10,
    "handyman": 8, "painting": 8, "construction": 8, "gardening": 8,
    "moving": 8, "events": 8, "business_support": 8,
    "home_cleaning": 6, "pets": 6, "beauty": 6,
}
_DEFAULT_VISIT = 8.0


def estimate_for_service(svc: dict) -> Optional[tuple[int, int]]:
    """(estimate_min, estimate_max) in whole USD for a catalog service dict,
    or None when the service carries no usable duration data."""
    dmin, dmax = svc.get("duration_min"), svc.get("duration_max")
    if not dmin or not dmax:
        return None
    prof = svc.get("profession", "")
    rate_min, rate_max = LABOR_RATES.get(prof, _DEFAULT_RATE)
    visit = MIN_VISIT.get(prof, _DEFAULT_VISIT)
    est_min = max(rate_min * (dmin / 60.0), visit)
    est_max = max(rate_max * (dmax / 60.0), est_min + 2)
    return (int(round(est_min)), int(round(est_max)))


def _build_estimates() -> dict[str, tuple[int, int]]:
    from services_catalog import ALL_SERVICES
    out: dict[str, tuple[int, int]] = {}
    for svc in ALL_SERVICES:
        est = estimate_for_service(svc)
        if est:
            out[svc["key"]] = est
    return out


# Precomputed at import: {service_key: (estimate_min, estimate_max)}.
ESTIMATES: dict[str, tuple[int, int]] = _build_estimates()


def payment_line_es(budget_min: Optional[float], budget_max: Optional[float],
                    service_key: Optional[str]) -> Optional[str]:
    """Spanish payment line for provider-facing offers. Prefers the client's
    REAL budget; falls back to the reference estimate (labelled as such);
    None when neither exists — never fabricates an amount."""
    if budget_max is not None:
        if budget_min is not None and budget_min != budget_max:
            return f"Presupuesto del cliente: USD {budget_min:g}–{budget_max:g}"
        return f"Presupuesto del cliente: hasta USD {budget_max:g}"
    est = ESTIMATES.get(service_key or "")
    if est:
        return f"Pago referencial: USD {est[0]}–{est[1]}"
    return None
