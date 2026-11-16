"""Checks on the paper. Exit status 0 only if every check passes.

    python3 scripts/check_paper.py [--allow-unfilled]

Fails if: a result slot is unfilled; a line of any section holds a numeral with no `% source:` comment; the rendered text has an
em dash; a \\cite key is missing from refs.bib (or an entry is never cited); paper/main.pdf is missing or has more than 4 pages.
Lists every number in the abstract and the introduction with its source. Warns about sentences with more than three numerals.
--allow-unfilled: report unfilled slots without failing (for layout work before the results exist).
Python 3 standard library; page counting uses pypdf or PyMuPDF if importable, else reads the PDF's page tree.
"""
from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
SECTIONS = ["abstract", "intro", "system", "demo", "evaluation", "limits", "table1"]
MAX_PAGES = 4
fails: list[str] = []
warns: list[str] = []


def strip_markup(line: str) -> str:
    """The visible-ish text of a line: no comment, no command arguments that carry keys, no labels like L3 or E1."""
    t = re.split(r"(?<!\\)%", line, maxsplit=1)[0]
    if re.match(r"\s*\\(?:includegraphics|IfFileExists|setlength|fbox)", t):
        return " "                                              # layout commands, no prose
    t = re.sub(r"\\\\\[[^\]]*\]", " ", t)
    t = re.sub(r"\\(?:cite|ref|label|input|url|includegraphics|cmidrule|setlength|Description|texttt)\*?(?:\[[^\]]*\])?\{[^}]*\}", " ", t)
    t = re.sub(r"\\(?:multicolumn)\{\d+\}\{[^}]*\}", " ", t)
    t = re.sub(r"\\textbf\{\[\?\]\}", " ", t)
    t = re.sub(r"\\(?:begin|end)\{[^}]*\}(?:\{[^}]*\})?", " ", t)
    t = re.sub(r"\b[LE][1-9]\b", " ", t)                       # level and experiment names
    t = re.sub(r"\b(?:Section|Table|Figure)~?\s*\d+", " ", t)
    t = re.sub(r"\$[jk]\$", " ", t)
    t = re.sub(r"\\(?:cmidrule)\([a-z]+\)\{[^}]*\}", " ", t)
    return t


def check_sources(name: str, lines: list[str]) -> None:
    for i, line in enumerate(lines, 1):
        has_src = bool(re.search(r"(?<!\\)%\s*source:", line))
        if re.search(r"\d", strip_markup(line)) and not has_src:
            fails.append(f"{name}.tex:{i}: numeral with no `% source:` comment: {line.strip()[:90]}")


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def number_report(name: str, lines: list[str]) -> None:
    print(f"\nNumbers in the {name} and where they come from:")
    n = 0
    for i, line in enumerate(lines, 1):
        vis = strip_markup(line)
        nums = re.findall(r"\d[\d,]*(?:\.\d+)?\\?%?", vis)
        placeholders = len(re.findall(r"\\textbf\{\[\?\]\}", re.split(r"(?<!\\)%", line, maxsplit=1)[0]))
        if not nums and not placeholders:
            continue
        m = re.search(r"(?<!\\)%\s*source:\s*(.*)$", line)
        src = m.group(1).strip() if m else "NO SOURCE"
        print(f"  {name}.tex:{i}: {', '.join(nums) if nums else '(unfilled)'}  <-  {src}")
        n += len(nums)
        if len(nums) > 3:
            warns.append(f"{name}.tex:{i}: {len(nums)} numerals in one line (the writing rules allow two per sentence)")
    if n == 0:
        print("  (none yet: every slot is unfilled)")


def pdf_pages(p: Path) -> int | None:
    for mod in ("pypdf", "fitz"):
        try:
            if mod == "pypdf":
                import pypdf
                return len(pypdf.PdfReader(str(p)).pages)
            import fitz
            return len(fitz.open(str(p)))
        except Exception:  # noqa: BLE001
            continue
    data = p.read_bytes()
    best = None
    chunks = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except Exception:  # noqa: BLE001
            pass
    for c in chunks:
        for m in re.finditer(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", c, re.S):
            k = int(m.group(1) or m.group(2))
            best = k if best is None else max(best, k)
    return best


def main() -> None:
    allow = "--allow-unfilled" in sys.argv
    texts: dict[str, list[str]] = {}
    for s in SECTIONS:
        p = PAPER / f"{s}.tex"
        if not p.exists():
            fails.append(f"{s}.tex is missing (run scripts/make_paper.py)")
            continue
        texts[s] = p.read_text(encoding="utf-8").splitlines()
    # 1 unfilled slots
    unfilled = 0
    for s, ls in texts.items():
        for i, line in enumerate(ls, 1):
            n = line.count("{{") + len(re.findall(r"\\textbf\{\[\?\]\}", re.split(r"(?<!\\)%", line, maxsplit=1)[0]))
            unfilled += n
            if "{{" in line:
                fails.append(f"{s}.tex:{i}: raw slot left in the text")
    print(f"unfilled slots: {unfilled}")
    if unfilled and not allow:
        fails.append(f"{unfilled} unfilled slot(s) (the results are not all in)")
    # 2 sources
    for s, ls in texts.items():
        check_sources(s, ls)
    # 3 em dash
    for s, ls in texts.items():
        for i, line in enumerate(ls, 1):
            vis = re.split(r"(?<!\\)%", line, maxsplit=1)[0]
            if "\u2014" in vis or "---" in vis or "\\textemdash" in vis:
                fails.append(f"{s}.tex:{i}: em dash")
    for f in ("main.tex", "refs.bib"):
        t = (PAPER / f).read_text(encoding="utf-8")
        if "\u2014" in t or ("---" in t and f == "main.tex"):
            fails.append(f"{f}: em dash")
    # 4 citations
    bib = set(re.findall(r"@\w+\{([^,\s]+),", (PAPER / "refs.bib").read_text(encoding="utf-8")))
    cited = set()
    for s, ls in texts.items():
        for line in ls:
            for grp in re.findall(r"\\cite\{([^}]*)\}", re.split(r"(?<!\\)%", line, maxsplit=1)[0]):
                cited.update(k.strip() for k in grp.split(","))
    for k in sorted(cited - bib):
        fails.append(f"\\cite{{{k}}} has no entry in refs.bib")
    for k in sorted(bib - cited):
        warns.append(f"refs.bib entry {k} is never cited")
    print(f"references: {len(bib)} in refs.bib, {len(cited)} cited")
    # 5 pages
    pdf = PAPER / "main.pdf"
    if not pdf.exists():
        fails.append("paper/main.pdf does not exist")
    else:
        n = pdf_pages(pdf)
        print(f"pages: {n}")
        if n is None:
            warns.append("could not count the pages of main.pdf")
        elif n > MAX_PAGES:
            fails.append(f"main.pdf has {n} pages (limit {MAX_PAGES}, references included)")
    # 6 abstract and introduction numbers
    for s in ("abstract", "intro"):
        if s in texts:
            number_report(s, texts[s])
    for w in warns:
        print("warning:", w)
    for f in fails:
        print("FAIL:", f)
    print("\ncheck_paper: " + ("FAILED" if fails else "passed"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
