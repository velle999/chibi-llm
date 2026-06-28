"""
Thoth RAG — primary-text retrieval for the scribe (phase 2).

Two halves:
  • build_index()  — offline. Chunk the .txt files in thoth_corpus/, embed each
                     passage via Ollama, and write thoth_index.npz (+ .json).
  • ThothRAG       — runtime. Embed the dream account, cosine-match against the
                     index, return a couple of short source passages.

Embeddings go through the same Ollama server as chat (config.llm_host/llm_port)
using nomic-embed-text, which wants task prefixes: "search_document: " when
indexing, "search_query: " when retrieving.

Everything degrades to silence: no index, no numpy, or no Ollama → retrieve()
returns "" and Thoth simply leans on the correspondence lexicon.

Build the index:
    ollama pull nomic-embed-text
    python thoth_rag.py build
"""

import os
import re
import sys
import json
import glob
import urllib.request


# ─── Ollama embeddings ───────────────────────────────────────────────────

def embed(text: str, model: str, base_url: str, timeout: float = 10.0):
    """Return the embedding vector for `text` from Ollama, or raise."""
    url = f"{base_url}/api/embeddings"
    payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    vec = data.get("embedding")
    if not vec:
        raise ValueError("Ollama returned no embedding (is the model pulled?)")
    return vec


# ─── Text preparation ────────────────────────────────────────────────────

_GUT_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*",
                        re.IGNORECASE | re.DOTALL)
_GUT_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*",
                      re.IGNORECASE | re.DOTALL)


def _strip_boilerplate(raw: str) -> str:
    """Drop Project Gutenberg header/footer if present."""
    m = _GUT_START.search(raw)
    if m:
        raw = raw[m.end():]
    m = _GUT_END.search(raw)
    if m:
        raw = raw[:m.start()]
    return raw


def _chunk(raw: str, target_words: int):
    """Paragraph-aware chunks of roughly `target_words` words.

    Packs whole paragraphs together up to the target; splits any single
    over-long paragraph on sentence boundaries.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    chunks, buf, count = [], [], 0

    def flush():
        nonlocal buf, count
        if buf:
            chunks.append(" ".join(buf).strip())
            buf, count = [], 0

    for para in paras:
        para = re.sub(r"\s+", " ", para)
        words = para.split()
        if len(words) > target_words * 1.6:
            # Over-long: break on sentences, packing to the target.
            flush()
            sents = re.split(r"(?<=[.!?])\s+", para)
            for s in sents:
                sw = s.split()
                if count + len(sw) > target_words and buf:
                    flush()
                buf.append(s)
                count += len(sw)
            flush()
        else:
            if count + len(words) > target_words and buf:
                flush()
            buf.append(para)
            count += len(words)
    flush()
    return [c for c in chunks if len(c.split()) >= 8]


# ─── Offline indexer ─────────────────────────────────────────────────────

def build_index(config) -> int:
    """Build the vector index from config.thoth_corpus_dir. Returns chunk count."""
    import numpy as np

    base_url = f"http://{config.llm_host}:{config.llm_port}"
    corpus_dir = config.thoth_corpus_dir
    files = sorted(glob.glob(os.path.join(corpus_dir, "*.txt")))
    if not files:
        print(f"[Thoth-RAG] No .txt files in {corpus_dir}/ — nothing to index.")
        return 0

    meta = []
    for fp in files:
        source = os.path.splitext(os.path.basename(fp))[0].replace("_", " ")
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            raw = _strip_boilerplate(f.read())
        chunks = _chunk(raw, config.thoth_chunk_words)
        print(f"[Thoth-RAG] {source}: {len(chunks)} passages")
        for ch in chunks:
            meta.append({"text": ch, "source": source})

    if not meta:
        print("[Thoth-RAG] No passages produced.")
        return 0

    print(f"[Thoth-RAG] Embedding {len(meta)} passages via {config.thoth_embed_model} "
          f"at {base_url} …")
    vectors = []
    for i, m in enumerate(meta, 1):
        v = embed("search_document: " + m["text"], config.thoth_embed_model, base_url,
                  timeout=max(30.0, config.thoth_rag_timeout))
        vectors.append(v)
        if i % 25 == 0 or i == len(meta):
            print(f"  … {i}/{len(meta)}")

    arr = np.asarray(vectors, dtype="float32")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms  # store L2-normalized so retrieval is a plain dot product

    np.savez_compressed(config.thoth_index_path, vectors=arr)
    json_path = os.path.splitext(config.thoth_index_path)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print(f"[Thoth-RAG] Wrote {config.thoth_index_path} and {json_path} "
          f"({len(meta)} passages, dim {arr.shape[1]}).")
    return len(meta)


# ─── Runtime retriever ───────────────────────────────────────────────────

class ThothRAG:
    def __init__(self, config):
        self.config = config
        self.vectors = None     # np.ndarray (N, D), L2-normalized
        self.meta = []          # aligned list of {"text", "source"}
        self._load()

    def _base_url(self) -> str:
        return f"http://{self.config.llm_host}:{self.config.llm_port}"

    def _load(self):
        try:
            import numpy as np
            json_path = os.path.splitext(self.config.thoth_index_path)[0] + ".json"
            with open(json_path, "r", encoding="utf-8") as f:
                self.meta = json.load(f)
            with np.load(self.config.thoth_index_path) as z:
                self.vectors = z["vectors"].astype("float32")
            if len(self.meta) != len(self.vectors):
                raise ValueError("index/metadata length mismatch")
            print(f"[Thoth-RAG] Loaded {len(self.meta)} passages.")
        except FileNotFoundError:
            print("[Thoth-RAG] No index found — run `python thoth_rag.py build`. "
                  "Falling back to the lexicon only.")
            self.vectors, self.meta = None, []
        except Exception as e:
            print(f"[Thoth-RAG] Index unavailable ({e}); lexicon only.")
            self.vectors, self.meta = None, []

    @property
    def ready(self) -> bool:
        return self.vectors is not None and len(self.meta) == len(self.vectors) > 0

    def retrieve(self, query: str, k: int = None) -> str:
        """Return a [SOURCE PASSAGES] block for `query`, or "" if nothing fits."""
        if not self.ready or not query or not query.strip():
            return ""
        import numpy as np
        k = k or self.config.thoth_rag_top_k

        try:
            qv = embed("search_query: " + query, self.config.thoth_embed_model,
                       self._base_url(), timeout=self.config.thoth_rag_timeout)
        except Exception as e:
            print(f"[Thoth-RAG] query embed failed ({e}); lexicon only.")
            return ""

        q = np.asarray(qv, dtype="float32")
        n = float(np.linalg.norm(q))
        if n == 0 or q.shape[0] != self.vectors.shape[1]:
            return ""  # empty or dimension mismatch (index built with another model)
        q /= n

        sims = self.vectors @ q                      # cosine, vectors pre-normalized
        order = np.argsort(-sims)[:k]
        picked = [(float(sims[i]), self.meta[i]) for i in order
                  if sims[i] >= self.config.thoth_rag_min_score]
        if not picked:
            return ""

        lines = ["[SOURCE PASSAGES — primary texts; quote sparingly, do not assert meaning]"]
        cap = self.config.thoth_passage_chars
        for _score, m in picked:
            text = m["text"].strip()
            if len(text) > cap:
                text = text[:cap].rsplit(" ", 1)[0] + " …"
            lines.append(f"— from {m.get('source', '?')}:\n{text}")
        return "\n\n".join(lines)


if __name__ == "__main__":
    from config import Config
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    cfg = Config()
    if cmd == "build":
        build_index(cfg)
    elif cmd == "query":
        rag = ThothRAG(cfg)
        q = " ".join(sys.argv[2:]) or "a serpent by dark water"
        print(rag.retrieve(q) or "(no passage above threshold)")
    else:
        print("usage: python thoth_rag.py [build | query <text>]")
