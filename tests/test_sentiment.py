"""Tests for tradeagent.analysis.sentiment."""
from __future__ import annotations

import hashlib
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradeagent.analysis.sentiment import (
    DEFAULT_MODEL,
    NEUTRAL_SCORE,
    ArticleScore,
    _cache_key,
    aggregate_ticker_sentiment,
    score_article,
)


# ── ArticleScore model ────────────────────────────────────────────────────────


def test_article_score_clamps_themes():
    s = ArticleScore(score=0.5, confidence=0.8, themes=["a", "b", "c", "d", "e"])
    assert len(s.themes) == 3


def test_article_score_bounds():
    with pytest.raises(Exception):
        ArticleScore(score=2.0, confidence=0.5)
    with pytest.raises(Exception):
        ArticleScore(score=0.0, confidence=-0.1)


# ── Cache key ────────────────────────────────────────────────────────────────


def test_cache_key_deterministic():
    k1 = _cache_key("abc123", "gpt-4o-mini")
    k2 = _cache_key("abc123", "gpt-4o-mini")
    assert k1 == k2


def test_cache_key_differs_by_model():
    k1 = _cache_key("abc123", "gpt-4o-mini")
    k2 = _cache_key("abc123", "gpt-4o")
    assert k1 != k2


def test_cache_key_differs_by_hash():
    k1 = _cache_key("hash_a", "gpt-4o-mini")
    k2 = _cache_key("hash_b", "gpt-4o-mini")
    assert k1 != k2


# ── score_article ─────────────────────────────────────────────────────────────


def _fake_openai_response(score: float = 0.7, confidence: float = 0.9) -> MagicMock:
    """Build a mock openai response object."""
    content = f'{{"score": {score}, "confidence": {confidence}, "themes": ["earnings"], "reasoning": "Good quarter"}}'
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def test_score_article_cache_hit():
    """Cache hit returns immediately without calling OpenAI."""
    article = {"hash": "abc", "title": "T", "source": "S", "body": "B"}
    cached_score = ArticleScore(score=0.5, confidence=0.8, themes=[], reasoning="cached")
    cache: dict[str, Any] = {_cache_key("abc", DEFAULT_MODEL): cached_score}

    result, cost = score_article(article, api_key="key", session_cache=cache)
    assert result is cached_score
    assert cost == 0.0


def test_score_article_calls_openai():
    article = {"hash": "xyz", "title": "Big earnings beat", "source": "Reuters", "body": "Revenue up 30%."}
    mock_resp = _fake_openai_response(0.8, 0.9)
    cache: dict[str, Any] = {}

    with patch("tradeagent.analysis.sentiment.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_cls.return_value = mock_client

        result, cost = score_article(article, api_key="sk-test", session_cache=cache)

    assert result.score == pytest.approx(0.8)
    assert result.confidence == pytest.approx(0.9)
    assert cost > 0.0


def test_score_article_writes_to_cache():
    article = {"hash": "xyz2", "title": "T", "source": "S", "body": "B"}
    mock_resp = _fake_openai_response(0.3, 0.6)
    cache: dict[str, Any] = {}

    with patch("tradeagent.analysis.sentiment.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_cls.return_value = mock_client

        score_article(article, api_key="sk-test", session_cache=cache)

    key = _cache_key("xyz2", DEFAULT_MODEL)
    assert key in cache


def test_score_article_second_call_is_free():
    article = {"hash": "xyz3", "title": "T", "source": "S", "body": "B"}
    mock_resp = _fake_openai_response(0.3, 0.6)
    cache: dict[str, Any] = {}

    with patch("tradeagent.analysis.sentiment.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_cls.return_value = mock_client

        _, cost1 = score_article(article, api_key="sk-test", session_cache=cache)
        _, cost2 = score_article(article, api_key="sk-test", session_cache=cache)

    assert cost1 > 0.0
    assert cost2 == 0.0


# ── aggregate_ticker_sentiment ────────────────────────────────────────────────


def _sample_articles(n: int = 5) -> pd.DataFrame:
    rows = []
    for i in range(n):
        url = f"https://news.example.com/{i}"
        rows.append(
            {
                "id": str(i),
                "ticker": "QQQ",
                "published_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=i),
                "title": f"Article {i}",
                "url": url,
                "source": "example",
                "body": f"Body {i}",
                "hash": hashlib.sha256(url.encode()).hexdigest(),
            }
        )
    return pd.DataFrame(rows)


def test_aggregate_no_key_returns_zeros():
    df = _sample_articles(5)
    score, conf, cost = aggregate_ticker_sentiment(df, api_key=None)
    assert score == 0.0
    assert conf == 0.0
    assert cost == 0.0


def test_aggregate_empty_df_returns_zeros():
    df = pd.DataFrame(columns=["id", "ticker", "published_at", "title", "url", "source", "body", "hash"])
    score, conf, cost = aggregate_ticker_sentiment(df, api_key="sk-test")
    assert score == 0.0


def test_aggregate_calls_openai_for_each_article():
    df = _sample_articles(3)
    mock_resp = _fake_openai_response(0.5, 0.9)

    with patch("tradeagent.analysis.sentiment.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_cls.return_value = mock_client

        score, conf, cost = aggregate_ticker_sentiment(df, api_key="sk-test")

    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0
    assert cost > 0.0


def test_aggregate_cache_prevents_re_spend():
    df = _sample_articles(3)
    mock_resp = _fake_openai_response(0.5, 0.9)
    cache: dict[str, Any] = {}

    with patch("tradeagent.analysis.sentiment.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_cls.return_value = mock_client

        _, _, cost1 = aggregate_ticker_sentiment(df, api_key="sk-test", session_cache=cache)
        _, _, cost2 = aggregate_ticker_sentiment(df, api_key="sk-test", session_cache=cache)

    assert cost1 > 0.0
    assert cost2 == 0.0  # full cache hit on second call


def test_aggregate_score_in_bounds():
    df = _sample_articles(5)
    mock_resp = _fake_openai_response(0.8, 0.9)

    with patch("tradeagent.analysis.sentiment.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp
        mock_cls.return_value = mock_client

        score, conf, _ = aggregate_ticker_sentiment(df, api_key="sk-test")

    assert -1.0 <= score <= 1.0
    assert 0.0 <= conf <= 1.0


def test_neutral_score_constant():
    assert NEUTRAL_SCORE.score == 0.0
    assert NEUTRAL_SCORE.confidence == 0.0
