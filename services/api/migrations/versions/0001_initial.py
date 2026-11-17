"""initial evidence schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluations",
        sa.Column("trace_id", sa.String(64), primary_key=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_mode", sa.String(16), nullable=False),
        sa.Column("fixture_id", sa.String(64)),
        sa.Column("studio_revision", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("subsystems", sa.JSON, nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("body", sa.JSON, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
    )
    for col in ("task", "status", "evaluated_at", "severity"):
        op.create_index(f"ix_evaluations_{col}", "evaluations", [col])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subsystem", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("data", sa.JSON, nullable=False),
    )
    for col in ("at", "subsystem", "severity", "trace_id"):
        op.create_index(f"ix_events_{col}", "events", [col])
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("args", sa.JSON, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("result_summary", sa.Text, nullable=False),
    )
    op.create_index("ix_tool_calls_trace_id", "tool_calls", ["trace_id"])


def downgrade():
    op.drop_table("tool_calls")
    op.drop_table("events")
    op.drop_table("evaluations")
