from array import array
from collections.abc import Callable, Iterator
from typing import Generic, TypeVar, overload

# A text: a str (positions in code points), bytes (UTF-8, positions in bytes) or an array('H') of UTF-16 code units
# (positions in code units).
AnyStr = TypeVar("AnyStr", str, bytes, array)

MAX_PATTERN_LENGTH: int
"""The longest pattern that is read, in bytes of UTF-8."""
MAX_NESTING: int
"""The deepest groups and classes may nest."""
UNICODE_VERSIONS: tuple[int, ...]
"""The versions of Unicode the package carries: (13, 17, 18)."""
DEFAULT_UNICODE_VERSION: int
"""The version of Unicode a pattern is read with by default: that of the V8 the answers are held to (17)."""
LATEST_UNICODE_VERSION: int
"""The latest version of Unicode the package carries (18): what ``unicode_version="latest"`` resolves to."""

class error(ValueError):
    """A pattern or its flags are not valid, or the pattern is over a limit of size."""

    kind: str
    """"pattern" (not valid in the grammar of its flags), "flags" or "too_large"."""

class MatchLimitError(error):
    """A match reached its limit of time, or of backtracking memory, so it has no answer."""

def set_default_timeout(seconds: float | None) -> None:
    """Sets the match timeout, in seconds, of every pattern compiled from now on without one: None for no limit."""
def default_timeout() -> float | None:
    """The match timeout of a pattern compiled without one: None (no limit) unless ``set_default_timeout`` set one."""

class Regex:
    """A compiled pattern. ``compile(pattern, flags, ...)`` makes one; it is immutable and safe to share between threads."""

    def __init__(
        self,
        pattern: str,
        flags: str = "",
        *,
        timeout: float | None = None,
        edition: str = "current",
        unicode_version: int | str | None = None,
    ) -> None:
        """Compiles a pattern, as ``compile`` does."""
    @staticmethod
    def is_valid(
        pattern: str, flags: str = "", *, edition: str = "current", unicode_version: int | str | None = None
    ) -> bool:
        """Whether a pattern is valid, as ``is_valid`` says."""
    @property
    def pattern(self) -> str:
        """The pattern, as it was given."""
    @property
    def flags(self) -> str:
        """The flags, in the order of ``RegExp.prototype.flags`` (dgimsuvy)."""
    @property
    def timeout(self) -> float | None:
        """The match timeout in seconds, or None for no limit."""
    @property
    def edition(self) -> str:
        """The grammar the pattern was read with: "current" or "es2020"."""
    @property
    def unicode_version(self) -> int:
        """The version of Unicode the pattern was read with, resolved: 13, 17 or 18."""
    @property
    def groups(self) -> int:
        """The number of capturing groups."""
    @property
    def group_names(self) -> list[str]:
        """The names of the named groups, in the order they open."""
    def test(self, string: str | bytes | array, pos: int = 0, *, timeout: float | None = None) -> bool:
        """``RegExp.prototype.test`` with ``lastIndex`` at ``pos`` (at ``pos`` alone with the y flag). ``timeout`` takes the
        place of the pattern's for this match. Raises ``MatchLimitError`` at the limit."""
    @overload
    def search(self, string: str, pos: int = 0, *, timeout: float | None = None) -> Match[str] | None: ...
    @overload
    def search(self, string: bytes, pos: int = 0, *, timeout: float | None = None) -> Match[bytes] | None: ...
    @overload
    def search(self, string: array, pos: int = 0, *, timeout: float | None = None) -> Match[array] | None:
        """The first match at or after ``pos``, as ``exec`` finds it: a ``Match``, or None. ``timeout`` takes the place of
        the pattern's for this match."""
    @overload
    def finditer(self, string: str) -> MatchIterator[str]: ...
    @overload
    def finditer(self, string: bytes) -> MatchIterator[bytes]: ...
    @overload
    def finditer(self, string: array) -> MatchIterator[array]:
        """A global search, as ``matchAll`` makes it, whether or not the pattern has the g flag: an iterator of ``Match``."""
    def replace(self, string: AnyStr, replacement: AnyStr | Callable[[Match[AnyStr]], AnyStr]) -> AnyStr:
        """``String.prototype.replace``: the first match, or every match with the g flag. The replacement is a template,
        with every ``$`` form of ECMA-262 (``$$``, ``$&``, `` $` ``, ``$'``, ``$n``, ``$<name>``), or a function of the ``Match``."""
    def replace_all(self, string: AnyStr, replacement: AnyStr | Callable[[Match[AnyStr]], AnyStr]) -> AnyStr:
        """``String.prototype.replaceAll``: every match, as ``replace`` replaces each."""
    def split(self, string: AnyStr, limit: int | None = None) -> list[AnyStr | None]:
        """``String.prototype.split``: the pieces, with what the groups captured spliced in between them, None for a group
        that did not take part; at most ``limit`` pieces."""

class MatchIterator(Generic[AnyStr]):
    """The matches of a global search, one at a time; it stops at a ``MatchLimitError``."""

    def __iter__(self) -> MatchIterator[AnyStr]: ...
    def __next__(self) -> Match[AnyStr]: ...

class Match(Generic[AnyStr]):
    """A match, read as an ``re.Match`` is. A group is a number (0 for the whole match) or a name; a group that did not
    take part is None, at -1. Positions are in the text's units: code points of a ``str``, bytes of ``bytes``, code
    units of an ``array``."""

    def start(self, group: int | str = 0) -> int:
        """Where the group starts, or -1."""
    def end(self, group: int | str = 0) -> int:
        """Where the group ends, or -1."""
    def span(self, group: int | str = 0) -> tuple[int, int]:
        """``(start, end)`` of the group, or ``(-1, -1)``."""
    @overload
    def group(self) -> AnyStr: ...
    @overload
    def group(self, group: int | str, /) -> AnyStr | None: ...
    @overload
    def group(self, group1: int | str, group2: int | str, /, *groups: int | str) -> tuple[AnyStr | None, ...]:
        """The text of a group (the whole match with none), or a tuple of several."""
    def __getitem__(self, group: int | str) -> AnyStr | None:
        """``m[g]`` is ``m.group(g)``."""
    def groups(self, default: AnyStr | None = None) -> tuple[AnyStr | None, ...]:
        """The text of every group but the whole match, ``default`` for a group that did not take part."""
    def groupdict(self, default: AnyStr | None = None) -> dict[str, AnyStr | None]:
        """The named groups by name, ``default`` for a group that did not take part."""
    @property
    def string(self) -> AnyStr:
        """The text the match was found in."""
    @property
    def re(self) -> Regex:
        """The pattern that found the match."""
