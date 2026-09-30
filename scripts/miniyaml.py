"""A YAML subset reader and writer in the standard library, so users need no PyYAML (SPEC E8).

Covers what Governor's own files use: block mappings and sequences, flow sequences and mappings,
plain, single- and double-quoted scalars (including multi-line ones as written by PyYAML's
safe_dump), comments, and YAML 1.1 scalar resolution as PyYAML's safe_load does it (null, bools,
ints, floats, dates). Not covered, and refused: anchors/aliases, tags, block scalars (| and >),
multiple documents. tests/test_miniyaml.py checks load() against yaml.safe_load on every YAML file
in the repository and round-trips dump() through both.
Known limit: flow collections ({...} / [...]) hold simple scalars; a key full of flow indicators
(for example 'a: ]{') inside a flow mapping is not read like PyYAML. Governor writes block style only.
"""
import datetime
import json
import re


class YamlError(ValueError):
    """Input outside the supported subset, or malformed."""


_NULL = {"", "~", "null", "Null", "NULL"}
_TRUE = {"yes", "Yes", "YES", "true", "True", "TRUE", "on", "On", "ON", "y", "Y"}
_FALSE = {"no", "No", "NO", "false", "False", "FALSE", "off", "Off", "OFF", "n", "N"}
_INT = re.compile(r"^[-+]?(0|[1-9][0-9_]*)$")
_FLOAT = re.compile(r"^[-+]?([0-9][0-9_]*)?\.[0-9_]*([eE][-+][0-9]+)?$|^[-+]?\.(inf|Inf|INF)$|^\.(nan|NaN|NAN)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ESC = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
        "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ", "P": " "}
# PyYAML resolves only y/Y/n/N... no: safe_load resolves yes/no/on/off/true/false; single y/n stay strings.
_TRUE -= {"y", "Y"}
_FALSE -= {"n", "N"}


def _plain(s):
    s = s.strip()
    if s in _NULL:
        return None
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    if _INT.match(s):
        return int(s.replace("_", ""))
    if _FLOAT.match(s) and s not in (".", "-.", "+."):
        low = s.lower().lstrip("+-")
        if low in (".inf",):
            return float("-inf") if s.startswith("-") else float("inf")
        if low == ".nan":
            return float("nan")
        return float(s.replace("_", ""))
    if _DATE.match(s):
        try:
            return datetime.date.fromisoformat(s)
        except ValueError:
            return s
    if s[:1] in ("&", "*", "!", "|", ">", "%", "@", "`"):
        raise YamlError(f"unsupported YAML construct: {s[:20]!r}")
    return s


def _fold(parts):
    """Join the lines of a multi-line flow scalar: a single break becomes a space, blank lines become newlines."""
    out, blank = "", 0
    for i, p in enumerate(parts):
        p = p.strip() if 0 < i < len(parts) - 1 else (p.rstrip() if i == 0 else p.lstrip())
        if i == 0:
            out = p
            continue
        if p == "" and i < len(parts) - 1:
            blank += 1
            continue
        out += ("\n" * blank) if blank else " "
        blank = 0
        out += p
    return out


def _dq(text, i):
    """Parse a double-quoted scalar starting at text[i] == '"'. Returns (value, end index)."""
    j, buf, lines = i + 1, [], []
    while j < len(text):
        c = text[j]
        if c == '"':
            lines.append("".join(buf))
            return _fold_quoted(lines), j + 1
        if c == "\\":
            n = text[j + 1] if j + 1 < len(text) else ""
            if n == "":
                raise YamlError("unterminated double-quoted string")
            if n == "\n":  # escaped line break: join without space
                j += 2
                while j < len(text) and text[j] in " \t":
                    j += 1
                buf.append("\x00JOIN\x00")
                continue
            if n in "xuU":
                k = {"x": 2, "u": 4, "U": 8}[n]
                buf.append(chr(int(text[j + 2:j + 2 + k], 16)))
                j += 2 + k
                continue
            if n not in _ESC:
                raise YamlError(f"bad escape \\{n}")
            buf.append(_ESC[n])
            j += 2
            continue
        if c == "\n":
            lines.append("".join(buf))
            buf = []
            j += 1
            continue
        buf.append(c)
        j += 1
    raise YamlError("unterminated double-quoted string")


def _fold_quoted(lines):
    if len(lines) == 1:
        return lines[0].replace("\x00JOIN\x00", "")
    out = _fold(lines)
    return out.replace(" \x00JOIN\x00", "").replace("\x00JOIN\x00", "")


def _sq(text, i):
    j, buf, lines = i + 1, [], []
    while j < len(text):
        c = text[j]
        if c == "'":
            if text[j + 1:j + 2] == "'":
                buf.append("'")
                j += 2
                continue
            lines.append("".join(buf))
            return (lines[0] if len(lines) == 1 else _fold(lines)), j + 1
        if c == "\n":
            lines.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        j += 1
    raise YamlError("unterminated single-quoted string")


def _skip_ws(text, i):
    while i < len(text) and text[i] in " \t\n\r":
        i += 1
    return i


def _flow(text, i):
    """Parse a flow node at text[i]. Returns (value, end index)."""
    i = _skip_ws(text, i)
    c = text[i] if i < len(text) else ""
    if c == "[":
        out, i = [], _skip_ws(text, i + 1)
        while True:
            if i >= len(text):
                raise YamlError("unterminated flow sequence")
            if text[i] == "]":
                return out, i + 1
            v, i = _flow_entry(text, i, "]")
            out.append(v)
            i = _skip_ws(text, i)
            if i < len(text) and text[i] == ",":
                i = _skip_ws(text, i + 1)
    if c == "{":
        out, i = {}, _skip_ws(text, i + 1)
        while True:
            if i >= len(text):
                raise YamlError("unterminated flow mapping")
            if text[i] == "}":
                return out, i + 1
            k, i = _flow_scalar(text, i, ":,}", key=True)
            i = _skip_ws(text, i)
            if i < len(text) and text[i] == ":":
                v, i = _flow(text, i + 1)
            else:
                v = None
            out[k] = v
            i = _skip_ws(text, i)
            if i < len(text) and text[i] == ",":
                i = _skip_ws(text, i + 1)
    return _flow_scalar(text, i, ",]}")


def _flow_entry(text, i, close):
    """A flow sequence entry, which may be a single-pair mapping (`[a: 1]`)."""
    v, j = _flow(text, i)
    k = _skip_ws(text, j)
    if k < len(text) and text[k] == ":" and not isinstance(v, (list, dict)):
        v2, j = _flow(text, k + 1)
        return {v: v2}, j
    return v, j


def _flow_scalar(text, i, stops, key=False):
    i = _skip_ws(text, i)
    if i < len(text) and text[i] == '"':
        return _dq(text, i)
    if i < len(text) and text[i] == "'":
        return _sq(text, i)
    if i < len(text) and text[i] in "[{" and not key:
        return _flow(text, i)
    j = i
    while j < len(text):
        c = text[j]
        if c in stops and c != ":":
            break
        if c == ":" and ":" in stops and (j + 1 >= len(text) or text[j + 1] in " \t\n,]}"):
            break
        if c == ":" and ":" not in stops and (j + 1 >= len(text) or text[j + 1] in " \t\n") and not key:
            break
        j += 1
    raw = " ".join(x.strip() for x in text[i:j].split("\n"))
    return _plain(raw), j


def _strip_comment(line):
    """Remove a trailing comment, respecting quotes."""
    q, i = None, 0
    while i < len(line):
        c = line[i]
        if q:
            if c == q:
                if q == "'" and line[i + 1:i + 2] == "'":
                    i += 2
                    continue
                q = None
            elif c == "\\" and q == '"':
                i += 2
                continue
        elif c in "'\"" and (i == 0 or line[i - 1] in " \t[{,:-"):
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
        i += 1
    return line.rstrip()


def _key_split(content):
    """Split 'key: value' outside quotes and brackets. Returns (key, rest) or None."""
    q, depth, i = None, 0, 0
    flow_key = content[:1] in "[{"  # brackets only nest inside a flow key; a plain key may contain them
    while i < len(content):
        c = content[i]
        if q:
            if c == q:
                if q == "'" and content[i + 1:i + 2] == "'":
                    i += 2
                    continue
                q = None
            elif c == "\\" and q == '"':
                i += 2
                continue
        elif c in "'\"" and i == 0:
            q = c
        elif c in "[{" and flow_key:
            depth += 1
        elif c in "]}" and flow_key:
            depth -= 1
        elif c == ":" and depth == 0 and (i + 1 == len(content) or content[i + 1] in " \t"):
            k = content[:i].strip()
            if k.startswith(('"', "'")):
                k = (_dq if k[0] == '"' else _sq)(k, 0)[0]
            else:
                k = _plain(k)
            return k, content[i + 1:].strip()
        i += 1
    return None


class _Lines:
    def __init__(self, text):
        if "\t" in text.replace("\t\n", ""):
            pass
        self.raw = text.split("\n")
        self.items = []
        for n, line in enumerate(self.raw):
            if line.strip() in ("---", "...") and n == 0:
                self.items.append(None)  # keep items[i] aligned with raw line i
                continue
            if line.strip().startswith(("---", "...")) and n > 0 and line.strip() in ("---", "..."):
                raise YamlError("multiple documents are not supported")
            body = _strip_comment(line)
            if not body.strip():
                self.items.append(None)
                continue
            stripped = body.strip()
            if stripped == "?" or stripped.startswith("? ") or stripped.startswith("- ? "):
                raise YamlError(f"complex keys ('? ') are not supported (line {n + 1})")
            self.items.append((len(body) - len(body.lstrip(" ")), stripped, n))

    def next(self, i):
        while i < len(self.items) and self.items[i] is None:
            i += 1
        return i


def _needs_more(s):
    """True while a scalar/flow text is not yet closed (unbalanced quotes or brackets)."""
    if not s:
        return False
    if s[0] == '"':
        try:
            _dq(s, 0)
            return False
        except YamlError:
            return True
    if s[0] == "'":
        try:
            _sq(s, 0)
            return False
        except YamlError:
            return True
    if s[0] in "[{":
        try:
            _flow(s, 0)
            return False
        except (YamlError, IndexError):
            return True
    return False


def _value(L, i, text, indent):
    """Parse the inline value `text` found on line i (key or item at `indent`), consuming continuation lines."""
    parts, r = [text], i + 1
    while _needs_more("\n".join(parts)) and r < len(L.raw):
        parts.append(L.raw[r].strip())  # raw lines, blank ones included: they are line breaks in the scalar
        r += 1
    j = L.next(r)
    if len(parts) == 1 and text[:1] not in "\"'[{":
        # a plain scalar may continue on more-indented lines that are not new structure
        while j < len(L.items) and L.items[j][0] > indent:
            parts.append(L.items[j][1])
            j = L.next(j + 1)
        if len(parts) > 1:
            return _plain(_fold(parts)), j
    s = "\n".join(parts)
    if s[:1] in "[{\"'":
        v, end = _flow(s, 0)
        if s[end:].strip():
            raise YamlError(f"unexpected text after value: {s[end:].strip()[:30]!r}")
        return v, j
    return _plain(s), j


def _block(L, i, indent):
    """Parse the block node starting at line index i (indent >= `indent`)."""
    i = L.next(i)
    if i >= len(L.items):
        return None, i
    ind, content, _ = L.items[i]
    if content.startswith("- ") or content == "-":
        return _seq(L, i, ind)
    return _map(L, i, ind)


def _seq(L, i, indent):
    out = []
    while True:
        i = L.next(i)
        if i >= len(L.items):
            return out, i
        ind, content, _ = L.items[i]
        if ind < indent or not (content.startswith("- ") or content == "-"):
            if ind > indent:
                raise YamlError(f"bad indentation at line {L.items[i][2] + 1}")
            return out, i
        if ind > indent:
            raise YamlError(f"bad indentation at line {L.items[i][2] + 1}")
        rest = content[1:].strip()
        if not rest:
            v, i = _block(L, i + 1, indent + 1)
            out.append(v)
            continue
        sub_indent = ind + (len(content) - len(content[1:].lstrip()))
        if rest.startswith("- ") or rest == "-":
            L.items[i] = (sub_indent, rest, L.items[i][2])
            v, i = _seq(L, i, sub_indent)
            out.append(v)
            continue
        if _key_split(rest) is not None:
            L.items[i] = (sub_indent, rest, L.items[i][2])
            v, i = _map(L, i, sub_indent)
            out.append(v)
            continue
        v, i = _value(L, i, rest, indent)
        out.append(v)


def _map(L, i, indent):
    out = {}
    while True:
        i = L.next(i)
        if i >= len(L.items):
            return out, i
        ind, content, n = L.items[i]
        if ind < indent:
            return out, i
        if ind > indent:
            raise YamlError(f"bad indentation at line {n + 1}")
        if content.startswith("- "):
            return out, i
        if content == "?" or content.startswith("? "):
            raise YamlError(f"complex keys ('? ') are not supported (line {n + 1})")
        kv = _key_split(content)
        if kv is None:
            raise YamlError(f"expected 'key: value' at line {n + 1}: {content[:40]!r}")
        k, rest = kv
        if k in out:
            raise YamlError(f"duplicate key {k!r} at line {n + 1}")
        if rest:
            out[k], i = _value(L, i, rest, indent)
            continue
        j = L.next(i + 1)
        if j < len(L.items) and (L.items[j][0] > indent or
                                 (L.items[j][0] == indent and (L.items[j][1].startswith("- ") or L.items[j][1] == "-"))):
            out[k], i = _block(L, j, indent)
        else:
            out[k], i = None, j


def load(text):
    """Parse YAML text (the subset above) into Python objects, like yaml.safe_load."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    text = text.lstrip("﻿").replace("\r\n", "\n")
    L = _Lines(text)
    i = L.next(0)
    if i >= len(L.items):
        return None
    ind, content, n = L.items[i]
    if ind == 0 and not (content.startswith("- ") or content == "-") and _key_split(content) is None:
        v, j = _value(L, i, content, -1)
        if L.next(j) < len(L.items):
            raise YamlError("unexpected content after top-level scalar")
        return v
    v, j = _block(L, i, 0)
    if L.next(j) < len(L.items):
        raise YamlError(f"unexpected content at line {L.items[L.next(j)][2] + 1}")
    return v


# ---------------------------------------------------------------- writer
_SAFE_PLAIN = re.compile(r"^[A-Za-z_/.][A-Za-z0-9_./@+-]*$")


def _scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    s = str(v)
    if _SAFE_PLAIN.match(s) and _plain(s) == s and not s.endswith(":"):
        return s
    return json.dumps(s, ensure_ascii=False)


def _dump(v, indent):
    pad = " " * indent
    if isinstance(v, dict):
        if not v:
            return ["{}"]
        lines = []
        for k, x in v.items():
            key = _scalar(k)
            if isinstance(x, (dict, list)) and x:
                lines.append(f"{pad}{key}:")
                lines += _dump(x, indent + 2) if isinstance(x, dict) else _dump(x, indent)
            else:
                lines.append(f"{pad}{key}: {_dump(x, 0)[0]}")
        return lines
    if isinstance(v, list):
        if not v:
            return ["[]"]
        lines = []
        for x in v:
            if isinstance(x, (dict, list)) and x:
                sub = _dump(x, indent + 2)
                lines.append(f"{pad}- {sub[0].lstrip()}")
                lines += sub[1:]
            else:
                lines.append(f"{pad}- {_dump(x, 0)[0]}")
        return lines
    return [pad + _scalar(v)]


def dump(obj):
    """Serialise dicts/lists/scalars as block YAML that both load() and yaml.safe_load read back identically."""
    return "\n".join(_dump(obj, 0)) + "\n"
