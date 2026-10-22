"""The package's tests: each member over str and bytes, against the answers V8 gives."""
import threading

import pytest

import corvus_regex_ecma262 as ecma


def test_compiling():
    r = ecma.compile(r"(?<year>\d{4})-(?<month>\d{2})", "gu")
    assert r.pattern == r"(?<year>\d{4})-(?<month>\d{2})"
    assert r.flags == "gu"
    assert r.groups == 2
    assert r.group_names == ["year", "month"]
    # The flags come back in the order RegExp.prototype.flags writes them.
    assert ecma.compile("a", "yig").flags == "giy"
    assert repr(ecma.compile("a+", "g")) == "corvus_regex_ecma262.Regex(\"a+\", \"g\")"


@pytest.mark.parametrize(
    "pattern,flags,kind",
    [("(", "", "pattern"), (r"\p{Nope}", "u", "pattern"), ("a", "uv", "flags"), ("a", "q", "flags"),
     ("(" * 1001 + ")" * 1001, "", "too_large")],
)
def test_errors_say_why(pattern, flags, kind):
    with pytest.raises(ecma.error) as e:
        ecma.compile(pattern, flags)
    assert e.value.kind == kind
    assert isinstance(e.value, ValueError)


def test_is_valid():
    assert ecma.is_valid("a+", "u")
    assert not ecma.is_valid("a{2,1}", "u")
    # Annex B reads {2,1 as text without u.
    assert ecma.is_valid("a{2,1", "")
    assert not ecma.is_valid("a{2,1", "u")


def test_search_and_test():
    r = ecma.compile("o+")
    assert r.test("foo") and not r.test("bar")
    m = r.search("a foo, a boo", 3)
    assert m.span() == (3, 5) and m.group() == "oo"
    assert r.search("a foo, a boo", 5).span() == (10, 12)
    assert r.search("a foo", 5) is None
    assert r.search("a foo", 99) is None
    # The y flag: a match starts where the search starts.
    sticky = ecma.compile("o", "y")
    assert sticky.test("foo", 1) and not sticky.test("foo", 0)


def test_positions_are_code_points_over_str_and_bytes_over_bytes():
    r = ecma.compile("ok")
    assert r.search("café ok").span() == (5, 7)
    assert r.search("café ok".encode()).span() == (6, 8)
    assert r.search("café ok".encode()).group() == b"ok"
    assert ecma.compile("é").search("café", 1).span() == (3, 4)


def test_half_characters_without_u():
    # Without u a character beyond the Basic Multilingual Plane is two code units, and . takes one: the match's text
    # is the lone half, as in JavaScript, and its span is the whole character's.
    m = ecma.compile("^.").search("😀x")
    assert m.group() == "\ud83d"
    assert m.span() == (0, 1)
    assert ecma.compile("^.", "u").search("😀x").group() == "😀"
    # Over bytes, the position between the halves is the character's third byte.
    b = ecma.compile("^.").search("😀x".encode())
    assert b.span() == (0, 2)


def test_lone_surrogates_in_str():
    text = "a\ud800b"
    assert ecma.compile("^...$").test(text)
    assert ecma.compile("^...$", "u").test(text)
    # The escape \ud800 matches the lone half; a lone half written into the pattern itself is read as U+FFFD, as a
    # pattern is read as UTF-8 (the crate's patterns are).
    assert ecma.compile(r"\ud800").search(text).span() == (1, 2)
    assert ecma.compile("\ud800").search(text) is None
    assert ecma.compile("\ud800").search("a\ufffdb").span() == (1, 2)


def test_groups():
    r = ecma.compile(r"(?<year>\d{4})-(?<month>\d{2})(-(\d{2}))?", "u")
    m = r.search("due 2026-10, then")
    assert m.group() == "2026-10"
    assert m.group(0) == "2026-10" and m[0] == "2026-10"
    assert m.group("year") == "2026" and m["month"] == "10"
    assert m.group(1, 2) == ("2026", "10")
    assert m.group(3) is None
    assert m.groups() == ("2026", "10", None, None)
    assert m.groups("") == ("2026", "10", "", "")
    assert m.groupdict() == {"year": "2026", "month": "10"}
    assert m.span("month") == (9, 11) and m.start(3) == -1 and m.end(4) == -1
    assert m.string == "due 2026-10, then" and m.re is r
    with pytest.raises(IndexError):
        m.group(9)
    with pytest.raises(IndexError):
        m.group("nope")
    # Two groups in separate alternatives may share a name: the one that took part is the name's.
    assert ecma.compile("(?<d>a)|(?<d>b)", "u").search("b")["d"] == "b"


def test_finditer():
    r = ecma.compile(r"\d+", "g")
    assert [m.group() for m in r.finditer("1 22 333 4444")] == ["1", "22", "333", "4444"]
    # More matches than one batch.
    assert sum(1 for _ in ecma.compile("a", "g").finditer("a " * 1000)) == 1000
    # After an empty match the search goes on one code point with u, one code unit without.
    assert len(list(ecma.compile("", "gu").finditer("😀"))) == 2
    assert len(list(ecma.compile("", "g").finditer("😀"))) == 3
    assert len(list(ecma.compile("", "gu").finditer("😀".encode()))) == 2
    # Without u, over bytes, the unit after a character's start is between its halves: its third byte. (A whole
    # character's step here gave one match too few.)
    assert [m.span() for m in ecma.compile("", "g").finditer("😀,".encode())] == [(0, 0), (2, 2), (4, 4), (5, 5)]
    # The y flag: each match starts where the one before ended.
    assert len(list(ecma.compile("a", "gy").finditer("aab"))) == 2
    assert list(ecma.compile("a", "gy").finditer("baa")) == []
    # Positions over non-ASCII text, in order.
    assert [m.span() for m in ecma.compile("é", "g").finditer("é a é b é")] == [(0, 1), (4, 5), (8, 9)]


def test_replace():
    date = ecma.compile(r"(?<y>\d{4})-(?<m>\d{2})", "g")
    assert date.replace("2026-10, 2027-01", "$<m>/$1") == "10/2026, 01/2027"
    first = ecma.compile(r"\d+")
    assert first.replace("1 2 3", "[$&]") == "[1] 2 3"
    assert first.replace_all("1 2 3", "[$&]") == "[1] [2] [3]"
    assert first.replace("a1b", "<$`|$'|$$>") == "a<a|b|$>b"
    assert first.replace(b"a1b", b"<$&>") == b"a<1>b"
    # A function of the match.
    assert first.replace_all("1 2 3", lambda m: str(int(m.group()) * 2)) == "2 4 6"
    assert first.replace(b"a1b", lambda m: m.group() * 3) == b"a111b"
    assert ecma.compile("", "g").replace_all("ab", lambda m: "-") == "-a-b-"
    with pytest.raises(TypeError):
        first.replace("a1", lambda m: 1)
    with pytest.raises(TypeError):
        first.replace("a1", b"x")
    # Without u a half character is a lone surrogate in a str, as in JavaScript.
    assert ecma.compile("^.").replace("😀", "x") == "x\ude00"


def test_split():
    comma = ecma.compile(r"\s*(;)\s*")
    assert comma.split("a ; b;c") == ["a", ";", "b", ";", "c"]
    assert comma.split("a;b;c", 2) == ["a", ";"]
    assert ecma.compile("(x)?,").split("a,b") == ["a", None, "b"]
    assert comma.split(b"a;b") == [b"a", b";", b"b"]


def test_limits():
    slow = ecma.compile(r"^(a+)+\1$")
    text = "a" * 64 + "!"
    with pytest.raises(ecma.MatchLimitError):
        slow.test(text, timeout=0.005)
    with pytest.raises(ecma.MatchLimitError):
        slow.search(text, timeout=0.005)
    assert issubclass(ecma.MatchLimitError, ecma.error)
    # A pattern without a backreference takes time in proportion to its size times the text.
    assert not ecma.compile(r"^(a+)+$").test(text, timeout=1)
    with pytest.raises(ValueError):
        slow.test(text, timeout=-1)


def test_a_pattern_has_a_timeout_every_method_honours():
    never = r"^(?:(a+)\1*)+$"
    text = "a" * 60 + "b"
    re = ecma.compile(never, "u", timeout=0.03)
    assert re.timeout == pytest.approx(0.03)
    for call in (
        lambda: re.test(text),
        lambda: re.search(text),
        lambda: list(re.finditer(text)),
        lambda: re.replace(text, "x"),
        lambda: re.replace_all(text, "x"),
        lambda: re.replace(text, lambda m: "x"),
        lambda: re.split(text),
        lambda: re.split(text, 2),
        lambda: re.test(text.encode()),
        lambda: list(re.finditer(text.encode())),
        lambda: re.replace(text.encode(), b"x"),
        lambda: re.split(text.encode()),
        lambda: re.test(text + "\ud800"),
    ):
        with pytest.raises(ecma.MatchLimitError):
            call()
    # A text answered within the timeout is answered by every method.
    assert re.test("aaaa")
    assert re.replace("aaaa", "<$&>") == "<aaaa>"
    assert len(re.split("aaaa")) == 3
    # A timeout of its own takes the pattern's place for one match (0 for none).
    assert ecma.compile(r"^(a+)\1$", timeout=0.000001).test("aaaa", timeout=0)
    long = ecma.compile(never, "u", timeout=3600)
    with pytest.raises(ecma.MatchLimitError):
        long.test(text, timeout=0.03)
    # The matches before the one that reached the timeout come first, then the error ends the search.
    mixed = ecma.compile(r"(?:(a+)\1*)+$|b", "g", timeout=0.03)
    found = []
    with pytest.raises(ecma.MatchLimitError):
        for m in mixed.finditer("b" + text):
            found.append(m.group())
    assert found == ["b"]


def test_a_timeout_caps_the_memory_of_a_match():
    re = ecma.compile(r"(?:a?){2147483647}", timeout=3600)
    with pytest.raises(ecma.MatchLimitError, match="memory"):
        re.test("")


def test_the_default_timeout():
    assert ecma.default_timeout() is None
    assert ecma.compile("a").timeout is None
    try:
        ecma.set_default_timeout(0.03)
        assert ecma.default_timeout() == pytest.approx(0.03)
        re = ecma.compile(r"^(?:(a+)\1*)+$", "u")
        own = ecma.compile("a", timeout=5)
        none = ecma.compile("a", timeout=0)
    finally:
        ecma.set_default_timeout(None)
    assert ecma.default_timeout() is None
    assert re.timeout == pytest.approx(0.03)
    with pytest.raises(ecma.MatchLimitError):
        re.test("a" * 60 + "b")
    assert own.timeout == 5
    assert none.timeout is None
    with pytest.raises(ValueError):
        ecma.set_default_timeout(-1)
    with pytest.raises(ValueError):
        ecma.compile("a", timeout=-1)


def test_types():
    r = ecma.compile("a")
    with pytest.raises(TypeError):
        r.search(3)
    with pytest.raises(ValueError):
        r.search(b"\xff")


def test_threads():
    r = ecma.compile(r"\w+", "g")
    text = "word " * 2000
    counts = []

    def work():
        counts.append(sum(sum(1 for _ in r.finditer(text)) for _ in range(20)))

    workers = [threading.Thread(target=work) for _ in range(4)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert counts == [40000] * 4


def test_nested_classes_on_a_small_stack():
    # With v a class holds classes, and each is a level of reading: the deepest nesting allowed is read, compiled and
    # matched on a thread of 256 KB, and deeper is refused as too large, which a caller can catch, rather than
    # overflowing the stack, which ends the process (as with the C library up to 0.1.1).
    def nest(depth):
        return "[" * depth + "a" + "]" * depth

    results = []

    def work():
        try:
            results.append(ecma.compile(nest(1000), "v").test("a"))
            for pattern in (nest(1001), "[" * 200_000):
                try:
                    ecma.compile(pattern, "v")
                    results.append("compiled")
                except ecma.error as e:
                    results.append(e.kind)
        except BaseException as e:  # noqa: BLE001 - reported by the assertion below
            results.append(e)

    previous = threading.stack_size(256 * 1024)
    try:
        worker = threading.Thread(target=work)
        worker.start()
        worker.join()
    finally:
        threading.stack_size(previous)
    assert results == [True, "too_large", "too_large"]
