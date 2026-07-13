"""Lever — Pydantic v2 request/response schemas.

CIA Triad Alignment:
  Confidentiality: Password strength validators, email format validation
  Integrity:       Input validation on all user-facing schemas
  Availability:    Clear error messages guide users to valid input
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from professions import PROFESSION_KEYS, PROFESSION_PATTERN, PROFESSIONS


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(client|mechanic)$")
    profession: Optional[str] = Field(default=None)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v

    @model_validator(mode="after")
    def validate_profession(self) -> "UserCreate":
        if self.role == "mechanic":
            if not self.profession:
                self.profession = "mechanic"
            if self.profession not in PROFESSION_KEYS:
                raise ValueError(f"Invalid profession. Valid: {PROFESSION_KEYS}")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    profession: Optional[str] = None
    email_verified: bool = False


class TokenData(BaseModel):
    user_id: Optional[int] = None
    role: Optional[str] = None


# ---------------------------------------------------------------------------
# Email Verification (Phase 1)
# ---------------------------------------------------------------------------

class VerifyEmailRequest(BaseModel):
    """6-digit numeric verification code."""
    code: str = Field(min_length=6, max_length=6, pattern="^[0-9]{6}$")


class VerifyEmailResponse(BaseModel):
    success: bool
    message: str
    email_verified: bool = False


class ResendVerificationResponse(BaseModel):
    success: bool
    message: str
    cooldown_seconds: int = 0


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    email_verified: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class UserAdminUpdate(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[str] = Field(default=None, pattern="^(client|mechanic|admin)$")


# ---------------------------------------------------------------------------
# Client Profile
# ---------------------------------------------------------------------------

class ClientProfileOut(BaseModel):
    id: int
    user_id: int
    full_name: str
    phone: str
    address: str
    avatar_url: str

    model_config = {"from_attributes": True}


class ClientProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=30)
    address: Optional[str] = Field(default=None, max_length=500)
    avatar_url: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Provider Profile (mechanic / HVAC / electrician / construction / carwash)
# ---------------------------------------------------------------------------

class MechanicProfileOut(BaseModel):
    id: int
    user_id: int
    profession: str
    full_name: str
    phone: str
    bio: str
    specialties: List[str]
    years_experience: int
    hourly_rate: float
    is_available: bool
    location: str
    service_radius_miles: int
    avg_rating: float
    total_jobs: int
    avatar_url: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_online: bool = False
    last_heartbeat: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @property
    def profession_label(self) -> str:
        return PROFESSIONS.get(self.profession, {}).get("label", self.profession)


class MechanicProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=30)
    bio: Optional[str] = None
    specialties: Optional[List[str]] = None
    years_experience: Optional[int] = Field(default=None, ge=0, le=60)
    hourly_rate: Optional[float] = Field(default=None, ge=0.0)
    is_available: Optional[bool] = None
    location: Optional[str] = Field(default=None, max_length=500)
    service_radius_miles: Optional[int] = Field(default=None, ge=1, le=500)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)


class MechanicCard(BaseModel):
    """Lightweight provider listing card for client browsing."""
    user_id: int
    profession: str
    full_name: str
    specialties: List[str]
    years_experience: int
    hourly_rate: float
    avg_rating: float
    total_jobs: int
    location: str
    service_radius_miles: int
    is_available: bool
    is_online: bool = False
    avatar_url: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    model_config = {"from_attributes": True}


class MechanicCardWithDistance(MechanicCard):
    """Provider card with calculated distance from search origin."""
    distance_miles: Optional[float] = None


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------

class VehicleCreate(BaseModel):
    make: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=1900, le=2100)
    color: Optional[str] = Field(default="", max_length=50)
    license_plate: Optional[str] = Field(default="", max_length=20)
    vin: Optional[str] = Field(default="", max_length=17)
    mileage: Optional[int] = Field(default=0, ge=0)
    notes: Optional[str] = Field(default="")

    @field_validator("vin")
    @classmethod
    def vin_format(cls, v: str) -> str:
        if v and len(v) not in (0, 17):
            raise ValueError("VIN must be exactly 17 characters if provided")
        return v.upper() if v else v


class VehicleUpdate(BaseModel):
    make: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    color: Optional[str] = Field(default=None, max_length=50)
    license_plate: Optional[str] = Field(default=None, max_length=20)
    vin: Optional[str] = Field(default=None, max_length=17)
    mileage: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None


class VehicleOut(BaseModel):
    id: int
    client_id: int
    make: str
    model: str
    year: int
    color: str
    license_plate: str
    vin: str
    mileage: int
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Service Request
# ---------------------------------------------------------------------------

class ServiceRequestCreate(BaseModel):
    vehicle_id: Optional[int] = None
    profession_type: str = Field(default="mechanic")
    title: str = Field(min_length=5, max_length=300)
    description: str = Field(min_length=10)
    location: str = Field(min_length=3, max_length=500)
    urgency: str = Field(default="scheduled", pattern="^(immediate|scheduled)$")
    scheduled_date: Optional[datetime] = None
    budget_min: Optional[float] = Field(default=None, ge=0)
    budget_max: Optional[float] = Field(default=None, ge=0)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)

    @field_validator("profession_type")
    @classmethod
    def validate_profession_type(cls, v: str) -> str:
        if v not in PROFESSION_KEYS:
            raise ValueError(f"Invalid profession_type. Valid: {PROFESSION_KEYS}")
        return v

    @model_validator(mode="after")
    def budget_order(self) -> "ServiceRequestCreate":
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("budget_min must be <= budget_max")
        return self


class ServiceRequestUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=5, max_length=300)
    description: Optional[str] = Field(default=None, min_length=10)
    location: Optional[str] = Field(default=None, min_length=3, max_length=500)
    urgency: Optional[str] = Field(default=None, pattern="^(immediate|scheduled)$")
    scheduled_date: Optional[datetime] = None
    budget_min: Optional[float] = Field(default=None, ge=0)
    budget_max: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = Field(
        default=None,
        pattern="^(pending|assigned|in_progress|completed|cancelled)$"
    )
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)


class ServiceRequestOut(BaseModel):
    id: int
    client_id: int
    vehicle_id: Optional[int]
    profession_type: str
    title: str
    description: str
    location: str
    urgency: str
    scheduled_date: Optional[datetime]
    budget_min: Optional[float]
    budget_max: Optional[float]
    status: str
    created_at: datetime
    updated_at: Optional[datetime]
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    model_config = {"from_attributes": True}


class ServiceRequestBoardOut(BaseModel):
    """Open job board listing — deliberately omits precise latitude/longitude.

    A provider browsing the board has no relationship with the client yet
    (they haven't accepted anything). Exact GPS coordinates are only
    appropriate once a provider has accepted a request — see JobDetail,
    which nests the full ServiceRequestOut (with coordinates) for exactly
    that reason. The free-text `location` field still gives a provider
    enough to judge distance/relevance without exposing exact coordinates
    to every online provider for every pending request.
    """
    id: int
    client_id: int
    vehicle_id: Optional[int]
    profession_type: str
    title: str
    description: str
    location: str
    urgency: str
    scheduled_date: Optional[datetime]
    budget_min: Optional[float]
    budget_max: Optional[float]
    status: str
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ServiceRequestDetail(ServiceRequestOut):
    """ServiceRequest with nested vehicle and job info."""
    vehicle: Optional[VehicleOut] = None
    job: Optional["JobOut"] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------

class JobOut(BaseModel):
    id: int
    request_id: int
    mechanic_id: int
    status: str
    mechanic_notes: str
    final_price: Optional[float]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class JobStatusUpdate(BaseModel):
    status: str
    mechanic_notes: Optional[str] = None
    final_price: Optional[float] = Field(default=None, ge=0)


class JobDetail(JobOut):
    """Job with nested request and mechanic profile."""
    request: Optional[ServiceRequestOut] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: int
    job_id: int
    sender_id: int
    content: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default="", max_length=2000)


class ReviewOut(BaseModel):
    id: int
    job_id: int
    client_id: int
    mechanic_id: int
    rating: int
    comment: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Dispute
# ---------------------------------------------------------------------------

class DisputeCreate(BaseModel):
    description: str = Field(min_length=20, max_length=5000)


class DisputeAdminUpdate(BaseModel):
    status: str = Field(pattern="^(open|reviewing|resolved)$")
    admin_notes: Optional[str] = Field(default=None, max_length=5000)


class DisputeOut(BaseModel):
    id: int
    job_id: int
    raised_by_id: int
    description: str
    status: str
    admin_notes: str
    created_at: datetime
    resolved_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Admin / Dashboard
# ---------------------------------------------------------------------------

class AdminStats(BaseModel):
    total_users: int
    total_clients: int
    total_mechanics: int
    total_providers: int = 0
    total_service_requests: int
    open_requests: int
    active_jobs: int
    completed_jobs: int
    open_disputes: int
    total_reviews: int
    avg_platform_rating: float


class PaginatedUsers(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[UserOut]


# ---------------------------------------------------------------------------
# Professions API
# ---------------------------------------------------------------------------

class ProfessionOut(BaseModel):
    key: str
    label: str
    icon: str
    description: str
    specialties: List[str]
    service_noun: str
    vehicle_required: bool


# ---------------------------------------------------------------------------
# Search (Day 60 addition)
# ---------------------------------------------------------------------------

class SearchProvidersRequest(BaseModel):
    """Advanced provider search with geo + filters."""
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    radius_miles: Optional[float] = Field(default=25.0, ge=1.0, le=500.0)
    profession: Optional[str] = None
    specialty: Optional[str] = None
    min_rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    max_hourly_rate: Optional[float] = Field(default=None, ge=0.0)
    min_experience_years: Optional[int] = Field(default=None, ge=0)
    available_only: bool = True
    sort_by: str = Field(default="distance", pattern="^(distance|rating|price|experience)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @field_validator("profession")
    @classmethod
    def validate_profession(cls, v):
        if v is not None and v not in PROFESSION_KEYS:
            raise ValueError(f"Invalid profession. Valid: {PROFESSION_KEYS}")
        return v


class SearchProvidersResponse(BaseModel):
    total: int
    page: int
    page_size: int
    has_more: bool
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_miles: Optional[float] = None
    results: List[MechanicCardWithDistance]


class SearchRequestsNearby(BaseModel):
    """Search service requests near a location (for providers)."""
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    radius_miles: float = Field(default=25.0, ge=1.0, le=500.0)
    profession_type: Optional[str] = None
    urgency: Optional[str] = Field(default=None, pattern="^(immediate|scheduled)$")

    @field_validator("profession_type")
    @classmethod
    def validate_profession_type(cls, v):
        if v is not None and v not in PROFESSION_KEYS:
            raise ValueError(f"Invalid profession_type. Valid: {PROFESSION_KEYS}")
        return v


class ServiceRequestWithDistance(ServiceRequestBoardOut):
    """Service request with calculated distance — used for provider search results.

    Deliberately extends ServiceRequestBoardOut (no precise lat/lng) rather
    than ServiceRequestOut: a provider searching nearby jobs needs to know
    how far away something is, not its exact coordinates, before they've
    accepted it. distance_miles is the privacy-appropriate signal here.
    """
    distance_miles: Optional[float] = None


# ---------------------------------------------------------------------------
# Geocode API
# ---------------------------------------------------------------------------

class GeocodeRequest(BaseModel):
    address: str = Field(min_length=3, max_length=500)


class GeocodeResponse(BaseModel):
    address: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    success: bool


# ---------------------------------------------------------------------------
# Utility / Generic
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    message: str


class ErrorDetail(BaseModel):
    detail: str


# Rebuild forward references
ServiceRequestDetail.model_rebuild()


# ---------------------------------------------------------------------------
# Password Reset (Day 30 addition)
# ---------------------------------------------------------------------------

class PasswordResetRequest(BaseModel):
    """Request a password reset code via email."""
    email: EmailStr


class PasswordResetVerify(BaseModel):
    """Verify reset code and set new password."""
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern="^[0-9]{6}$")
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class PasswordResetResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# Notifications (Day 30 addition)
# ---------------------------------------------------------------------------

class NotificationOut(BaseModel):
    id: int
    user_id: int
    type: str
    title: str
    message: str
    is_read: bool
    link: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationMarkRead(BaseModel):
    notification_ids: List[int] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Dispatch (Active provider queue)
# ---------------------------------------------------------------------------

class RequestDispatchOut(BaseModel):
    id: int
    request_id: int
    provider_user_id: int
    status: str
    position: int
    offered_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# GPS Live Tracking
# ---------------------------------------------------------------------------

class LocationUpdate(BaseModel):
    """Incoming GPS location update from provider device."""
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    accuracy: Optional[float] = Field(default=None, ge=0.0, le=5000.0)
    heading: Optional[float] = Field(default=None, ge=0.0, le=360.0)
    speed: Optional[float] = Field(default=None, ge=0.0, le=500.0)
    altitude: Optional[float] = None
    recorded_at: Optional[datetime] = None


class LocationOut(BaseModel):
    """Single location point for API responses."""
    id: int
    job_id: int
    provider_user_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    heading: Optional[float] = None
    speed: Optional[float] = None
    altitude: Optional[float] = None
    recorded_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class LocationTrail(BaseModel):
    """Route trail for a job — list of breadcrumbs."""
    job_id: int
    provider_user_id: int
    total_points: int
    trail: List[LocationOut]


class TrackingStatus(BaseModel):
    """Current tracking state for a job."""
    job_id: int
    is_tracking: bool
    provider_user_id: Optional[int] = None
    provider_name: Optional[str] = None
    current_location: Optional[LocationOut] = None
    destination_latitude: Optional[float] = None
    destination_longitude: Optional[float] = None
    distance_miles: Optional[float] = None
    eta_minutes: Optional[float] = None
    job_status: Optional[str] = None
