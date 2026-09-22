#!/usr/bin/env python3
"""
Build a vector database RAG index for the markdown vault.

Since we're in the Apple Container:
- /Volumes/ doesn't exist (no macOS volumes)
- ~/Documents, ~/Library don't exist (not a macOS home)
- /workspace is the only Mac-host mount (virtiofs)
- The vault is /workspace (ARES docs + JaegerAI + knowledge-base + hermes-work)
- Ollama is at http://192.168.65.1:11434 (not localhost)
- nomic-embed-text is already pulled (768-dim embeddings via /v1/embeddings)
- sqlite_vec can't be pip-installed (no DNS) and isn't available
  -> We'll build a pure-Python vector store with cosine similarity search
     in SQLite using JSON-serialized vectors (no native extension needed)

The output is a SQLite database with:
  - sources table (file metadata)
  - chunks table (text chunks with embeddings stored as JSON)
  - A Python query function for cosine similarity search
"""
import sys, os, json, time, hashlib, sqlite3, urllib.request, urllib.error
from pathlib import Path

# Add ARES to path for context_chunker
ARES_ROOT = Path("/workspace/ARES")
sys.path.insert(0, str(ARES_ROOT))

from core.memory.context_chunker import chunk_markdown

# --- Config ---
VAULT_ROOT = Path("/workspace")
OLLAMA_URL = "http://192.168.65.1:11434"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIMS = 768
DB_PATH = Path("/workspace/hermes-work/vault_rag.db")
BATCH_SIZE = 20

# --- Prune dirs we don't want to index ---
PRUNE_DIRS = {'.git', 'node_modules', '.pytest_cache', '__pycache__',
              '.hermes', '.venv', '__pycache__', 'venv', '.tox', '.mypy_cache',
              '.DS_Store', '.pytest_cache'}

def collect_md_files(root):
    """Collect all .md files, excluding dotdirs and build artifacts."""
    md_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune
        prune = [d for d in dirnames if d in PRUNE_DIRS or d.startswith('.')]
        for p in prune:
            if p in dirnames:
                dirnames.remove(p)
        for f in filenames:
            if f.endswith('.md') and not f.startswith('.'):
                md_files.append(Path(dirpath) / f)
    return sorted(md_files)

def embed_texts(texts):
    """Call Ollama /v1/embeddings endpoint, return list of vectors."""
    if not texts:
        return []
    payload = json.dumps({"model": EMBED_MODEL, "input": list(texts)}).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        vectors = []
        for item in body.get("data", []):
            vectors.append([float(v) for v in item.get("embedding", [])])
        return vectors
    except Exception as e:
        print(f"  EMBED ERROR: {e}", flush=True)
        return [[] for _ in texts]  # empty vectors will be skipped

def cosine_sim(a, b):
    """Pure-Python cosine similarity."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def setup_db(db_path):
    """Create the SQLite database schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            source_key TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            path TEXT NOT NULL,
            last_mtime REAL,
            last_hash TEXT,
            last_indexed_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            source_key TEXT NOT NULL,
            source_type TEXT NOT NULL,
            path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            heading TEXT,
            text TEXT NOT NULL,
            embedding TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedded_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_key)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)
    """)
    conn.commit()
    return conn

def build_index():
    """Main: collect .md files, chunk them, embed chunks, store in SQLite."""
    print("=== MARKDOWN VAULT RAG INDEXER ===", flush=True)
    print(f"Vault root: {VAULT_ROOT}", flush=True)
    print(f"Ollama: {OLLAMA_URL}", flush=True)
    print(f"Embedding model: {EMBED_MODEL} ({EMBED_DIMS} dims)", flush=True)
    print(f"Database: {DB_PATH}", flush=True)
    print(f"Batch size: {BATCH_SIZE}", flush=True)

    # Step 1: Collect markdown files
    md_files = collect_md_files(VAULT_ROOT)
    print(f"\nFound {len(md_files)} markdown files", flush=True)
    if not md_files:
        print("No markdown files found!", flush=True)
        return

    # Step 2: Setup database
    conn = setup_db(DB_PATH)
    print(f"Database initialized at {DB_PATH}", flush=True)

    # Step 3: Index each file
    total_chunks = 0
    indexed_files = 0
    errors = 0
    all_chunks_for_embedding = []  # (file_idx, chunk_idx, chunk_text)
    file_chunk_map = {}  # file_idx -> [(chunk_idx, chunk_obj), ...]

    print("\n=== Chunking all files ===", flush=True)
    for i, md_file in enumerate(md_files):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                continue
            chunks = chunk_markdown(content)
            if not chunks:
                continue
            file_chunk_map[i] = (md_file, chunks)
            for chunk in chunks:
                all_chunks_for_embedding.append((i, chunk.index, chunk.text))
            if (i + 1) % 10 == 0 or i + 1 == len(md_files):
                print(f"  [{i+1}/{len(md_files)}] {len(all_chunks_for_embedding)} chunks so far", flush=True)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  CHUNK ERROR on {md_file}: {e}", flush=True)

    print(f"\nTotal chunks to embed: {len(all_chunks_for_embedding)}", flush=True)

    # Step 4: Embed in batches and store
    print("\n=== Embedding and storing ===", flush=True)
    embedded_count = 0
    now = time.time()

    for batch_start in range(0, len(all_chunks_for_embedding), BATCH_SIZE):
        batch = all_chunks_for_embedding[batch_start:batch_start + BATCH_SIZE]
        texts = [b[2] for b in batch]
        try:
            vectors = embed_texts(texts)
        except Exception as e:
            print(f"  BATCH ERROR at {batch_start}: {e}", flush=True)
            errors += len(batch)
            continue

        for (file_idx, chunk_idx, chunk_text), vector in zip(batch, vectors):
            if len(vector) != EMBED_DIMS:
                errors += 1
                continue
            md_file, chunks = file_chunk_map[file_idx]
            # Find the chunk object for this index
            chunk_obj = None
            for c in chunks:
                if c.index == chunk_idx:
                    chunk_obj = c
                    break
            if chunk_obj is None:
                continue

            source_key = f"vault:{md_file.relative_to(VAULT_ROOT)}"
            content_hash = hashlib.sha256(
                md_file.read_text(encoding="utf-8", errors="replace").encode()
            ).hexdigest()

            conn.execute(
                "INSERT INTO chunks(source_key, source_type, path, chunk_index, heading, text, embedding, embedding_model, embedded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source_key, "vault", str(md_file), chunk_obj.index,
                 chunk_obj.heading, chunk_obj.text,
                 json.dumps(vector), "nomic-embed-text", now)
            )
            # Upsert source
            conn.execute(
                "INSERT INTO sources(source_key, source_type, path, last_mtime, last_hash, last_indexed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(source_key) DO UPDATE SET"
                " source_type=excluded.source_type, path=excluded.path, last_mtime=excluded.last_mtime,"
                " last_hash=excluded.last_hash, last_indexed_at=excluded.last_indexed_at",
                (source_key, "vault", str(md_file), md_file.stat().st_mtime, content_hash, now)
            )
            embedded_count += 1

        conn.commit()
        if (batch_start // BATCH_SIZE + 1) % 5 == 0 or batch_start + BATCH_SIZE >= len(all_chunks_for_embedding):
            print(f"  [{batch_start + len(batch)}/{len(all_chunks_for_embedding)}] {embedded_count} chunks embedded", flush=True)

    conn.commit()

    # Step 5: Report
    print("\n=== RAG INDEX COMPLETE ===", flush=True)
    print(f"  Files found: {len(md_files)}", flush=True)
    print(f"  Files indexed: {len(file_chunk_map)}", flush=True)
    print(f"  Total chunks: {embedded_count}", flush=True)
    print(f"  Errors: {errors}", flush=True)
    print(f"  Database: {DB_PATH}", flush=True)

    # Verify by counting rows
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    print(f"  DB verification: {chunk_count} chunk rows, {source_count} source rows", flush=True)

    # Show top directories by chunk count
    print(f"\n=== Chunks by directory ===", flush=True)
    rows = conn.execute(
        "SELECT path FROM chunks"
    ).fetchall()
    dir_counts = {}
    for (p,) in rows:
        d = str(Path(p).parent.relative_to(VAULT_ROOT))
        dir_counts[d] = dir_counts.get(d, 0) + 1
    for d, c in sorted(dir_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c:4d}  {d}", flush=True)

    # Test a query
    print(f"\n=== Test query: 'architecture' ===", flush=True)
    test_vec = embed_texts(["architecture system design"])[0]
    if test_vec and len(test_vec) == EMBED_DIMS:
        all_rows = conn.execute("SELECT id, path, heading, text, embedding FROM chunks").fetchall()
        scored = []
        for row in all_rows:
            vec = json.loads(row[4])
            score = cosine_sim(test_vec, vec)
            scored.append((score, row[1], row[2], row[3][:100]))
        scored.sort(key=lambda x: -x[0])
        for score, path, heading, snippet in scored[:5]:
            print(f"  {score:.4f}  {Path(path).name} | {heading[:40]} | {snippet[:60]}...", flush=True)

    conn.close()
    print(f"\nDatabase ready at: {DB_PATH}", flush=True)


if __name__ == "__main__":
    build_index()