"""Единый клиент языковой модели для ответов и переформулировщика.

Провайдер задаёт config.LLM_PROVIDER. DeepSeek отвечает на запросы в формате
Anthropic по своему адресу (config.DEEPSEEK_BASE_URL), поэтому оба провайдера
обслуживает один SDK anthropic: меняются только адрес, ключ и модели.
"""
import concurrent.futures as cf

import anthropic
import httpx

import config

_client = None
# Вызовы идут через свой пул, чтобы у каждого был жёсткий потолок по часам:
# DeepSeek в очереди шлёт пустые строки-«пинги», они сбрасывают read-таймаут
# httpx, и без потолка один вопрос мог висеть до 10 минут на попытку. А Slack
# Bolt обслуживает всего 5 обработчиков одновременно — несколько зависших
# вопросов заморозили бы бота для всех. Зависший поток пула доживает сам
# (сервер рвёт соединение), а сотрудник сразу получает сообщение об ошибке.
_pool = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm")


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        config.require(config.LLM_KEY_NAME)
        timeout = httpx.Timeout(config.LLM_READ_TIMEOUT, connect=10)
        if config.LLM_PROVIDER == "deepseek":
            _client = anthropic.Anthropic(api_key=config.DEEPSEEK_API_KEY,
                                          base_url=config.DEEPSEEK_BASE_URL,
                                          timeout=timeout, max_retries=1)
        else:
            _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY,
                                          timeout=timeout, max_retries=1)
    return _client


def create(**kwargs):
    """messages.create с потолком config.LLM_HARD_TIMEOUT секунд на весь вызов
    (с повтором). Не уложились — TimeoutError, как любой другой сбой модели."""
    future = _pool.submit(client().messages.create, **kwargs)
    try:
        return future.result(timeout=config.LLM_HARD_TIMEOUT)
    except cf.TimeoutError:
        raise TimeoutError(
            f"модель не ответила за {config.LLM_HARD_TIMEOUT:g} с") from None
