"""
Phase 9 — RAG (retrieval-augmented generation) over uploaded documents.
-------------------------------------------------------------------------
Same "plain module, zero PySide6/provider import" discipline as
memory.py/reminders.py/gmail_client.py -- reusable from a CLI or the GUI
without changes. Two callers only:
    lyra/tools/rag_tool.py   -- registers `search_documents` as just
                                 another Phase-4-framework tool (per the
                                 plan: "no separate RAG mode, it's just
                                 one more tool the agent can call").
    main.py's upload button  -- calls ingest_file() directly when the
                                 user picks a PDF/text file.

Pipeline (matches the plan's Phase 9 exactly):
    extraction (pypdf for .pdf, plain read for .txt/.md)
      -> chunking (~500 words, ~50-word overlap)
      -> embeddings (sentence-transformers, local, free, no API key)
      -> stored in Chroma (persisted to disk, survives app restarts)

Every heavy dependency (chromadb, sentence_transformers, pypdf) is
imported lazily inside functions, not at module top -- same "don't crash
the whole app over one missing dependency" reasoning as
weather_tool.py/websearch_tool.py/gmail_client.py. tools/__init__.py
auto-imports rag_tool.py (and therefore this module) at startup, so a
top-level import here would otherwise take down the whole app over one
missing package.

The embedding model is cached at module level (_get_embedder) so it's
only loaded into memory once per process, not once per ingest/search
call -- loading a sentence-transformers model is the slow part (a couple
seconds), running it on already-loaded weights is fast.
"""

from pathlib import Path
from typing import Optional

from .paths import PROJECT_ROOT as _PROJECT_ROOT

CHROMA_DIR = _PROJECT_ROOT / "rag_store"
COLLECTION_NAME = "lyra_docs"

_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # small, fast, good-enough local model
CHUNK_WORDS = 500       # plan's own number ("chunking ~500 tokens, some overlap")
CHUNK_OVERLAP_WORDS = 50

_embedder = None    # sentence_transformers.SentenceTransformer, cached
_collection = None  # chromadb collection handle, cached


def _get_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(
            "RAG needs 'sentence-transformers'. Run "
            "'pip install -r requirements.txt' to enable document upload/search."
        ) from e
    _embedder = SentenceTransformer(_EMBED_MODEL_NAME)
    return _embedder


def _get_collection():
    global _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
    except ImportError as e:
        raise RuntimeError(
            "RAG needs 'chromadb'. Run 'pip install -r requirements.txt' "
            "to enable document upload/search."
        ) from e
    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    except Exception as e:
        raise RuntimeError(f"Could not open the document store: {e}") from e
    return _collection


def _extract_text(path: Path) -> str:
    """Plain text out of a .pdf/.txt/.md file. Raises RuntimeError on any
    failure (unsupported type, corrupt file, missing pypdf) -- same
    contract as every ToolSpec.func in this project."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError(
                "Reading PDFs needs 'pypdf'. Run "
                "'pip install -r requirements.txt' to enable it."
            ) from e
        try:
            reader = PdfReader(str(path))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise RuntimeError(f"Could not read PDF '{path.name}': {e}") from e

    if suffix in (".txt", ".md"):
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            raise RuntimeError(f"Could not read '{path.name}': {e}") from e

    raise RuntimeError(
        f"Unsupported file type '{suffix}' -- only .pdf, .txt, and .md are supported."
    )


def _chunk_text(text: str) -> list[str]:
    """Word-count chunking with overlap (plan: '~500 tokens, some
    overlap'). Word count instead of a real tokenizer -- close enough for
    this project's scope and avoids pulling in tiktoken as another
    dependency just for chunk boundaries."""
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    step = CHUNK_WORDS - CHUNK_OVERLAP_WORDS
    while start < len(words):
        chunk = " ".join(words[start : start + CHUNK_WORDS])
        if chunk.strip():
            chunks.append(chunk)
        start += step
    return chunks


def ingest_file(path: str) -> str:
    """Extract, chunk, embed, and store one file. Returns a short summary
    string for the UI to show. Raises RuntimeError on failure (missing
    deps, unreadable file, no extractable text)."""
    file_path = Path(path)
    if not file_path.exists():
        raise RuntimeError(f"File not found: {path}")

    text = _extract_text(file_path)
    if not text.strip():
        raise RuntimeError(
            f"No extractable text found in '{file_path.name}' "
            "(it may be a scanned/image-only PDF)."
        )

    chunks = _chunk_text(text)
    if not chunks:
        raise RuntimeError(f"'{file_path.name}' produced no chunks to index.")

    embedder = _get_embedder()
    collection = _get_collection()

    embeddings = embedder.encode(chunks).tolist()
    ids = [f"{file_path.name}::{i}" for i in range(len(chunks))]
    metadatas = [{"source": file_path.name, "chunk_index": i} for i in range(len(chunks))]

    # Re-ingesting the same filename replaces its old chunks rather than
    # duplicating them -- upsert keyed on the same deterministic ids.
    collection.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

    return f"Indexed '{file_path.name}' -- {len(chunks)} chunk(s) added to the document store."


def search(query: str, top_k: int = 4) -> list[dict]:
    """Return up to `top_k` most relevant chunks for `query`, each as
    {"source": ..., "text": ...}. Empty list if the store has nothing yet
    -- not an error, just nothing to retrieve."""
    collection = _get_collection()
    try:
        if collection.count() == 0:
            return []

        embedder = _get_embedder()
        query_embedding = embedder.encode([query]).tolist()

        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, collection.count()),
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        return [
            {"source": meta.get("source", "unknown"), "text": doc}
            for doc, meta in zip(documents, metadatas)
        ]
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Document search failed for '{query}': {e}") from e


def list_documents() -> list[str]:
    """Distinct source filenames currently indexed, for a future dashboard
    panel (Phase 11) or just debugging -- not wired to any tool/UI yet."""
    collection = _get_collection()
    if collection.count() == 0:
        return []
    all_meta = collection.get()["metadatas"]
    return sorted({m["source"] for m in all_meta if m and "source" in m})
