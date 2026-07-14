"""Lever — SQLAlchemy database models.

CIA Triad Alignment:
  Confidentiality: password_hash (bcrypt), verification tokens hashed, OAuth secrets never stored
  Integrity:       email_verified flag enforces ownership proof before platform access
  Availability:    nullable fields for backward compatibility, no destructive migrations

ISO 27001 Controls Referenced:
  A.9.2.1  User registration and de-registration
  A.9.4.2  Secure log-on procedures
  A.9.4.3  Password management system
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, Enum as SAEnum, JSON, Index
)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # Nullable for future OAuth-only users
    role = Column(SAEnum("client", "mechanic", "admin", name="role_enum"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # ── Email Verification (Phase 1) ──
    # ISO 27001 A.9.4.2: Prove email ownership before granting platform access
    email_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String(255), nullable=True)       # Hashed 6-digit code
    verification_token_expires = Column(DateTime, nullable=True)  # UTC expiry
    verification_attempts = Column(Integer, default=0, nullable=False)  # Brute-force counter
    last_verification_sent = Column(DateTime, nullable=True)      # Rate limiting

    # Password reset fields (separate from verification)
    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    reset_attempts = Column(Integer, default=0, nullable=False)
    last_reset_sent = Column(DateTime, nullable=True)

    # ── OAuth (Phase 2+) — columns added now for migration simplicity ──
    oauth_provider = Column(String(50), nullable=True)            # 'google', 'microsoft', or None
    oauth_provider_id = Column(String(255), nullable=True)        # Unique ID from provider

    # ── Terms & Privacy Policy acceptance (Google Play readiness, GP-05/GP-06) ──
    # Terms and Privacy are versioned together since they're revised in lockstep.
    terms_accepted_version = Column(String(20), nullable=True)
    terms_accepted_at = Column(DateTime, nullable=True)

    # ── Account deletion (GP-07) ──
    deleted_at = Column(DateTime, nullable=True)  # Soft-delete marker; anonymized, not hard-removed

    # ── Token revocation (GP-13) ──
    # Embedded as the "ver" claim in every JWT issued for this user.
    # get_current_user rejects any token whose "ver" doesn't match the
    # current value. Bumping this instantly invalidates every previously
    # issued token — used for "log out of all devices" and automatically
    # on password reset, without needing a server-side session table.
    token_version = Column(Integer, default=0, nullable=False)

    # Relationships
    client_profile = relationship("ClientProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    mechanic_profile = relationship("MechanicProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    vehicles = relationship("Vehicle", back_populates="client", cascade="all, delete-orphan", foreign_keys="Vehicle.client_id")
    service_requests = relationship("ServiceRequest", back_populates="client", foreign_keys="ServiceRequest.client_id")
    sent_messages = relationship("Message", back_populates="sender", foreign_keys="Message.sender_id")

    @property
    def is_oauth_user(self) -> bool:
        return self.oauth_provider is not None

    # Composite index for OAuth lookups (Phase 2+)
    __table_args__ = (
        Index("ix_users_oauth_lookup", "oauth_provider", "oauth_provider_id",
              unique=True, postgresql_where=Column("oauth_provider").isnot(None)),
    )


class ClientProfile(Base):
    __tablename__ = "client_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    full_name = Column(String(200), default="")
    phone = Column(String(30), default="")
    address = Column(String(500), default="")
    avatar_url = Column(String(500), default="")

    user = relationship("User", back_populates="client_profile")


class MechanicProfile(Base):
    """Provider profile — used for all professions (mechanic, HVAC, electrician, etc.)."""
    __tablename__ = "mechanic_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    profession = Column(String(50), default="mechanic", nullable=False, index=True)
    full_name = Column(String(200), default="")
    phone = Column(String(30), default="")
    bio = Column(Text, default="")
    specialties = Column(JSON, default=list)
    years_experience = Column(Integer, default=0)
    hourly_rate = Column(Float, default=0.0)
    is_available = Column(Boolean, default=True)
    location = Column(String(500), default="")
    service_radius_miles = Column(Integer, default=25)
    avg_rating = Column(Float, default=0.0)
    total_jobs = Column(Integer, default=0)
    avatar_url = Column(String(500), default="")

    # ── Geolocation (Day 60) ──
    # Nullable for backward compatibility — existing providers without coords still work
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # ── Active Status (provider online/offline) ──
    is_online = Column(Boolean, default=False, nullable=False)
    last_heartbeat = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="mechanic_profile")
    jobs = relationship(
        "Job",
        back_populates="mechanic",
        primaryjoin="MechanicProfile.user_id == foreign(Job.mechanic_id)",
        foreign_keys="[Job.mechanic_id]",
    )

    __table_args__ = (
        # Spatial index for bounding-box pre-filter queries
        Index("ix_mechanic_profiles_geo", "latitude", "longitude"),
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    make = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    color = Column(String(50), default="")
    license_plate = Column(String(20), default="")
    vin = Column(String(17), default="")
    mileage = Column(Integer, default=0)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    client = relationship("User", back_populates="vehicles", foreign_keys=[client_id])
    service_requests = relationship("ServiceRequest", back_populates="vehicle")


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    profession_type = Column(String(50), default="mechanic", nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(500), nullable=False)
    urgency = Column(SAEnum("immediate", "scheduled", name="urgency_enum"), default="scheduled")
    scheduled_date = Column(DateTime, nullable=True)
    budget_min = Column(Float, nullable=True)
    budget_max = Column(Float, nullable=True)
    status = Column(
        SAEnum("pending", "assigned", "in_progress", "completed", "cancelled", name="request_status_enum"),
        default="pending", nullable=False
    )
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # ── Geolocation (Day 60) ──
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    client = relationship("User", back_populates="service_requests", foreign_keys=[client_id])
    vehicle = relationship("Vehicle", back_populates="service_requests")
    job = relationship("Job", back_populates="request", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_service_requests_geo", "latitude", "longitude"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("service_requests.id", ondelete="CASCADE"), unique=True, nullable=False)
    mechanic_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(
        SAEnum("accepted", "en_route", "diagnosing", "repairing", "inspecting",
               "servicing", "working", "assessing", "prepping", "washing",
               "completed", "cancelled", name="job_status_enum"),
        default="accepted", nullable=False
    )
    mechanic_notes = Column(Text, default="")
    final_price = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    request = relationship("ServiceRequest", back_populates="job")
    mechanic = relationship("MechanicProfile", back_populates="jobs", foreign_keys=[mechanic_id],
                            primaryjoin="Job.mechanic_id == MechanicProfile.user_id")
    messages = relationship("Message", back_populates="job", cascade="all, delete-orphan", order_by="Message.created_at")
    review = relationship("Review", back_populates="job", uselist=False, cascade="all, delete-orphan")
    dispute = relationship("Dispute", back_populates="job", uselist=False, cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    job = relationship("Job", back_populates="messages")
    sender = relationship("User", back_populates="sent_messages", foreign_keys=[sender_id])


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    mechanic_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)   # 1-5
    comment = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    job = relationship("Job", back_populates="review")


class Dispute(Base):
    __tablename__ = "disputes"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    raised_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(SAEnum("open", "reviewing", "resolved", name="dispute_status_enum"), default="open")
    admin_notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    job = relationship("Job", back_populates="dispute")


# ---------------------------------------------------------------------------
# Notification (Day 30 addition)
# ---------------------------------------------------------------------------

class Notification(Base):
    """In-app notification system.

    CIA Triad:
      Confidentiality: Notifications are scoped to individual users
      Integrity:       Type field constrains notification categories
      Availability:    Non-blocking — notifications don't block core operations
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # job_update, message, review, system
    title = Column(String(300), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    link = Column(String(500), nullable=True)  # Frontend route to navigate to
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", backref="notifications")

    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "is_read"),
    )


# ---------------------------------------------------------------------------
# Request Dispatch Queue (tracks 30-second offer rotation)
# ---------------------------------------------------------------------------

class RequestDispatch(Base):
    """Tracks the dispatch of a service request to individual providers.

    Each row represents one offer to one provider. The system offers
    to providers one at a time (by position order) with a 30-second window.

    Status flow: queued → offered → accepted | timeout | cancelled
    """
    __tablename__ = "request_dispatches"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(
        SAEnum("queued", "offered", "accepted", "timeout", "cancelled", name="dispatch_status_enum"),
        default="queued", nullable=False
    )
    position = Column(Integer, nullable=False)  # Order in dispatch queue (0-based)
    offered_at = Column(DateTime, nullable=True)  # When offer was sent
    responded_at = Column(DateTime, nullable=True)  # When provider accepted or timed out
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    request = relationship("ServiceRequest", backref="dispatches")
    provider = relationship("User", foreign_keys=[provider_user_id])

    __table_args__ = (
        Index("ix_request_dispatch_active", "request_id", "status"),
    )


# ---------------------------------------------------------------------------
# Content moderation: reports + blocking (GP-08)
# ---------------------------------------------------------------------------

class Report(Base):
    """A user-submitted report against another user, or a specific piece of
    content (message, review, service request) that user authored."""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reported_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(
        SAEnum("user", "message", "review", "service_request", name="report_entity_enum"),
        nullable=False,
    )
    entity_id = Column(Integer, nullable=True)  # id of the message/review/request; null for a direct user report
    category = Column(
        SAEnum("spam", "harassment", "fraud", "inappropriate", "safety", "other", name="report_category_enum"),
        nullable=False,
    )
    description = Column(Text, default="")
    status = Column(
        SAEnum("open", "reviewing", "resolved", "dismissed", name="report_status_enum"),
        default="open", nullable=False,
    )
    admin_notes = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    reporter = relationship("User", foreign_keys=[reporter_id])
    reported_user = relationship("User", foreign_keys=[reported_user_id])

    __table_args__ = (
        Index("ix_reports_status", "status"),
        Index("ix_reports_reported_user", "reported_user_id"),
    )


class Block(Base):
    """One-directional block: blocker no longer sees or can be contacted
    by blocked in matching/discovery/messaging. Enforced symmetrically —
    either party having blocked the other is enough to hide/restrict."""
    __tablename__ = "blocks"

    id = Column(Integer, primary_key=True, index=True)
    blocker_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    blocked_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    blocker = relationship("User", foreign_keys=[blocker_id])
    blocked = relationship("User", foreign_keys=[blocked_id])

    __table_args__ = (
        Index("ix_blocks_blocker_blocked", "blocker_id", "blocked_id", unique=True),
    )


# ---------------------------------------------------------------------------
# GPS Live Tracking (provider location breadcrumbs per active job)
# ---------------------------------------------------------------------------

class ProviderLocation(Base):
    """GPS breadcrumb for a service provider during an active job.

    Each row captures one location point. The provider's device sends
    updates every 3-10 seconds while en_route or actively working.
    Breadcrumbs are retained for route history and ETA calculation.

    CIA Triad:
      Confidentiality: Location scoped to job participants only
      Integrity:       Validated lat/lng, server-side timestamps
      Availability:    Non-blocking writes, auto-pruning of stale data
    """
    __tablename__ = "provider_locations"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)       # GPS accuracy in meters
    heading = Column(Float, nullable=True)         # Bearing 0-360 degrees
    speed = Column(Float, nullable=True)           # Speed in m/s
    altitude = Column(Float, nullable=True)        # Altitude in meters
    recorded_at = Column(DateTime, nullable=False)  # Client-side timestamp
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    job = relationship("Job", backref="location_breadcrumbs")
    provider = relationship("User", foreign_keys=[provider_user_id])

    __table_args__ = (
        Index("ix_provider_locations_job_time", "job_id", "created_at"),
        Index("ix_provider_locations_provider", "provider_user_id", "created_at"),
    )
