#!/usr/bin/env python3
"""Static HTML SSR Pre-Renderer, JSON-LD FAQ Enricher & IndexNow Notifier for LLMCostComparison.com."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"
JSON_PATH = PUBLIC_DIR / "llm_costs.json"
TARGETS_PATH = PUBLIC_DIR / "seo_targets.json"
HTML_PATH = PUBLIC_DIR / "index.html"
SITEMAP_PATH = PUBLIC_DIR / "sitemap.xml"
HOST = "llmcostcomparison.com"
SITE_URL = f"https://{HOST}/"
INDEXNOW_KEY = hashlib.sha256(f"indexnow:{HOST}:v1".encode("utf-8")).hexdigest()[:32]


def _esc(val: object) -> str:
    return html.escape(str(val or ""), quote=True)


def _fmt_rate(val: object) -> str:
    n = float(val or 0.0)
    if n <= 0:
        return "$0.00"
    if n < 0.01:
        return f"${n:.4f}"
    if n < 0.1:
        return f"${n:.3f}"
    return f"${n:.2f}"


def _select_ssr_models(models: list[dict[str, object]]) -> list[dict[str, object]]:
    """Select representative flagship, reasoning, fast & open-weight LLM models across providers (~64 rows)."""
    chat_rows = [m for m in models if str(m.get("tier")) != "Embedding"]
    chat_rows.sort(key=lambda r: float(r.get("blended_per_1m_usd") or 999.0))
    picked: list[dict[str, object]] = []
    prov_counts: dict[str, int] = {}
    for m in chat_rows:
        prov = str(m.get("provider_id") or "")
        if prov_counts.get(prov, 0) < 4:
            picked.append(m)
            prov_counts[prov] = prov_counts.get(prov, 0) + 1
        if len(picked) >= 64:
            break
    return picked


def _render_rows_html(models: list[dict[str, object]]) -> str:
    rows_html: list[str] = []
    for r in _select_ssr_models(models):
        lic = str(r.get("license_type") or "Proprietary")
        lic_badge = '<span class="badge b-open">Open-Weight</span>' if lic == "Open-Weight" else '<span class="badge b-prop">Proprietary</span>'
        rows_html.append(
            "<tr>"
            f'<td><div><a class="provider-link" href="{_esc(r.get("provider_url"))}" target="_blank" rel="noopener">{_esc(r.get("provider_name"))} ↗</a></div>'
            f'<div class="fs-xs text-muted">{_esc(r.get("provider_category"))}</div></td>'
            f'<td><div class="fw-800">{_esc(r.get("model_name"))}</div>'
            f'<div class="fs-xs text-muted">{_esc(r.get("family"))} · <code>{_esc(r.get("model_id"))}</code></div></td>'
            f'<td><div><span class="badge b-tier">{_esc(r.get("tier"))}</span></div><div style="margin-top:4px;">{lic_badge}</div></td>'
            f'<td class="fw-800">{_esc(r.get("context_label"))}</td>'
            f'<td class="fw-800">{_fmt_rate(r.get("input_per_1m_usd"))}</td>'
            f'<td class="fw-800">{_fmt_rate(r.get("output_per_1m_usd"))}</td>'
            f'<td class="fw-900">{_fmt_rate(r.get("blended_per_1m_usd"))}</td>'
            "</tr>"
        )
    return "\n          ".join(rows_html)


def _build_ldjson(data: dict[str, object], iso_date: str) -> str:
    summ = data.get("summary") or {}
    total_models = int(summ.get("curated_offers") or summ.get("total_models") or 228)
    providers = int(summ.get("providers_tracked") or 25)
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Dataset",
                "name": "Live LLM Cost Comparison & API Token Pricing Index",
                "description": f"Normalized $/1M input token, $/1M output token, 3:1 blended token rates, and context window benchmarks across {providers} Frontier Labs and Open-Weight Inference Clouds ({total_models} live endpoints).",
                "url": SITE_URL,
                "dateModified": iso_date,
                "keywords": ["llm cost comparison", "llm api pricing", "token cost calculator", "deepseek api price", "llama inference cost", "claude vs gpt token pricing"],
                "distribution": {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": f"{SITE_URL}llm_costs.json"},
            },
            {
                "@type": "WebApplication",
                "name": "LLMCostComparison.com — Monthly LLM Token Cost & Cloud Savings Calculator",
                "url": SITE_URL,
                "applicationCategory": "DeveloperApplication",
                "operatingSystem": "All",
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": "How is the 3:1 Blended $/1M LLM token rate calculated?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "Blended token pricing weights 3 parts input tokens to 1 part output tokens: (3 × Input $/1M + 1 × Output $/1M) ÷ 4, matching real-world RAG, coding agent, and multi-turn chat prompt-to-completion ratios.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "How often are LLM API prices updated on LLMCostComparison.com?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": f"An automated GitHub Actions pipeline runs every 6 hours, cross-checking {total_models} live endpoints across {providers} Frontier Labs and Open-Weight Inference Clouds (OpenAI, Anthropic, Google, DeepSeek, Groq, Cerebras, Together AI, Fireworks AI, DeepInfra, Baseten, SambaNova).",
                        },
                    },
                ],
            },
        ],
    }
    return json.dumps(graph, indent=2)


def prerender_all(ping_indexnow: bool = False) -> dict[str, object]:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    now_dt = datetime.now(timezone.utc)
    day_str = now_dt.strftime("%Y-%m-%d")
    iso_str = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    models = list(data.get("models") or [])
    total_models = int((data.get("summary") or {}).get("total_models") or len(models))

    doc = HTML_PATH.read_text(encoding="utf-8")
    doc = re.sub(
        r'(<script id="seo-ldjson" type="application/ld\+json">)(.*?)(</script>)',
        lambda m: f"{m.group(1)}\n{_build_ldjson(data, iso_str)}\n  {m.group(3)}",
        doc,
        count=1,
        flags=re.DOTALL,
    )
    doc = re.sub(
        r'(<span id="row-count-lbl"[^>]*>)(.*?)(</span>)',
        lambda m: f"{m.group(1)}{total_models} live endpoints{m.group(3)}",
        doc,
        count=1,
        flags=re.DOTALL,
    )
    doc = re.sub(
        r'(<tbody id="models-tbody">)(.*?)(</tbody>)',
        lambda m: f"{m.group(1)}\n          {_render_rows_html(models)}\n        {m.group(3)}",
        doc,
        count=1,
        flags=re.DOTALL,
    )
    HTML_PATH.write_text(doc, encoding="utf-8")

    entries = [(SITE_URL, "1.0")]
    if TARGETS_PATH.exists():
        tcfg = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        for p in list(tcfg.get("pages") or [])[: int(tcfg.get("max_total_pages") or 15)]:
            if p.get("slug"):
                entries.append((f"{SITE_URL}{p['slug']}/", "0.85"))
    url_nodes = "\n".join(
        f"  <url>\n    <loc>{u}</loc>\n    <lastmod>{day_str}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>{pr}</priority>\n  </url>"
        for u, pr in entries
    )
    SITEMAP_PATH.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{url_nodes}\n</urlset>\n',
        encoding="utf-8",
    )
    key_file = PUBLIC_DIR / f"{INDEXNOW_KEY}.txt"
    key_file.write_text(INDEXNOW_KEY, encoding="utf-8")

    sitemap_urls = re.findall(r"<loc>\s*(https?://[^<\s]+)\s*</loc>", SITEMAP_PATH.read_text(encoding="utf-8")) or [SITE_URL]
    ping_status = None
    if ping_indexnow:
        body = json.dumps({
            "host": HOST,
            "key": INDEXNOW_KEY,
            "keyLocation": f"{SITE_URL}{INDEXNOW_KEY}.txt",
            "urlList": sitemap_urls,
        }).encode("utf-8")
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            ping_status = resp.status
    return {"host": HOST, "ssr_rows": len(_select_ssr_models(models)), "sitemap_urls": len(sitemap_urls), "indexnow_key": INDEXNOW_KEY, "ping_status": ping_status}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ping-indexnow", action="store_true")
    args = ap.parse_args()
    print(json.dumps(prerender_all(ping_indexnow=args.ping_indexnow)))
