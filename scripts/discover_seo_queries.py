#!/usr/bin/env python3
"""Live US Google Autocomplete & GSC Query Poller + Guardrailed Subpage Auto-Expander for LLMCostComparison.com."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"
COSTS_PATH = PUBLIC_DIR / "llm_costs.json"
TARGETS_PATH = PUBLIC_DIR / "seo_targets.json"
SIGNALS_PATH = PUBLIC_DIR / "live_search_signals.json"
SITE_PROP = "sc-domain:llmcostcomparison.com"

SEED_PREFIXES: tuple[str, ...] = (
    "llm cost ",
    "llm api pricing",
    "claude api pricing",
    "mistral api pricing",
    "groq api pricing",
    "together ai pricing",
    "deepseek api ",
    "llama api ",
    "qwen api ",
    "gemma api ",
    "token cost ",
    "inference cloud pricing",
)

BLUEPRINT_POOL: tuple[dict[str, object], ...] = (
    {
        "trigger_tokens": ["mistral"],
        "min_models": 5,
        "page": {
            "slug": "mistral-api-pricing",
            "nav_label": "Mistral API Pricing",
            "target_query": "Mistral & Codestral API Pricing Comparison",
            "title": "Mistral & Codestral API Pricing Comparison (2026 Live $/1M)",
            "h1": "Mistral & Codestral API Pricing Comparison",
            "lead": "Compare live $/1M input, output, and 3:1 blended token pricing for Mistral Large, Mistral Medium/Small, Ministral, and Codestral endpoints across Mistral AI and open-weight inference clouds.",
            "match_mode": "keyword",
            "keywords": ["mistral", "codestral", "ministral"],
            "quantization_note": "Mistral AI hosts official EU-resident endpoints alongside open-weight Mistral/Ministral checkpoints on Fireworks AI, Together AI, DeepInfra, and Nebius. Compare EU GDPR data residency, FP8 vs BF16 precision, and coding latency.",
        },
    },
    {
        "trigger_tokens": ["claude api", "anthropic"],
        "min_models": 5,
        "page": {
            "slug": "claude-api-pricing",
            "nav_label": "Claude API Pricing",
            "target_query": "Anthropic Claude API Token Pricing & Cost Calculator",
            "title": "Anthropic Claude API Token Pricing & Cost Calculator (2026 Live)",
            "h1": "Anthropic Claude API Token Pricing & Cost Calculator",
            "lead": "Live $/1M input, output, and 3:1 blended token pricing across Anthropic Claude Opus, Claude Sonnet, and Claude Haiku model generations with monthly agent/RAG bill estimation.",
            "match_mode": "providers",
            "provider_ids": ["anthropic"],
            "quantization_note": "Anthropic Claude API rates apply separate prompt-caching write/read multipliers (up to 90% read discount on repeated system/RAG context) and 50% async Message Batches API discounts. Verify >200K extended context tiers.",
        },
    },
    {
        "trigger_tokens": ["groq", "together ai", "inference cloud"],
        "min_models": 8,
        "page": {
            "slug": "inference-cloud-pricing",
            "nav_label": "Inference Clouds",
            "target_query": "AI Inference Cloud Pricing (Groq, Together, Fireworks, DeepInfra, Baseten)",
            "title": "AI Inference Cloud Pricing — Groq, Together AI, Fireworks & DeepInfra",
            "h1": "AI Inference Cloud API Pricing Benchmark",
            "lead": "Side-by-side $/1M token pricing across specialized open-weight inference clouds including Fireworks AI, Together AI, DeepInfra, Baseten, Nebius AI, SambaNova, Novita, and Hyperbolic.",
            "match_mode": "providers",
            "provider_ids": ["fireworks_ai", "together_ai", "deepinfra", "baseten", "nebius", "sambanova", "novita", "hyperbolic"],
            "quantization_note": "Wafer-scale/ASIC providers (SambaNova, Groq, Cerebras) optimize ultra-low time-to-first-token and high tokens/sec, while GPU clouds (Together, Fireworks, DeepInfra, Baseten) offer broad FP8/BF16 catalog coverage and LoRA hosting.",
        },
    },
)


def _fetch_us_autocomplete(prefix: str) -> list[dict[str, object]]:
    url = "https://suggestqueries.google.com/complete/search?client=chrome&hl=en&gl=us&q=" + urllib.parse.quote(prefix)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    queries = list(data[1] or [])[:8]
    rels = list(((data[4] if len(data) > 4 and isinstance(data[4], dict) else {}).get("google:suggestrelevance")) or [])
    return [
        {"query": str(q).strip().lower(), "score": int(rels[i]) if i < len(rels) else max(500, 900 - i * 50), "source": "google_us_autocomplete", "seed": prefix.strip()}
        for i, q in enumerate(queries)
    ]


def _fetch_gsc_api_if_configured() -> list[dict[str, object]]:
    cid = os.environ.get("GSC_CLIENT_ID", "").strip()
    csec = os.environ.get("GSC_CLIENT_SECRET", "").strip()
    rtok = os.environ.get("GSC_REFRESH_TOKEN", "").strip()
    if not (cid and csec and rtok):
        return []
    tbody = urllib.parse.urlencode({"client_id": cid, "client_secret": csec, "refresh_token": rtok, "grant_type": "refresh_token"}).encode("utf-8")
    treq = urllib.request.Request("https://oauth2.googleapis.com/token", data=tbody, method="POST")
    with urllib.request.urlopen(treq, timeout=10) as tresp:
        atok = json.loads(tresp.read().decode("utf-8"))["access_token"]
    end_d = datetime.now(timezone.utc).date()
    start_d = end_d - timedelta(days=28)
    api_url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(SITE_PROP, safe='')}/searchAnalytics/query"
    qbody = json.dumps({"startDate": str(start_d), "endDate": str(end_d), "dimensions": ["query"], "rowLimit": 50}).encode("utf-8")
    qreq = urllib.request.Request(api_url, data=qbody, headers={"Authorization": f"Bearer {atok}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(qreq, timeout=10) as qresp:
        rows = json.loads(qresp.read().decode("utf-8")).get("rows") or []
    return [
        {
            "query": str((r.get("keys") or [""])[0]).lower(),
            "impressions": int(r.get("impressions") or 0),
            "clicks": int(r.get("clicks") or 0),
            "position": round(float(r.get("position") or 0.0), 1),
            "score": 1000 + int(r.get("impressions") or 0) * 20,
            "source": "google_search_console_api",
        }
        for r in rows
    ]


def _count_matching_models(models: list[dict[str, object]], page_def: dict[str, object]) -> int:
    mode = str(page_def.get("match_mode") or "")
    if mode == "keyword":
        kws = [str(k).lower() for k in (page_def.get("keywords") or [])]
        return sum(1 for m in models if any(k in f"{m.get('model_id','')} {m.get('model_name','')} {m.get('family','')}".lower() for k in kws))
    if mode == "providers":
        pids = set(page_def.get("provider_ids") or [])
        return sum(1 for m in models if str(m.get("provider_id")) in pids)
    return len(models)


def run_discovery() -> dict[str, object]:
    now_dt = datetime.now(timezone.utc)
    iso_week = f"{now_dt.isocalendar()[0]}-W{now_dt.isocalendar()[1]:02d}"
    now_utc = now_dt.strftime("%Y-%m-%d %H:%M UTC")

    seen: dict[str, dict[str, object]] = {}
    for pref in SEED_PREFIXES:
        try:
            for item in _fetch_us_autocomplete(pref):
                q = str(item["query"])
                if q not in seen or int(item["score"]) > int(seen[q]["score"]):
                    seen[q] = item
        except Exception:
            continue
    try:
        for item in _fetch_gsc_api_if_configured():
            seen[str(item["query"])] = item
    except Exception:
        pass

    ranked_signals = sorted(seen.values(), key=lambda x: int(x.get("score") or 0), reverse=True)
    models = list(json.loads(COSTS_PATH.read_text(encoding="utf-8")).get("models") or [])
    targets_cfg = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    pages = list(targets_cfg.get("pages") or [])
    existing_slugs = {str(p.get("slug")) for p in pages}
    promotions = list(targets_cfg.get("auto_promotions") or [])

    max_weekly = int(targets_cfg.get("max_new_pages_per_week") or 2)
    max_total = int(targets_cfg.get("max_total_pages") or 15)
    added_this_week = sum(1 for x in promotions if str(x.get("iso_week")) == iso_week)
    newly_promoted: list[dict[str, object]] = []

    for bp in BLUEPRINT_POOL:
        if len(pages) >= max_total or added_this_week >= max_weekly:
            break
        page_def = dict(bp["page"])  # type: ignore[arg-type]
        slug = str(page_def["slug"])
        if slug in existing_slugs:
            continue
        live_cnt = _count_matching_models(models, page_def)
        if live_cnt < int(bp.get("min_models") or 5):
            continue
        tokens = [str(t).lower() for t in (bp.get("trigger_tokens") or [])]
        matched = [s for s in ranked_signals if any(tok in str(s["query"]) for tok in tokens) and int(s.get("score") or 0) >= 550]
        if not matched:
            continue
        best = matched[0]
        pages.append(page_def)
        existing_slugs.add(slug)
        rec = {
            "slug": slug,
            "iso_week": iso_week,
            "promoted_at_utc": now_utc,
            "trigger_query": best["query"],
            "trigger_score": best["score"],
            "trigger_source": best["source"],
            "live_models_verified": live_cnt,
        }
        promotions.append(rec)
        newly_promoted.append(rec)
        added_this_week += 1

    targets_cfg["pages"] = pages
    targets_cfg["auto_promotions"] = promotions
    targets_cfg["observed_gsc_queries"] = ranked_signals[:25]
    TARGETS_PATH.write_text(json.dumps(targets_cfg, indent=2) + "\n", encoding="utf-8")

    SIGNALS_PATH.write_text(
        json.dumps(
            {
                "site": "LLMCostComparison.com",
                "updated_at_utc": now_utc,
                "iso_week": iso_week,
                "total_signals_collected": len(ranked_signals),
                "active_subpages_count": len(pages),
                "newly_promoted_this_run": newly_promoted,
                "top_live_queries": ranked_signals[:30],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"signals": len(ranked_signals), "active_pages": len(pages), "newly_promoted": newly_promoted}


if __name__ == "__main__":
    print(json.dumps(run_discovery()))
