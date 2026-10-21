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
bytes. Without the u or v flag a pattern is matched by UTF-16 code unit, as ECMA-262 matches it, so a match can take
half of a character beyond the Basic Multilingual Plane: its text then holds that half as a lone surrogate, as a
JavaScript string would, and its start and end are given as the whole character's.
"""

from __future__ import annotations

from ._native import MAX_NESTING, MAX_PATTERN_LENGTH, Match, MatchIterator, MatchLimitError, Regex, error

__version__ = "0.1.1"

__all__ = [
    "MAX_NESTING",
    "MAX_PATTERN_LENGTH",
    "Match",
    "MatchIterator",
    "MatchLimitError",
    "Regex",
    "compile",
    "error",
    "is_valid",
]


def compile(pattern: str, flags: str = "") -> Regex:
    """Compiles a pattern with the flags ``new RegExp(pattern, flags)`` takes, any of dgimsuvy. Raises ``error`` when
    the pattern or the flags are not valid, or the pattern is over a limit of size."""
    return Regex(pattern, flags)


def is_valid(pattern: str, flags: str = "") -> bool:
    """Whether a pattern is valid with the flags, without compiling it."""
    return Regex.is_valid(pattern, flags)
