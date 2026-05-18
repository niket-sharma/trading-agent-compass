"""News sentiment analysis via OpenAI (BYOK model).

Architecture:
    Articles are pre-fetched into data/news/{TICKER}.parquet by GitHub Actions.
    Scoring runs on demand using the visitor's OpenAI key. The session_cache
    dict (keyed by sha256 of article_hash+model) prevents re-spending within
    a session. Pass st.session_state.sentiment_cache from the UI layer.

BYOK rules enforced here:
    - api_key is accepted as a parameter; never read from disk or written anywhere.
    - No key → returns NEUTRAL_SCORE with confidence=0.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger(__name__)

try:
    from openai import OpenAI
except ImportError:  # allow import without openai installed (tests, CLI)
    OpenAI = None  # type: ignore[assignment,misc]

# (input_usd_per_1M, output_usd_per_1M)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    # Update when OpenAI releases newer models:
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (2.50, 10.00),
}
DEFAULT_MODEL = "gpt-4o-mini"

_SCORE_PROMPT = """\
You are a financial sentiment analyst. Score the following news article for its \
directional sentiment toward the company or ETF mentioned.

Respond ONLY with valid JSON matching this exact schema — no markdown, no extra text:
{{"score": <float -1 to 1>, "confidence": <float 0 to 1>, \
"themes": [<string>, ...], "reasoning": <string max 100 chars>}}

- score: -1 = very bearish, 0 = neutral, +1 = very bullish
- confidence: how clearly directional the article is (0 = ambiguous, 1 = very clear)
- themes: up to 3 short tags (e.g. "earnings_beat", "guidance_raised", "lawsuit")
- reasoning: one brief sentence

Article:
Title: {title}
Source: {source}
Body (truncated): {body}
"""


class ArticleScore(BaseModel):
    score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    themes: list[str] = Field(default_factory=list)
    reasoning: str = ""

    @field_validator("themes")
    @classmethod
    def cap_themes(cls, v: list[str]) -> list[str]:
        return v[:3]


NEUTRAL_SCORE = ArticleScore(score=0.0, confidence=0.0, themes=[], reasoning="skipped: no key")


def _cache_key(article_hash: str, model: str) -> str:
    return hashlib.sha256(f"{article_hash}:{model}".encode()).hexdigest()


def score_article(
    article: dict[str, Any],
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    session_cache: dict[str, Any] | None = None,
) -> tuple[ArticleScore, float]:
    """Score a single article via OpenAI structured output.

    Args:
        article: Dict with keys: hash, title, source, body.
        api_key: Caller's OpenAI key (never stored).
        model: Model name; must be in MODEL_PRICING.
        session_cache: Mutable dict shared within a session for dedup.

    Returns:
        (ArticleScore, cost_usd)
        cost_usd is 0.0 on a cache hit.

    Raises:
        Exception from openai if the call fails (caller handles gracefully).
    """
    key = _cache_key(str(article.get("hash", "")), model)
    if session_cache is not None and key in session_cache:
        return session_cache[key], 0.0

    if OpenAI is None:
        raise ImportError("openai package is not installed")

    client = OpenAI(api_key=api_key)
    prompt = _SCORE_PROMPT.format(
        title=article.get("title", ""),
        source=article.get("source", ""),
        body=str(article.get("body", ""))[:1500],
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=200,
    )
    raw = resp.choices[0].message.content or "{}"
    scored = ArticleScore(**json.loads(raw))

    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    pricing = MODEL_PRICING.get(model, (0.0, 0.0))
    cost = (in_tok * pricing[0] + out_tok * pricing[1]) / 1_000_000

    if session_cache is not None:
        session_cache[key] = scored

    return scored, cost


def aggregate_ticker_sentiment(
    articles_df: pd.DataFrame,
    *,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    session_cache: dict[str, Any] | None = None,
    max_articles: int = 20,
    recency_halflife_days: float = 7.0,
) -> tuple[float, float, float]:
    """Compute aggregate sentiment for a ticker from its news DataFrame.

    Args:
        articles_df: DataFrame from store.load_news(); columns include
                     [published_at, title, source, body, hash].
        api_key: Caller's OpenAI key. None → returns (0.0, 0.0, 0.0).
        model: OpenAI model name.
        session_cache: Session-scoped dedup dict.
        max_articles: Cap articles scored per ticker.
        recency_halflife_days: Exponential decay half-life for article age.

    Returns:
        (weighted_score, avg_confidence, total_cost_usd)
        weighted_score: confidence x recency-weighted score in [-1, 1].
    """
    if api_key is None or articles_df.empty:
        return 0.0, 0.0, 0.0

    df = (
        articles_df.sort_values("published_at", ascending=False)
        .head(max_articles)
        .reset_index(drop=True)
    )

    now = pd.Timestamp.now("UTC")
    ages = (now - pd.to_datetime(df["published_at"], utc=True)).dt.total_seconds() / 86400.0
    weights = np.exp(-np.log(2) * ages / recency_halflife_days)

    scores, confs, costs = [], [], []
    for _i, row in df.iterrows():
        article = {
            "hash": row.get("hash", ""),
            "title": row.get("title", ""),
            "source": row.get("source", ""),
            "body": row.get("body", ""),
        }
        try:
            scored, cost = score_article(
                article, api_key=api_key, model=model, session_cache=session_cache
            )
        except Exception as exc:
            log.warning("article_score_failed", error=str(exc))
            scored, cost = NEUTRAL_SCORE, 0.0
        scores.append(scored.score)
        confs.append(scored.confidence)
        costs.append(cost)

    s_arr = np.array(scores, dtype=float)
    c_arr = np.array(confs, dtype=float)
    w = weights.values[: len(s_arr)]

    eff_w = w * c_arr
    if eff_w.sum() == 0.0:
        return 0.0, float(c_arr.mean()) if len(c_arr) else 0.0, float(sum(costs))

    weighted_score = float(np.dot(eff_w, s_arr) / eff_w.sum())
    avg_confidence = float(c_arr.mean())
    return weighted_score, avg_confidence, float(sum(costs))
