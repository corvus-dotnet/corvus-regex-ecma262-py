#!/usr/bin/env python3
"""Runs this package over the ECMA-262 regular expression test data (github.com/corvus-dotnet/ecma262-regex-test-data),
judged by the data's own rule ("How a runner judges an engine" in its README) as the C library's runner judges it:

    python tools/dataset.py <data directory> <wrong-cases output file> [--files <filter>] [--workers N]
                            [--compliance <file>] [--edition current|es2020] [--unicode 13|17|18|latest]

Each record is asked about under each grammar V8 found it valid in: the record's flags with u added (the unicode
answers), the record's flags alone (the legacy answers) and, in the file that has them, the flags with v added (the
unicode_sets answers). A text is matched as a str (positions in code points) and as UTF-8 bytes (positions in bytes);
a text with a lone surrogate has no UTF-8 form and is matched as a str alone. Records marked v8_deviation are left out.
Any difference from V8 is a wrong answer; a refusal of a valid pattern, an acceptance of an invalid one, and a match
that reaches its limit are counted apart and listed too. captures.jsonl is judged on exec, the global search, the
sticky flag, replace and split, over the str and over the bytes; the sticky flag's search at UTF-16 index 1, where
that falls between the halves of the first character (which a str position cannot name), over the text's code units
as an array('H'). A match is given 2 seconds.

The data gives positions in UTF-16 code units. Over a str they are compared as the package gives them, in code
points, a position between the halves of a character (which a match without u or v can reach) as the character's
start for a start and its end for an end; over bytes they are compared in bytes, such a position as the character's
third byte, as the crate gives it. Texts are compared exactly over a str (a half character is a lone surrogate, as in
V8's answer), and over bytes with V8's answer converted to UTF-8, a lone surrogate as U+FFFD.

ill-formed-utf8.jsonl holds bytes that are not UTF-8, each one answer over UTF-8 under each grammar the pattern is valid
in, whose right answer is a refusal: the package's ValueError for bytes that are not UTF-8.

exec/test262.jsonl, the exec calls of test262 (in a directory of its own), is judged last: each call one exec with the
record's flags from its lastIndex, right when the positions of the match and of every group, the named groups and, with
g or y, the lastIndex after are V8's; one answer over the text's code units as an array('H') (positions in code units,
the data's own, since lastIndex can fall between the halves of a character) and, when the text holds no lone surrogate
and lastIndex is not between the halves of a pair, one over UTF-8 bytes with positions in bytes.

--edition and --unicode compile every pattern with that edition and version of Unicode, for the data as its own scripts
write it for them (edition.js apply and unicode.js apply in the data repository). Under es2020 a refusal of the d or v
flag is a refusal of the pattern, as the data's overlay counts it.

With --compliance <file>, the engine's compliance object is written to the file, as the benchmark page reads it
(docs/implementing-a-source.md in corvus-regex-ecma262-benchmarks): the counts, this runner and the calls it makes in
each encoding, and what it leaves out, which for this package is nothing.
"""
from __future__ import annotations

import argparse
import array
import fnmatch
import json
import os
import sys
import time
from multiprocessing import Pool

import corvus_regex_ecma262 as ecma

LIMIT = 2.0
REPLACEMENT = "<$&|$1|$2|$10|$<a>|$$|$`|$'>"
REPLACEMENT8 = REPLACEMENT.encode()

# The edition and the version of Unicode every pattern is compiled with (--edition, --unicode).
SETTINGS = {"edition": "current", "unicode_version": None}


def use_settings(settings):
    SETTINGS.update(settings)


def lone(s: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def utf8_lossy(s: str) -> bytes:
    """UTF-8, a lone surrogate as U+FFFD (as String::from_utf16_lossy writes it)."""
    return "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in s).encode() if lone(s) else s.encode()


def units_to_points(s: str):
    """For each UTF-16 code unit index of s (and its end), the code point index, a start between halves rounded down
    and an end rounded up: (starts, ends)."""
    starts, ends = [], []
    p = 0
    for c in s:
        if ord(c) > 0xFFFF:
            starts += [p, p]
            ends += [p, p + 1]
        else:
            starts.append(p)
            ends.append(p)
        p += 1
    starts.append(p)
    ends.append(p)
    return starts, ends


def units_to_bytes(s: str):
    """For each UTF-16 code unit index of s (and its end), the UTF-8 byte offset; the low half of a pair is its
    character's third byte."""
    at, b = [], 0
    for c in s:
        n = len(c.encode("utf-8", "surrogatepass"))
        if ord(c) > 0xFFFF:
            at += [b, b + 2]
        else:
            at.append(b)
        b += n
    at.append(b)
    return at


def shown(pattern: str) -> str:
    """The pattern as the Rust runner shows it: through UTF-8 (a lone surrogate as U+FFFD) and back, escaped."""
    return escape(utf8_lossy(pattern).decode())


def code_units(s: str) -> array.array:
    """The UTF-16 code units of s, lone surrogates and all, as the package takes them: an array('H')."""
    return array.array("H", s.encode("utf-16-le" if sys.byteorder == "little" else "utf-16-be", "surrogatepass"))


def escape(s: str) -> str:
    """The UTF-16 code units of s, printable ASCII as it is and anything else as \\uXXXX."""
    data = s.encode("utf-16-le", "surrogatepass")
    out = []
    for i in range(0, len(data), 2):
        v = data[i] | (data[i + 1] << 8)
        out.append(chr(v) if 0x20 <= v < 0x7F and v != 0x5C else f"\\u{v:04x}")
    return "".join(out)


class Counts:
    __slots__ = ("right", "wrong", "refused", "accepted", "limited", "errors")

    def __init__(self):
        self.right = self.wrong = self.refused = self.accepted = self.limited = self.errors = 0

    def add(self, o):
        for k in self.__slots__:
            setattr(self, k, getattr(self, k) + getattr(o, k))


def compile_or_why(pattern: str, flags: str):
    try:
        return ecma.compile(pattern, flags, **SETTINGS), None, False
    except ecma.error as e:
        kind = getattr(e, "kind", "pattern")
        if kind == "pattern":
            return None, f"PARSE: {e}", False
        if kind == "flags" and SETTINGS["edition"] == "es2020":
            return None, f"FLAGS: {e}", False
        if kind == "too_large":
            return None, f"TOO-LARGE: {e}", False
        return None, f"ERROR: {e}", True


def modes_of(r):
    valid = r.get("valid", {})
    out = [("u", "unicode", bool(valid.get("unicode"))), ("", "legacy", bool(valid.get("legacy")))]
    if "unicode_sets" in valid:
        out.append(("v", "unicode_sets", bool(valid.get("unicode_sets"))))
    return out


def judge_tests(name, r, pattern, c, w):
    flags = r.get("flags", "")
    head_pattern = shown(pattern)
    for suffix, answer, valid in modes_of(r):
        mode_flags = flags + suffix
        head = f"{name}\t/{head_pattern}/{mode_flags}"
        re, message, is_error = compile_or_why(pattern, mode_flags)
        if re is None:
            if is_error:
                c.errors += 1
            if valid:
                c.refused += 1
                w.append(f"REFUSED\t{head}\t{message.splitlines()[0] if message else ''}")
            continue
        if not valid:
            c.accepted += 1
            w.append(f"ACCEPTED-INVALID\t{head}")
            continue
        for test in r.get("tests", []):
            expected = test.get(answer)
            text = test.get("text")
            if not isinstance(expected, bool) or text is None:
                continue
            for enc in ("utf16", "utf8"):
                if enc == "utf8" and lone(text):
                    continue
                subject = text if enc == "utf16" else text.encode()
                try:
                    got = re.test(subject, timeout=LIMIT)
                except ecma.MatchLimitError as e:
                    c.limited += 1
                    w.append(f"LIMIT\t{head}\t{escape(text)}\t{enc}\t{'memory' if 'memory' in str(e) else 'time'}")
                    continue
                if got == expected:
                    c.right += 1
                else:
                    c.wrong += 1
                    w.append(f"WRONG\t{head}\t{escape(text)}\t{enc}\texpected {'true' if expected else 'false'}")


def judge_ill_formed(r, pattern, c, w):
    name = "ill-formed-utf8.jsonl"
    flags = r.get("flags", "")
    head_pattern = shown(pattern)
    for suffix, _, valid in modes_of(r):
        mode_flags = flags + suffix
        head = f"{name}\t/{head_pattern}/{mode_flags}"
        re, message, is_error = compile_or_why(pattern, mode_flags)
        if re is None:
            if is_error:
                c.errors += 1
            if valid:
                c.refused += 1
                w.append(f"REFUSED\t{head}\t{message.splitlines()[0] if message else ''}")
            continue
        if not valid:
            c.accepted += 1
            w.append(f"ACCEPTED-INVALID\t{head}")
            continue
        for test in r.get("tests", []):
            subject = bytes.fromhex(test["bytes"])
            try:
                got = re.test(subject, timeout=LIMIT)
            except ecma.MatchLimitError as e:
                c.limited += 1
                w.append(f"LIMIT\t{head}\t{test['bytes']}\tutf8\t{'memory' if 'memory' in str(e) else 'time'}")
                continue
            except ValueError as e:
                # The package's refusal of bytes that are not UTF-8 (a MatchLimitError is a ValueError too, and is
                # caught above).
                if "utf-8" in str(e).lower():
                    c.right += 1
                else:
                    c.errors += 1
                    w.append(f"ERROR\t{head}\t{test['bytes']}\tutf8\t{type(e).__name__}: {e}")
                continue
            c.wrong += 1
            w.append(f"WRONG\t{head}\t{test['bytes']}\tutf8\tread as UTF-8 ({got}), not refused")


def same_slots(expected, m, starts, ends):
    """Whether a match's groups are the expected [start, end] pairs (None for a group that did not take part), the
    expected positions mapped by starts and ends (identity when None)."""
    if expected is None or m is None:
        return expected is None and m is None
    if len(expected) != (m.re.groups + 1):
        return False
    for g, e in enumerate(expected):
        span = m.span(g)
        if e is None:
            if span != (-1, -1):
                return False
        else:
            s, t = e
            want = (starts[s], ends[t]) if starts is not None else (s, t)
            if span != want:
                return False
    return True


def judge_all(matches, all_, starts, ends):
    n = 0
    for m in matches:
        if n >= len(all_):
            # One match more than the data has: wrong, unless the data kept only the first twenty.
            return len(all_) == 20
        e = all_[n]
        if e is None:
            return False
        s, t = e[0]
        want = (starts[s], ends[t]) if starts is not None else (s, t)
        if m.span() != want:
            return False
        n += 1
    return not ((len(all_) < 20 and n != len(all_)) or (len(all_) == 20 and n < 20))


def same_split(expected, got):
    return isinstance(expected, list) and len(expected) == len(got) and all(e == g for e, g in zip(expected, got))


def judge_mode(where, a, text, re, g, y, c, w):
    def check(what, ok):
        if ok:
            c.right += 1
        else:
            c.wrong += 1
            w.append(f"WRONG\tcaptures.jsonl\t{where}\t{what}")

    has_lone = lone(text)
    starts, ends = units_to_points(text)
    byte_at = None if has_lone else units_to_bytes(text)
    utf8 = None if has_lone else text.encode()
    exec_ = a.get("exec")
    try:
        m = re.search(text, timeout=LIMIT)
    except ecma.MatchLimitError:
        c.limited += 1
        w.append(f"LIMIT\tcaptures.jsonl\t{where}")
        return
    check("exec", same_slots(exec_, m, starts, ends))
    if utf8 is not None:
        check("exec-utf8", same_slots(exec_, re.search(utf8), byte_at, byte_at))

    all_ = a.get("all") or []
    # The groups of each match too, over the str.
    ok = True
    n = 0
    for m in g.finditer(text):
        if n >= len(all_):
            ok = ok and len(all_) == 20
            break
        if not same_slots(all_[n], m, starts, ends):
            ok = False
            break
        n += 1
    if (len(all_) < 20 and n != len(all_)) or (len(all_) == 20 and n < 20):
        ok = False
    check("all", ok and judge_all(g.finditer(text), all_, starts, ends))
    if utf8 is not None:
        check("all-utf8", judge_all(g.finditer(utf8), all_, byte_at, byte_at))

    # Sticky at UTF-16 index 1: over the str where that is a position of it, and over code units where it falls
    # between the halves of the first character, which a str position cannot name (positions then are the data's own).
    if text:
        sticky = a.get("sticky")
        if ord(text[0]) <= 0xFFFF:
            check("sticky", same_slots(sticky, y.search(text, 1), starts, ends))
        else:
            check("sticky", same_slots(sticky, y.search(code_units(text), 1), None, None))
        if utf8 is not None and (byte_at[1] >= len(utf8) or (utf8[byte_at[1]] & 0xC0) != 0x80):
            check("sticky-utf8", same_slots(sticky, y.search(utf8, byte_at[1]), byte_at, byte_at))

    replace, replace_all = a.get("replace"), a.get("replaceAll")
    check("replace", replace is not None and re.replace(text, REPLACEMENT) == replace)
    check("replaceAll", replace_all is not None and g.replace(text, REPLACEMENT) == replace_all)
    if utf8 is not None:
        check("replace-utf8", replace is not None and re.replace(utf8, REPLACEMENT8) == utf8_lossy(replace))
        check("replaceAll-utf8", replace_all is not None and g.replace(utf8, REPLACEMENT8) == utf8_lossy(replace_all))

    check("split", same_split(a.get("split"), re.split(text)))
    check("split3", same_split(a.get("split3"), re.split(text, 3)))


def judge_captures(r, pattern, c, w):
    flags = r.get("flags", "")
    valid = r.get("valid", {})
    head_pattern = shown(pattern)
    cache = {}

    def make(f):
        if f not in cache:
            cache[f] = compile_or_why(pattern, f)[0]
        return cache[f]

    for test in r.get("tests", []):
        if test.get("v8_deviation"):
            continue
        text = test.get("text")
        if text is None:
            continue
        for mode in ("unicode", "legacy"):
            if not valid.get(mode) or mode not in test:
                continue
            mode_flags = flags + ("u" if mode == "unicode" else "")
            where = f"/{head_pattern}/{mode_flags}\t{escape(text)}"
            re, g, y = make(mode_flags), make(mode_flags + "g"), make(mode_flags + "y")
            if re is None or g is None or y is None:
                c.refused += 1
                w.append(f"REFUSED\tcaptures.jsonl\t{where}")
                continue
            try:
                judge_mode(where, test[mode], text, re, g, y, c, w)
            except Exception as e:  # anything else a match raises is an error, as in the C runner
                c.errors += 1
                w.append(f"ERROR\tcaptures.jsonl\t{where}\t{type(e).__name__}: {e}")


EXEC = "exec/test262.jsonl"


def last_index_of(t, length):
    """A call's lastIndex. Past the end of the text exec gives null; test262 sets it as far as 2^53 - 1 and
    Number.MAX_VALUE, so anything past the end reads as the text's length plus one."""
    v = t["lastIndex"]
    return length + 1 if v > length else int(v)


def inside_pair(units, at):
    """Whether a position is between the halves of a surrogate pair, where UTF-8 has no position."""
    return 0 < at < len(units) and 0xDC00 <= units[at] <= 0xDFFF and 0xD800 <= units[at - 1] <= 0xDBFF


def same_exec(answer, m, names, carries, at):
    """Whether a match (None for none) is the call's answer: both null, or the same groups, the same named groups
    (present exactly when the pattern has names) and, with g or y, a lastIndex after at the match's end. at maps the
    answer's UTF-16 positions to the match's."""
    if answer is None or m is None:
        return answer is None and m is None
    span = lambda e: (-1, -1) if e is None else (at[e[0]], at[e[1]])
    captures = answer["captures"]
    if len(captures) != m.re.groups + 1 or any(m.span(g) != span(e) for g, e in enumerate(captures)):
        return False
    groups = answer.get("groups")
    if groups is None:
        if names:
            return False
    elif sorted(groups) != sorted(names) or any(m.span(n) != span(e) for n, e in groups.items()):
        return False
    return not carries or at[answer["lastIndex"]] == m.end(0)


def judge_exec(r, pattern, c, w):
    """A record of exec/test262.jsonl: the pattern with its own flags (g, y and d among them), from each lastIndex."""
    flags = r["flags"]
    re, why, is_error = compile_or_why(pattern, flags)
    if re is None:
        c.refused += 1
        w.append(f"REFUSED\t{EXEC}\t/{shown(pattern)}/{flags}\t{why}")
        return
    carries = "g" in flags or "y" in flags
    names = re.group_names
    for t in r.get("tests") or []:
        if t.get("v8_deviation"):
            continue
        text = t["text"]
        units = code_units(text)
        start = last_index_of(t, len(units)) if carries else 0
        answer = t["answer"]
        where = f"/{shown(pattern)}/{flags}\t{escape(text)}\t{t['lastIndex']}"
        for encoding, subject, at in [("utf16", units, range(len(units) + 1))] + (
                [] if lone(text) or inside_pair(units, start) else [("utf8", text.encode(), units_to_bytes(text))]):
            try:
                m = None if start > len(units) else re.search(subject, at[start], timeout=LIMIT)
            except ecma.MatchLimitError:
                c.limited += 1
                w.append(f"LIMIT\t{EXEC}\t{where}\t{encoding}")
                continue
            if same_exec(answer, m, names, carries, at):
                c.right += 1
            else:
                c.wrong += 1
                w.append(f"WRONG\t{EXEC}\t{where}\t{encoding}")


def write_compliance(path, total):
    """The engine's compliance as the benchmark page reads it: the counts, this runner and the calls it makes in each
    encoding, and what it leaves out."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"right": total.right, "wrong": total.wrong, "refused": total.refused, "acceptedInvalid": total.accepted,
                   "limited": total.limited + total.errors,
                   "judge": {"runner": "https://github.com/corvus-dotnet/corvus-regex-ecma262-py/blob/main/tools/dataset.py",
                             "calls": {"utf16": ["Regex.test(str)", "Regex.search(str)", "Regex.search(array)",
                                                 "Regex.finditer(str)", "Regex.replace(str)", "Regex.replace_all(str)",
                                                 "Regex.split(str)"],
                                       "utf8": ["Regex.test(bytes)", "Regex.search(bytes)", "Regex.finditer(bytes)",
                                                "Regex.replace(bytes)", "Regex.replace_all(bytes)"]}},
                   "excludes": []}, f)
        f.write("\n")


def judge_lines(args):
    name, lines = args
    c, w = Counts(), []
    records = skipped = 0
    for line in lines:
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("v8_deviation"):
            skipped += 1
            continue
        records += 1
        pattern = r.get("pattern")
        if pattern is None:
            continue
        if name == EXEC:
            judge_exec(r, pattern, c, w)
        elif name == "captures.jsonl":
            judge_captures(r, pattern, c, w)
        elif name == "ill-formed-utf8.jsonl":
            judge_ill_formed(r, pattern, c, w)
        else:
            judge_tests(name, r, pattern, c, w)
    return c, w, records, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("wrong")
    ap.add_argument("--files", default="*.jsonl")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--compliance")
    ap.add_argument("--edition", choices=["current", "es2020"], default="current")
    ap.add_argument("--unicode", choices=["13", "17", "18", "latest"])
    args = ap.parse_args()
    version = None if args.unicode is None else args.unicode if args.unicode == "latest" else int(args.unicode)
    settings = {"edition": args.edition, "unicode_version": version}
    use_settings(settings)
    files = sorted(f for f in os.listdir(args.data) if f.endswith(".jsonl") and fnmatch.fnmatch(f, args.files))
    # The exec calls of test262, in a directory of their own: with the default filter, or one that names them.
    if (args.files == "*.jsonl" or args.files.startswith("exec")) and os.path.isfile(os.path.join(args.data, EXEC)):
        files.append(EXEC)
    total, wrong = Counts(), []
    records = skipped = 0
    start = time.monotonic()
    with Pool(args.workers, initializer=use_settings, initargs=(settings,)) as pool:
        for name in files:
            with open(os.path.join(args.data, name), encoding="utf-8", errors="surrogatepass") as f:
                lines = f.read().splitlines()
            chunks = [(name, lines[i:i + 200]) for i in range(0, len(lines), 200)]
            file_total = Counts()
            for c, w, rec, skip in pool.imap(judge_lines, chunks):
                file_total.add(c)
                wrong.extend(w)
                records += rec
                skipped += skip
            print(f"{name:<24} right {file_total.right:>10}  wrong {file_total.wrong:>6}  refused-valid {file_total.refused:>4}  "
                  f"accepted-invalid {file_total.accepted:>4}  limit {file_total.limited:>4}  {time.monotonic() - start:6.1f}s", flush=True)
            total.add(file_total)
    wrong.sort()
    with open(args.wrong, "w", encoding="utf-8", errors="surrogatepass") as f:
        for line in wrong:
            f.write(line + "\n")
    if args.compliance:
        write_compliance(args.compliance, total)
    print(f"\nrecords {records} (skipped {skipped} deviations)  right {total.right}  wrong {total.wrong}  "
          f"refused-valid {total.refused}  accepted-invalid {total.accepted}  limit {total.limited}  errors {total.errors}  "
          f"in {time.monotonic() - start:.1f}s")
    return 0 if total.wrong + total.refused + total.accepted + total.errors + total.limited == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
