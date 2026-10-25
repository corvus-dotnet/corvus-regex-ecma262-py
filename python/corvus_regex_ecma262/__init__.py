"""ECMA-262 (JavaScript) regular expressions for Python: the grammar and the answers of RegExp, every flag, backed by
the corvus-regex-ecma262 Rust crate.

    >>> import corvus_regex_ecma262 as ecma
    >>> date = ecma.compile(r"(?<year>\\d{4})-(?<month>\\d{2})", "gu")
    >>> date.search("due 2026-10")["year"]
    '2026'
    >>> [m.group() for m in date.finditer("2026-10, 2027-01")]
    ['2026-10', '2027-01']
    >>> date.replace("2026-10, 2027-01", "$<month>/$1")
    '10/2026, 01/2027'

A ``str`` is matched with positions in code points, as Python indexes it; ``bytes`` are UTF-8, with positions in
bytes; an ``array.array('H')`` is UTF-16 code units, as JavaScript holds a string, with positions in code units (so a
position between the halves of a character can be named). Without the u or v flag a pattern is matched by UTF-16 code unit, as ECMA-262 matches it, so a match can take
half of a character beyond the Basic Multilingual Plane: its text then holds that half as a lone surrogate, as a
JavaScript string would, and its start and end are given as the whole character's.

A pattern has a match timeout, as a ``Regex`` of .NET has: ``compile(pattern, flags, timeout=1.0)``, or for every
pattern ``set_default_timeout(1.0)``. Every method that matches (``test``, ``search``, ``finditer``, ``replace``,
``split``) gives each of its matches the timeout, and a match that reaches it raises ``MatchLimitError``.
"""

from __future__ import annotations

from ._native import (
    MAX_NESTING,
    MAX_PATTERN_LENGTH,
    Match,
    MatchIterator,
    MatchLimitError,
    Regex,
    default_timeout,
    error,
    set_default_timeout,
)

__version__ = "0.0.0"

__all__ = [
    "MAX_NESTING",
    "MAX_PATTERN_LENGTH",
    "Match",
    "MatchIterator",
    "MatchLimitError",
    "Regex",
    "compile",
    "default_timeout",
    "error",
    "is_valid",
    "set_default_timeout",
]


def compile(pattern: str, flags: str = "", *, timeout: float | None = None) -> Regex:
    """Compiles a pattern with the flags ``new RegExp(pattern, flags)`` takes, any of dgimsuvy. Raises ``error`` when
    the pattern or the flags are not valid, or the pattern is over a limit of size.

    ``timeout`` is the time in seconds each match may take before it is abandoned with ``MatchLimitError`` (0 for no
    limit); None takes ``default_timeout()``, which is no limit unless ``set_default_timeout`` set one. A timeout also
    caps the backtracking memory of a match. Without one a match has no limit of time or of memory, so give a pattern
    or a text from outside one."""
    return Regex(pattern, flags, timeout=timeout)


def is_valid(pattern: str, flags: str = "") -> bool:
    """Whether a pattern is valid with the flags, without compiling it."""
    return Regex.is_valid(pattern, flags)
