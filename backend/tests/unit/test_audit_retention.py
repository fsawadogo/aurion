"""Regression guard for the 7-year audit-log retention guarantee (#606).

The "Audit Log Viewer" feature promises **7-year retention** (Quebec
medical-records law). For the immutable DynamoDB audit table that means one
concrete, testable invariant: the table must carry **no TTL**, so audit
rows never auto-expire and the trail is retained indefinitely (well beyond
the ≥ 7-year floor the CloudTrail/logs bucket lifecycle already encodes).

DynamoDB TTL is the *only* mechanism that could silently delete audit rows
without an application-layer write (which is already forbidden — the table
is append-only). This test parses the Terraform and fails if a `ttl` block
is ever introduced on the audit table, turning a policy sentence into an
enforced, reviewable contract.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DYNAMODB_TF = _REPO_ROOT / "infrastructure" / "dynamodb.tf"


def _extract_resource_block(hcl: str, resource_label: str) -> str:
    """Return the `{ ... }` body of a Terraform resource by brace-matching
    from its declaration to the matching close brace."""
    marker = f'resource "aws_dynamodb_table" "{resource_label}"'
    start = hcl.index(marker)
    brace_open = hcl.index("{", start)
    depth = 0
    for i in range(brace_open, len(hcl)):
        if hcl[i] == "{":
            depth += 1
        elif hcl[i] == "}":
            depth -= 1
            if depth == 0:
                return hcl[brace_open : i + 1]
    raise AssertionError(f"Unbalanced braces in resource {resource_label!r}")


def _strip_comments(block: str) -> str:
    """Drop `# ...` line comments so the word 'ttl' inside the explanatory
    comment doesn't count as a TTL declaration."""
    return "\n".join(line.split("#", 1)[0] for line in block.splitlines())


def test_dynamodb_tf_exists() -> None:
    assert _DYNAMODB_TF.is_file(), f"missing {_DYNAMODB_TF}"


def test_audit_log_table_has_no_ttl() -> None:
    """The audit table must not declare a TTL — a `ttl` block would start
    expiring immutable audit rows and break the 7-year guarantee."""
    hcl = _DYNAMODB_TF.read_text(encoding="utf-8")
    block = _strip_comments(_extract_resource_block(hcl, "audit_log"))
    assert not re.search(r"\bttl\b", block), (
        "The aurion audit-log DynamoDB table declares a `ttl` — remove it. "
        "Audit rows must never auto-expire (7-year retention, #606)."
    )


def test_audit_log_retention_rationale_documented() -> None:
    """The 7-year retention floor must be documented at the audit table so
    the guarantee is discoverable in code, not only in policy docs."""
    hcl = _DYNAMODB_TF.read_text(encoding="utf-8")
    block = _extract_resource_block(hcl, "audit_log")
    assert "7-year" in block or "2555" in block, (
        "Document the 7-year audit retention floor next to the audit_log "
        "table so the no-TTL invariant is self-explaining."
    )
