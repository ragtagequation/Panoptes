"""Shared NLP primitives used across the Panoptes AI engine.

Pure stdlib — no torch, no spaCy, no paid embeddings. Designed so every
downstream feature (intent, match, graph, forecast) speaks the same language.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

STOP = {
    "the", "and", "for", "with", "that", "this", "have", "has", "had", "are", "was",
    "were", "you", "your", "yours", "any", "all", "one", "two", "but", "not", "can",
    "cant", "get", "got", "how", "who", "what", "when", "where", "why", "does", "did",
    "doing", "from", "into", "out", "our", "ours", "their", "they", "them", "there",
    "here", "just", "like", "really", "would", "could", "should", "need", "needs",
    "needed", "want", "wants", "looking", "look", "help", "someone", "anyone",
    "anybody", "know", "about", "some", "much", "many", "very", "been", "being",
    "will", "its", "i'm", "i've", "dont", "also", "than", "then", "these", "those",
    "over", "under", "more", "most", "less", "least", "each", "other", "another",
    "same", "such", "only", "own", "too", "use", "using", "used", "way", "ways",
    "thing", "things", "make", "makes", "made", "new", "old", "good", "bad", "best",
    "better", "worse", "worst", "please", "thanks", "thank", "hey", "hi", "hello",
    "guys", "everyone", "advice", "recommendations", "recommendation", "recommend",
    "suggestions", "suggestion", "tips", "question", "actually", "already", "nothing",
    "even", "still", "again", "maybe", "anything", "everything", "something",
    "somebody", "basically", "literally", "currently", "trying", "tried", "keeps",
    "keep", "gets", "getting", "given", "since", "though", "because", "before",
    "after", "around", "without", "within", "while", "against", "been", "being",
}

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
MIN_LEN = 4


def stem(word: str) -> str:
    word = word.lower()
    if word.endswith(("ss", "us", "is")):
        return word
    for suffix in ("ing", "ers", "er", "ies", "ied", "ed", "es", "s"):
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            stem_ = word[: -len(suffix)]
            if suffix == "ies":
                return stem_ + "y"
            if (
                suffix in ("ing", "ed", "er", "ers")
                and len(stem_) > 3
                and stem_[-1] == stem_[-2]
                and stem_[-1] in "bdglmnprt"
            ):
                return stem_[:-1]
            return stem_
    return word


def tokenize(text: str, *, stem_words: bool = True) -> list[str]:
    words = WORD_RE.findall((text or "").lower())
    out: list[str] = []
    for w in words:
        if w in STOP or len(w) < MIN_LEN:
            continue
        out.append(stem(w) if stem_words else w)
    return out


def ngrams(tokens: list[str], n: int = 2) -> list[str]:
    if n <= 1:
        return list(tokens)
    return ["_".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def bag(text: str, *, bigrams: bool = True) -> Counter[str]:
    toks = tokenize(text)
    counts: Counter[str] = Counter(toks)
    if bigrams:
        counts.update(ngrams(toks, 2))
    return counts


def char_ngrams(text: str, n: int = 3) -> Counter[str]:
    """Character n-grams — robust when vocab is tiny / domain-shifted."""
    s = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if len(s) < n:
        return Counter({s: 1}) if s else Counter()
    return Counter(s[i : i + n] for i in range(len(s) - n + 1))


def l2_normalize(vec: dict[str, float]) -> dict[str, float]:
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def tfidf_vectors(docs: list[Counter[str]]) -> list[dict[str, float]]:
    """Smoothed TF-IDF over a small corpus (ask piles are rarely huge)."""
    n = len(docs) or 1
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    out: list[dict[str, float]] = []
    for d in docs:
        vec: dict[str, float] = {}
        for term, tf in d.items():
            idf = math.log(1 + n / (1 + df[term]))
            vec[term] = (1 + math.log(tf)) * idf
        out.append(l2_normalize(vec))
    return out


def bm25_score(
    query: Counter[str],
    doc: Counter[str],
    df: Counter[str],
    n_docs: int,
    avgdl: float,
    *,
    k1: float = 1.4,
    b: float = 0.75,
) -> float:
    """Classic BM25 — the workhorse ranking function behind search engines."""
    if not query or not doc:
        return 0.0
    dl = sum(doc.values()) or 1.0
    score = 0.0
    for term, qtf in query.items():
        tf = doc.get(term, 0)
        if not tf:
            continue
        idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
        denom = tf + k1 * (1 - b + b * dl / max(avgdl, 1.0))
        score += idf * ((tf * (k1 + 1)) / denom) * (1 + math.log(1 + qtf))
    return score


def clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
