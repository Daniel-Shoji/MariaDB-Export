"""Parse Home Assistant recorder database URLs."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from .models import ConnectionConfig, InvalidDatabaseUrl, NotMariaDBError

_MARIADB_SCHEMES = frozenset({"mysql", "mariadb"})
_TRUE = frozenset({"1", "true", "yes", "required", "on"})
_SSL_MODES = frozenset({"REQUIRED", "VERIFY_CA", "VERIFY_IDENTITY"})


def parse_db_url(url: str) -> ConnectionConfig:
    """Parse a SQLAlchemy recorder URL into connection settings.

    Passwords are percent-decoded. The password is returned only in memory so
    a recorder-backed entry does not have to store a second copy.
    """

    raw = url.strip()
    if "://" not in raw:
        raise InvalidDatabaseUrl("The recorder database URL has no scheme.")
    scheme, rest = raw.split("://", 1)
    base_scheme = scheme.split("+", 1)[0].lower()
    if base_scheme not in _MARIADB_SCHEMES:
        raise NotMariaDBError(base_scheme or scheme)
    parsed = urlparse(f"mysql://{rest}")
    if parsed.hostname is None and "unix_socket" not in parse_qs(parsed.query):
        raise InvalidDatabaseUrl("The recorder database URL has no host.")
    username = unquote(parsed.username) if parsed.username else ""
    if not username:
        raise InvalidDatabaseUrl("The recorder database URL has no username.")
    password = unquote(parsed.password) if parsed.password else ""
    database = unquote(parsed.path.lstrip("/"))
    if not database or "/" in database:
        raise InvalidDatabaseUrl("The recorder database URL has no database name.")
    query = parse_qs(parsed.query, keep_blank_values=True)
    socket = _first(query, "unix_socket")
    ssl_mode = (_first(query, "ssl_mode") or "").upper()
    ssl_flag = (_first(query, "ssl") or "").lower() in _TRUE
    port = parsed.port if parsed.port is not None else 3306
    if port < 1 or port > 65535:
        raise InvalidDatabaseUrl("The recorder database URL has an invalid port.")
    host = parsed.hostname or "localhost"
    return ConnectionConfig(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        unix_socket=socket or None,
        ssl=ssl_flag or ssl_mode in _SSL_MODES,
    )


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None
