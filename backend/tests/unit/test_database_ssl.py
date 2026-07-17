"""TLS pinning for the asyncpg engine (RDS rds.force_ssl=1).

The URL rebuilt from the RDS-managed master secret carries no ``sslmode``,
so asyncpg would attempt a non-SSL connection that RDS rejects
(``no pg_hba.conf entry ... no encryption``). ``_ssl_connect_args`` pins
``ssl=require`` for RDS hosts while leaving local docker plaintext.

The host is PARSED, not substring-matched (loop-0). Substring matching read
the whole URL and was wrong in both directions — it under-matched the real
compose service name (no local stack could boot) and it over-matched any
remote host merely starting with a local name (TLS silently dropped). The two
tests marked "REGRESSION" below fail against the substring implementation;
the rest are guards on the current one.
"""

from __future__ import annotations

from app.core.database import _resolve_database_url, _ssl_connect_args

_RDS = "aurion-db-dev.abc123.ca-central-1.rds.amazonaws.com"
_REQUIRE = {"ssl": "require"}


class TestSslConnectArgs:
    def test_rds_host_requires_ssl(self):
        assert _ssl_connect_args(f"postgresql+asyncpg://aurion:pw@{_RDS}:5432/aurion") == _REQUIRE

    def test_localhost_stays_plaintext(self):
        assert _ssl_connect_args("postgresql+asyncpg://aurion:aurion@localhost:5432/aurion") == {}

    def test_loopback_ip_stays_plaintext(self):
        assert _ssl_connect_args("postgresql+asyncpg://aurion:aurion@127.0.0.1:5432/aurion") == {}

    def test_compose_postgres_host_stays_plaintext(self):
        # REGRESSION (loop-0, under-match). docker-compose.yml names the
        # service `postgres` and sets DATABASE_URL to ...@postgres:5432/aurion,
        # but the allowlist only knew `db` — so ssl=require was forced against
        # a Postgres with no TLS and aurion-api died at startup with
        # "rejected SSL upgrade". No local stack could boot, which blocked the
        # workflow's "stack boots" gate for every task in every lane.
        assert _ssl_connect_args("postgresql+asyncpg://aurion:aurion@postgres:5432/aurion") == {}

    def test_remote_host_merely_starting_with_localhost_requires_ssl(self):
        # REGRESSION (loop-0, over-match) — the security half, and the reason
        # this is a parser and not one more substring. "@localhost" matched
        # ANYWHERE in the URL, so a REMOTE host like localhost.internal.foo
        # was treated as the dev box and TLS was silently dropped: PHI in
        # plaintext, no error, no log. Only an EXACT host match is local.
        url = "postgresql+asyncpg://aurion:pw@localhost.internal.example.com:5432/aurion"
        assert _ssl_connect_args(url) == _REQUIRE

    def test_legacy_db_host_stays_plaintext(self):
        # Older compose files named the service `db`; keep them working.
        assert _ssl_connect_args("postgresql+asyncpg://aurion:aurion@db:5432/aurion") == {}

    def test_rds_host_merely_starting_with_postgres_requires_ssl(self):
        # Guard, not a regression: the substring version got this right by
        # accident (it had no "@postgres:" entry at all). It pins the fix
        # against the tempting one-line "just add @postgres: to the list"
        # patch, which would reintroduce the over-match above for `postgres`.
        url = "postgresql+asyncpg://aurion:pw@postgres.abc123.ca-central-1.rds.amazonaws.com:5432/aurion"
        assert _ssl_connect_args(url) == _REQUIRE

    def test_ipv6_loopback_stays_plaintext(self):
        # `::1` is a live entry in _LOCAL_DB_HOSTS. make_url strips the
        # brackets, so .host is "::1" not "[::1]" — pin that, or the entry is
        # silently dead code.
        assert _ssl_connect_args("postgresql+asyncpg://u:p@[::1]:5432/aurion") == {}

    def test_unparseable_url_fails_closed(self):
        # Guard on the current implementation: parsing introduces a raise the
        # substring version couldn't have. Never blow up at import (this runs
        # at module scope), and never fall open to plaintext.
        assert _ssl_connect_args("not a url at all") == _REQUIRE

    def test_bad_port_fails_closed_without_raising(self):
        # make_url raises a BARE ValueError here, not its own ArgumentError,
        # so `except ArgumentError` alone would let it escape at import and
        # take the app down. Empty port is the realistic trigger: the JSON
        # -envelope path interpolates DB_PORT straight into the URL, so an
        # unset DB_PORT produces "...@host:/db".
        assert _ssl_connect_args("postgresql+asyncpg://u:p@host:notaport/db") == _REQUIRE
        assert _ssl_connect_args("postgresql+asyncpg://u:p@host:/db") == _REQUIRE

    def test_hostless_socket_url_fails_closed(self):
        # .host is None -> not in _LOCAL_DB_HOSTS -> TLS. Nothing in the repo
        # uses socket URLs; pinning that it fails closed rather than open.
        assert _ssl_connect_args("postgresql+asyncpg:///aurion") == _REQUIRE


class TestResolvedProdUrlRequiresSsl:
    """The composition that actually runs in prod.

    Every test above calls _ssl_connect_args directly. This one goes through
    _resolve_database_url's JSON-envelope path — the shape ECS injects, where
    the RDS master secret arrives as {"username","password"} and the host comes
    from DB_HOST (ecs.tf sets it to aws_db_instance.main.address).
    """

    def test_rds_secret_envelope_resolves_to_a_tls_connection(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", '{"username": "aurion", "password": "s3cret"}')
        monkeypatch.setenv("DB_HOST", _RDS)
        monkeypatch.setenv("DB_PORT", "5432")
        monkeypatch.setenv("DB_NAME", "aurion")
        url = _resolve_database_url()
        assert url == f"postgresql+asyncpg://aurion:s3cret@{_RDS}:5432/aurion"
        assert _ssl_connect_args(url) == _REQUIRE
