"""EMR connector registry — maps a connector key to a concrete instance.

Mirrors the AI provider registry pattern; routes never instantiate a
connector directly. The foundation slice ships with only the `stub`
connector; real backends register themselves here in follow-up issues.

Per-clinic connector selection (different clinics may use different
EMRs) is post-pilot — for now `get_default_connector` returns the
single registered default. AppConfig-driven selection comes next.
"""

from __future__ import annotations

import logging

from app.modules.emr.base import EmrConnector
from app.modules.emr.stub import StubEmrConnector

logger = logging.getLogger("aurion.emr.registry")

_REGISTRY: dict[str, EmrConnector] = {
    "stub": StubEmrConnector(),
}

_DEFAULT_CONNECTOR_KEY = "stub"


def get_connector(key: str) -> EmrConnector:
    """Return the connector registered under `key`. Raises
    `KeyError` if unknown — caller should map to a 400 / 422 with a
    clear message; never to a 500."""
    if key not in _REGISTRY:
        known = sorted(_REGISTRY.keys())
        raise KeyError(
            f"Unknown EMR connector {key!r}; known: {known}"
        )
    return _REGISTRY[key]


def get_default_connector() -> EmrConnector:
    """The connector used when the caller didn't specify one. Today
    that's the stub; AppConfig-driven selection lands post-pilot."""
    return _REGISTRY[_DEFAULT_CONNECTOR_KEY]


def list_connector_keys() -> list[str]:
    """Connector keys available in this deployment. The portal calls
    this to populate the "Send to EMR" dropdown."""
    return sorted(_REGISTRY.keys())


def register_connector(connector: EmrConnector) -> None:
    """Used by tests + future connector packages to register a
    concrete connector. Production code uses the static
    `_REGISTRY` map above."""
    _REGISTRY[connector.key] = connector
    logger.info("emr registry: registered connector=%s", connector.key)
