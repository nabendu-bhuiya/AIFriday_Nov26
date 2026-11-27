"""Pretrained LLM access through the lab's OpenAI-compatible endpoint. No training or fine-tuning."""
import json
import re
import time

import httpx
from openai import OpenAI

from .config import LLM_API_KEY, LLM_BASE_URL, SSL_MODE
from .tracing import record_llm

if SSL_MODE == "system":
    try:  # trust the Windows certificate store (corporate TLS inspection)
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


class LLMError(RuntimeError):
    pass


_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not LLM_API_KEY or not LLM_BASE_URL:
            raise LLMError("LLM not configured: set LLM_BASE_URL and LLM_API_KEY in .env")
        http = httpx.Client(verify=SSL_MODE != "off", timeout=180)
        _client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, http_client=http, max_retries=2)
    return _client


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise LLMError("Model did not return valid JSON")


def chat_json(model: str, system: str, user: str, max_tokens: int = 1200) -> dict:
    """One JSON-mode call. Static instructions go first (system) so the provider can cache the prefix."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    kwargs = dict(model=model, messages=messages, temperature=0, max_tokens=max_tokens)
    try:
        try:
            resp = client().chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception as e:  # some proxies reject response_format
            if "response_format" not in str(e):
                raise
            resp = client().chat.completions.create(**kwargs)
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"LLM call failed ({model}): {e}") from e
    u = resp.usage
    cached = 0
    if u is not None:
        details = getattr(u, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        record_llm(model, u.prompt_tokens or 0, u.completion_tokens or 0, cached)
    return _parse_json(resp.choices[0].message.content or "{}")


def ping(model: str) -> dict:
    t0 = time.perf_counter()
    out = chat_json(model, 'Reply with JSON {"ok": true}.', "ping", max_tokens=20)
    return {"model": model, "ok": bool(out.get("ok")), "ms": int((time.perf_counter() - t0) * 1000)}
