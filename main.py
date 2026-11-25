#!/usr/bin/env python3
"""Funniest One-Line Out-of-Office Reply — make.fun entry.

Writes one funny out-of-office reply (1-160 characters) to
``$MAKEFUN_OUTPUT_DIR/entry.txt`` (default ``/output/entry.txt``).

Publishing is atomic and grader-friendly:

* the staging file lives *inside* the output directory (never ``/tmp``),
  because the grader bind-mounts that directory and a cross-filesystem
  rename would fail with EXDEV;
* the staging file is fsynced, chmodded 0644, then renamed into place
  with :func:`os.replace`, and the directory itself is fsynced so the
  rename is durable;
* the published file is read back and re-validated before we report
  success, so a partial or corrupted write can never pass silently.

The output directory itself is never deleted or recreated from scratch:
the grader mounts it, so only files inside it are touched.
"""

import os
import sys
import tempfile
import unicodedata

LINE = "I'm out of the office this week — my auto-reply is the only one of us still working, and it's furious."

MAX_CHARS = 160

# Characters the gate treats as line breaks even though they are not
# "\n" or "\r": Unicode line/paragraph separators.
_SEPARATORS = ("\u2028", "\u2029")

# Categories rejected outright: Cc (controls, incl. C0/C1/DEL), Cf
# (invisible formats such as zero-width joiners), Cs (surrogates).
_FORBIDDEN_CATEGORIES = ("Cc", "Cf", "Cs")


def _reject_bad_char(ch):
    """Raise ValueError if a single character is gate-illegal.

    Split out of :func:`check_entry` so each rejection reason lives in
    exactly one place and can be unit-tested on its own.
    """
    cp = ord(ch)
    if ch == "\ufeff":
        raise ValueError("entry contains a byte-order mark (U+FEFF)")
    if 0x0080 <= cp <= 0x009F:
        raise ValueError("entry contains a C1 control character U+%04X" % cp)
    if ch in _SEPARATORS:
        raise ValueError(
            "entry contains a line/paragraph separator U+%04X" % cp
        )
    if unicodedata.category(ch) in _FORBIDDEN_CATEGORIES:
        raise ValueError(
            "entry contains an invisible control/format/surrogate "
            "character U+%04X" % cp
        )


def check_entry(text):
    """Validate a candidate entry line; return it unchanged.

    Rejects anything the gate would reject: non-strings, empty or
    whitespace-only text, lines over ``MAX_CHARS``, multi-line text,
    and any invisible / control / separator / surrogate character.
    Also rejects text that is not in Unicode NFC form, so two
    byte-different spellings of the "same" line cannot slip through,
    and text with leading or trailing whitespace, which would make the
    published line look padded and could miscount against the gate.
    Raises ValueError with a specific reason on the first problem.
    """
    if not isinstance(text, str):
        raise ValueError("entry must be a str")
    if text == "":
        raise ValueError("entry is empty")
    if text.strip() == "":
        raise ValueError("entry is whitespace-only")
    if text != text.strip():
        raise ValueError("entry has leading or trailing whitespace")
    if len(text) > MAX_CHARS:
        raise ValueError(
            "entry is %d chars, over the %d limit" % (len(text), MAX_CHARS)
        )
    if "\n" in text or "\r" in text:
        raise ValueError("entry must be a single line")
    if unicodedata.normalize("NFC", text) != text:
        raise ValueError("entry is not in Unicode NFC form")
    for ch in text:
        _reject_bad_char(ch)
    return text


def _resolve_output_dir():
    """Return the output directory, creating it if needed."""
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _publish_atomically(out_dir, data):
    """Write *data* to ``entry.txt`` inside *out_dir*, atomically.

    Stages the bytes in a temp file inside *out_dir*, fsyncs it,
    chmods it 0644, renames it over ``entry.txt`` with
    :func:`os.replace`, then fsyncs the directory. Returns the target
    path. A leftover staging file is removed on any failure.
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=out_dir, prefix=".entry.txt.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o644)
        target = os.path.join(out_dir, "entry.txt")
        os.replace(tmp_path, target)
        # Fsync the directory so the rename itself is durable.
        dir_fd = os.open(out_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return target
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _verify_published(target, data):
    """Read back *target* and confirm bytes, mode, and content."""
    with open(target, "rb") as f:
        read_back = f.read()
    if read_back != data:
        raise ValueError("read-back mismatch after publish")
    if (os.stat(target).st_mode & 0o777) != 0o644:
        raise ValueError("entry.txt is not mode 0644")
    check_entry(read_back.decode("utf-8"))


def main():
    out_dir = _resolve_output_dir()
    line = check_entry(LINE)
    data = line.encode("utf-8")
    target = _publish_atomically(out_dir, data)
    _verify_published(target, data)
    print("wrote %s (%d chars)" % (target, len(line)))
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
