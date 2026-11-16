"""Validate a manually entered MariaDB connection."""

from __future__ import annotations

from .models import ConnectionConfig, InvalidConnection


def connection_from_fields(
    *,
    host: object,
    port: object,
    database: object,
    username: object,
    password: object,
    unix_socket: object,
    ssl: object,
) -> ConnectionConfig:
    """Build a connection from config-flow fields."""

    socket = _text(unix_socket)
    hostname = _text(host)
    if not hostname and not socket:
        raise InvalidConnection("host", "missing_host")
    schema = _text(database)
    if not schema:
        raise InvalidConnection("database", "missing_database")
    user = _text(username)
    if not user:
        raise InvalidConnection("username", "missing_username")
    return ConnectionConfig(
        host=hostname or "localhost",
        port=_port(port),
        database=schema,
        username=user,
        password="" if password is None else str(password),
        unix_socket=socket or None,
        ssl=bool(ssl),
    )


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InvalidConnection("port", "invalid_port")
    try:
        if isinstance(value, str):
            port = int(value.strip())
        elif isinstance(value, float):
            if not value.is_integer():
                raise InvalidConnection("port", "invalid_port")
            port = int(value)
        else:
            port = value
    except ValueError as err:
        raise InvalidConnection("port", "invalid_port") from err
    if port < 1 or port > 65535:
        raise InvalidConnection("port", "invalid_port")
    return port
