"""Groot domain — a Semente app that helps with all things Semente documentation.

The agent has no knowledge base or vector DB: it gets three plain tools that
read the Markdown files of this repository's ``docs/`` folder (override the
location with ``SEMENTE_DOCS_DIR``). Gemini decides when to list, search and
read pages, then answers from what it read.
"""

import os
import re
from pathlib import Path

from semente import tool
from semente.domain import DomainSpec

# examples/groot/domain/__init__.py -> repo root is three levels up.
_DEFAULT_DOCS = Path(__file__).resolve().parents[3] / "docs"
DOCS_DIR = Path(os.getenv("SEMENTE_DOCS_DIR", _DEFAULT_DOCS)).resolve()

_SKIP_PARTS = {"node_modules", ".vitepress", "public", "scripts"}
_MAX_READ_CHARS = 20_000
_HEADING_RE = re.compile(r"^#{1,3}\s+(.*)$")


def _pages(language: str) -> list[Path]:
    """Markdown pages of one language: ``pt`` = ``docs/pt/``, else English."""
    pages = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(DOCS_DIR)
        if _SKIP_PARTS & set(rel.parts):
            continue
        if (rel.parts[0] == "pt") != (language == "pt"):
            continue
        pages.append(path)
    return pages


def _rel(path: Path) -> str:
    return path.relative_to(DOCS_DIR).as_posix()


def _title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _sections(path: Path) -> list[tuple[str, str]]:
    """Split a page into (heading, body) chunks at #, ## and ### headings."""
    sections: list[tuple[str, list[str]]] = [(_title(path), [])]
    in_code = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING_RE.match(line)
        if match:
            sections.append((match.group(1).strip(), []))
        else:
            sections[-1][1].append(line)
    return [(heading, "\n".join(body).strip()) for heading, body in sections]


@tool(
    description=(
        "Lists every page of the Semente documentation (path + title). "
        "Call it first when you do not know where a topic lives. "
        "Args: language ('en' for English, 'pt' for Portuguese)."
    )
)
def list_docs(language: str = "en") -> str:
    pages = _pages(language)
    if not pages:
        return f"No documentation found in {DOCS_DIR}."
    return "\n".join(f"- {_rel(p)} — {_title(p)}" for p in pages)


@tool(
    description=(
        "Keyword search over the Semente documentation. Returns the most "
        "relevant sections with their page path. Use it to find where a "
        "topic is documented, then call read_doc for the full page. "
        "Args: query (a few keywords), language ('en' or 'pt'), "
        "max_results (default 5)."
    )
)
def search_docs(query: str, language: str = "en", max_results: int = 5) -> str:
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    if not terms:
        return "Provide at least one keyword with 3+ characters."

    scored = []
    for path in _pages(language):
        for heading, body in _sections(path):
            haystack = f"{heading}\n{body}".lower()
            score = sum(haystack.count(t) for t in terms)
            score += 5 * sum(t in heading.lower() for t in terms)  # title hits
            if score:
                scored.append((score, path, heading, body))

    if not scored:
        return f"No section matched {query!r}. Try list_docs or other keywords."

    scored.sort(key=lambda item: item[0], reverse=True)
    out = []
    for _, path, heading, body in scored[: max(1, max_results)]:
        snippet = body[:800] + ("…" if len(body) > 800 else "")
        out.append(f"### {_rel(path)} — {heading}\n{snippet}")
    return "\n\n".join(out)


@tool(
    description=(
        "Reads one documentation page in full. "
        "Args: path (as returned by list_docs/search_docs, "
        "e.g. 'guide/manifest.md' or 'pt/guide/manifest.md')."
    )
)
def read_doc(path: str) -> str:
    target = (DOCS_DIR / path).resolve()
    if DOCS_DIR not in target.parents or target.suffix != ".md":
        return "Invalid path. Use a path returned by list_docs or search_docs."
    if not target.is_file():
        return f"Page not found: {path}. Call list_docs to see the valid paths."
    text = target.read_text(encoding="utf-8")
    if len(text) > _MAX_READ_CHARS:
        text = text[:_MAX_READ_CHARS] + "\n\n[truncated]"
    return text


domain_spec = DomainSpec(
    name="groot",
    tools=[list_docs, search_docs, read_doc],
)
