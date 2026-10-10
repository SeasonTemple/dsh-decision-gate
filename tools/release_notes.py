"""Curated release notes: extract the title, and refuse a note that is not one.

The release workflow calls `title` to name the GitHub Release. `check` is the
quality gate: a note that exists but is missing its sections fails, because a
half-written note published as release text is worse than the auto-generated
one it replaced.

Both languages are required -- this project ships bilingual docs, and a note
with only one language is a note someone stopped writing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = ("Highlights", "Compatibility", "Verification", "Notes")
LANGUAGES = ("中文", "English")


def _sections(text: str) -> set[str]:
    return set(re.findall(r"^###\s+(.+?)\s*$", text, re.MULTILINE))


def _languages(text: str) -> set[str]:
    return {name for name in LANGUAGES if re.search(rf"^##\s+{re.escape(name)}\s*$", text, re.MULTILINE)}


def title_of(text: str) -> str:
    """The first `# ` heading, which is `<tag> - <one-line title>`."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    raise SystemExit("release note has no '# ' title heading")


def problems(text: str) -> list[str]:
    found: list[str] = []
    sections = _sections(text)
    for name in REQUIRED_SECTIONS:
        if name not in sections:
            found.append(f"missing section: {name}")
    languages = _languages(text)
    for name in LANGUAGES:
        if name not in languages:
            found.append(f"missing language block: {name}")
    if not text.lstrip().startswith("# "):
        found.append("no '# ' title heading")
    # A note that still carries angle-bracket placeholders is a template someone
    # copied and never filled in. Publishing that is worse than the auto notes.
    placeholders = sorted(set(re.findall(r"<[^\n<>]{1,60}>", text)))
    if placeholders:
        found.append("unfilled placeholders: " + ", ".join(placeholders[:5]))
    return found


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in {"title", "check"}:
        print("usage: release_notes.py <title|check> <note.md> [--allow-missing]", file=sys.stderr)
        return 2
    mode, note = argv[1], Path(argv[2])
    allow_missing = "--allow-missing" in argv
    if not note.exists():
        if allow_missing:
            print(f"no note at {note}; keeping auto-generated notes")
            return 0
        print(f"no note at {note}", file=sys.stderr)
        return 1
    text = note.read_text(encoding="utf-8")
    if mode == "title":
        print(title_of(text))
        return 0
    found = problems(text)
    if found:
        for problem in found:
            print(f"{note}: {problem}", file=sys.stderr)
        return 1
    print(f"{note}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
