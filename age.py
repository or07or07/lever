"""Lever — authoritative minimum-age policy (18+).

The backend is the ONLY source of truth for age eligibility. A device clock,
a client-side check, or a client-supplied flag such as {"isAdult": true} is
never trusted: eligibility is always recomputed here from a submitted date of
birth against the backend's own business date.

Business date
-------------
Lever's launch market is Guayaquil, so eligibility is evaluated against the
calendar date in ``America/Guayaquil``. Ecuador does not observe DST (fixed
UTC-5), so if the tz database is unavailable we fall back to a fixed -05:00
offset, which is exactly equivalent for this market.

Leap-year rule (documented business rule)
-----------------------------------------
A person born on 29 February reaches their birthday on **1 March** in
non-leap years. This is the conservative reading (they are not treated as
18 until 1 March), and it is applied consistently by ``birthday_on``.

CIA Triad:
  Confidentiality: only a boolean/None is returned — the DOB is never echoed.
  Integrity:       one pure function, calendar-correct, no client input trusted.
  Availability:    stdlib-only, no network or tz-data hard dependency.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

MINIMUM_AGE = 18
MINIMUM_AGE_POLICY_VERSION = "2026-07-17.v1"
MARKET_TIMEZONE = "America/Guayaquil"

# Reasonable calendar bounds — rejects corrupt/absurd dates without
# discriminating against legitimate users.
MAX_REASONABLE_AGE = 120

# Structured error code returned to clients (never includes the DOB).
ERR_MINIMUM_AGE = "MINIMUM_AGE_REQUIREMENT_NOT_MET"
ERR_INVALID_DOB = "INVALID_DATE_OF_BIRTH"


def market_today() -> date:
    """Today's calendar date in the market's timezone (backend time source)."""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        return datetime.now(ZoneInfo(MARKET_TIMEZONE)).date()
    except Exception:
        # Ecuador is a fixed UTC-5 with no DST — exactly equivalent here.
        return datetime.now(timezone(timedelta(hours=-5))).date()


def birthday_on(dob: date, years: int) -> date:
    """The calendar date the person born on `dob` reaches `years` of age.

    29 February in a non-leap target year resolves to 1 March (see module
    docstring for the documented business rule).
    """
    try:
        return dob.replace(year=dob.year + years)
    except ValueError:
        # Only reachable for 29 Feb → non-leap year.
        return date(dob.year + years, 3, 1)


def is_valid_dob(dob: Optional[date], today: Optional[date] = None) -> bool:
    """Reject empty, future, and absurdly old dates. (Invalid calendar dates
    like 31-Feb never construct a `date`, so they are rejected upstream.)"""
    if dob is None or not isinstance(dob, date):
        return False
    today = today or market_today()
    if dob > today:
        return False
    if dob < date(today.year - MAX_REASONABLE_AGE, today.month, 1):
        return False
    return True


def is_old_enough(dob: date, minimum_age: int = MINIMUM_AGE,
                  today: Optional[date] = None) -> bool:
    """True only once the person has actually reached `minimum_age`.

    Calendar-correct: never `current_year - birth_year`. Turning 18 *today*
    is eligible; turning 18 tomorrow is not.
    """
    today = today or market_today()
    return today >= birthday_on(dob, minimum_age)


def assert_minimum_age(dob: Optional[date], minimum_age: int = MINIMUM_AGE,
                       today: Optional[date] = None) -> None:
    """Raise a 403 with a structured, Spanish-facing error when ineligible.

    Deliberately raises the SAME error for 'too young' regardless of how far
    off they are, and never echoes the submitted date of birth back.
    """
    from fastapi import HTTPException

    today = today or market_today()
    if not is_valid_dob(dob, today):
        raise HTTPException(status_code=422, detail=ERR_INVALID_DOB)
    if not is_old_enough(dob, minimum_age, today):
        raise HTTPException(status_code=403, detail=ERR_MINIMUM_AGE)
