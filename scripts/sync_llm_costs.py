#!/usr/bin/env python3
"""
Zero-Maintenance Multi-Provider LLM API Cost Sync Engine (sync_llm_costs.py)
----------------------------------------------------------------------------
Fetches live unauthenticated LLM token pricing ($/1M input, $/1M output, 3:1 blended)
from OpenRouter (`openrouter.ai/api/v1/models`) and cross-enriches direct inference
cloud endpoints from LiteLLM (`BerriAI/litellm`), curating ~220 high-demand commercial
and open-weight models with an 80-model safety circuit breaker.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
OUT_JSON = PUBLIC_DIR / "llm_costs.json"
HISTORY_DIR = PUBLIC_DIR / "history"

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"
LITELLM_JSON_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
_UA = "Mozilla/5.0 (compatible; LLMCostComparisonBot/1.0; +https://llmcostcomparison.com)"

LITELLM_PROVIDERS: dict[str, tuple[str, str, str, int]] = {
    "groq": ("Groq", "https://groq.com/pricing/", "Inference Cloud", 10),
    "cerebras": ("Cerebras", "https://cerebras.ai/inference", "Inference Cloud", 10),
    "sambanova": ("SambaNova", "https://sambanova.ai/fast-api", "Inference Cloud", 10),
    "together_ai": ("Together AI", "https://www.together.ai/pricing", "Inference Cloud", 18),
    "fireworks_ai": ("Fireworks AI", "https://fireworks.ai/pricing", "Inference Cloud", 18),
    "fireworks_ai-embedding-models": ("Fireworks AI", "https://fireworks.ai/pricing", "Inference Cloud", 3),
    "deepinfra": ("DeepInfra", "https://deepinfra.com/pricing", "Inference Cloud", 18),
    "baseten": ("Baseten", "https://www.baseten.co/pricing/", "Inference Cloud", 14),
    "novita": ("Novita AI", "https://novita.ai/pricing", "Inference Cloud", 14),
    "nebius": ("Nebius AI", "https://nebius.com/prices", "Inference Cloud", 10),
    "hyperbolic": ("Hyperbolic", "https://hyperbolic.xyz", "Inference Cloud", 8),
    "anyscale": ("Anyscale", "https://www.anyscale.com", "Inference Cloud", 4),
    "openai": ("OpenAI", "https://openai.com/api/pricing/", "Frontier Lab", 3),
    "cohere": ("Cohere", "https://cohere.com/pricing", "Frontier Lab", 3),
}

OR_VENDORS: dict[str, tuple[str, str, str, str, int]] = {
    "openai": ("OpenAI", "https://openai.com/api/pricing/", "Frontier Lab", "Proprietary", 14),
    "anthropic": ("Anthropic", "https://www.anthropic.com/pricing", "Frontier Lab", "Proprietary", 10),
    "google": ("Google", "https://ai.google.dev/pricing", "Frontier Lab", "Proprietary", 10),
    "deepseek": ("DeepSeek", "https://api-docs.deepseek.com/quick_start/pricing", "Model Lab", "Open-Weight", 9),
    "qwen": ("Qwen (Alibaba)", "https://openrouter.ai/qwen", "Model Lab", "Open-Weight", 10),
    "meta-llama": ("Meta Llama (OpenRouter)", "https://openrouter.ai/meta-llama", "Inference Cloud", "Open-Weight", 7),
    "meta": ("Meta AI", "https://openrouter.ai/meta", "Model Lab", "Proprietary", 4),
    "mistralai": ("Mistral AI", "https://mistral.ai/products/la-plateforme#pricing", "Model Lab", "Open-Weight", 9),
    "x-ai": ("xAI", "https://docs.x.ai/docs/models", "Frontier Lab", "Proprietary", 5),
    "cohere": ("Cohere", "https://cohere.com/pricing", "Frontier Lab", "Proprietary", 4),
    "moonshotai": ("Moonshot (Kimi)", "https://platform.moonshot.ai", "Model Lab", "Open-Weight", 5),
    "nvidia": ("NVIDIA Nemotron", "https://build.nvidia.com", "Model Lab", "Open-Weight", 4),
    "z-ai": ("Z.ai (GLM)", "https://openrouter.ai/z-ai", "Model Lab", "Open-Weight", 4),
    "minimax": ("MiniMax", "https://openrouter.ai/minimax", "Model Lab", "Open-Weight", 3),
}

SKIP_RE = re.compile(
    r"(:free|:batch|:extended|^~|^ft:|whisper|tts|audio|realtime|dall-e|image|vision-preview|"
    r"moderation|rerank|prompt-guard|llama-guard|safeguard|decision-models|openrouter/auto|test)",
    re.IGNORECASE,
)
DEMAND_RE = re.compile(
    r"(llama-4|llama-3\.[13]|deepseek-(r1|v3|v4)|qwen(4|3|2\.5)|qwq|claude-(fable|opus|sonnet|haiku)|"
    r"gpt-(6|5|4o|4\.1|oss)|o[134]-|gemini-(4|3|2\.5)|grok-(4|3)|mistral-(large|small)|codestral|"
    r"devstral|kimi-k[23]|glm-[45]|nemotron|gemma-[34]|command-(a|r)|text-embedding-3|embed-v[45]|bge-)",
    re.IGNORECASE,
)
SMALL_DISTILL_RE = re.compile(
    r"(distill.*(1\.5b|1p5b|7b|8b|14b)|-(1\.5b|1p5b|3b|4b|7b|8b|9b)\b|\b(flash|lite|mini|haiku|nano|small|lightning)\b)",
    re.IGNORECASE,
)


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".llm_costs_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, str(path))
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=18.0) as resp:
        return json.loads(resp.read(12_000_000).decode("utf-8", errors="replace"))


def _fmt_ctx(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M".replace(".0M", "M")
    return f"{int(round(tokens / 1000.0))}K" if tokens >= 1000 else (str(tokens) if tokens > 0 else "128K")


def _classify_tier(slug: str, mode: str, in_1m: float, is_reasoning: bool) -> str:
    low = slug.lower()
    if mode == "embedding" or any(k in low for k in ("embed", "bge-", "e5-", "gte-")):
        return "Embedding"
    if any(k in low for k in ("coder", "codestral", "devstral", "-code", "code-", "starcoder", "codex", "grok-build")):
        return "Coding"
    if SMALL_DISTILL_RE.search(low) and in_1m <= 1.0:
        return "Fast 70B-8B"
    if is_reasoning or any(
        k in low for k in (
            "deepseek-r1", "deepseek-v3", "deepseek-v4-pro", "qwq", "thinking", "fable", "opus",
            "sonnet", "gpt-6", "gpt-5", "gpt-oss-120b", "o1", "o3", "o4", "gemini-4", "gemini-2.5-pro",
            "grok-4", "qwen4-max", "qwen3.8-max", "qwen3-235b", "kimi-k3", "kimi-k2.5", "mistral-large",
            "405b", "llama-4-maverick", "nemotron-3-ultra", "glm-5", "command-a",
        )
    ) or in_1m >= 1.25:
        return "Frontier Reasoning"
    return "Fast 70B-8B"


def _infer_family(slug: str) -> str:
    low = slug.lower()
    for token, label in (
        ("claude", "Claude"), ("gpt-oss", "GPT-OSS"), ("gpt-", "GPT"), ("codex", "GPT"),
        ("o3", "OpenAI o-Series"), ("o4", "OpenAI o-Series"), ("gemini", "Gemini"), ("gemma", "Gemma"),
        ("deepseek", "DeepSeek"), ("llama", "Llama"), ("qwen", "Qwen"), ("qwq", "Qwen"),
        ("mistral", "Mistral"), ("codestral", "Mistral"), ("devstral", "Mistral"), ("ministral", "Mistral"),
        ("grok", "Grok"), ("kimi", "Kimi"), ("glm", "GLM"), ("nemotron", "Nemotron"),
        ("command", "Command"), ("embed", "Embedding"), ("bge", "Embedding"), ("minimax", "MiniMax"),
    ):
        if token in low:
            return label
    return "Other LLM"


def _clean_name(raw_id: str, prefix: str) -> str:
    s = raw_id[len(prefix) + 1:] if raw_id.startswith(prefix + "/") else raw_id
    return s.replace("accounts/fireworks/models/", "").replace("models/", "").split("/")[-1]


def sync_live_llm_costs() -> dict:
    or_raw = _fetch_json(OPENROUTER_API_URL)
    ll_raw = _fetch_json(LITELLM_JSON_URL)
    or_items = (or_raw.get("data") if isinstance(or_raw, dict) else []) or []
    ll_dict = ll_raw if isinstance(ll_raw, dict) else {}

    buckets: dict[str, list[dict[str, object]]] = {}
    seen: set[tuple[str, str]] = set()
    scanned = 0

    for m in or_items:
        mid = str((m or {}).get("id") or "").strip()
        if "/" not in mid or SKIP_RE.search(mid):
            continue
        pr = (m or {}).get("pricing") or {}
        try:
            in_1m, out_1m = round(float(pr.get("prompt") or -1) * 1e6, 4), round(float(pr.get("completion") or -1) * 1e6, 4)
        except (TypeError, ValueError):
            continue
        is_emb = "embed" in mid.lower()
        if in_1m <= 0 or in_1m > 150.0 or out_1m < 0 or (not is_emb and out_1m <= 0) or out_1m > 250.0:
            continue
        scanned += 1
        vk = mid.split("/", 1)[0].lower()
        if vk not in OR_VENDORS:
            continue
        pname, purl, pcat, dlic, _ = OR_VENDORS[vk]
        dedup = (pname.lower(), _clean_name(mid, vk).lower().replace(".", "").replace("-", ""))
        if dedup in seen:
            continue
        seen.add(dedup)
        ctx = int(m.get("context_length") or 128000)
        lic = "Open-Weight" if any(x in mid.lower() for x in ("gpt-oss", "gemma", "muse-spark-open")) else dlic
        buckets.setdefault(f"or:{vk}", []).append({
            "provider_id": vk, "provider_name": pname, "provider_url": purl, "provider_category": pcat,
            "model_id": mid, "model_name": str(m.get("name") or _clean_name(mid, vk)),
            "family": _infer_family(mid), "tier": _classify_tier(mid, "embedding" if is_emb else "chat", in_1m, bool(m.get("reasoning"))),
            "license_type": lic, "context_tokens": ctx, "context_label": _fmt_ctx(ctx),
            "input_per_1m_usd": in_1m, "output_per_1m_usd": out_1m,
            "blended_per_1m_usd": round((3.0 * in_1m + out_1m) / 4.0, 4), "source": "openrouter_live",
        })

    for rk, v in ll_dict.items():
        if not isinstance(v, dict) or SKIP_RE.search(rk):
            continue
        prov = str(v.get("litellm_provider") or "").strip().lower()
        mode = str(v.get("mode") or "chat").strip().lower()
        if mode not in ("chat", "embedding", "completion", "") or v.get("input_cost_per_token") is None:
            continue
        try:
            in_1m = round(float(v["input_cost_per_token"]) * 1e6, 4)
            out_1m = round(float(v.get("output_cost_per_token") or 0.0) * 1e6, 4)
        except (TypeError, ValueError):
            continue
        is_emb = mode == "embedding" or "embed" in rk.lower() or "bge-" in rk.lower()
        if in_1m <= 0 or in_1m > 150.0 or out_1m < 0 or (not is_emb and out_1m <= 0) or out_1m > 250.0:
            continue
        scanned += 1
        if prov not in LITELLM_PROVIDERS or (prov.startswith(("together_ai", "fireworks_ai")) and "/" not in rk):
            continue
        if prov in ("openai", "cohere") and not is_emb:
            continue
        pname, purl, pcat, _ = LITELLM_PROVIDERS[prov]
        disp = _clean_name(rk, prov)
        dedup = (pname.lower(), disp.lower().replace(".", "").replace("-", ""))
        if dedup in seen:
            continue
        seen.add(dedup)
        ctx = int(v.get("max_input_tokens") or v.get("max_tokens") or (8192 if is_emb else 131072))
        buckets.setdefault(f"ll:{prov}", []).append({
            "provider_id": prov.replace("_ai-embedding-models", "_ai"), "provider_name": pname,
            "provider_url": purl, "provider_category": pcat, "model_id": rk, "model_name": disp,
            "family": _infer_family(rk), "tier": _classify_tier(rk, "embedding" if is_emb else "chat", in_1m, False),
            "license_type": "Proprietary" if prov in ("openai", "cohere") else "Open-Weight",
            "context_tokens": ctx, "context_label": _fmt_ctx(ctx),
            "input_per_1m_usd": in_1m, "output_per_1m_usd": out_1m,
            "blended_per_1m_usd": round((3.0 * in_1m + out_1m) / 4.0, 4), "source": "litellm_direct",
        })

    curated: list[dict[str, object]] = []
    for bkey, rows in buckets.items():
        rows.sort(key=lambda r: (-(2 if DEMAND_RE.search(f"{r['model_id']} {r['model_name']}") else 0), float(r["blended_per_1m_usd"])))
        cap = OR_VENDORS[bkey[3:]][4] if bkey.startswith("or:") else LITELLM_PROVIDERS[bkey[3:]][3]
        curated.extend(rows[:cap])
    curated.sort(key=lambda r: (float(r["blended_per_1m_usd"]), float(r["input_per_1m_usd"])))

    now_dt = datetime.now(timezone.utc)
    now_utc = now_dt.strftime("%Y-%m-%d %H:%M UTC")
    if len(curated) < 80:
        if OUT_JSON.exists():
            prev = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            prev["stale_warning"], prev["last_failed_check_utc"] = True, now_utc
            _atomic_write_json(OUT_JSON, prev)
            return prev
        raise RuntimeError(f"Circuit breaker tripped: only {len(curated)} valid models (< 80 minimum)")

    calc_clouds = ("DeepInfra", "Together AI", "Fireworks AI", "Groq", "Cerebras", "Baseten", "Novita AI", "SambaNova")
    tier_benchmarks: dict[str, dict[str, object]] = {}
    for tname in ("Frontier Reasoning", "Coding", "Fast 70B-8B"):
        prop = sorted(
            [r for r in curated if r["tier"] == tname and r["license_type"] == "Proprietary"]
            or [r for r in curated if r["license_type"] == "Proprietary" and r["tier"] != "Embedding"],
            key=lambda r: float(r["blended_per_1m_usd"]),
        )
        anchor = prop[len(prop) // 2] if prop else curated[-1]
        quotes = []
        for cname in calc_clouds:
            cands = [r for r in curated if r["provider_name"] == cname and r["tier"] == tname] or [
                r for r in curated if r["provider_name"] == cname and r["tier"] == ("Frontier Reasoning" if tname == "Coding" else "Fast 70B-8B")
            ] or [r for r in curated if r["provider_name"] == cname and r["tier"] != "Embedding"]
            if cands:
                best = min(cands, key=lambda r: float(r["blended_per_1m_usd"]))
                quotes.append({k: best[k] for k in ("provider_name", "provider_url", "model_name", "input_per_1m_usd", "output_per_1m_usd", "blended_per_1m_usd")})
        quotes.sort(key=lambda x: float(x["blended_per_1m_usd"]))
        tier_benchmarks[tname] = {
            "proprietary_baseline": {k: anchor[k] for k in ("provider_name", "model_name", "input_per_1m_usd", "output_per_1m_usd", "blended_per_1m_usd")},
            "open_weight_clouds": quotes,
        }

    payload = {
        "site": "LLMCostComparison.com", "updated_at_utc": now_utc, "updated_epoch": int(now_dt.timestamp()),
        "stale_warning": False,
        "summary": {
            "curated_offers": len(curated), "total_models_scanned": scanned,
            "providers_tracked": len({str(r["provider_name"]) for r in curated}),
            "inference_clouds_tracked": len({str(r["provider_name"]) for r in curated if r["provider_category"] == "Inference Cloud"}),
            "lowest_blended_per_1m_usd": curated[0]["blended_per_1m_usd"],
        },
        "tier_benchmarks": tier_benchmarks, "models": curated,
    }
    _atomic_write_json(OUT_JSON, payload)
    _atomic_write_json(HISTORY_DIR / f"{now_dt.strftime('%Y-%m-%d')}.json", {
        "date_utc": now_dt.strftime("%Y-%m-%d"), "updated_at_utc": now_utc,
        "summary": payload["summary"], "tier_benchmarks": tier_benchmarks,
    })
    return payload


if __name__ == "__main__":
    res = sync_live_llm_costs()
    print(json.dumps({"updated": res["updated_at_utc"], "summary": res["summary"]}, indent=2))
