"""TLS pinning for the asyncpg engine (RDS rds.force_ssl=1).

The URL rebuilt from the RDS-managed master secret carries no ``sslmode``,
so asyncpg would attempt a non-SSL connection that RDS rejects
(``no pg_hba.conf entry ... no encryption``). ``_ssl_connect_args`` pins
``ssl=require`` for RDS hosts while leaving local docker plaintext.
"""

from __future__ import annotations

from app.core.database import _ssl_connect_args


class TestSslConnectArgs:
    def test_rds_host_requires_ssl(self):
        url = "postgresql+asyncpg://aurion:pw@aurion-db-dev.abc123.ca-central-1.rds.amazonaws.com:5432/aurion"
        assert _ssl_connect_args(url) == {"ssl": "require"}

    def test_localhost_stays_plaintext(self):
        assert _ssl_connect_args("postgresql+asyncpg://aurion:aurion@localhost:5432/aurion") == {}

    def test_loopback_ip_stays_plaintext(self):
        assert _ssl_connect_args("postgresql+asyncpg://aurion:aurion@127.0.0.1:5432/aurion") == {}

    def test_docker_compose_host_stays_plaintext(self):
        # docker-compose service name `db`
        assert _ssl_connect_args("postgresql+asyncpg://aurion:aurion@db:5432/aurion") == {}
