#!/usr/bin/env python3
"""Tests for `build_postman_collection.py`.

Runs as a plain script (`python3 scripts/test_build_postman_collection.py`)
and as a pytest module. Either invocation exits non-zero on failure.

What we check
-------------
1. Generator runs without error.
2. Every OpenAPI path appears in the generated collection (matched by
   `url.raw` ending in the OpenAPI path with `{x}` rewritten to `:x`).
3. Every `{path_param}` from the spec ends up as a collection
   variable.
4. The probe endpoint specifically: body mode is `formdata`, `clip`
   field is type `file`, optional `provider_override` is type `text`.
5. Re-running the generator yields byte-identical output (idempotence).
6. Top-level shape matches Postman v2.1 (`info`, `item`, `auth`,
   `variable`, `event` keys present; `info` carries `_postman_id`,
   `name`, `schema`).

We deliberately do not pull the canonical v2.1 JSON schema over the
network — CI flakiness isn't worth it. The structural checks here
are exactly what Postman validates on import.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_postman_collection.py"
SPEC_PATH = REPO_ROOT / "docs" / "dev" / "postman" / "source-openapi.json"


def _run_generator(out_dir: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            str(SPEC_PATH),
            "--out-dir",
            str(out_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _load_collection(out_dir: Path) -> dict:
    return json.loads(
        (out_dir / "Aurion-API.postman_collection.json").read_text(encoding="utf-8")
    )


def _walk_requests(items):
    """Recursively yield every request-bearing leaf item."""

    for item in items:
        if "request" in item:
            yield item
        if "item" in item:
            yield from _walk_requests(item["item"])


def _all_request_urls(collection: dict) -> list[str]:
    return [
        item["request"]["url"]["raw"]
        for item in _walk_requests(collection["item"])
    ]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_generator_runs_and_produces_three_files(out_dir: Path) -> None:
    _run_generator(out_dir)
    assert (out_dir / "Aurion-API.postman_collection.json").is_file()
    assert (out_dir / "Aurion-Dev.postman_environment.json").is_file()
    assert (out_dir / "Aurion-Local.postman_environment.json").is_file()


def test_collection_shape_is_postman_v21(out_dir: Path) -> None:
    coll = _load_collection(out_dir)
    for key in ("info", "item", "auth", "variable", "event"):
        assert key in coll, f"missing top-level key: {key}"
    info = coll["info"]
    assert "_postman_id" in info
    assert info["name"] == "Aurion API (Dev)"
    assert info["schema"] == (
        "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    )
    assert coll["auth"]["type"] == "bearer"


def test_every_openapi_path_appears_in_collection(out_dir: Path) -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    coll = _load_collection(out_dir)
    raw_urls = _all_request_urls(coll)
    for openapi_path in spec["paths"]:
        # OpenAPI path `/api/v1/sessions/{session_id}` becomes the
        # Postman `url.raw` `{{base_url}}/api/v1/sessions/:session_id`.
        postman_suffix = openapi_path.replace("{", ":").replace("}", "")
        expected_substring = f"{{{{base_url}}}}{postman_suffix}"
        matches = [u for u in raw_urls if u == expected_substring]
        assert matches, (
            f"OpenAPI path missing from collection: {openapi_path}"
            f" (expected url.raw = {expected_substring})"
        )


def test_every_path_param_is_a_collection_variable(out_dir: Path) -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    coll = _load_collection(out_dir)

    declared_params: set[str] = set()
    for openapi_path in spec["paths"]:
        for seg in openapi_path.split("/"):
            if seg.startswith("{") and seg.endswith("}"):
                declared_params.add(seg[1:-1])

    collection_vars = {entry["key"] for entry in coll["variable"]}
    missing = declared_params - collection_vars
    assert not missing, f"missing collection variables: {sorted(missing)}"


def test_probe_endpoint_has_correct_formdata(out_dir: Path) -> None:
    coll = _load_collection(out_dir)
    probe = None
    for item in _walk_requests(coll["item"]):
        url = item["request"]["url"]["raw"]
        if url.endswith("/api/v1/admin/probe/vision-clip"):
            probe = item
            break
    assert probe is not None, "probe endpoint not found in collection"

    body = probe["request"].get("body") or {}
    assert body.get("mode") == "formdata", f"probe body mode: {body.get('mode')}"

    formdata = body["formdata"]
    by_key = {entry["key"]: entry for entry in formdata}

    # `clip` must be a file field — anything else means the converter
    # missed the contentMediaType=application/octet-stream signal.
    assert "clip" in by_key, "probe body missing `clip` field"
    assert by_key["clip"]["type"] == "file", (
        f"probe `clip` field type should be 'file', got "
        f"{by_key['clip']['type']}"
    )

    # `provider_override` is optional → ships disabled.
    assert "provider_override" in by_key
    assert by_key["provider_override"]["type"] == "text"
    assert by_key["provider_override"].get("disabled") is True, (
        "provider_override should be disabled by default (optional field)"
    )


def test_generator_is_idempotent(out_dir: Path) -> None:
    coll_before = (out_dir / "Aurion-API.postman_collection.json").read_bytes()
    env_before = (out_dir / "Aurion-Dev.postman_environment.json").read_bytes()
    _run_generator(out_dir)
    coll_after = (out_dir / "Aurion-API.postman_collection.json").read_bytes()
    env_after = (out_dir / "Aurion-Dev.postman_environment.json").read_bytes()
    assert coll_before == coll_after, "collection JSON changed on rerun"
    assert env_before == env_after, "environment JSON changed on rerun"


def test_dev_env_points_at_dev_host(out_dir: Path) -> None:
    env = json.loads(
        (out_dir / "Aurion-Dev.postman_environment.json").read_text(encoding="utf-8")
    )
    by_key = {v["key"]: v for v in env["values"]}
    assert by_key["base_url"]["value"] == "https://api-dev.aurionclinical.com"
    assert by_key["jwt"]["type"] == "secret"
    assert by_key["jwt"]["value"] == ""


def test_local_env_points_at_localhost(out_dir: Path) -> None:
    env = json.loads(
        (out_dir / "Aurion-Local.postman_environment.json").read_text(encoding="utf-8")
    )
    by_key = {v["key"]: v for v in env["values"]}
    assert by_key["base_url"]["value"] == "http://localhost:8080"


# --------------------------------------------------------------------------- #
# pytest wiring
# --------------------------------------------------------------------------- #


def _pytest_fixture():
    """Lazy pytest fixture — only imported if pytest is the runner."""

    import pytest  # type: ignore[import-not-found]

    @pytest.fixture(scope="module")
    def out_dir(tmp_path_factory):
        d = tmp_path_factory.mktemp("postman-out")
        _run_generator(d)
        return d

    return out_dir


# Make the pytest fixture available when collected by pytest, without
# making pytest a hard requirement to run this file as a script.
try:
    out_dir = _pytest_fixture()
except Exception:  # noqa: BLE001 — pytest not installed; fall back to main()
    pass


# --------------------------------------------------------------------------- #
# Script-mode entrypoint
# --------------------------------------------------------------------------- #


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="postman-test-"))
    try:
        tests = [
            test_generator_runs_and_produces_three_files,
            test_collection_shape_is_postman_v21,
            test_every_openapi_path_appears_in_collection,
            test_every_path_param_is_a_collection_variable,
            test_probe_endpoint_has_correct_formdata,
            test_generator_is_idempotent,
            test_dev_env_points_at_dev_host,
            test_local_env_points_at_localhost,
        ]
        failed = 0
        for fn in tests:
            try:
                fn(tmp)
                print(f"  PASS  {fn.__name__}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {fn.__name__}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  ERROR {fn.__name__}: {exc!r}")
        if failed:
            print(f"\n{failed} failure(s).")
            return 1
        print(f"\nAll {len(tests)} tests passed.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
