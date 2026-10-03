"""Apply a single-file unified diff with exact context verification (no fuzz)."""

from __future__ import annotations

import re

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    """Message is safe to show to the client."""


def apply_patch(original: str, patch: str) -> str:
    lines = original.split("\n")
    trailing_nl = original.endswith("\n")
    if trailing_nl:
        lines.pop()
    plines = patch.replace("\r\n", "\n").split("\n")

    i = 0
    while i < len(plines) and not plines[i].startswith("@@"):
        if plines[i].startswith(("--- ", "+++ ", "diff ", "index ")) or not plines[i].strip():
            i += 1
        else:
            raise PatchError(f"unexpected line before first hunk: {plines[i][:60]!r}")
    if i >= len(plines):
        raise PatchError("patch contains no hunks")

    out: list[str] = []
    cursor = 0  # index into `lines` of the next unconsumed original line
    n_hunk = 0
    while i < len(plines):
        m = _HUNK.match(plines[i])
        if not m:
            if plines[i] == "" and i == len(plines) - 1:
                break
            raise PatchError(f"malformed hunk header: {plines[i][:60]!r}")
        n_hunk += 1
        old_start = int(m.group(1))
        old_len = int(m.group(2)) if m.group(2) is not None else 1
        start = max(old_start - 1, 0) if old_len else old_start
        if start < cursor:
            raise PatchError(f"hunk {n_hunk} overlaps the previous hunk")
        out.extend(lines[cursor:start])
        cursor = start
        i += 1
        seen_old = 0
        while i < len(plines) and not plines[i].startswith("@@"):
            pl = plines[i]
            if pl.startswith("\\"):  # "\ No newline at end of file"
                i += 1
                continue
            if pl == "" and i == len(plines) - 1:
                i += 1
                continue
            tag, text = (pl[:1] or " "), pl[1:]
            if tag in (" ", "-"):
                if cursor >= len(lines) or lines[cursor] != text:
                    got = lines[cursor] if cursor < len(lines) else "<end of file>"
                    raise PatchError(f"hunk {n_hunk} does not match at line {cursor + 1}: expected {text!r}, found {got!r}")
                if tag == " ":
                    out.append(text)
                cursor += 1
                seen_old += 1
            elif tag == "+":
                out.append(text)
            else:
                raise PatchError(f"hunk {n_hunk}: invalid line prefix {tag!r}")
            i += 1
        if seen_old != old_len:
            raise PatchError(f"hunk {n_hunk} declares {old_len} old lines but has {seen_old}")
    out.extend(lines[cursor:])
    return "\n".join(out) + ("\n" if trailing_nl or (out and not original) else "")
