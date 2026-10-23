//! Python bindings for the corvus-regex-ecma262 crate: ECMA-262 (JavaScript) regular expressions, with the grammar and
//! the answers of RegExp. The Python package (python/corvus_regex_ecma262) re-exports these types.
//!
//! A `str` is matched where it is cheapest and exact. Its UTF-8 (which CPython keeps once made) is matched when the
//! pattern has the u or v flag or the text has no character beyond the Basic Multilingual Plane, and its UTF-16 when
//! the pattern has neither flag and the text has such a character (without u or v a pattern matches by UTF-16 code
//! unit, so a match can take half of one) or when the text holds a lone surrogate, which has no UTF-8. Positions are
//! given in code points, as Python indexes a `str`; a position between the halves of a character is given as the
//! character's start for a start and its end for an end. `bytes` are UTF-8, matched as they are, positions in bytes.
//! An `array.array` of typecode 'H' is UTF-16 code units, matched as they are, positions in code units: the text as
//! JavaScript holds it, a position between the halves of a character and a lone surrogate included, which a `str`,
//! indexed by code point, cannot give. Every match runs without the GIL.

use std::sync::Arc;
use std::time::Duration;

use corvus_regex_ecma262 as ecma;
use pyo3::create_exception;
use pyo3::exceptions::{PyIndexError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyString, PyTuple};

// `error`, as `re.error` is named.
#[allow(non_camel_case_types)]
mod errors {
    use super::*;
    create_exception!(
        corvus_regex_ecma262,
        error,
        PyValueError,
        "A pattern or its flags are not valid (the SyntaxError of new RegExp), or the pattern is over a limit of size."
    );
}
use errors::error;
create_exception!(
    corvus_regex_ecma262,
    MatchLimitError,
    error,
    "A match reached its limit of time, or of backtracking memory, so it has no answer."
);

/// UTF-8 a Python object holds: a `str`'s UTF-8 (which CPython keeps with the string once made) or the bytes of a
/// `bytes`, read without asking Python again for each match.
#[derive(Clone, Copy)]
struct Utf8Text {
    ptr: *const u8,
    len: usize,
}

// SAFETY: the text is immutable and lives as long as the Python object the Hay holds beside it.
unsafe impl Send for Utf8Text {}
unsafe impl Sync for Utf8Text {}

impl Utf8Text {
    fn of(s: &str) -> Utf8Text {
        Utf8Text { ptr: s.as_ptr(), len: s.len() }
    }

    /// SAFETY: the object it was taken from must be alive, and its text must be UTF-8.
    unsafe fn get(&self) -> &str {
        unsafe { std::str::from_utf8_unchecked(std::slice::from_raw_parts(self.ptr, self.len)) }
    }
}

/// The text of a call, as the engine reads it, with the Python object that holds it.
enum Hay {
    /// A `str` whose UTF-8 is matched; `ascii` when every character is ASCII, so that a byte is a code point.
    Utf8 { _s: Py<PyString>, text: Utf8Text, ascii: bool },
    /// A `str` matched as UTF-16.
    Utf16(Arc<Vec<u16>>),
    /// `bytes`, UTF-8 (checked when the Hay is made), positions in bytes.
    Bytes { _b: Py<PyBytes>, text: Utf8Text },
    /// An `array.array('H')`: UTF-16 code units, positions in code units.
    Units(Arc<Vec<u16>>),
}

/// The engine's text for the length of a call.
#[derive(Clone, Copy)]
enum View<'a> {
    Utf8(&'a str),
    Utf16(&'a [u16]),
}

impl Hay {
    fn view(&self) -> View<'_> {
        match self {
            // SAFETY: the Hay holds the object the text is in, and the text was UTF-8 when it was taken.
            Hay::Utf8 { text, .. } | Hay::Bytes { text, .. } => View::Utf8(unsafe { text.get() }),
            Hay::Utf16(u) | Hay::Units(u) => View::Utf16(u),
        }
    }

    /// The text's units counted as Python counts them: identity for ASCII, bytes and code units.
    fn identity(&self) -> bool {
        matches!(self, Hay::Utf8 { ascii: true, .. } | Hay::Bytes { .. } | Hay::Units(_))
    }
}

/// Converts between the engine's positions (bytes of UTF-8, or UTF-16 code units) and Python's (code points), going
/// on from where it was last asked, since a search asks in order.
struct Positions {
    unit: usize,
    point: usize,
}

impl Positions {
    fn new() -> Positions {
        Positions { unit: 0, point: 0 }
    }

    /// The code point index of an engine position; `end` rounds a position between the halves of a character up.
    fn point(&mut self, view: View<'_>, identity: bool, at: usize, end: bool) -> usize {
        if identity {
            return at;
        }
        if at < self.unit {
            self.unit = 0;
            self.point = 0;
        }
        match view {
            View::Utf8(s) => {
                let bytes = s.as_bytes();
                // A lead byte starts a character; a position inside one (the third byte of a four-byte one, between
                // the halves of a pair) counts it as begun. Counted over the slice, which the compiler vectorises.
                let p = self.point + bytes[self.unit..at].iter().filter(|&&b| (b as i8) >= -0x40).count();
                self.unit = at;
                self.point = p;
                // Inside a character: its start, or (for an end) past it.
                if at < bytes.len() && (bytes[at] & 0xC0) == 0x80 { if end { p } else { p - 1 } } else { p }
            }
            View::Utf16(units) => {
                let mut u = self.unit;
                let mut p = self.point;
                while u < at {
                    let c = units[u];
                    if (0xD800..0xDC00).contains(&c) && u + 1 < units.len() && (0xDC00..0xE000).contains(&units[u + 1])
                    {
                        if u + 1 == at {
                            // Between the halves.
                            self.unit = u;
                            self.point = p;
                            return if end { p + 1 } else { p };
                        }
                        u += 2;
                    } else {
                        u += 1;
                    }
                    p += 1;
                }
                self.unit = u;
                self.point = p;
                p
            }
        }
    }

    /// The engine position of a code point index (the text's end when it is past it); with `identity` (ASCII, bytes
    /// and code units) the position itself.
    fn unit(view: View<'_>, identity: bool, point: usize) -> usize {
        if identity {
            return point.min(Regex::text_len(view));
        }
        match view {
            View::Utf8(s) => s.char_indices().nth(point).map_or(s.len(), |(b, _)| b),
            View::Utf16(units) => {
                let mut u = 0;
                let mut p = 0;
                while u < units.len() && p < point {
                    let c = units[u];
                    u += if (0xD800..0xDC00).contains(&c)
                        && u + 1 < units.len()
                        && (0xDC00..0xE000).contains(&units[u + 1])
                    {
                        2
                    } else {
                        1
                    };
                    p += 1;
                }
                u
            }
        }
    }
}

/// The error of a pattern that does not compile, with `kind`: "pattern" (not valid in the grammar of its flags),
/// "flags" (the flags are not valid) or "too_large" (over a limit of size).
fn compile_error(py: Python<'_>, e: ecma::Error) -> PyErr {
    let kind = match e {
        ecma::Error::TooLarge(_) => "too_large",
        ecma::Error::Flags(_) => "flags",
        _ => "pattern",
    };
    let err = error::new_err(e.to_string());
    let _ = err.value(py).setattr("kind", kind);
    err
}

fn limit_error(e: ecma::MatchError) -> PyErr {
    MatchLimitError::new_err(e.to_string())
}

/// A timeout in seconds as the crate takes it: None for none (as is 0).
fn seconds_of(timeout: Option<Duration>) -> Option<f64> {
    timeout.map(|t| t.as_secs_f64())
}

fn limit_of(timeout: Option<f64>) -> PyResult<Option<Duration>> {
    match timeout {
        None => Ok(None),
        Some(t) if t.is_finite() && t >= 0.0 => Ok(Some(Duration::from_secs_f64(t))),
        Some(_) => Err(PyValueError::new_err("timeout must be a number of seconds, 0 or more")),
    }
}

/// A Python string from UTF-16 that may hold lone surrogates.
fn str_of_units<'py>(py: Python<'py>, units: &[u16]) -> PyResult<Bound<'py, PyAny>> {
    if let Ok(s) = String::from_utf16(units) {
        return Ok(PyString::new(py, &s).into_any());
    }
    let bytes: Vec<u8> = units.iter().flat_map(|u| u.to_le_bytes()).collect();
    PyBytes::new(py, &bytes).call_method1("decode", ("utf-16-le", "surrogatepass"))
}

/// The UTF-16 of a Python string, lone surrogates and all.
fn units_of(s: &Bound<'_, PyString>) -> PyResult<Vec<u16>> {
    let encoded = s.call_method1("encode", ("utf-16-le", "surrogatepass"))?;
    let bytes = encoded.cast::<PyBytes>()?.as_bytes();
    Ok(bytes.as_chunks::<2>().0.iter().map(|c| u16::from_le_bytes(*c)).collect())
}

/// The type `array.array`.
fn array_type(py: Python<'_>) -> PyResult<Bound<'_, PyAny>> {
    py.import("array")?.getattr("array")
}

/// The code units of an `array.array('H')`, which holds them in the machine's byte order.
fn units_of_array(a: &Bound<'_, PyAny>) -> PyResult<Vec<u16>> {
    let typecode: String = a.getattr("typecode")?.extract()?;
    if typecode != "H" {
        return Err(PyTypeError::new_err(format!(
            "an array of UTF-16 code units has the typecode 'H', not {typecode:?}"
        )));
    }
    let bytes = a.call_method0("tobytes")?;
    Ok(bytes.cast::<PyBytes>()?.as_bytes().as_chunks::<2>().0.iter().map(|c| u16::from_ne_bytes(*c)).collect())
}

/// An `array.array('H')` of code units.
fn array_of_units<'py>(py: Python<'py>, units: &[u16]) -> PyResult<Bound<'py, PyAny>> {
    let a = array_type(py)?.call1(("H",))?;
    let bytes: Vec<u8> = units.iter().flat_map(|u| u.to_ne_bytes()).collect();
    a.call_method1("frombytes", (PyBytes::new(py, &bytes),))?;
    Ok(a)
}

/// A compiled ECMA-262 regular expression: `Regex(pattern, flags="")`, as `new RegExp(pattern, flags)`.
#[pyclass(frozen, module = "corvus_regex_ecma262", name = "Regex")]
struct Regex {
    inner: Arc<ecma::Regex>,
    /// Neither u nor v: a match is by UTF-16 code unit.
    legacy: bool,
    global: bool,
    names: Vec<String>,
}

impl Regex {
    /// The engine's text for a `str`, `bytes` or an `array.array('H')`.
    fn hay(&self, text: &Bound<'_, PyAny>) -> PyResult<Hay> {
        if let Ok(s) = text.cast::<PyString>() {
            let Ok(utf8) = s.to_str() else {
                // A lone surrogate: UTF-16 alone holds it.
                return Ok(Hay::Utf16(Arc::new(units_of(s)?)));
            };
            let ascii = utf8.len() == s.len()?;
            // Without u or v a character beyond the Basic Multilingual Plane is two units a match may part.
            if !ascii && self.legacy && utf8.as_bytes().iter().any(|&b| b >= 0xF0) {
                return Ok(Hay::Utf16(Arc::new(utf8.encode_utf16().collect())));
            }
            return Ok(Hay::Utf8 { _s: s.clone().unbind(), text: Utf8Text::of(utf8), ascii });
        }
        if let Ok(b) = text.cast::<PyBytes>() {
            // Checked once here: a view of the text reads it unchecked from then on.
            let text = match simdutf8::basic::from_utf8(b.as_bytes()) {
                Ok(t) => t,
                // The vectorised check says only whether; the standard one says where.
                Err(_) => std::str::from_utf8(b.as_bytes()).map_err(|e| PyValueError::new_err(e.to_string()))?,
            };
            return Ok(Hay::Bytes { _b: b.clone().unbind(), text: Utf8Text::of(text) });
        }
        if text.is_instance(&array_type(text.py())?)? {
            return Ok(Hay::Units(Arc::new(units_of_array(text)?)));
        }
        Err(PyTypeError::new_err(format!(
            "expected str, bytes or an array.array('H') of UTF-16 code units, not {}",
            text.get_type().name()?
        )))
    }

    /// The groups of a match, in engine positions: the whole match, then each group (None for one that did not take
    /// part), then the group of each name.
    fn spans_of_utf8(&self, caps: &ecma::Captures<'_>) -> Spans {
        Spans {
            groups: caps.iter().map(|m| m.map(|m| (m.start(), m.end()))).collect(),
            named: self.names.iter().map(|n| caps.name(n).map(|m| (m.start(), m.end()))).collect(),
        }
    }

    fn spans_of_utf16(&self, caps: &ecma::Captures<'_, [u16]>) -> Spans {
        Spans {
            groups: caps.iter().map(|m| m.map(|m| (m.start(), m.end()))).collect(),
            named: self.names.iter().map(|n| caps.name(n).map(|m| (m.start(), m.end()))).collect(),
        }
    }

    /// The first match at or after `start` (engine position), with a limit of its own, or the pattern's timeout.
    fn captures_at(&self, view: View<'_>, start: usize, limit: Option<Duration>) -> PyResult<Option<Spans>> {
        match view {
            View::Utf8(s) => {
                let caps = match limit {
                    Some(l) => self.inner.captures_at_within(s, start, l),
                    None => self.inner.captures_at(s, start),
                };
                Ok(caps.map_err(limit_error)?.map(|c| self.spans_of_utf8(&c)))
            }
            View::Utf16(u) => {
                let caps = match limit {
                    Some(l) => self.inner.captures_at_within_utf16(u, start, l),
                    None => self.inner.captures_at_utf16(u, start),
                };
                Ok(caps.map_err(limit_error)?.map(|c| self.spans_of_utf16(&c)))
            }
        }
    }

    /// The next match of a global search at or after `start`: where it is alone when the pattern has no group, which
    /// spares the engine the groups' memory.
    fn next_at(&self, view: View<'_>, start: usize) -> PyResult<Option<Spans>> {
        if self.inner.captures_len() > 1 {
            return self.captures_at(view, start, None);
        }
        let found = match view {
            View::Utf8(s) => self.inner.find_at(s, start).map_err(limit_error)?.map(|m| (m.start(), m.end())),
            View::Utf16(u) => self.inner.find_at_utf16(u, start).map_err(limit_error)?.map(|m| (m.start(), m.end())),
        };
        Ok(found.map(|m| Spans { groups: vec![Some(m)], named: Vec::new() }))
    }

    /// The engine position after an empty match at `at`: one code point on with u or v, one code unit without.
    fn advance(&self, view: View<'_>, at: usize) -> usize {
        match view {
            View::Utf8(s) => {
                let b = s.as_bytes();
                // Without u or v a character beyond the Basic Multilingual Plane is two code units: from its start
                // the next unit is between its halves, which UTF-8 gives as its third byte.
                if self.legacy && at < b.len() && b[at] >= 0xF0 {
                    return at + 2;
                }
                let mut next = at + 1;
                while next < b.len() && (b[next] & 0xC0) == 0x80 {
                    next += 1;
                }
                next
            }
            View::Utf16(u) => {
                if !self.legacy
                    && at + 1 < u.len()
                    && (0xD800..0xDC00).contains(&u[at])
                    && (0xDC00..0xE000).contains(&u[at + 1])
                {
                    at + 2
                } else {
                    at + 1
                }
            }
        }
    }

    fn text_len(view: View<'_>) -> usize {
        match view {
            View::Utf8(s) => s.len(),
            View::Utf16(u) => u.len(),
        }
    }
}

/// Where a group is, start to end, or None when it did not take part.
type Span = Option<(usize, usize)>;

/// A match's groups in engine positions.
#[derive(Clone)]
struct Spans {
    groups: Vec<Option<(usize, usize)>>,
    named: Vec<Option<(usize, usize)>>,
}

impl Spans {
    fn whole(&self) -> (usize, usize) {
        self.groups[0].expect("group 0 is the match")
    }
}

#[pymethods]
impl Regex {
    #[new]
    #[pyo3(signature = (pattern, flags = "", *, timeout = None))]
    fn new(py: Python<'_>, pattern: &Bound<'_, PyAny>, flags: &str, timeout: Option<f64>) -> PyResult<Regex> {
        let pattern: String = if let Ok(s) = pattern.cast::<PyString>() {
            match s.to_str() {
                Ok(p) => p.to_owned(),
                // A lone surrogate in a pattern is read as U+FFFD, as the crate's UTF-8 patterns have none.
                Err(_) => String::from_utf16_lossy(&units_of(s)?),
            }
        } else {
            return Err(PyTypeError::new_err("the pattern must be a str"));
        };
        let inner = match limit_of(timeout)? {
            // None: the default timeout (see set_default_timeout).
            None => py.detach(|| ecma::Regex::new(&pattern, flags)),
            Some(t) => {
                let flags = ecma::Flags::parse(flags).map_err(|e| compile_error(py, e))?;
                py.detach(|| ecma::Regex::with_timeout(&pattern, flags, Some(t)))
            }
        }
        .map_err(|e| compile_error(py, e))?;
        let f = inner.flags();
        let flag_text = format!("{f}");
        let names = inner.group_names().map(str::to_owned).collect();
        Ok(Regex {
            inner: Arc::new(inner),
            legacy: !flag_text.contains('u') && !flag_text.contains('v'),
            global: flag_text.contains('g'),
            names,
        })
    }

    /// Whether a pattern is valid with the flags, without compiling it.
    #[staticmethod]
    #[pyo3(signature = (pattern, flags = ""))]
    fn is_valid(pattern: &str, flags: &str) -> bool {
        ecma::Regex::is_valid(pattern, flags)
    }

    /// The pattern as it was given.
    #[getter]
    fn pattern(&self) -> &str {
        self.inner.as_str()
    }

    /// The flags as RegExp.prototype.flags writes them, in the order dgimsuvy.
    #[getter]
    fn flags(&self) -> String {
        format!("{}", self.inner.flags())
    }

    /// The time in seconds each match may take before it is abandoned with MatchLimitError, or None for no limit.
    #[getter]
    fn timeout(&self) -> Option<f64> {
        seconds_of(self.inner.match_timeout())
    }

    /// The number of capturing groups.
    #[getter]
    fn groups(&self) -> usize {
        self.inner.captures_len() - 1
    }

    /// The distinct names of the groups, in the order of the first group of each name.
    #[getter]
    fn group_names(&self) -> Vec<String> {
        self.names.clone()
    }

    /// Whether the pattern matches at or after pos (at pos alone with the y flag), as RegExp.prototype.test with
    /// lastIndex set to pos. A match that reaches the pattern's timeout raises MatchLimitError; a timeout in seconds
    /// here takes the timeout's place for this match (0 for none).
    #[pyo3(signature = (string, pos = 0, *, timeout = None))]
    fn test(&self, py: Python<'_>, string: &Bound<'_, PyAny>, pos: usize, timeout: Option<f64>) -> PyResult<bool> {
        let limit = limit_of(timeout)?;
        let hay = self.hay(string)?;
        let view = hay.view();
        let start = Positions::unit(view, hay.identity(), pos);
        if start > Regex::text_len(view) {
            return Ok(false);
        }
        let inner = &self.inner;
        py.detach(|| match (view, limit) {
            (View::Utf8(s), None) => inner.is_match_at(s, start).map_err(limit_error),
            (View::Utf16(u), None) => inner.is_match_at_utf16(u, start).map_err(limit_error),
            (View::Utf8(s), Some(l)) => inner.find_at_within(s, start, l).map(|m| m.is_some()).map_err(limit_error),
            (View::Utf16(u), Some(l)) => {
                inner.find_at_within_utf16(u, start, l).map(|m| m.is_some()).map_err(limit_error)
            }
        })
    }

    /// The first match at or after pos, as exec finds it with lastIndex set to pos: a Match, or None. A match that
    /// reaches the pattern's timeout raises MatchLimitError; a timeout in seconds here takes its place (0 for none).
    #[pyo3(signature = (string, pos = 0, *, timeout = None))]
    fn search(
        slf: &Bound<'_, Regex>,
        string: &Bound<'_, PyAny>,
        pos: usize,
        timeout: Option<f64>,
    ) -> PyResult<Option<Match>> {
        let py = slf.py();
        let this = slf.get();
        let limit = limit_of(timeout)?;
        let hay = Arc::new(this.hay(string)?);
        let view = hay.view();
        let start = Positions::unit(view, hay.identity(), pos);
        if start > Regex::text_len(view) {
            return Ok(None);
        }
        let Some(spans) = py.detach(|| this.captures_at(view, start, limit))? else {
            return Ok(None);
        };
        Ok(Some(Match::new(slf, string, &hay, spans, &Arc::new(std::sync::Mutex::new(Positions::new())))))
    }

    /// Every match of a global search of the string, as matchAll makes one: an iterator of Match. After an empty match
    /// the search goes on one character later, and with the y flag each match must start where the one before ended.
    /// A match that reaches the pattern's timeout raises MatchLimitError, and ends the search.
    fn finditer(slf: &Bound<'_, Regex>, string: &Bound<'_, PyAny>) -> PyResult<MatchIterator> {
        let hay = Arc::new(slf.get().hay(string)?);
        Ok(MatchIterator {
            regex: slf.clone().unbind(),
            string: string.clone().unbind(),
            hay,
            next: Some(0),
            positions: Arc::new(std::sync::Mutex::new(Positions::new())),
            buffer: std::collections::VecDeque::with_capacity(BATCH),
            pending: None,
        })
    }

    /// The string with the first match replaced, or every match with the g flag, as String.prototype.replace replaces
    /// them. The replacement is a template ($& the match, $` the text before it, $' the text after it, $1 to $99 a
    /// group, $<name> a named group, $$ a dollar sign) or a function of the Match that returns the text to put in.
    fn replace<'py>(
        slf: &Bound<'py, Regex>,
        string: &Bound<'py, PyAny>,
        replacement: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let all = slf.get().global;
        Regex::replace_impl(slf, string, replacement, all)
    }

    /// The string with every match replaced, whether or not the g flag is set (String.prototype.replaceAll).
    fn replace_all<'py>(
        slf: &Bound<'py, Regex>,
        string: &Bound<'py, PyAny>,
        replacement: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        Regex::replace_impl(slf, string, replacement, true)
    }

    /// The string split around the matches, as String.prototype.split(separator, limit) splits it: what each group
    /// captured is spliced in after the piece before it (None for a group that did not take part), an empty match at
    /// the start or the end splits nothing, and there are at most limit pieces.
    #[pyo3(signature = (string, limit = None))]
    fn split<'py>(&self, string: &Bound<'py, PyAny>, limit: Option<usize>) -> PyResult<Vec<Option<Bound<'py, PyAny>>>> {
        let py = string.py();
        let hay = self.hay(string)?;
        let view = hay.view();
        let inner = &self.inner;
        match view {
            View::Utf8(s) => {
                let pieces = py
                    .detach(|| match limit {
                        Some(n) => inner.splitn(s, n),
                        None => inner.split(s),
                    })
                    .map_err(limit_error)?;
                let bytes = matches!(hay, Hay::Bytes { .. });
                Ok(pieces
                    .into_iter()
                    .map(|p| {
                        p.map(|p| {
                            if bytes {
                                PyBytes::new(py, p.as_bytes()).into_any()
                            } else {
                                PyString::new(py, &p).into_any()
                            }
                        })
                    })
                    .collect())
            }
            View::Utf16(u) => {
                let pieces = py
                    .detach(|| match limit {
                        Some(n) => inner.splitn_utf16(u, n),
                        None => inner.split_utf16(u),
                    })
                    .map_err(limit_error)?;
                let units = matches!(hay, Hay::Units(_));
                pieces
                    .into_iter()
                    .map(|p| p.map(|p| if units { array_of_units(py, &p) } else { str_of_units(py, &p) }).transpose())
                    .collect()
            }
        }
    }

    fn __repr__(&self) -> String {
        format!("corvus_regex_ecma262.Regex({:?}, {:?})", self.inner.as_str(), format!("{}", self.inner.flags()))
    }
}

impl Regex {
    fn replace_impl<'py>(
        slf: &Bound<'py, Regex>,
        string: &Bound<'py, PyAny>,
        replacement: &Bound<'py, PyAny>,
        all: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = slf.py();
        let this = slf.get();
        let hay = Arc::new(this.hay(string)?);
        let view = hay.view();
        let inner = &this.inner;
        let bytes = matches!(*hay, Hay::Bytes { .. });
        let units = matches!(*hay, Hay::Units(_));
        if !replacement.is_callable() {
            match view {
                View::Utf8(s) => {
                    let template: String = if bytes {
                        let b = replacement.cast::<PyBytes>().map_err(|_| {
                            PyTypeError::new_err("the replacement of bytes must be bytes or a function")
                        })?;
                        std::str::from_utf8(b.as_bytes()).map_err(|e| PyValueError::new_err(e.to_string()))?.to_owned()
                    } else {
                        replacement
                            .cast::<PyString>()
                            .map_err(|_| PyTypeError::new_err("the replacement of a str must be a str or a function"))?
                            .to_str()?
                            .to_owned()
                    };
                    let out = py
                        .detach(|| {
                            if all { inner.replace_all(s, &template) } else { inner.replace(s, &template) }
                                .map(|o| o.into_owned())
                        })
                        .map_err(limit_error)?;
                    return Ok(if bytes {
                        PyBytes::new(py, out.as_bytes()).into_any()
                    } else {
                        PyString::new(py, &out).into_any()
                    });
                }
                View::Utf16(u) => {
                    let template = if units {
                        // Code units, or a str (its UTF-16, lone surrogates and all).
                        match replacement.cast::<PyString>() {
                            Ok(s) => units_of(s)?,
                            Err(_) if replacement.is_instance(&array_type(py)?)? => units_of_array(replacement)?,
                            Err(_) => {
                                return Err(PyTypeError::new_err(
                                    "the replacement of an array of code units must be an array('H'), a str or a function",
                                ));
                            }
                        }
                    } else {
                        units_of(replacement.cast::<PyString>().map_err(|_| {
                            PyTypeError::new_err("the replacement of a str must be a str or a function")
                        })?)?
                    };
                    let out = py
                        .detach(|| {
                            if all { inner.replace_all_utf16(u, &template) } else { inner.replace_utf16(u, &template) }
                                .map(|o| o.into_owned())
                        })
                        .map_err(limit_error)?;
                    return if units { array_of_units(py, &out) } else { str_of_units(py, &out) };
                }
            }
        }
        // A function: called with each Match, its result put in place of the match.
        let mut pieces: Vec<Bound<'py, PyAny>> = Vec::new();
        let positions = Arc::new(std::sync::Mutex::new(Positions::new()));
        let mut last = 0;
        let mut at = 0;
        let len = Regex::text_len(view);
        while at <= len {
            let Some(spans) = py.detach(|| this.captures_at(view, at, None))? else { break };
            let (s, e) = spans.whole();
            pieces.push(Regex::slice(py, &hay, view, last, s)?);
            let m = Match::new(slf, string, &hay, spans, &positions);
            let put = replacement.call1((m,))?;
            let ok = if bytes {
                put.cast::<PyBytes>().is_ok()
            } else if units {
                put.is_instance(&array_type(py)?)?
            } else {
                put.cast::<PyString>().is_ok()
            };
            if !ok {
                return Err(PyTypeError::new_err("the replacement function must return the type of the string"));
            }
            pieces.push(put);
            last = e;
            if !all {
                break;
            }
            at = if e == s { this.advance(view, e) } else { e };
        }
        pieces.push(Regex::slice(py, &hay, view, last, len)?);
        if units {
            let out = array_type(py)?.call1(("H",))?;
            for piece in pieces {
                out.call_method1("extend", (piece,))?;
            }
            return Ok(out);
        }
        let empty = if bytes { PyBytes::new(py, b"").into_any() } else { PyString::new(py, "").into_any() };
        empty.call_method1("join", (pieces,))
    }

    /// The text from a to b (engine positions) as the string's type.
    fn slice<'py>(py: Python<'py>, hay: &Hay, view: View<'_>, a: usize, b: usize) -> PyResult<Bound<'py, PyAny>> {
        Ok(match (hay, view) {
            (Hay::Bytes { .. }, View::Utf8(s)) => PyBytes::new(py, &s.as_bytes()[a..b]).into_any(),
            (_, View::Utf8(s)) => PyString::new(py, &String::from_utf8_lossy(&s.as_bytes()[a..b])).into_any(),
            (Hay::Units(_), View::Utf16(u)) => array_of_units(py, &u[a..b])?,
            (_, View::Utf16(u)) => str_of_units(py, &u[a..b])?,
        })
    }
}

/// The global search of finditer, read in batches without the GIL.
#[pyclass(module = "corvus_regex_ecma262", name = "MatchIterator")]
struct MatchIterator {
    regex: Py<Regex>,
    string: Py<PyAny>,
    hay: Arc<Hay>,
    /// Where the search goes on (engine position), or None once it has found every match.
    next: Option<usize>,
    positions: Arc<std::sync::Mutex<Positions>>,
    buffer: std::collections::VecDeque<Spans>,
    /// The error of a match that reached the timeout, given once the matches before it have been.
    pending: Option<PyErr>,
}

const BATCH: usize = 64;

#[pymethods]
impl MatchIterator {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> PyResult<Option<Match>> {
        let py = slf.py();
        let it = &mut *slf;
        let regex = it.regex.bind(py);
        let view = it.hay.view();
        if it.buffer.is_empty() {
            if let Some(e) = it.pending.take() {
                return Err(e);
            }
            let Some(mut at) = it.next else { return Ok(None) };
            let this = regex.get();
            let len = Regex::text_len(view);
            let buffer = &mut it.buffer;
            let next = py.detach(|| -> PyResult<Option<usize>> {
                while buffer.len() < BATCH {
                    if at > len {
                        return Ok(None);
                    }
                    let Some(spans) = this.next_at(view, at)? else { return Ok(None) };
                    let (s, e) = spans.whole();
                    buffer.push_back(spans);
                    at = if e == s { this.advance(view, e) } else { e };
                }
                Ok(Some(at))
            });
            match next {
                Ok(next) => it.next = next,
                // A match that reached the timeout: the matches found before it come first, then the error, and the
                // search ends.
                Err(e) if it.buffer.is_empty() => {
                    it.next = None;
                    return Err(e);
                }
                Err(e) => {
                    it.next = None;
                    it.pending = Some(e);
                }
            }
        }
        let Some(spans) = it.buffer.pop_front() else { return Ok(None) };
        let string = it.string.bind(py);
        Ok(Some(Match::new(regex, string, &it.hay, spans, &it.positions)))
    }
}

/// A match: where it is and what each group captured, as Python positions, with the string it was found in.
#[pyclass(frozen, module = "corvus_regex_ecma262", name = "Match")]
struct Match {
    regex: Py<Regex>,
    string: Py<PyAny>,
    hay: Arc<Hay>,
    /// Engine positions, for the text of a group.
    spans: Spans,
    /// Python positions, where they are not the engine's (a str that is not all ASCII): worked out when first asked
    /// for, by the converter the search shares, so that a program that reads the text of each match alone never pays
    /// for them, and one that reads the positions of each match in turn pays once for the text.
    points: std::sync::OnceLock<Spans>,
    converter: Option<Arc<std::sync::Mutex<Positions>>>,
}

impl Match {
    fn new(
        regex: &Bound<'_, Regex>,
        string: &Bound<'_, PyAny>,
        hay: &Arc<Hay>,
        spans: Spans,
        converter: &Arc<std::sync::Mutex<Positions>>,
    ) -> Match {
        Match {
            regex: regex.clone().unbind(),
            string: string.clone().unbind(),
            hay: hay.clone(),
            spans,
            points: std::sync::OnceLock::new(),
            converter: (!hay.identity()).then(|| converter.clone()),
        }
    }

    /// The Python positions of the groups.
    fn points(&self) -> &Spans {
        let Some(converter) = &self.converter else { return &self.spans };
        self.points.get_or_init(|| {
            let view = self.hay.view();
            let mut positions = converter.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            let mut convert = |g: &Span| {
                g.map(|(s, e)| (positions.point(view, false, s, false), positions.point(view, false, e, true)))
            };
            Spans {
                groups: self.spans.groups.iter().map(&mut convert).collect(),
                named: self.spans.named.iter().map(&mut convert).collect(),
            }
        })
    }

    /// The index of a group given by number or name: Ok(Some(i)) into groups, or Err for a name into named.
    fn index(&self, py: Python<'_>, group: &Bound<'_, PyAny>) -> PyResult<Result<usize, usize>> {
        if let Ok(i) = group.extract::<usize>() {
            if i < self.spans.groups.len() {
                return Ok(Ok(i));
            }
            return Err(PyIndexError::new_err("no such group"));
        }
        if let Ok(name) = group.extract::<String>()
            && let Some(k) = self.regex.bind(py).get().names.iter().position(|n| *n == name)
        {
            return Ok(Err(k));
        }
        Err(PyIndexError::new_err("no such group"))
    }

    fn span_of(&self, py: Python<'_>, group: &Bound<'_, PyAny>) -> PyResult<(Span, Span)> {
        Ok(match self.index(py, group)? {
            Ok(i) => (self.points().groups[i], self.spans.groups[i]),
            Err(k) => (self.points().named[k], self.spans.named[k]),
        })
    }

    fn text<'py>(&self, py: Python<'py>, engine: Option<(usize, usize)>) -> PyResult<Option<Bound<'py, PyAny>>> {
        let Some((a, b)) = engine else { return Ok(None) };
        let view = self.hay.view();
        Regex::slice(py, &self.hay, view, a, b).map(Some)
    }
}

#[pymethods]
impl Match {
    /// The start of the group (0, the whole match, by default), or -1 when it did not take part.
    #[pyo3(signature = (group = None))]
    fn start(&self, py: Python<'_>, group: Option<&Bound<'_, PyAny>>) -> PyResult<isize> {
        let span = match group {
            Some(g) => self.span_of(py, g)?.0,
            None => self.points().groups[0],
        };
        Ok(span.map_or(-1, |(s, _)| s as isize))
    }

    /// The end of the group (0, the whole match, by default), or -1 when it did not take part.
    #[pyo3(signature = (group = None))]
    fn end(&self, py: Python<'_>, group: Option<&Bound<'_, PyAny>>) -> PyResult<isize> {
        let span = match group {
            Some(g) => self.span_of(py, g)?.0,
            None => self.points().groups[0],
        };
        Ok(span.map_or(-1, |(_, e)| e as isize))
    }

    /// The start and the end of the group, or (-1, -1) when it did not take part.
    #[pyo3(signature = (group = None))]
    fn span(&self, py: Python<'_>, group: Option<&Bound<'_, PyAny>>) -> PyResult<(isize, isize)> {
        let span = match group {
            Some(g) => self.span_of(py, g)?.0,
            None => self.points().groups[0],
        };
        Ok(span.map_or((-1, -1), |(s, e)| (s as isize, e as isize)))
    }

    /// The text of one group (None when it did not take part), or a tuple of several; with no argument, the match.
    #[pyo3(signature = (*groups))]
    fn group<'py>(&self, py: Python<'py>, groups: &Bound<'py, PyTuple>) -> PyResult<Bound<'py, PyAny>> {
        if groups.is_empty() {
            return Ok(self.text(py, self.spans.groups[0])?.into_pyobject(py)?);
        }
        if groups.len() == 1 {
            let (_, engine) = self.span_of(py, &groups.get_item(0)?)?;
            return Ok(self.text(py, engine)?.into_pyobject(py)?);
        }
        let mut out = Vec::with_capacity(groups.len());
        for g in groups.iter() {
            let (_, engine) = self.span_of(py, &g)?;
            out.push(self.text(py, engine)?);
        }
        Ok(PyTuple::new(py, out)?.into_any())
    }

    fn __getitem__<'py>(&self, py: Python<'py>, group: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyAny>>> {
        let (_, engine) = self.span_of(py, group)?;
        self.text(py, engine)
    }

    /// The text of every capturing group, default for one that did not take part.
    #[pyo3(signature = (default = None))]
    fn groups<'py>(&self, py: Python<'py>, default: Option<Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyTuple>> {
        let mut out = Vec::with_capacity(self.spans.groups.len().saturating_sub(1));
        for &g in &self.spans.groups[1..] {
            out.push(match self.text(py, g)? {
                Some(t) => t,
                None => default.clone().unwrap_or_else(|| py.None().into_bound(py)),
            });
        }
        PyTuple::new(py, out)
    }

    /// The text of the group of each name, default for a name whose group did not take part.
    #[pyo3(signature = (default = None))]
    fn groupdict<'py>(&self, py: Python<'py>, default: Option<Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        let names = &self.regex.bind(py).get().names;
        for (k, name) in names.iter().enumerate() {
            let v = match self.text(py, self.spans.named[k])? {
                Some(t) => t,
                None => default.clone().unwrap_or_else(|| py.None().into_bound(py)),
            };
            d.set_item(name, v)?;
        }
        Ok(d)
    }

    /// The string the match was found in.
    #[getter]
    fn string(&self, py: Python<'_>) -> Py<PyAny> {
        self.string.clone_ref(py)
    }

    /// The regular expression that found the match.
    #[getter]
    fn re(&self, py: Python<'_>) -> Py<Regex> {
        self.regex.clone_ref(py)
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        let (s, e) = self.points().groups[0].expect("group 0 is the match");
        let text = self.text(py, self.spans.groups[0])?.expect("group 0 is the match");
        Ok(format!("<corvus_regex_ecma262.Match object; span=({s}, {e}), match={}>", text.repr()?))
    }

    fn __bool__(&self) -> bool {
        true
    }
}

/// Sets the timeout of every Regex made from now on without one of its own: the time in seconds each match may take
/// before it is abandoned with MatchLimitError, or None (or 0) for no limit, the default. A program that matches
/// patterns or texts from outside should set one when it starts. A Regex already made keeps its own.
#[pyfunction]
#[pyo3(signature = (seconds))]
fn set_default_timeout(seconds: Option<f64>) -> PyResult<()> {
    ecma::set_default_match_timeout(limit_of(seconds)?);
    Ok(())
}

/// The timeout in seconds a Regex made now without one takes, or None for no limit.
#[pyfunction]
fn default_timeout() -> Option<f64> {
    seconds_of(ecma::default_match_timeout())
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(set_default_timeout, m)?)?;
    m.add_function(wrap_pyfunction!(default_timeout, m)?)?;
    m.add_class::<Regex>()?;
    m.add_class::<Match>()?;
    m.add_class::<MatchIterator>()?;
    m.add("error", m.py().get_type::<error>())?;
    m.add("MatchLimitError", m.py().get_type::<MatchLimitError>())?;
    m.add("MAX_PATTERN_LENGTH", ecma::MAX_PATTERN_LENGTH)?;
    m.add("MAX_NESTING", ecma::MAX_NESTING)?;
    Ok(())
}
