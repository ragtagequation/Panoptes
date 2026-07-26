"""Panoptes AI engine — turns unanswered public demand into answers.

Stack (all free / stdlib by default; LLM optional):
  nlp        tokenization, stemming, TF-IDF, BM25, char n-grams
  intel      Naive-Bayes intent, urgency, sentiment, buying stage, reply odds
  match      offer↔ask BM25 + n-gram ranking
  graph      co-occurrence demand graph + PageRank hubs
  personas   buyer personas + objection mining
  forecast   OLS trend + forward projections
  variants   A/B outreach scored by expected value
  memory     outcome-trained case retrieval (RAG without vectors)
  solutions  Answer Engine (help-first solutions)
  synthesis  clustering, demand brief, offer doctor
  pipeline   cockpit orchestrator
"""

from __future__ import annotations

from app.ai.engine import ai_available, ai_mode, complete_json, complete_text

__all__ = ["ai_available", "ai_mode", "complete_json", "complete_text"]
