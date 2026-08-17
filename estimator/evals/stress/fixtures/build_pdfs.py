"""Generate deterministic synthetic PDF attachments for the size sweep.

Five target sizes: 0 (no attachment — never generated, absence is the
baseline), 5, 20, 50, 100 KB. "KB" here means KB of the *plain text* the
attachment carries, not the PDF file's byte size on disk — that is the
quantity that actually stresses the pipeline (``extract_text`` turns the PDF
back into a string, and that string is what gets truncated at
``MAX_ATTACHMENT_CHARS`` and folded into the prompt). A fixed paragraph is
repeated until the text hits the target character count, so re-running this
script always produces byte-identical PDFs.

Usage::

    uv run python -m evals.stress.fixtures.build_pdfs

Not committed — ``.gitignore`` excludes ``evals/stress/fixtures/*.pdf``; the
runner (or this script directly) regenerates them on demand.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

_PARAGRAPH = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
    "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
    "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate "
    "velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint "
    "occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
    "mollit anim id est laborum. "
)

_TARGET_SIZES_KB = (5, 20, 50, 100)
_FIXTURES_DIR = Path(__file__).parent


def _text_of_length(target_chars: int) -> str:
    repeats = target_chars // len(_PARAGRAPH) + 1
    return (_PARAGRAPH * repeats)[:target_chars]


def _write_pdf(text: str, path: Path) -> None:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, text)
    pdf.output(str(path))


def build_all() -> list[Path]:
    written: list[Path] = []
    for size_kb in _TARGET_SIZES_KB:
        target_chars = size_kb * 1024
        text = _text_of_length(target_chars)
        path = _FIXTURES_DIR / f"attach_{size_kb}kb.pdf"
        _write_pdf(text, path)
        written.append(path)
    return written


def fixture_path(size_kb: int) -> Path:
    """Path for a given size, without regenerating it. Raises if size is 0
    (no fixture exists — the caller should skip attaching a file)."""
    if size_kb == 0:
        raise ValueError("size_kb=0 means 'no attachment'; there is no fixture for it")
    return _FIXTURES_DIR / f"attach_{size_kb}kb.pdf"


def main() -> int:
    for path in build_all():
        print(f"wrote {path} ({path.stat().st_size} bytes on disk)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
