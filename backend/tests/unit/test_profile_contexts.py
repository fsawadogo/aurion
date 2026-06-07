"""Unit tests for the visit-type → context → template foundation (#313, B1;
#318, B3).

Locks (pure, no DB — exercises the pydantic models + helpers directly):
  * ``VisitTypeContext`` label validation has parity with custom
    consultation-type labels (shared ``_validate_consultation_type``).
  * ``template_key`` membership gate (must be a built-in template).
  * ``template_ref`` is now PRESERVED (#318 / B3) and is mutually
    exclusive with ``template_key``; its ownership + existence check
    lives at PUT time (see ``tests/integration/test_context_custom_template.py``).
  * Orphan visit-type keys are pruned against the request's
    ``consultation_types``; built-in keys always survive.
  * Context ids are server-assigned when absent/malformed and preserved
    when well-formed.
  * 30-contexts-per-visit-type soft cap.
  * ``_diff_contexts`` returns AGGREGATE COUNTS ONLY (seven counts,
    incl. the B3 custom-template pair), and the
    ``PROFILE_CONTEXTS_UPDATED`` audit whitelist carries no free text.
"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from app.api.v1.profile import (
    _MAX_CONTEXTS_PER_VISIT_TYPE,
    UpdateProfileRequest,
    VisitTypeContext,
    _diff_contexts,
)
from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
    validate_audit_kwargs,
)
from app.modules.note_gen.service import list_available_templates

_ID_RE = re.compile(r"^ctx_[0-9a-f]{8}$")

# A template key guaranteed to exist on disk; assert the assumption so a
# template-file rename surfaces here rather than as a silent miss.
_BUILTIN_TEMPLATE = "orthopedic_surgery"


def test_builtin_template_assumption_holds() -> None:
    assert _BUILTIN_TEMPLATE in list_available_templates()


# ── VisitTypeContext: label validation parity ────────────────────────────


@pytest.mark.parametrize(
    "label",
    ["LL", "Breast visit", "Pre-op", "LL new pt", "Lower limb"],
)
def test_visitTypeContext_acceptsReasonableLabels(label: str) -> None:
    """Same labels the consultation-type gate accepts pass here too."""
    ctx = VisitTypeContext(label=label)
    assert ctx.label == label


def test_visitTypeContext_stripsLabelWhitespace() -> None:
    ctx = VisitTypeContext(label="  Breast  ")
    assert ctx.label == "Breast"


@pytest.mark.parametrize(
    "bad_label,leak_phrase",
    [
        ("Marie Gdalevitch", "full name"),
        ("perry@clinic.lan", "email"),
        ("123-45-6789", "SSN"),
        ("123456789", "SSN"),
        ("X" * 61, "61"),  # over the 60-char cap
    ],
)
def test_visitTypeContext_rejectsPHIShapedLabels(
    bad_label: str, leak_phrase: str
) -> None:
    """SSN / email / full-name / over-long labels are rejected, and the
    rejected value never echoes in the error (hide_input_in_errors)."""
    with pytest.raises(ValidationError) as exc:
        VisitTypeContext(label=bad_label)
    assert bad_label not in str(exc.value)


def test_visitTypeContext_rejectsBlankLabel() -> None:
    with pytest.raises(ValidationError):
        VisitTypeContext(label="   ")


# ── VisitTypeContext: template_key membership + template_ref nulling ──────


def test_visitTypeContext_acceptsBuiltinTemplateKey() -> None:
    ctx = VisitTypeContext(label="LL", template_key=_BUILTIN_TEMPLATE)
    assert ctx.template_key == _BUILTIN_TEMPLATE


def test_visitTypeContext_nullTemplateKeyAllowed() -> None:
    ctx = VisitTypeContext(label="LL")
    assert ctx.template_key is None


def test_visitTypeContext_rejectsUnknownTemplateKey() -> None:
    with pytest.raises(ValidationError):
        VisitTypeContext(label="LL", template_key="not_a_real_template_xyz")


def test_visitTypeContext_acceptsTemplateRefAlone() -> None:
    """A ``template_ref`` alone (no ``template_key``) is now PRESERVED
    (#318 / B3) — it's no longer forced to None. Ownership + existence is
    validated at PUT time, not in the model."""
    ref = "a1b2c3d4-0000-0000-0000-000000000000"
    ctx = VisitTypeContext(label="LL", template_ref=ref)
    assert ctx.template_ref == ref
    assert ctx.template_key is None


def test_visitTypeContext_blankTemplateRefNormalizesToNone() -> None:
    """A whitespace-only ``template_ref`` reads as 'no ref' (None), so it
    doesn't trip the mutual-exclusion gate or the PUT-time lookup."""
    ctx = VisitTypeContext(label="LL", template_ref="   ")
    assert ctx.template_ref is None


def test_visitTypeContext_rejectsBothTemplateKeyAndRef() -> None:
    """Mutual exclusion (#318 / B3): a context binds EITHER a built-in
    ``template_key`` OR a custom ``template_ref`` — never both. The
    rejected values never echo (hide_input_in_errors)."""
    secret_ref = "a1b2c3d4-0000-0000-0000-000000000000"
    with pytest.raises(ValidationError) as exc:
        VisitTypeContext(
            label="LL",
            template_key=_BUILTIN_TEMPLATE,
            template_ref=secret_ref,
        )
    assert secret_ref not in str(exc.value)


# ── VisitTypeContext: id assignment + preservation ────────────────────────


def test_visitTypeContext_assignsIdWhenAbsent() -> None:
    ctx = VisitTypeContext(label="LL")
    assert _ID_RE.match(ctx.id), ctx.id


def test_visitTypeContext_preservesWellFormedId() -> None:
    ctx = VisitTypeContext(id="ctx_1a2b3c4d", label="LL")
    assert ctx.id == "ctx_1a2b3c4d"


@pytest.mark.parametrize(
    "bad_id",
    ["evil PHI value", "ctx_NOTHEX1", "ctx_123", "12345678", ""],
)
def test_visitTypeContext_regeneratesMalformedId(bad_id: str) -> None:
    """A client can't smuggle free text into the id field — anything that
    isn't ``ctx_<8 hex>`` is regenerated server-side."""
    ctx = VisitTypeContext(id=bad_id, label="LL")
    assert _ID_RE.match(ctx.id), ctx.id
    assert ctx.id != bad_id


def test_visitTypeContext_assignedIdsAreUnique() -> None:
    ids = {VisitTypeContext(label="LL").id for _ in range(50)}
    assert len(ids) == 50


# ── UpdateProfileRequest: orphan prune ────────────────────────────────────


def test_update_prunesOrphanCustomKeys() -> None:
    """A context keyed under a custom visit type NOT present in the
    request's consultation_types is dropped; a present custom + the
    built-in default both survive."""
    req = UpdateProfileRequest(
        consultation_types=["new_patient", "Breast"],
        contexts_per_visit_type={
            "new_patient": [{"label": "LL"}],  # built-in → kept
            "Breast": [{"label": "Left"}],  # present custom → kept
            "Removed": [{"label": "stale"}],  # orphan custom → pruned
        },
    )
    keys = set(req.contexts_per_visit_type)
    assert keys == {"new_patient", "Breast"}


def test_update_builtinKeySurvivesWithoutConsultationTypes() -> None:
    """Built-in default keys are canonical even when the request omits
    consultation_types entirely; orphan customs still prune."""
    req = UpdateProfileRequest(
        contexts_per_visit_type={
            "follow_up": [{"label": "Routine"}],  # built-in → kept
            "Custom": [{"label": "x"}],  # no consult list → pruned
        },
    )
    assert set(req.contexts_per_visit_type) == {"follow_up"}


def test_update_noneContextsPassesThrough() -> None:
    req = UpdateProfileRequest(consultation_types=["new_patient"])
    assert req.contexts_per_visit_type is None


# ── UpdateProfileRequest: 30-cap ──────────────────────────────────────────


def test_update_acceptsUpToCap() -> None:
    contexts = [{"label": f"c{i}"} for i in range(_MAX_CONTEXTS_PER_VISIT_TYPE)]
    req = UpdateProfileRequest(
        consultation_types=["new_patient"],
        contexts_per_visit_type={"new_patient": contexts},
    )
    assert len(req.contexts_per_visit_type["new_patient"]) == (
        _MAX_CONTEXTS_PER_VISIT_TYPE
    )


def test_update_rejectsOverCap() -> None:
    contexts = [
        {"label": f"c{i}"} for i in range(_MAX_CONTEXTS_PER_VISIT_TYPE + 1)
    ]
    with pytest.raises(ValidationError):
        UpdateProfileRequest(
            consultation_types=["new_patient"],
            contexts_per_visit_type={"new_patient": contexts},
        )


def test_update_assignsAndKeepsIdsAcrossEdit() -> None:
    """First write mints an id; sending it back preserves it while a new
    sibling without an id gets its own."""
    first = UpdateProfileRequest(
        consultation_types=["new_patient"],
        contexts_per_visit_type={"new_patient": [{"label": "LL"}]},
    )
    minted = first.contexts_per_visit_type["new_patient"][0].id
    assert _ID_RE.match(minted)

    second = UpdateProfileRequest(
        consultation_types=["new_patient"],
        contexts_per_visit_type={
            "new_patient": [
                {"id": minted, "label": "LL (lower limb)"},  # preserved
                {"label": "Breast"},  # fresh id
            ]
        },
    )
    rows = second.contexts_per_visit_type["new_patient"]
    assert rows[0].id == minted
    assert _ID_RE.match(rows[1].id)
    assert rows[1].id != minted


# ── _diff_contexts: aggregate count deltas only ───────────────────────────


def _ctx(cid: str, label: str, tk=None) -> dict:
    return {
        "id": cid,
        "label": label,
        "template_key": tk,
        "template_ref": None,
    }


def test_diff_addContext() -> None:
    deltas = _diff_contexts(
        {},
        {"new_patient": [_ctx("ctx_00000001", "LL")]},
    )
    assert deltas == {
        "visit_types_touched": 1,
        "contexts_added": 1,
        "contexts_removed": 0,
        "templates_attached": 0,
        "templates_detached": 0,
        "custom_templates_attached": 0,
        "custom_templates_detached": 0,
    }


def test_diff_addContextWithTemplate() -> None:
    deltas = _diff_contexts(
        {},
        {"new_patient": [_ctx("ctx_00000001", "LL", _BUILTIN_TEMPLATE)]},
    )
    assert deltas["contexts_added"] == 1
    assert deltas["templates_attached"] == 1
    assert deltas["templates_detached"] == 0


def test_diff_removeContextWithTemplate() -> None:
    before = {"new_patient": [_ctx("ctx_00000001", "LL", _BUILTIN_TEMPLATE)]}
    deltas = _diff_contexts(before, {})
    assert deltas["contexts_removed"] == 1
    assert deltas["templates_detached"] == 1
    assert deltas["templates_attached"] == 0
    assert deltas["visit_types_touched"] == 1


def test_diff_attachTemplateInPlace() -> None:
    before = {"new_patient": [_ctx("ctx_00000001", "LL")]}
    after = {"new_patient": [_ctx("ctx_00000001", "LL", _BUILTIN_TEMPLATE)]}
    deltas = _diff_contexts(before, after)
    assert deltas["contexts_added"] == 0
    assert deltas["contexts_removed"] == 0
    assert deltas["templates_attached"] == 1
    assert deltas["templates_detached"] == 0
    assert deltas["visit_types_touched"] == 1


def test_diff_labelEditInPlaceTouchesVisitTypeOnly() -> None:
    before = {"new_patient": [_ctx("ctx_00000001", "LL")]}
    after = {"new_patient": [_ctx("ctx_00000001", "Lower limb")]}
    deltas = _diff_contexts(before, after)
    assert deltas["visit_types_touched"] == 1
    assert deltas["contexts_added"] == 0
    assert deltas["contexts_removed"] == 0
    assert deltas["templates_attached"] == 0
    assert deltas["templates_detached"] == 0


def test_diff_noChangeIsAllZero() -> None:
    same = {"new_patient": [_ctx("ctx_00000001", "LL", _BUILTIN_TEMPLATE)]}
    deltas = _diff_contexts(same, dict(same))
    assert all(v == 0 for v in deltas.values())


def test_diff_returnsOnlyCountFields_noFreeText() -> None:
    """The diff payload must be COUNTS ONLY — no labels, keys, ids, or
    template names leak through."""
    before = {"new_patient": [_ctx("ctx_00000001", "SecretLabelLL")]}
    after = {
        "Breast": [_ctx("ctx_00000002", "AnotherSecret", _BUILTIN_TEMPLATE)]
    }
    deltas = _diff_contexts(before, after)
    assert set(deltas) == {
        "visit_types_touched",
        "contexts_added",
        "contexts_removed",
        "templates_attached",
        "templates_detached",
        "custom_templates_attached",
        "custom_templates_detached",
    }
    assert all(isinstance(v, int) for v in deltas.values())
    blob = repr(deltas)
    assert "SecretLabelLL" not in blob
    assert "AnotherSecret" not in blob
    assert _BUILTIN_TEMPLATE not in blob
    assert "ctx_00000001" not in blob


# ── Audit contract ────────────────────────────────────────────────────────


def test_audit_eventTypeExists() -> None:
    assert AuditEventType.PROFILE_CONTEXTS_UPDATED == "profile_contexts_updated"


def test_audit_whitelistIsCountsPlusActorOnly() -> None:
    """The whitelist must be exactly actor_id + the seven aggregate
    counts (incl. the #318 / B3 custom-template pair) — no field that
    could carry a label/key/ref/id/template name."""
    assert ALLOWED_AUDIT_KWARGS[AuditEventType.PROFILE_CONTEXTS_UPDATED] == (
        frozenset(
            {
                "actor_id",
                "visit_types_touched",
                "contexts_added",
                "contexts_removed",
                "templates_attached",
                "templates_detached",
                "custom_templates_attached",
                "custom_templates_detached",
            }
        )
    )


def test_audit_emittedKwargsMatchWhitelist() -> None:
    """The kwargs the route would emit (actor_id + diff keys) are all
    whitelisted, and a stray label kwarg would be flagged."""
    deltas = _diff_contexts({}, {"new_patient": [_ctx("ctx_00000001", "LL")]})
    emitted = {"actor_id": "uuid", **deltas}
    assert validate_audit_kwargs(
        AuditEventType.PROFILE_CONTEXTS_UPDATED, emitted.keys()
    ) == set()
    # A label would be rejected by the whitelist.
    assert validate_audit_kwargs(
        AuditEventType.PROFILE_CONTEXTS_UPDATED, ["label"]
    ) == {"label"}
