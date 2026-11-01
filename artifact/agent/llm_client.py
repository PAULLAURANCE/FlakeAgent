# -*- coding: utf-8 -*-
"""llm_client: OpenAI-compatible chat completions for the four providers.

Keys come from environment variables (exported by run_cell.sh):
  DEEPSEEK_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, GROK_API_KEY
DeepSeek is reached directly (China). OpenAI/Gemini/Grok go through the
ModelFlare relay (https://modelflare.dev/v1, OpenAI-compatible, no proxy).
Usage is logged by the caller.
"""
import json
import os
import time
import urllib.error
import urllib.request

PROXY = "http://127.0.0.1:7897"

MODELS = {
    "ds-flash": {"provider": "deepseek", "model": "deepseek-flash"},
    "ds-pro":   {"provider": "deepseek", "model": "deepseek-v4-pro"},
    "gemini38": {"provider": "gemini", "model": "gemini-3.8-flash"},
    "grok47":   {"provider": "grok", "model": "grok-4.7"},
    "sol":      {"provider": "openai", "model": "gpt-5.6-sol"},
    "astra":    {"provider": "openai", "model": "gpt-6-astra"},
}

PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY", "proxy": False},
    "openai":   {"base_url": "https://modelflare.dev/v1", "key_env": "OPENAI_API_KEY", "proxy": False},
    "gemini":   {"base_url": "https://modelflare.dev/v1", "key_env": "GEMINI_API_KEY", "proxy": False},
    "grok":     {"base_url": "https://modelflare.dev/v1", "key_env": "GROK_API_KEY", "proxy": False},
}

# per-model extra request fields. DeepSeek V4.x default to reasoning
# effort "high"; at max_tokens=2000 the hidden reasoning consumes the whole
# output budget and the reply comes back empty. Low effort + 4000 tokens
# keeps a visible plan in the reply.
MODEL_EXTRAS = {
    "grok47": {"reasoning_effort": "low"},
    "ds-pro": {"reasoning_effort": "low", "max_tokens": 4000},
    "ds-flash": {"reasoning_effort": "low", "max_tokens": 4000},
    # Gemini reasoning models use `thinking_level` (not `reasoning_effort`).
    # At default thinking the hidden reasoning burns the output budget and the
    # visible JSON plan comes back empty -> extract_json returns {} -> strategy
    # degenerates to T1/T5. Low thinking + 4000 tokens keeps a visible plan.
    "gemini38": {"thinking_level": "low", "max_tokens": 4000},
}

# List prices, USD per 1M tokens (input, output). Single source of truth for
# cost accounting. DeepSeek: official off-peak list prices (direct billing).
# OpenAI/Gemini/Grok: official list prices x user's ModelFlare relay discount
# (OpenAI x0.1, Gemini x0.15, Grok x0.1); see data/model_prices.md.
PRICES = {
    "ds-flash": (0.15, 0.60),
    "ds-pro": (0.66, 1.98),
    "gemini38": (0.11, 0.56),
    "grok47": (0.22, 0.66),
    "sol": (0.40, 2.00),
    "astra": (1.00, 5.00),
}


class LLMError(Exception):
    pass


def _opener(provider):
    if not PROVIDERS[provider]["proxy"]:
        return urllib.request.build_opener()
    ph = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    return urllib.request.build_opener(ph)


def chat(model_key, messages, temperature=0.2, max_tokens=4000, tries=3):
    """One chat completion. Returns (content, usage_dict)."""
    if model_key == "mock":
        user = messages[-1]["content"]
        if "just failed" in user:
            return (json.dumps({"category": "NIO", "root_cause": "static state mutated across runs",
                                "evidence": [{"file": "x.java", "lines": "L1", "snippet": "n/a",
                                              "why": "mock"}], "confidence": 0.5}), {})
        return (json.dumps({"hypothesis": "mock: timing sensitivity",
                            "strategy": "T6",
                            "params": {"sleep_ms": 500, "target_method": ""},
                            "expected": "test fails under injected delay"}), {})
    spec = MODELS[model_key]
    prov = PROVIDERS[spec["provider"]]
    key = os.environ.get(prov["key_env"], "")
    if not key:
        raise LLMError("missing API key for %s (%s)" % (model_key, prov["key_env"]))
    url = prov["base_url"] + "/chat/completions"
    body = {
        "model": spec["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    body.update(MODEL_EXTRAS.get(model_key, {}))
    data = json.dumps(body).encode("utf-8")
    opener = _opener(spec["provider"])
    last_err = None
    for i in range(tries):
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + key})
        try:
            with opener.open(req, timeout=180) as r:
                resp = json.loads(r.read().decode("utf-8"))
            content = resp["choices"][0]["message"]["content"] or ""
            usage = resp.get("usage") or {}
            return content, usage
        except urllib.error.HTTPError as e:
            body_err = ""
            try:
                body_err = e.read().decode("utf-8")[:300]
            except Exception:
                pass
            last_err = "HTTP %s %s" % (e.code, body_err)
            if e.code in (401, 403, 404):
                break
            time.sleep(2 + 3 * i)
        except Exception as e:
            last_err = str(e)
            time.sleep(2 + 3 * i)
    raise LLMError("chat failed for %s: %s" % (model_key, last_err))


def extract_json(content):
    """Pull the first {...} JSON object out of an LLM reply.

    Uses JSONDecoder.raw_decode, which respects string escaping — evidence
    snippets containing '{'/'}' inside strings must not break parsing (a
    naive brace-depth scan does).
    """
    start = content.find("{")
    if start < 0:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(content[start:])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


if __name__ == "__main__":
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else "ds-flash"
    msg = sys.argv[2] if len(sys.argv) > 2 else "reply with the JSON object {\"ok\": true}"
    c, u = chat(key, [{"role": "user", "content": msg}])
    print(c[:500])
    print("usage:", u)
