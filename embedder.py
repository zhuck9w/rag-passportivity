"""Тексты → векторы (Voyage AI voyage-3.5, 1024 числа). input_type различает
документы и запросы — модель дообучена под это, поиск от этого точнее."""
import time

import voyageai

import config

_client = None


def _voyage() -> voyageai.Client:
    global _client
    if _client is None:
        config.require("VOYAGE_API_KEY")
        _client = voyageai.Client(api_key=config.VOYAGE_API_KEY)
    return _client


def _embed_batch(texts: list[str], input_type: str):
    """У бесплатного тарифа Voyage (без карты) низкий лимит запросов в минуту:
    на 429/rate limit ждём 25 секунд и повторяем, до 5 попыток."""
    for attempt in range(5):
        try:
            return _voyage().embed(texts, model=config.EMBED_MODEL,
                                   input_type=input_type)  # truncation включён по умолчанию
        except Exception as e:
            msg = str(e).lower()
            rate_limited = (type(e).__name__ == "RateLimitError"
                            or "rate limit" in msg or "429" in msg)
            if not rate_limited or attempt == 4:
                raise
            print(f"Voyage rate limit — жду 25 с и повторяю "
                  f"(попытка {attempt + 2}/5)")
            time.sleep(25)


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), 100):  # лимит Voyage — 128 текстов на запрос
        resp = _embed_batch(texts[i:i + 100], input_type)
        vectors += resp.embeddings
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    return _embed(texts, "document")


def embed_query(text: str) -> list[float]:
    return _embed([text], "query")[0]
