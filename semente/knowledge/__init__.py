"""Engine-neutral knowledge base factory.

Absorbs the generic vector-KB machinery (markdown ingestion, content-hash
sync, embedder, PgVector/ChromaDb selection) so a domain's KB module shrinks
to a single ``build_knowledge(...)`` call.

DECISION (#3): agno is used as a vector-DB *library* here, not as the agent
engine. The embedder, chunking, and PgVector/ChromaDb storage classes are
re-exported for domains to build their KB; retrieval is already engine-neutral
(``build_search_tool`` returns a plain function). Full de-agno of the storage
stack (~3-4 days: own embedder + pgvector/chroma clients) buys nothing
functional — deferred until a non-agno deployment actually needs it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from google.genai.types import HttpOptions
from sqlalchemy import create_engine, select, text

from semente.configs.config import config
from semente.logging import log_debug, log_error, log_warning

# Re-export the engine's knowledge/vectordb classes under stable names (Level 1
# surface; the domain's KB module imports these).
from agno.knowledge.chunking.recursive import RecursiveChunking  # noqa: F401
from agno.knowledge.embedder.google import GeminiEmbedder  # noqa: F401
from agno.knowledge.knowledge import Knowledge  # noqa: F401
from agno.vectordb.chroma import ChromaDb  # noqa: F401
from agno.vectordb.distance import Distance  # noqa: F401
from agno.vectordb.pgvector import PgVector  # noqa: F401

__all__ = [
    "build_knowledge",
    "build_search_tool",
    "synchronize",
    "RecursiveChunking",
    "GeminiEmbedder",
    "Knowledge",
    "ChromaDb",
    "Distance",
    "PgVector",
]

def build_search_tool(kb: Knowledge):
    """Build a Semente-native ``search_knowledge_base`` tool over a Knowledge instance.

    Returns a plain function (engine-agnostic): the ADK and bare backends adapt
    it directly; Agno keeps its native auto-injected tool. Mirrors agno's
    ``create_knowledge_search_tool`` formatting (YAML dump of documents).
    """

    def search_knowledge_base(query: str) -> str:
        """Search the knowledge base for information about a query.

        Args:
            query: The query to search for.

        Returns:
            str: The relevant documents from the knowledge base.
        """
        try:
            docs = kb.search(query)
        except Exception as exc:
            return f"Error searching knowledge base: {type(exc).__name__}"
        if not docs:
            return "No documents found"
        return yaml.dump(
            [d.to_dict() if hasattr(d, "to_dict") else d for d in docs],
            default_flow_style=False,
        )

    return search_knowledge_base


# Mirrors agno Knowledge._SEARCH_KNOWLEDGE_INSTRUCTIONS (the block agno injects
# when add_search_knowledge_instructions=True).
SEARCH_KNOWLEDGE_INSTRUCTIONS = (
    "You have a knowledge base you can search using the search_knowledge_base tool. "
    "Search before answering questions—don't assume you know the answer. "
    "For ambiguous questions, search first rather than asking for clarification."
)


# Advisory lock keys (stable, per-purpose) for multi-worker bootstrap/indexing.
_BOOTSTRAP_LOCK_KEY = (0x70675F31, 0x6B625F31)
_INDEXING_LOCK_KEY = (0x70675F32, 0x6B625F32)

_EMBED_TIMEOUT_MS = 60_000


def _build_embedder() -> GeminiEmbedder:
    return GeminiEmbedder(
        id="gemini-embedding-001",
        api_key=config.GOOGLE_API_KEY,
        client_params={"http_options": HttpOptions(timeout=_EMBED_TIMEOUT_MS)},
    )


def _build_pgvector(embedder, table_name: str, schema: str) -> PgVector:
    db_url = (
        f"postgresql+psycopg://{config.PGVECTOR_USER}:{config.PGVECTOR_PASSWORD}"
        f"@{config.PGVECTOR_HOST}:{config.PGVECTOR_PORT}/{config.PGVECTOR_DBNAME}"
    )
    engine = create_engine(db_url, pool_pre_ping=True)

    vector_db = PgVector(
        table_name=table_name,
        schema=schema,
        db_engine=engine,
        embedder=embedder,
        distance=Distance.cosine,
    )

    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT pg_advisory_xact_lock(:k1, :k2);"),
                {"k1": _BOOTSTRAP_LOCK_KEY[0], "k2": _BOOTSTRAP_LOCK_KEY[1]},
            )
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS ai;"))
            vector_db.table.create(conn, checkfirst=True)
    except Exception as exc:
        log_error(f"knowledge: failed to bootstrap vector DB schema: {exc}")

    return vector_db


def _build_chroma(embedder, collection: str) -> ChromaDb:
    persist_path = Path.cwd() / "tmp" / f"chromadb_{collection}"
    persist_path.mkdir(parents=True, exist_ok=True)
    return ChromaDb(
        collection=collection,
        path=str(persist_path),
        persistent_client=True,
        embedder=embedder,
        distance=Distance.cosine,
    )


def _select_vector_db(embedder, table_name: str, collection: str) -> Any:
    use_pgvector = (
        config.DATABASE_TYPE != "sqlite"
        and bool(config.PGVECTOR_HOST)
        and bool(config.PGVECTOR_DBNAME)
        and bool(config.PGVECTOR_USER)
    )
    if use_pgvector:
        try:
            return _build_pgvector(embedder, table_name, "ai")
        except Exception as exc:
            log_error(f"knowledge: PgVector setup failed, falling back to ChromaDb: {exc}")
    return _build_chroma(embedder, collection)


def build_knowledge(
    docs_dir: str | Path,
    *,
    name: str = "Knowledge Base",
    description: str = "",
    table_name: str = "semente_kb",
    collection: str = "semente_kb",
    excluded_files: set[str] | None = None,
    max_results: int = 3,
    sync: bool = True,
) -> Knowledge:
    """Build a vector knowledge base over the markdown files in ``docs_dir``.

    Uses Gemini embeddings and PgVector when configured, else a local ChromaDb.
    When ``sync`` is True, indexes new/changed files (content-hash diff) before
    returning.
    """
    embedder = _build_embedder()
    vector_db = _select_vector_db(embedder, table_name, collection)

    kb = Knowledge(
        name=name,
        description=description,
        vector_db=vector_db,
        max_results=max_results,
    )

    if sync:
        synchronize(kb, docs_dir, excluded_files or set())

    return kb


def _compute_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _get_indexed_source_hashes(vector_db) -> set[str]:
    hashes: set[str] = set()
    try:
        if isinstance(vector_db, PgVector):
            with vector_db.Session() as sess:
                stmt = (
                    select(vector_db.table.c.meta_data["source_content_hash"].astext)
                    .where(vector_db.table.c.meta_data["source_content_hash"].isnot(None))
                    .distinct()
                )
                for row in sess.execute(stmt):
                    if row[0] is not None:
                        hashes.add(row[0])
        elif isinstance(vector_db, ChromaDb):
            collection = vector_db.client.get_collection(name=vector_db.collection_name)
            result = collection.get(include=["metadatas"])
            for meta in result.get("metadatas", []) or []:
                value = meta.get("source_content_hash") if meta else None
                if value is not None:
                    hashes.add(value)
    except Exception as exc:
        log_error(f"knowledge: failed to read indexed source hashes: {exc}")
    return hashes


def synchronize(kb: Knowledge, docs_dir: str | Path, excluded_files: set[str] | None = None) -> None:
    """Sync the KB with the markdown files in ``docs_dir`` (content-hash diff).

    ponytail: the multi-worker leader-only advisory lock from the original
    deployment was dropped; add it back (session-level pg_try_advisory_lock)
    when a multi-worker deployment re-embeds concurrently.
    """
    excluded = excluded_files or set()
    kb_dir = Path(docs_dir)
    vector_db = kb.vector_db

    if not kb_dir.exists():
        log_error(f"knowledge: directory not found at {kb_dir}")
        return

    current_hashes: set[str] = set()
    hash_to_path: dict[str, Path] = {}
    for md_file in sorted(kb_dir.glob("*.md")):
        if md_file.name in excluded:
            continue
        if md_file.stat().st_size == 0:
            log_warning(f"knowledge: skipping empty file {md_file.name}")
            continue
        try:
            file_hash = _compute_file_hash(md_file)
        except Exception as exc:
            log_error(f"knowledge: failed to hash {md_file.name}: {exc}")
            continue
        current_hashes.add(file_hash)
        hash_to_path[file_hash] = md_file

    db_hashes = _get_indexed_source_hashes(vector_db)

    for stale_hash in db_hashes - current_hashes:
        try:
            vector_db.delete_by_metadata({"source_content_hash": stale_hash})
            log_debug(f"knowledge: dropped stale hash {stale_hash}")
        except Exception as exc:
            log_error(f"knowledge: failed to drop stale hash {stale_hash}: {exc}")

    for new_hash in current_hashes - db_hashes:
        md_file = hash_to_path[new_hash]
        try:
            kb.insert(
                path=str(md_file),
                metadata={"source_content_hash": new_hash},
                skip_if_exists=False,
                upsert=True,
            )
            log_debug(f"knowledge: indexed {md_file.name} ({new_hash})")
        except Exception as exc:
            log_error(f"knowledge: failed to index {md_file.name}: {exc}")
