"""Выбор провайдера языковой модели (config.py) и клиент (llm.py)."""
import importlib

import pytest

import config
import llm


@pytest.fixture
def reload_config(monkeypatch):
    """Перечитывает config с заданными переменными и возвращает всё как было."""
    def _reload(**env):
        # .env рабочей копии (например, LLM_PROVIDER=anthropic на сервере) не
        # должен подмешиваться: при reload config снова вызвал бы load_dotenv
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
        for name in ("LLM_PROVIDER", "ANSWER_MODEL", "REWRITE_MODEL", "DEEPSEEK_BASE_URL"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        importlib.reload(config)
        monkeypatch.setattr(llm, "_client", None)
        return config
    yield _reload
    monkeypatch.undo()
    importlib.reload(config)
    llm._client = None


def test_default_provider_is_deepseek(reload_config):
    c = reload_config()
    assert c.LLM_PROVIDER == "deepseek"
    assert c.LLM_KEY_NAME == "DEEPSEEK_API_KEY"
    assert c.ANSWER_MODEL == "deepseek-flash"
    assert c.REWRITE_MODEL == "deepseek-v4-pro"
    assert c.DEEPSEEK_BASE_URL == "https://api.deepseek.com/anthropic"


def test_anthropic_rollback(reload_config):
    c = reload_config(LLM_PROVIDER="Anthropic")
    assert c.LLM_KEY_NAME == "ANTHROPIC_API_KEY"
    assert c.ANSWER_MODEL == "claude-haiku-4-5-20251001"
    assert c.REWRITE_MODEL == "claude-sonnet-5"


def test_old_claude_model_line_ignored_on_deepseek(reload_config):
    # на сервере могла остаться строка REWRITE_MODEL=claude-... от прошлого отката
    c = reload_config(REWRITE_MODEL="claude-haiku-4-5-20251001", ANSWER_MODEL="deepseek-v4-pro")
    assert c.REWRITE_MODEL == "deepseek-v4-pro"
    assert c.ANSWER_MODEL == "deepseek-v4-pro"


def test_unknown_provider_stops_start(reload_config):
    with pytest.raises(SystemExit):
        reload_config(LLM_PROVIDER="openai")


def test_client_uses_deepseek_address(reload_config, monkeypatch):
    c = reload_config()
    monkeypatch.setattr(c, "DEEPSEEK_API_KEY", "test-key")
    client = llm.client()
    assert str(client.base_url).startswith("https://api.deepseek.com/anthropic")
    assert client.api_key == "test-key"
    assert llm.client() is client


def test_client_without_key_stops(reload_config, monkeypatch):
    c = reload_config()
    monkeypatch.setattr(c, "DEEPSEEK_API_KEY", "")
    with pytest.raises(SystemExit, match="DEEPSEEK_API_KEY"):
        llm.client()


def test_client_has_short_timeouts(reload_config, monkeypatch):
    c = reload_config()
    monkeypatch.setattr(c, "DEEPSEEK_API_KEY", "test-key")
    client = llm.client()
    assert client.max_retries == 1
    assert client.timeout.read == c.LLM_READ_TIMEOUT
    assert client.timeout.connect == 10


def test_create_hard_timeout(monkeypatch):
    """Зависший вызов не держит обработчик Slack дольше LLM_HARD_TIMEOUT."""
    import threading
    release = threading.Event()

    class Hung:
        class messages:
            @staticmethod
            def create(**kwargs):
                release.wait(5)

    monkeypatch.setattr(llm, "_client", Hung)
    monkeypatch.setattr(config, "LLM_HARD_TIMEOUT", 0.2)
    try:
        with pytest.raises(TimeoutError, match="не ответила"):
            llm.create(model="m", max_tokens=1, messages=[])
    finally:
        release.set()


def test_create_passes_arguments(monkeypatch):
    seen = {}

    class Fake:
        class messages:
            @staticmethod
            def create(**kwargs):
                seen.update(kwargs)
                return "ok"

    monkeypatch.setattr(llm, "_client", Fake)
    assert llm.create(model="m", max_tokens=5, messages=[]) == "ok"
    assert seen == {"model": "m", "max_tokens": 5, "messages": []}
