"""Unit tests for the adoption & ROI analytics rollup (#71, slice 1).

The aggregation is factored into pure functions (`aggregate_adoption`,
`parse_edit_rate`, `adoption_csv`) operating on plain dataclasses, so the
math is tested without a DB; the route itself is covered by a registration
check + the response-schema shape (mirrors test_metrics_timeseries.py).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone

from app.api.v1.admin.analytics import (
    MetricRow,
    SessionAgg,
    adoption_csv,
    aggregate_adoption,
    parse_edit_rate,
)


def test_adoption_endpoint_registered() -> None:
    from app.api.v1.admin.analytics import router

    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert ("/admin/analytics/adoption", ("GET",)) in paths


def _agg(cid=None, total=5, exported=4, days=2, last=None) -> SessionAgg:
    return SessionAgg(
        clinician_id=cid or uuid.uuid4(),
        sessions_total=total,
        sessions_exported=exported,
        active_days=days,
        last_active_at=last,
    )


def _metric(cid, comp=0.9, cite=0.95, edits='{"hpi": 0.2, "plan": 0.4}',
            s1=20_000, s2=120_000) -> MetricRow:
    return MetricRow(
        clinician_id=cid,
        template_section_completeness=comp,
        citation_traceability_rate=cite,
        physician_edit_rate_json=edits,
        stage1_latency_ms=s1,
        stage2_latency_ms=s2,
    )


# ── parse_edit_rate ──────────────────────────────────────────────────────────


def test_edit_rate_dict_means_section_values() -> None:
    assert abs(parse_edit_rate('{"a": 0.2, "b": 0.4}') - 0.3) < 1e-9


def test_edit_rate_bare_number_and_garbage() -> None:
    assert parse_edit_rate("0.25") == 0.25
    assert parse_edit_rate(None) is None
    assert parse_edit_rate("not json") is None
    assert parse_edit_rate("{}") is None
    # Non-numeric section values are skipped, not crashed on.
    assert parse_edit_rate('{"a": "high", "b": 0.5}') == 0.5


# ── aggregate_adoption ───────────────────────────────────────────────────────


def test_per_clinician_join_and_derived_fields() -> None:
    cid = uuid.uuid4()
    last = datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc)
    resp = aggregate_adoption(
        [_agg(cid=cid, total=6, exported=4, days=2, last=last)],
        [_metric(cid), _metric(cid, comp=0.7, cite=None, edits=None, s1=None, s2=None)],
        {cid: "marie@aurionclinical.com"},
        since=None, until=None, baseline_minutes_per_note=None,
    )
    row = resp.by_clinician[0]
    assert row.email == "marie@aurionclinical.com"
    assert row.sessions_total == 6
    assert row.sessions_exported == 4
    assert row.notes_per_active_day == 2.0          # 4 exported / 2 active days
    assert abs(row.avg_completeness - 0.8) < 1e-9   # mean(0.9, 0.7)
    assert row.avg_citation_traceability == 0.95    # null skipped from mean
    assert abs(row.avg_edit_rate - 0.3) < 1e-9      # one parseable dict
    assert row.avg_stage1_latency_ms == 20_000.0
    assert row.last_active_at == last.isoformat()
    assert row.time_saved_minutes is None           # no baseline given
    assert resp.totals.active_clinicians == 1
    assert resp.totals.time_saved_minutes is None


def test_time_saved_only_with_explicit_baseline() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    resp = aggregate_adoption(
        [_agg(cid=a, exported=4), _agg(cid=b, exported=6)],
        [],
        {},
        since=None, until=None, baseline_minutes_per_note=12.5,
    )
    # Echoed assumption + per-clinician and aggregate estimates.
    assert resp.baseline_minutes_per_note == 12.5
    assert resp.totals.time_saved_minutes == 125.0      # 10 notes × 12.5
    by_id = {r.clinician_id: r for r in resp.by_clinician}
    assert by_id[str(a)].time_saved_minutes == 50.0
    assert by_id[str(b)].time_saved_minutes == 75.0


def test_aggregate_notes_per_day_uses_clinician_days() -> None:
    # Two clinicians, each 3 active days, 3 exported each:
    # aggregate = 6 notes / 6 clinician-days = 1.0 (not 6/3=2.0).
    resp = aggregate_adoption(
        [_agg(exported=3, days=3), _agg(exported=3, days=3)],
        [], {}, since=None, until=None, baseline_minutes_per_note=None,
    )
    assert resp.totals.notes_per_active_day == 1.0


def test_zero_division_guards() -> None:
    resp = aggregate_adoption(
        [_agg(total=1, exported=0, days=0)],
        [], {}, since=None, until=None, baseline_minutes_per_note=None,
    )
    assert resp.by_clinician[0].notes_per_active_day == 0.0
    assert resp.totals.notes_per_active_day == 0.0
    # No metric rows → quality averages are null, not 0 (absence ≠ zero).
    assert resp.totals.avg_completeness is None
    assert resp.totals.avg_edit_rate is None


def test_rows_sorted_by_sessions_desc() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    resp = aggregate_adoption(
        [_agg(cid=a, total=2), _agg(cid=b, total=9)],
        [], {}, since=None, until=None, baseline_minutes_per_note=None,
    )
    assert [r.clinician_id for r in resp.by_clinician] == [str(b), str(a)]


def test_metrics_for_unknown_clinician_count_in_totals_only() -> None:
    """A pilot_metrics row whose clinician has no sessions in the window
    still feeds the aggregate quality averages (totals reflect the window's
    metric rows), but creates no per-clinician row."""
    known, stray = uuid.uuid4(), uuid.uuid4()
    resp = aggregate_adoption(
        [_agg(cid=known)],
        [_metric(known, comp=0.9), _metric(stray, comp=0.5)],
        {}, since=None, until=None, baseline_minutes_per_note=None,
    )
    assert len(resp.by_clinician) == 1
    assert abs(resp.totals.avg_completeness - 0.7) < 1e-9  # mean(0.9, 0.5)


# ── CSV export ───────────────────────────────────────────────────────────────


def test_csv_shape_and_total_row() -> None:
    cid = uuid.uuid4()
    resp = aggregate_adoption(
        [_agg(cid=cid, total=6, exported=4, days=2)],
        [_metric(cid)],
        {cid: "perry@aurionclinical.com"},
        since=None, until=None, baseline_minutes_per_note=10.0,
    )
    rows = list(csv.reader(io.StringIO(adoption_csv(resp))))
    header, body, total = rows[0], rows[1], rows[2]
    assert header[0] == "clinician_id"
    assert body[1] == "perry@aurionclinical.com"
    assert body[3] == "4"                  # sessions_exported
    assert total[0] == "TOTAL"
    assert total[3] == "4"
    assert total[11] == "40.0"             # 4 notes × 10 min
    # Nulls render as empty cells, never "None".
    assert "None" not in adoption_csv(resp)
