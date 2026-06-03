"""pilot_metrics — clip-aware columns (P1-FU-METRICS)

Adds 5 nullable, additive columns to the existing ``pilot_metrics`` table
so the eval team can quantify clip processing per session:

- ``clip_count``                            — # of clip-kind evidence items
- ``clip_bytes_uploaded``                   — total uploaded MP4 bytes
- ``clip_avg_latency_ms``                   — mean per-clip ``caption_clip`` latency
- ``clip_vision_spend_estimate_usd_micros`` — Σ(input + output token spend),
                                               stored as USD micros (integer
                                               so arithmetic is precise)
- ``clip_degraded_to_frame_count``          — # of citations where the clip
                                               provider fell back to a midpoint
                                               still (``degraded_to_frame=True``)

All five are nullable. ``clip_count``, ``clip_bytes_uploaded``, and
``clip_degraded_to_frame_count`` default to ``0`` server-side so old rows
decode predictably; the two means/sums (latency, spend) stay null because
"no clips processed" should not be confused with "0 ms" or "$0".

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the 5 clip-aware columns. All nullable, additive — no backfill."""
    op.add_column(
        "pilot_metrics",
        sa.Column(
            "clip_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "pilot_metrics",
        sa.Column(
            "clip_bytes_uploaded",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
    )
    # Mean latency stays NULL until we record at least one clip — "no
    # clips processed" must not collapse to "0 ms".
    op.add_column(
        "pilot_metrics",
        sa.Column(
            "clip_avg_latency_ms",
            sa.Integer(),
            nullable=True,
        ),
    )
    # USD micros (1 USD = 1_000_000 micros) — integer so arithmetic stays
    # precise. NULL until at least one clip was priced (token plumbing
    # ships in a follow-up; today this lands as 0 once any clip is processed).
    op.add_column(
        "pilot_metrics",
        sa.Column(
            "clip_vision_spend_estimate_usd_micros",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "pilot_metrics",
        sa.Column(
            "clip_degraded_to_frame_count",
            sa.Integer(),
            nullable=True,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Drop the 5 columns. Reversible."""
    op.drop_column("pilot_metrics", "clip_degraded_to_frame_count")
    op.drop_column("pilot_metrics", "clip_vision_spend_estimate_usd_micros")
    op.drop_column("pilot_metrics", "clip_avg_latency_ms")
    op.drop_column("pilot_metrics", "clip_bytes_uploaded")
    op.drop_column("pilot_metrics", "clip_count")
