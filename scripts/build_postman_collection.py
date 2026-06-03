#!/usr/bin/env python3
"""Convert the Aurion OpenAPI v3 spec into a Postman Collection v2.1.

Inputs
------
* `docs/dev/postman/source-openapi.json` — the snapshot of the live
  dev API's OpenAPI v3 document. Override via argv[1].

Outputs (all under `docs/dev/postman/`)
---------------------------------------
* `Aurion-API.postman_collection.json`  — Postman Collection v2.1.
* `Aurion-Dev.postman_environment.json` — env pointing at `https://api-dev.aurionclinical.com`.
* `Aurion-Local.postman_environment.json` — env pointing at `http://localhost:8080`.

Design notes
------------
* No third-party deps: stdlib only, so this runs anywhere — CI, a
  fresh clone, a Docker sidecar.
* Idempotent: stable IDs derived from `sha1(method + path)`, sorted
  keys on JSON dump, no timestamps, no GUIDs. Re-running yields
  byte-identical files.
* Auth at collection root only (Bearer `{{jwt}}`) — every nested
  request inherits.
* Folders mirror OpenAPI tags. Untagged ops bucket under "untagged".
* Multipart bodies: a `string` schema with
  `contentMediaType: application/octet-stream` becomes a Postman
  `formdata.file` entry; everything else becomes a `text` entry.
* JSON bodies: synthesized from the referenced schema using zero-
  values keyed by `type` (string→"", integer→0, etc.), preferring
  `example` when supplied.
* Path parameters become Postman `:var` slugs bound to collection
  variables of the same name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

POSTMAN_SCHEMA = (
    "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
)

DEV_BASE_URL = "https://api-dev.aurionclinical.com"
LOCAL_BASE_URL = "http://localhost:8080"

# Placeholder values per known path-parameter name. Anything not listed
# falls back to the generic UUID placeholder. UUIDs are all-zeros so
# they're obviously placeholders and never collide with real session
# IDs in audit search.
PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"
PATH_PARAM_DEFAULTS: dict[str, str] = {
    "session_id": PLACEHOLDER_UUID,
    "note_id": PLACEHOLDER_UUID,
    "user_id": PLACEHOLDER_UUID,
    "report_id": PLACEHOLDER_UUID,
    "template_id": PLACEHOLDER_UUID,
    "macro_id": PLACEHOLDER_UUID,
    "order_id": PLACEHOLDER_UUID,
    "suggestion_id": PLACEHOLDER_UUID,
    "claim_id": PLACEHOLDER_UUID,
    "template_key": "orthopedic_surgery",
    "provider_type": "vision",
    "identifier": "patient-placeholder",
}

PRE_REQUEST_SCRIPT = """\
if (!pm.environment.get('jwt')) {
  console.warn('[Aurion] No JWT set. See docs/dev/postman/README.md → \"Mint a JWT\".');
}
"""

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def stable_id(*parts: str) -> str:
    """SHA1 over the joined parts; first 24 hex chars."""

    h = hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()
    return h[:24]


def resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a local `#/components/...` JSON pointer."""

    assert ref.startswith("#/"), f"non-local $ref unsupported: {ref}"
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def is_file_field(schema: dict[str, Any]) -> bool:
    """Heuristic for multipart file fields.

    OpenAPI v3 marks file uploads as `string` with
    `contentMediaType: application/octet-stream`. FastAPI emits this
    for `UploadFile` parameters.
    """

    if schema.get("type") == "string" and schema.get("contentMediaType"):
        return schema["contentMediaType"] in (
            "application/octet-stream",
            "video/mp4",
            "image/jpeg",
            "image/png",
        )
    # `anyOf` wrappers (e.g. optional file) — check children.
    for child in schema.get("anyOf", []) or schema.get("oneOf", []):
        if isinstance(child, dict) and is_file_field(child):
            return True
    return False


def zero_value(schema: dict[str, Any], spec: dict[str, Any]) -> Any:
    """Return a placeholder value matching the schema's type.

    Resolves `$ref` and prefers `example` when supplied. Recurses for
    objects and arrays. The output is for users to overwrite, so we
    optimize for "obviously a placeholder" over "actually valid"; e.g.
    enums emit the first option.
    """

    if "$ref" in schema:
        return zero_value(resolve_ref(spec, schema["$ref"]), spec)

    if "example" in schema:
        return schema["example"]

    if "default" in schema:
        return schema["default"]

    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    # `anyOf` / `oneOf` — pick the first non-null branch.
    for combinator in ("anyOf", "oneOf"):
        branches = schema.get(combinator)
        if branches:
            for branch in branches:
                if not (isinstance(branch, dict) and branch.get("type") == "null"):
                    return zero_value(branch, spec)
            return None

    schema_type = schema.get("type")
    if schema_type == "object":
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        out: dict[str, Any] = {}
        # Sort to keep output deterministic.
        for name in sorted(props.keys()):
            if required and name not in required:
                continue
            out[name] = zero_value(props[name], spec)
        return out
    if schema_type == "array":
        item_schema = schema.get("items", {}) or {}
        return [zero_value(item_schema, spec)]
    if schema_type == "string":
        fmt = schema.get("format")
        if fmt == "uuid":
            return PLACEHOLDER_UUID
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        if fmt == "date":
            return "2026-01-01"
        if fmt == "email":
            return "user@example.com"
        return ""
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "null":
        return None

    # Unknown / mixed — return empty object as a safe placeholder.
    return {}


# --------------------------------------------------------------------------- #
# Path / parameter conversion
# --------------------------------------------------------------------------- #


def to_postman_path(openapi_path: str) -> tuple[str, list[str]]:
    """Convert `/api/v1/foo/{bar}` to `/api/v1/foo/:bar` + list of vars."""

    segments: list[str] = []
    variables: list[str] = []
    for raw in openapi_path.split("/"):
        if not raw:
            continue
        if raw.startswith("{") and raw.endswith("}"):
            name = raw[1:-1]
            variables.append(name)
            segments.append(f":{name}")
        else:
            segments.append(raw)
    return "/" + "/".join(segments), variables


def collect_path_params(spec: dict[str, Any]) -> list[str]:
    """Every distinct `{param}` across every path in the spec."""

    seen: set[str] = set()
    for path in spec.get("paths", {}):
        for segment in path.split("/"):
            if segment.startswith("{") and segment.endswith("}"):
                seen.add(segment[1:-1])
    return sorted(seen)


# --------------------------------------------------------------------------- #
# Request body conversion
# --------------------------------------------------------------------------- #


def build_request_body(
    operation: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any] | None:
    """Translate the operation's requestBody into a Postman body block."""

    request_body = operation.get("requestBody")
    if not request_body:
        return None
    content = request_body.get("content", {}) or {}

    if "application/json" in content:
        media = content["application/json"]
        # Postman v2.1 raw JSON body.
        skeleton = media.get("example")
        if skeleton is None:
            schema = media.get("schema", {}) or {}
            skeleton = zero_value(schema, spec)
        raw = json.dumps(skeleton, indent=2, sort_keys=True)
        return {
            "mode": "raw",
            "raw": raw,
            "options": {"raw": {"language": "json"}},
        }

    if "multipart/form-data" in content:
        media = content["multipart/form-data"]
        schema = media.get("schema", {}) or {}
        if "$ref" in schema:
            schema = resolve_ref(spec, schema["$ref"])
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])

        formdata: list[dict[str, Any]] = []
        for name in sorted(props.keys()):
            field_schema = props[name]
            entry: dict[str, Any] = {"key": name}
            if is_file_field(field_schema):
                entry["type"] = "file"
                entry["src"] = []
                entry["description"] = (
                    "Attach a local file. For the vision-clip probe use "
                    "backend/tests/fixtures/probe_clip.mp4."
                )
            else:
                entry["type"] = "text"
                value = zero_value(field_schema, spec)
                if isinstance(value, (dict, list)):
                    entry["value"] = json.dumps(value, sort_keys=True)
                elif value is None:
                    entry["value"] = ""
                else:
                    entry["value"] = str(value)
            if required and name not in required:
                entry["disabled"] = True
            formdata.append(entry)
        return {"mode": "formdata", "formdata": formdata}

    if "application/x-www-form-urlencoded" in content:
        media = content["application/x-www-form-urlencoded"]
        schema = media.get("schema", {}) or {}
        if "$ref" in schema:
            schema = resolve_ref(spec, schema["$ref"])
        props = schema.get("properties", {}) or {}
        urlencoded = []
        for name in sorted(props.keys()):
            value = zero_value(props[name], spec)
            urlencoded.append(
                {
                    "key": name,
                    "value": "" if value is None else str(value),
                    "type": "text",
                }
            )
        return {"mode": "urlencoded", "urlencoded": urlencoded}

    # Unknown content type — surface as raw with the first media type.
    first_type = sorted(content.keys())[0]
    return {
        "mode": "raw",
        "raw": "",
        "options": {"raw": {"language": "text"}},
        "description": f"Body type {first_type} — populate manually.",
    }


# --------------------------------------------------------------------------- #
# Operation conversion
# --------------------------------------------------------------------------- #


def build_request_url(path: str, query_params: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the Postman `url` object."""

    postman_path, path_vars = to_postman_path(path)
    full = f"{{{{base_url}}}}{postman_path}"

    url_obj: dict[str, Any] = {
        "raw": full,
        "host": ["{{base_url}}"],
        "path": [seg for seg in postman_path.split("/") if seg],
    }
    if path_vars:
        url_obj["variable"] = [
            {"key": name, "value": f"{{{{{name}}}}}", "description": "Path parameter."}
            for name in path_vars
        ]
    if query_params:
        url_obj["query"] = query_params
    return url_obj


def build_operation_item(
    path: str, method: str, operation: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """Translate one OpenAPI operation into a Postman request item."""

    summary = operation.get("summary") or f"{method.upper()} {path}"
    description = operation.get("description") or ""
    full_description = description.strip()
    if not full_description:
        full_description = summary

    # Headers + query params from `parameters`.
    headers: list[dict[str, Any]] = []
    query: list[dict[str, Any]] = []
    for param in operation.get("parameters", []) or []:
        location = param.get("in")
        name = param.get("name")
        if not name:
            continue
        param_desc = param.get("description") or ""
        if location == "header":
            if name.lower() == "authorization":
                continue  # handled at collection root
            entry = {
                "key": name,
                "value": "",
                "description": param_desc,
            }
            if not param.get("required"):
                entry["disabled"] = True
            headers.append(entry)
        elif location == "query":
            example = ""
            schema = param.get("schema", {}) or {}
            value = zero_value(schema, spec)
            if value not in ("", None):
                example = str(value) if not isinstance(value, (dict, list)) else ""
            entry = {
                "key": name,
                "value": example,
                "description": param_desc,
            }
            if not param.get("required"):
                entry["disabled"] = True
            query.append(entry)

    body = build_request_body(operation, spec)
    if body and body.get("mode") == "raw":
        headers.insert(
            0,
            {
                "key": "Content-Type",
                "value": "application/json",
                "description": "Required for JSON request bodies.",
            },
        )

    request_obj: dict[str, Any] = {
        "method": method.upper(),
        "header": headers,
        "url": build_request_url(path, query),
        "description": full_description,
    }
    if body is not None:
        request_obj["body"] = body

    item: dict[str, Any] = {
        "name": summary,
        "id": stable_id("op", method, path),
        "request": request_obj,
        "response": [],
    }
    return item


# --------------------------------------------------------------------------- #
# Collection assembly
# --------------------------------------------------------------------------- #


def first_tag(operation: dict[str, Any]) -> str:
    tags = operation.get("tags") or []
    return tags[0] if tags else "untagged"


def build_collection(spec: dict[str, Any]) -> dict[str, Any]:
    """Top-level: assemble the Postman v2.1 collection JSON."""

    paths = spec.get("paths", {}) or {}

    # Bucket operations by their first tag.
    folders: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(paths.keys()):
        path_item = paths[path]
        for method in sorted(path_item.keys()):
            if method.startswith("x-"):
                continue
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            operation = path_item[method]
            tag = first_tag(operation)
            folders.setdefault(tag, []).append(
                build_operation_item(path, method, operation, spec)
            )

    # Render folders sorted by tag, items inside sorted by name.
    folder_items: list[dict[str, Any]] = []
    for tag in sorted(folders.keys()):
        children = sorted(folders[tag], key=lambda x: x["name"])
        folder_items.append(
            {
                "name": tag.title() if tag != "untagged" else "Untagged",
                "id": stable_id("folder", tag),
                "description": f"Endpoints tagged `{tag}` in the OpenAPI spec.",
                "item": children,
            }
        )

    # Collection-level variables: every distinct path param + base_url.
    path_params = collect_path_params(spec)
    variables: list[dict[str, Any]] = [
        {
            "key": "base_url",
            "value": DEV_BASE_URL,
            "type": "default",
            "description": "Override per-environment.",
        },
    ]
    for name in path_params:
        variables.append(
            {
                "key": name,
                "value": PATH_PARAM_DEFAULTS.get(name, PLACEHOLDER_UUID),
                "type": "default",
                "description": "Placeholder; replace with a real value before sending.",
            }
        )

    info = spec.get("info", {}) or {}
    title = info.get("title", "Aurion API")
    api_version = info.get("version", "0.0.0")
    collection = {
        "info": {
            "_postman_id": stable_id("collection", title, api_version),
            "name": "Aurion API (Dev)",
            "description": (
                f"{title} v{api_version} — generated from the deployed "
                "dev OpenAPI v3 spec. See `docs/dev/postman/README.md` for "
                "import and JWT instructions. Regenerate via "
                "`python3 scripts/build_postman_collection.py` after pulling "
                "a fresh `openapi.json`."
            ),
            "schema": POSTMAN_SCHEMA,
        },
        "item": folder_items,
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{jwt}}", "type": "string"}],
        },
        "event": [
            {
                "listen": "prerequest",
                "script": {
                    "type": "text/javascript",
                    "exec": PRE_REQUEST_SCRIPT.splitlines(),
                },
            }
        ],
        "variable": variables,
    }
    return collection


# --------------------------------------------------------------------------- #
# Environment files
# --------------------------------------------------------------------------- #


def build_environment(name: str, base_url: str, path_params: list[str]) -> dict[str, Any]:
    values: list[dict[str, Any]] = [
        {
            "key": "base_url",
            "value": base_url,
            "type": "default",
            "enabled": True,
        },
        {
            "key": "jwt",
            "value": "",
            "type": "secret",
            "enabled": True,
        },
    ]
    for param in path_params:
        values.append(
            {
                "key": param,
                "value": PATH_PARAM_DEFAULTS.get(param, PLACEHOLDER_UUID),
                "type": "default",
                "enabled": True,
            }
        )
    return {
        "id": stable_id("env", name),
        "name": name,
        "values": values,
        "_postman_variable_scope": "environment",
    }


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "spec",
        nargs="?",
        default="docs/dev/postman/source-openapi.json",
        help="Path to the OpenAPI v3 JSON spec.",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/dev/postman",
        help="Directory to write collection + environments into.",
    )
    args = parser.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"error: spec not found at {spec_path}", file=sys.stderr)
        return 1

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)

    collection = build_collection(spec)
    write_json(out_dir / "Aurion-API.postman_collection.json", collection)

    path_params = collect_path_params(spec)
    dev_env = build_environment("Aurion Dev", DEV_BASE_URL, path_params)
    local_env = build_environment("Aurion Local", LOCAL_BASE_URL, path_params)
    write_json(out_dir / "Aurion-Dev.postman_environment.json", dev_env)
    write_json(out_dir / "Aurion-Local.postman_environment.json", local_env)

    print(
        f"wrote {out_dir / 'Aurion-API.postman_collection.json'}\n"
        f"wrote {out_dir / 'Aurion-Dev.postman_environment.json'}\n"
        f"wrote {out_dir / 'Aurion-Local.postman_environment.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
