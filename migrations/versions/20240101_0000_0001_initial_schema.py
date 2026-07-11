"""Initial schema — all MechFix tables

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

# revision identifiers, used by Alembic
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -----------------------------------------------------------------
    # Enums (PostgreSQL only — SQLite uses VARCHAR)
    # -----------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE role_enum AS ENUM ('client', 'mechanic', 'admin');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE urgency_enum AS ENUM ('immediate', 'scheduled');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE request_status_enum AS ENUM ('pending', 'assigned', 'in_progress', 'completed', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE job_status_enum AS ENUM ('accepted', 'en_route', 'diagnosing', 'repairing', 'completed', 'cancelled');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE dispute_status_enum AS ENUM ('open', 'reviewing', 'resolved');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)

    # -----------------------------------------------------------------
    # users
    # -----------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            PgEnum("client", "mechanic", "admin", name="role_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # -----------------------------------------------------------------
    # client_profiles
    # -----------------------------------------------------------------
    op.create_table(
        "client_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("phone", sa.String(length=30), nullable=True, server_default=""),
        sa.Column("address", sa.String(length=500), nullable=True, server_default=""),
        sa.Column("avatar_url", sa.String(length=500), nullable=True, server_default=""),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    # -----------------------------------------------------------------
    # mechanic_profiles
    # -----------------------------------------------------------------
    op.create_table(
        "mechanic_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("phone", sa.String(length=30), nullable=True, server_default=""),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("specialties", sa.JSON(), nullable=True),
        sa.Column("years_experience", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("hourly_rate", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("is_available", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("location", sa.String(length=500), nullable=True, server_default=""),
        sa.Column("service_radius_miles", sa.Integer(), nullable=True, server_default="25"),
        sa.Column("avg_rating", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("total_jobs", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("avatar_url", sa.String(length=500), nullable=True, server_default=""),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    # -----------------------------------------------------------------
    # vehicles
    # -----------------------------------------------------------------
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("make", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(length=50), nullable=True, server_default=""),
        sa.Column("license_plate", sa.String(length=20), nullable=True, server_default=""),
        sa.Column("vin", sa.String(length=17), nullable=True, server_default=""),
        sa.Column("mileage", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vehicles_id", "vehicles", ["id"])

    # -----------------------------------------------------------------
    # service_requests
    # -----------------------------------------------------------------
    op.create_table(
        "service_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=500), nullable=False),
        sa.Column(
            "urgency",
            PgEnum("immediate", "scheduled", name="urgency_enum", create_type=False),
            nullable=True,
            server_default="scheduled",
        ),
        sa.Column("scheduled_date", sa.DateTime(), nullable=True),
        sa.Column("budget_min", sa.Float(), nullable=True),
        sa.Column("budget_max", sa.Float(), nullable=True),
        sa.Column(
            "status",
            PgEnum(
                "pending", "assigned", "in_progress", "completed", "cancelled",
                name="request_status_enum", create_type=False
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_requests_id", "service_requests", ["id"])

    # -----------------------------------------------------------------
    # jobs
    # -----------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("mechanic_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            PgEnum(
                "accepted", "en_route", "diagnosing", "repairing", "completed", "cancelled",
                name="job_status_enum", create_type=False
            ),
            nullable=False,
            server_default="accepted",
        ),
        sa.Column("mechanic_notes", sa.Text(), nullable=True),
        sa.Column("final_price", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["mechanic_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["service_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_jobs_id", "jobs", ["id"])

    # -----------------------------------------------------------------
    # messages
    # -----------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_id", "messages", ["id"])

    # -----------------------------------------------------------------
    # reviews
    # -----------------------------------------------------------------
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("mechanic_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mechanic_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )

    # -----------------------------------------------------------------
    # disputes
    # -----------------------------------------------------------------
    op.create_table(
        "disputes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("raised_by_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            PgEnum("open", "reviewing", "resolved", name="dispute_status_enum", create_type=False),
            nullable=True,
            server_default="open",
        ),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raised_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )


def downgrade() -> None:
    op.drop_table("disputes")
    op.drop_table("reviews")
    op.drop_table("messages")
    op.drop_table("jobs")
    op.drop_table("service_requests")
    op.drop_table("vehicles")
    op.drop_table("mechanic_profiles")
    op.drop_table("client_profiles")
    op.drop_table("users")

    # Drop enums (PostgreSQL only)
    op.execute("DROP TYPE IF EXISTS dispute_status_enum")
    op.execute("DROP TYPE IF EXISTS job_status_enum")
    op.execute("DROP TYPE IF EXISTS request_status_enum")
    op.execute("DROP TYPE IF EXISTS urgency_enum")
    op.execute("DROP TYPE IF EXISTS role_enum")
