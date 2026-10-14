"""Retrieval over runbooks and postmortems (RAG).

Documents are split into markdown sections and indexed with BM25. BM25 suits
this corpus well: queries are full of exact operational terms ("OOMKilled",
"connection pool", service names) where lexical match beats fuzzy semantics,
and it needs no embedding service or vector database.

Retrieval is exposed two ways:
- `search_runbooks` tool, so agents decide *when* to look something up (agentic RAG)
- `KnowledgeBase.context()`, injected up front into the planner prompt
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from voxa.tools.base import Tool, schema

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TOKEN = re.compile(r"[a-z0-9_]+")
STOP = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from", "if", "in", "is",
    "it", "its", "no", "not", "of", "on", "or", "that", "the", "then", "this", "to", "with",
])


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


@dataclass(frozen=True)
class Chunk:
    source: str
    title: str
    text: str


def chunk_markdown(source: str, text: str) -> list[Chunk]:
    """Split on '## ' headings; each chunk keeps the document title for context."""
    lines = text.strip().splitlines()
    doc_title = lines[0].lstrip("# ").strip() if lines else source
    chunks, heading, body = [], doc_title, []
    for line in lines[1:]:
        if line.startswith("## "):
            if "".join(body).strip():
                chunks.append(Chunk(source, heading, "\n".join(body).strip()))
            heading, body = f"{doc_title} > {line[3:].strip()}", []
        else:
            body.append(line)
    if "".join(body).strip():
        chunks.append(Chunk(source, heading, "\n".join(body).strip()))
    return chunks


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf = [Counter(d) for d in docs]
        self.avgdl = sum(map(len, docs)) / max(len(docs), 1)
        df = Counter(term for d in docs for term in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for doc, tf in zip(self.docs, self.tf, strict=True):
            norm = self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl)
            out.append(sum(self.idf.get(q, 0) * tf[q] * (self.k1 + 1) / (tf[q] + norm)
                           for q in query if q in tf))
        return out


class KnowledgeBase:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.index = BM25([tokenize(f"{c.title} {c.text}") for c in chunks])

    @classmethod
    def from_dir(cls, root: Path = DATA_DIR) -> KnowledgeBase:
        chunks = []
        for path in sorted(root.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            chunks += chunk_markdown(rel, path.read_text(encoding="utf-8"))
        return cls(chunks)

    def search(self, query: str, k: int = 3) -> list[dict]:
        scores = self.index.scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
        return [{"source": self.chunks[i].source, "title": self.chunks[i].title,
                 "text": self.chunks[i].text, "score": round(scores[i], 2)}
                for i in ranked[:k] if scores[i] > 0]

    def context(self, query: str, k: int = 3) -> str:
        hits = self.search(query, k)
        return "\n\n".join(f"[{h['source']}] {h['title']}\n{h['text']}" for h in hits)

    def tool(self) -> Tool:
        return Tool("search_runbooks",
                    "Search internal runbooks and past postmortems. Use it to check the "
                    "documented remediation for a symptom before recommending an action.",
                    schema({"query": {"type": "string"}}),
                    lambda query: self.search(query, 3))
