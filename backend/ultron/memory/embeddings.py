"""Embeddings: vetor local (hashing de características, custo zero) + embeddings de provedor
quando disponíveis (OpenAI, Gemini, Mistral)."""

from __future__ import annotations

import math
import re
import unicodedata
import zlib
from collections import Counter

DIMS = 256
_WORD = re.compile(r"[a-z0-9]{2,}")
STOPWORDS = set(
    "a o e de do da dos das em no na nos nas um uma uns umas para por com sem que se ao aos as os eu tu ele ela "
    "nos vos eles elas meu minha seu sua isso isto esse essa este esta the and of to in is for on with as at by "
    "it be are was this that from or an não nao sim mais muito".split()
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return text


def tokenize(text: str) -> list[str]:
    return [t for t in _WORD.findall(normalize(text)) if t not in STOPWORDS]


def _h(s: str) -> int:
    return zlib.crc32(s.encode())


def local_embedding(text: str) -> list[float]:
    toks = tokenize(text)
    feats = Counter(toks)
    feats.update(f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False))
    # n-gramas de caracteres ajudam com variações (plural, conjugação)
    for t in set(toks):
        if len(t) > 4:
            feats.update(t[i : i + 4] for i in range(len(t) - 3))
    vec = [0.0] * DIMS
    for f, tf in feats.items():
        hv = _h(f)
        sign = 1.0 if (hv >> 9) & 1 else -1.0
        vec[hv % DIMS] += sign * (1.0 + math.log(tf))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 4) for v in vec]


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(0.0, dot / (na * nb))


def bm25_scores(query: str, docs: list[str], k1: float = 1.4, b: float = 0.75) -> list[float]:
    q = tokenize(query)
    if not q or not docs:
        return [0.0] * len(docs)
    tokd = [tokenize(d) for d in docs]
    n = len(docs)
    avgdl = sum(len(t) for t in tokd) / n or 1.0
    df: Counter = Counter()
    for t in tokd:
        df.update(set(t))
    scores = []
    for t in tokd:
        tf = Counter(t)
        dl = len(t) or 1
        s = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    return scores
