"""Unicode-aware case-insensitive lookups for SQLite.

SQLite's built-in LIKE/UPPER only fold ASCII A–Z, so Django `__icontains`
stays case-sensitive for Cyrillic. Register Python `str.upper` as SQL UPPER
and mirror PostgreSQL's `UPPER(lhs) LIKE UPPER(rhs)` pattern on connect.
"""

from __future__ import annotations

from django.db.backends.signals import connection_created

_ILOOKUPS = frozenset({"iexact", "icontains", "istartswith", "iendswith"})


def _unicode_upper(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value.upper()


def _configure_sqlite_unicode(sender, connection, **kwargs) -> None:
    if connection.vendor != "sqlite":
        return

    connection.connection.create_function("UPPER", 1, _unicode_upper, deterministic=True)

    original_lookup_cast = connection.ops.lookup_cast

    def lookup_cast(lookup_type, internal_type=None):
        lookup = original_lookup_cast(lookup_type, internal_type)
        if lookup_type in _ILOOKUPS and "UPPER(" not in lookup:
            return f"UPPER({lookup})"
        return lookup

    connection.ops.lookup_cast = lookup_cast
    connection.operators = {
        **connection.operators,
        "iexact": "LIKE UPPER(%s) ESCAPE '\\'",
        "icontains": "LIKE UPPER(%s) ESCAPE '\\'",
        "istartswith": "LIKE UPPER(%s) ESCAPE '\\'",
        "iendswith": "LIKE UPPER(%s) ESCAPE '\\'",
    }
    connection.pattern_ops = {
        **connection.pattern_ops,
        "icontains": r"LIKE '%%' || UPPER({}) || '%%' ESCAPE '\'",
        "istartswith": r"LIKE UPPER({}) || '%%' ESCAPE '\'",
        "iendswith": r"LIKE '%%' || UPPER({}) ESCAPE '\'",
    }


def enable_sqlite_unicode_search() -> None:
    """Connect the SQLite Unicode search patch once at app startup."""

    connection_created.connect(_configure_sqlite_unicode, dispatch_uid="sqlite_unicode_search")
