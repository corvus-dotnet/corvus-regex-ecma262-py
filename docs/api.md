# API reference

The public names of `corvus_regex_ecma262`, generated from the package's typed stubs by `tools/docs/gen-api.py`. [Getting started](getting-started.md) shows them at work.

## Functions

### compile

```python
compile(pattern: str, flags: str = '', *, timeout: float | None = None, edition: str = 'current', unicode_version: int | str | None = None) -> Regex
```

Compiles a pattern with the flags ``new RegExp(pattern, flags)`` takes, any of dgimsuvy. Raises ``error`` when
the pattern or the flags are not valid, or the pattern is over a limit of size.

``timeout`` is the time in seconds each match may take before it is abandoned with ``MatchLimitError`` (0 for no
limit); None takes ``default_timeout()``, which is no limit unless ``set_default_timeout`` set one. A timeout also
caps the backtracking memory of a match. Without one a match has no limit of time or of memory, so give a pattern
or a text from outside one.

``edition`` is the grammar the pattern is read with: "current" (today's, the default) or "es2020", the grammar of
ECMAScript 2020, which JSON Schema 2020-12 names. It refuses what later editions added, and nothing else: the d and
v flags, modifier groups such as ``(?i:...)``, a group name used by two groups, and a property name or value that
is not in that edition's tables.

``unicode_version`` is the version of Unicode whose tables the pattern is read with: None (the default, V8's,
``DEFAULT_UNICODE_VERSION``), 13, 17, 18 or "latest" (``LATEST_UNICODE_VERSION``). It is independent of the
edition. Both are settled when the pattern is compiled, and cost a match nothing.

### default_timeout

```python
default_timeout() -> float | None
```

The match timeout of a pattern compiled without one: None (no limit) unless ``set_default_timeout`` set one.

### is_valid

```python
is_valid(pattern: str, flags: str = '', *, edition: str = 'current', unicode_version: int | str | None = None) -> bool
```

Whether a pattern is valid with the flags, in the edition and the version of Unicode, without compiling it.

### set_default_timeout

```python
set_default_timeout(seconds: float | None) -> None
```

Sets the match timeout, in seconds, of every pattern compiled from now on without one: None for no limit.

## Constants

| Name | Type | |
|---|---|---|
| `DEFAULT_UNICODE_VERSION` | `int` | The version of Unicode a pattern is read with by default: that of the V8 the answers are held to (17). |
| `LATEST_UNICODE_VERSION` | `int` | The latest version of Unicode the package carries (18): what ``unicode_version="latest"`` resolves to. |
| `MAX_NESTING` | `int` | The deepest groups and classes may nest. |
| `MAX_PATTERN_LENGTH` | `int` | The longest pattern that is read, in bytes of UTF-8. |
| `UNICODE_VERSIONS` | `tuple[int, ...]` | The versions of Unicode the package carries: (13, 17, 18). |

## Match (Generic[AnyStr])

A match, read as an ``re.Match`` is. A group is a number (0 for the whole match) or a name; a group that did not
take part is None, at -1. Positions are in the text's units: code points of a ``str``, bytes of ``bytes``, code
units of an ``array``.

| Property | Type | |
|---|---|---|
| `string` | `AnyStr` | The text the match was found in. |
| `re` | `Regex` | The pattern that found the match. |

### Match.start

```python
Match.start(group: int | str = 0) -> int
```

Where the group starts, or -1.

### Match.end

```python
Match.end(group: int | str = 0) -> int
```

Where the group ends, or -1.

### Match.span

```python
Match.span(group: int | str = 0) -> tuple[int, int]
```

``(start, end)`` of the group, or ``(-1, -1)``.

### Match.group

```python
Match.group() -> AnyStr
Match.group(group: int | str, /) -> AnyStr | None
Match.group(group1: int | str, group2: int | str, /, *groups: int | str) -> tuple[AnyStr | None, ...]
```

The text of a group (the whole match with none), or a tuple of several.

### Match.__getitem__

```python
Match.__getitem__(group: int | str) -> AnyStr | None
```

``m[g]`` is ``m.group(g)``.

### Match.groups

```python
Match.groups(default: AnyStr | None = None) -> tuple[AnyStr | None, ...]
```

The text of every group but the whole match, ``default`` for a group that did not take part.

### Match.groupdict

```python
Match.groupdict(default: AnyStr | None = None) -> dict[str, AnyStr | None]
```

The named groups by name, ``default`` for a group that did not take part.

## MatchIterator (Generic[AnyStr])

The matches of a global search, one at a time; it stops at a ``MatchLimitError``.

## MatchLimitError (error)

A match reached its limit of time, or of backtracking memory, so it has no answer.

## Regex

A compiled pattern. ``compile(pattern, flags, ...)`` makes one; it is immutable and safe to share between threads.

| Property | Type | |
|---|---|---|
| `pattern` | `str` | The pattern, as it was given. |
| `flags` | `str` | The flags, in the order of ``RegExp.prototype.flags`` (dgimsuvy). |
| `timeout` | `float | None` | The match timeout in seconds, or None for no limit. |
| `edition` | `str` | The grammar the pattern was read with: "current" or "es2020". |
| `unicode_version` | `int` | The version of Unicode the pattern was read with, resolved: 13, 17 or 18. |
| `groups` | `int` | The number of capturing groups. |
| `group_names` | `list[str]` | The names of the named groups, in the order they open. |

### Regex(...)

```python
Regex(pattern: str, flags: str = '', *, timeout: float | None = None, edition: str = 'current', unicode_version: int | str | None = None) -> None
```

Compiles a pattern, as ``compile`` does.

### Regex.is_valid (static)

```python
Regex.is_valid(pattern: str, flags: str = '', *, edition: str = 'current', unicode_version: int | str | None = None) -> bool
```

Whether a pattern is valid, as ``is_valid`` says.

### Regex.test

```python
Regex.test(string: str | bytes | array, pos: int = 0, *, timeout: float | None = None) -> bool
```

``RegExp.prototype.test`` with ``lastIndex`` at ``pos`` (at ``pos`` alone with the y flag). ``timeout`` takes the
place of the pattern's for this match. Raises ``MatchLimitError`` at the limit.

### Regex.search

```python
Regex.search(string: str, pos: int = 0, *, timeout: float | None = None) -> Match[str] | None
Regex.search(string: bytes, pos: int = 0, *, timeout: float | None = None) -> Match[bytes] | None
Regex.search(string: array, pos: int = 0, *, timeout: float | None = None) -> Match[array] | None
```

The first match at or after ``pos``, as ``exec`` finds it: a ``Match``, or None. ``timeout`` takes the place of
the pattern's for this match.

### Regex.finditer

```python
Regex.finditer(string: str) -> MatchIterator[str]
Regex.finditer(string: bytes) -> MatchIterator[bytes]
Regex.finditer(string: array) -> MatchIterator[array]
```

A global search, as ``matchAll`` makes it, whether or not the pattern has the g flag: an iterator of ``Match``.

### Regex.replace

```python
Regex.replace(string: AnyStr, replacement: AnyStr | Callable[[Match[AnyStr]], AnyStr]) -> AnyStr
```

``String.prototype.replace``: the first match, or every match with the g flag. The replacement is a template,
with every ``$`` form of ECMA-262 (``$$``, ``$&``, `` $` ``, ``$'``, ``$n``, ``$<name>``), or a function of the ``Match``.

### Regex.replace_all

```python
Regex.replace_all(string: AnyStr, replacement: AnyStr | Callable[[Match[AnyStr]], AnyStr]) -> AnyStr
```

``String.prototype.replaceAll``: every match, as ``replace`` replaces each.

### Regex.split

```python
Regex.split(string: AnyStr, limit: int | None = None) -> list[AnyStr | None]
```

``String.prototype.split``: the pieces, with what the groups captured spliced in between them, None for a group
that did not take part; at most ``limit`` pieces.

## error (ValueError)

A pattern or its flags are not valid, or the pattern is over a limit of size.

### error.kind

```python
kind: str
```

"pattern" (not valid in the grammar of its flags), "flags" or "too_large".
