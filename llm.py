"""Единый клиент языковой модели для ответов и переформулировщика.

Провайдер задаёт config.LLM_PROVIDER. DeepSeek отвечает на запросы в формате
Anthropic по своему адресу (config.DEEPSEEK_BASE_URL), поэтому оба провайдера
обслуживает один SDK anthropic: меняются только адрес, ключ и модели.
"""
import anthropic

import config

_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        config.require(config.LLM_KEY_NAME)
        if config.LLM_PROVIDER == "deepseek":
            _client = anthropic.Anthropic(api_key=config.DEEPSEEK_API_KEY,
                                          base_url=config.DEEPSEEK_BASE_URL)
        else:
            _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client
