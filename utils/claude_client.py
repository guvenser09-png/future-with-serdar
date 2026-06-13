"""Anthropic Claude API sarmalayıcı.

- Resmî `anthropic` SDK'sını kullanır.
- Yapılandırılmış çıktı için `messages.parse()` + Pydantic (Sonnet 4.6 destekler).
- Token kullanımını loglar (CLAUDE.md: maliyet logu).
"""
from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config_loader import require_env
from .logging_utils import get_logger

log = get_logger("claude")

T = TypeVar("T", bound=BaseModel)

# Süreç boyunca biriken token sayacı (maliyet logu için)
_usage = {"input_tokens": 0, "output_tokens": 0}


def _client() -> anthropic.Anthropic:
    # API anahtarını ortamdan çözer (ANTHROPIC_API_KEY)
    require_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic()


def _track(resp) -> None:
    try:
        _usage["input_tokens"] += resp.usage.input_tokens
        _usage["output_tokens"] += resp.usage.output_tokens
    except AttributeError:
        pass


def usage_summary() -> dict[str, int]:
    """Bu çalışmadaki toplam token kullanımı."""
    return dict(_usage)


def parse(
    *,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    max_tokens: int = 8000,
) -> T:
    """Yapılandırılmış (Pydantic) çıktı döndüren tek seferlik çağrı.

    messages.parse mevcut değilse output_config.format'a düşer.
    """
    client = _client()
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        _track(resp)
        parsed = resp.parsed_output
        if parsed is None:
            raise RuntimeError("Model yapılandırılmış çıktı döndürmedi (parsed_output=None).")
        return parsed
    except AttributeError:
        # Eski SDK: parse helper yok -> manuel json_schema + doğrulama
        log.warning("messages.parse bulunamadı; output_config.format'a düşülüyor.")
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": schema.model_json_schema(),
                }
            },
        )
        _track(resp)
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return schema.model_validate_json(text)
