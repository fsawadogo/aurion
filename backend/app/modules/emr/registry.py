"""EMR connector registry — maps a connector key to a concrete instance.

Mirrors the AI provider registry pattern; routes never instantiate a
connector directly.

Connectors register through one of three paths:
  1. Built-in defaults — `stub` is always registered (safety floor)
  2. Env-driven backends — `fhir_generic` registers when its
     endpoint env var is set. Adding more env-driven backends
     (Oscar, Epic SMART) goes through `_bootstrap_env_connectors()`
  3. Test hooks — `register_connector()` for ad-hoc registration

Per-clinic connector selection (different clinics may use different
EMRs) is post-pilot — `get_default_connector` returns the deployment's
single configured default.
"""

from __future__ import annotations

import logging

from app.modules.emr.base import EmrConnector
from app.modules.emr.fhir_generic import GenericFhirConnector
from app.modules.emr.stub import StubEmrConnector

logger = logging.getLogger("aurion.emr.registry")


def _bootstrap_env_connectors() -> dict[str, EmrConnector]:
    """Read environment variables and register the env-driven
    connectors that have their config set. Stub is ALWAYS registered;
    everything else is opt-in via the matching env vars."""
    registry: dict[str, EmrConnector] = {
        "stub": StubEmrConnector(),
    }
    fhir = GenericFhirConnector.from_env()
    if fhir is not None:
        registry[fhir.key] = fhir
        logger.info(
            "emr registry: registered env-driven connector=%s endpoint=%s",
            fhir.key, fhir.endpoint,
        )
    else:
        logger.debug(
            "emr registry: fhir_generic not registered "
            "(AURION_EMR_FHIR_ENDPOINT not set)"
        )
    return registry


_REGISTRY: dict[str, EmrConnector] = _bootstrap_env_connectors()


# Default stays `stub` even when fhir_generic is registered — choosing
# the default per deployment is post-pilot (AppConfig-driven). For now
# the portal renders a dropdown when there's more than one available,
# and the user picks; the stub remains the safety default.
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
    concrete connector. Production code uses `_bootstrap_env_connectors`
    above; this is for explicit ad-hoc registration."""
    _REGISTRY[connector.key] = connector
    logger.info("emr registry: registered connector=%s", connector.key)


def reset_registry_for_tests() -> None:
    """Reload the registry from env. Used by tests that set/unset env
    vars to verify the env-driven connector behavior. Production code
    has no business calling this."""
    global _REGISTRY
    _REGISTRY = _bootstrap_env_connectors()
