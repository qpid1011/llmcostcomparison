#!/usr/bin/env python3
"""Closed-Loop Programmatic SEO & Multi-Day Price Trend Builder (v5.0) for LLMCostComparison.com."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re

ROOT_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = ROOT_DIR / "public"
COSTS_PATH = PUBLIC_DIR / "llm_costs.json"
TARGETS_PATH = PUBLIC_DIR / "seo_targets.json"
HISTORY_DIR = PUBLIC_DIR / "history"
INDEX_PATH = PUBLIC_DIR / "index.html"
SITEMAP_PATH = PUBLIC_DIR / "sitemap.xml"
SITE_URL = "https://llmcostcomparison.com/"
GA4_ID = "G-88B5QR95FL"


def _esc(val: object) -> str:
    return html.escape(str(val or ""), quote=True)


def _fmt_rate(val: object) -> str:
    n = float(val or 0.0)
    if n <= 0:
        return "$0.00"
    return f"${n:.4f}" if n < 0.01 else (f"${n:.3f}" if n < 0.1 else f"${n:.2f}")


def _fmt_usd(val: float) -> str:
    return f"${round(val):,}" if val >= 1000.0 else f"${val:,.2f}"


def _cloud_floor(snap: dict[str, object], tier: str) -> float:
    clouds = ((snap.get("tier_benchmarks") or {}).get(tier) or {}).get("open_weight_clouds") or []
    vals = [float(c.get("blended_per_1m_usd") or 0) for c in clouds if float(c.get("blended_per_1m_usd") or 0) > 0]
    return min(vals) if vals else 0.0


def _load_history_metrics() -> dict[str, object]:
    files = sorted(HISTORY_DIR.glob("*.json"))
    snaps = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    if not snaps:
        return {"days": 1, "first_date": "-", "latest_date": "-", "first_scanned": 0, "latest_scanned": 0,
                "fr_first": 0.0, "fr_last": 0.0, "fr_prop": 0.0, "fa_first": 0.0, "fa_last": 0.0}
    first, last = snaps[0], snaps[-1]
    fr_prop = float((((last.get("tier_benchmarks") or {}).get("Frontier Reasoning") or {}).get("proprietary_baseline") or {}).get("blended_per_1m_usd") or 0.0)
    return {
        "days": len(snaps),
        "first_date": str(first.get("date_utc") or files[0].stem),
        "latest_date": str(last.get("date_utc") or files[-1].stem),
        "first_scanned": int((first.get("summary") or {}).get("total_models_scanned") or 0),
        "latest_scanned": int((last.get("summary") or {}).get("total_models_scanned") or 0),
        "fr_first": _cloud_floor(first, "Frontier Reasoning"),
        "fr_last": _cloud_floor(last, "Frontier Reasoning"),
        "fr_prop": fr_prop,
        "fa_first": _cloud_floor(first, "Fast 70B-8B"),
        "fa_last": _cloud_floor(last, "Fast 70B-8B"),
    }


def _match_models(models: list[dict[str, object]], page: dict[str, object]) -> list[dict[str, object]]:
    chat = [m for m in models if str(m.get("tier")) != "Embedding" and float(m.get("blended_per_1m_usd") or 0) > 0]
    mode = str(page.get("match_mode") or "keyword")
    if mode == "keyword":
        kws = [str(k).lower() for k in (page.get("keywords") or [])]
        matched = [m for m in chat if any(k in f"{m.get('family', '')} {m.get('model_name', '')} {m.get('model_id', '')}".lower() for k in kws)]
    elif mode == "providers":
        pset = {str(p) for p in (page.get("provider_ids") or [])}
        matched = [m for m in chat if str(m.get("provider_id")) in pset]
    elif mode == "providers_families":
        pset, fset = {str(p) for p in (page.get("provider_ids") or [])}, {str(f) for f in (page.get("families") or [])}
        matched = [m for m in chat if str(m.get("provider_id")) in pset and str(m.get("family")) in fset]
    elif mode == "top_cheapest":
        return sorted(chat, key=lambda r: float(r.get("blended_per_1m_usd") or 999.0))[: int(page.get("limit") or 40)]
    else:
        matched = []
    return sorted(matched, key=lambda r: float(r.get("blended_per_1m_usd") or 999.0))


def _render_table_rows(rows: list[dict[str, object]]) -> str:
    out: list[str] = []
    for r in rows:
        lic_b = '<span class="badge b-open">Open-Weight</span>' if r.get("license_type") == "Open-Weight" else '<span class="badge b-prop">Proprietary</span>'
        hay = _esc(f"{r.get('provider_name', '')} {r.get('model_name', '')} {r.get('model_id', '')} {r.get('family', '')} {r.get('tier', '')}".lower())
        out.append(
            f'<tr data-hay="{hay}"><td><div><a class="provider-link" href="{_esc(r.get("provider_url"))}" target="_blank" rel="noopener">{_esc(r.get("provider_name"))} ↗</a></div>'
            f'<div class="fs-xs text-muted">{_esc(r.get("provider_category"))}</div></td>'
            f'<td><div class="fw-800">{_esc(r.get("model_name"))}</div><div class="fs-xs text-muted">{_esc(r.get("family"))} · <code>{_esc(r.get("model_id"))}</code></div></td>'
            f'<td><div><span class="badge b-tier">{_esc(r.get("tier"))}</span></div><div style="margin-top:4px;">{lic_b}</div></td>'
            f'<td class="fw-800">{_esc(r.get("context_label"))}</td><td class="fw-800">{_fmt_rate(r.get("input_per_1m_usd"))}</td>'
            f'<td class="fw-800">{_fmt_rate(r.get("output_per_1m_usd"))}</td><td class="fw-900">{_fmt_rate(r.get("blended_per_1m_usd"))}</td></tr>'
        )
    return "\n          ".join(out)


def _build_subpage_ldjson(page: dict[str, object], rows: list[dict[str, object]], hist: dict[str, object], iso_str: str) -> str:
    url = f"{SITE_URL}{page['slug']}/"
    low, med, high = rows[0], rows[len(rows) // 2], rows[-1]
    q1 = (f"Across {len(rows)} verified endpoints on this benchmark, the lowest 3:1 blended rate is {_fmt_rate(low['blended_per_1m_usd'])}/1M tokens "
          f"({low['provider_name']} · {low['model_name']}: {_fmt_rate(low['input_per_1m_usd'])} input / {_fmt_rate(low['output_per_1m_usd'])} output), "
          f"versus page median {_fmt_rate(med['blended_per_1m_usd'])}/1M ({med['model_name']}) and upper-tier {_fmt_rate(high['blended_per_1m_usd'])}/1M ({high['model_name']}).")
    q2 = (f"LLMCostComparison.com archives daily pricing snapshots ({hist['days']} days tracked from {hist['first_date']} to {hist['latest_date']}, "
          f"expanding audited catalog coverage from {hist['first_scanned']:,} to {hist['latest_scanned']:,} API entries). Frontier Reasoning open-weight "
          f"cloud floors tracked {_fmt_rate(hist['fr_first'])}/1M to {_fmt_rate(hist['fr_last'])}/1M vs {_fmt_rate(hist['fr_prop'])}/1M proprietary baseline.")
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Dataset", "name": str(page["h1"]), "url": url, "dateModified": iso_str,
             "description": f"{page['lead']} Tracks {len(rows)} live endpoints starting at {_fmt_rate(low['blended_per_1m_usd'])}/1M blended across {hist['days']} daily snapshots.",
             "distribution": {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": f"{SITE_URL}llm_costs.json"}},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE_URL},
                {"@type": "ListItem", "position": 2, "name": str(page["h1"]), "item": url}]},
            {"@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": f"What is the lowest $/1M token rate for {page['nav_label']}?", "acceptedAnswer": {"@type": "Answer", "text": q1}},
                {"@type": "Question", "name": "How have LLM API token rates moved across multi-day historical snapshots?", "acceptedAnswer": {"@type": "Answer", "text": q2}},
                {"@type": "Question", "name": f"What quantization, precision, and ZDR terms matter for {page['nav_label']}?", "acceptedAnswer": {"@type": "Answer", "text": str(page["quantization_note"])}}]},
        ],
    }
    return json.dumps(graph, indent=2)


SUBPAGE_CSS = "".join([
    ':root{--bg:#0f172a;--surface:#1e293b;--surface-alt:#0b1220;--border:#334155;--text:#f8fafc;--text-muted:#94a3b8;--accent:#38bdf8;--row-hover:rgba(56,189,248,0.07)}',
    'html.light-theme,body.light-theme{--bg:#f8fafc;--surface:#ffffff;--surface-alt:#f1f5f9;--border:#cbd5e1;--text:#0f172a;--text-muted:#475569;--accent:#0369a1;--row-hover:#f1f5f9}',
    '*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}',
    '.text-accent{color:var(--accent)}.text-muted{color:var(--text-muted)}.fw-800{font-weight:800}.fw-900{font-weight:900}.fs-xs{font-size:0.75rem}.fs-sm{font-size:0.84rem}',
    '.topbar{position:sticky;top:0;z-index:30;background:var(--surface);border-bottom:1px solid var(--border);padding:14px 24px;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px}',
    '.brand,.top-actions,.pill-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.brand-link{text-decoration:none;color:var(--text);font-size:1.18rem;font-weight:900;letter-spacing:-0.02em}',
    '.lime-badge,html.light-theme .lime-badge,body.light-theme .lime-badge{background:#d9f99d;color:#1a2e05;border:1px solid #65a30d;padding:2px 9px;border-radius:999px;font-size:0.74rem;font-weight:800;display:inline-block}',
    '.btn{background:var(--surface-alt);color:var(--text);border:1px solid var(--border);padding:7px 13px;border-radius:8px;font-size:0.82rem;font-weight:700;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:6px}',
    '.btn:hover,.pill-btn:hover{border-color:var(--accent)}.container{max-width:1360px;margin:20px auto 64px;padding:0 20px}',
    '.breadcrumb{font-size:0.8rem;font-weight:700;color:var(--text-muted);margin-bottom:12px;display:flex;gap:7px;align-items:center;flex-wrap:wrap}.breadcrumb a,.provider-link{color:var(--accent);text-decoration:none;font-weight:800}',
    '.breadcrumb a:hover,.provider-link:hover{text-decoration:underline}.hero h1{margin:0 0 8px;font-size:1.62rem;font-weight:900;letter-spacing:-0.02em;color:var(--text)}.hero p{margin:0 0 18px;color:var(--text-muted);font-size:0.93rem}',
    '.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:11px;margin-bottom:20px}.kcard,.panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:15px 17px;margin-bottom:18px}',
    '.kcard{margin-bottom:0}.kcard-lbl{font-size:0.76rem;font-weight:800;color:var(--text-muted)}.kcard-val{font-size:1.34rem;font-weight:900;margin:4px 0 2px;color:var(--text)}',
    '.calc-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:12px 0 14px}.ctrl-input{width:100%;padding:8px 11px;border-radius:8px;border:1px solid var(--border);background:var(--surface-alt);color:var(--text);font-size:0.86rem;font-weight:700}',
    '.calc-results,.cross-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;padding-top:12px;border-top:1px solid var(--border)}.cross-grid{border-top:none;padding-top:8px}',
    '.res-box{padding:12px 14px;border-radius:10px;background:var(--surface-alt);border:1px solid var(--border)}.pill-btn{padding:5px 11px;border-radius:999px;border:1px solid var(--border);background:var(--surface-alt);color:var(--text);font-size:0.76rem;font-weight:700;cursor:pointer}',
    '.table-wrap{width:100%;overflow-x:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface);margin-bottom:20px}table{width:100%;border-collapse:collapse;min-width:820px}',
    'th,td{padding:10px 13px;text-align:left;border-bottom:1px solid var(--border);font-size:0.84rem;color:var(--text)}th{background:var(--surface-alt);font-size:0.76rem;font-weight:800}tr:hover td{background:var(--row-hover)}tr.row-hidden{display:none}',
    '.badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:0.71rem;font-weight:800}.b-open{background:#064e3b;color:#a7f3d0;border:1px solid #10b981}html.light-theme .b-open,body.light-theme .b-open{background:#d1fae5;color:#065f46;border:1px solid #10b981}',
    '.b-prop{background:#312e81;color:#e0e7ff;border:1px solid #6366f1}html.light-theme .b-prop,body.light-theme .b-prop{background:#ede9fe;color:#5b21b6;border:1px solid #8b5cf6}',
    '.b-tier{background:#1e293b;color:#e2e8f0;border:1px solid #64748b}html.light-theme .b-tier,body.light-theme .b-tier{background:#f1f5f9;color:#0f172a;border:1px solid #94a3b8}',
    '.b-save,html.light-theme .b-save,body.light-theme .b-save{background:#d9f99d;color:#1a2e05;border:1px solid #65a30d}.footer{margin-top:26px;font-size:0.78rem;color:var(--text-muted);text-align:center;padding-top:16px;border-top:1px solid var(--border)}',
])


def _render_subpage_html(page: dict[str, object], rows: list[dict[str, object]], all_pages: list[dict[str, object]],
                         hist: dict[str, object], total_offers: int, iso_str: str) -> str:
    slug = str(page["slug"])
    canon = f"{SITE_URL}{slug}/"
    low, med, high = rows[0], rows[len(rows) // 2], rows[-1]
    provs = len({str(r.get("provider_id")) for r in rows})
    desc = f"{page['lead']} Compare {len(rows)} live endpoints across {provs} providers starting at {_fmt_rate(low['blended_per_1m_usd'])}/1M blended, backed by {hist['days']} daily historical snapshots."
    in_m, out_m = 500.0, 150.0
    low_mo = in_m * float(low["input_per_1m_usd"]) + out_m * float(low["output_per_1m_usd"])
    med_mo = in_m * float(med["input_per_1m_usd"]) + out_m * float(med["output_per_1m_usd"])
    high_mo = in_m * float(high["input_per_1m_usd"]) + out_m * float(high["output_per_1m_usd"])
    save_pct = max(0, round((1.0 - (low_mo / high_mo)) * 100)) if high_mo > 0 else 0
    ldjson = _build_subpage_ldjson(page, rows, hist, iso_str)
    other_links = [f'<a class="res-box provider-link" href="/"><div class="fw-900">← Full LLM Cost Index</div><div class="fs-xs text-muted">All {total_offers} live endpoints &amp; 25 providers</div></a>'] + [
        f'<a class="res-box provider-link" href="/{_esc(p["slug"])}/"><div class="fw-900">{_esc(p["nav_label"])} →</div><div class="fs-xs text-muted">{_esc(p["target_query"])}</div></a>'
        for p in all_pages if p["slug"] != slug
    ]
    calc_cfg = json.dumps({
        "low": {"in": float(low["input_per_1m_usd"]), "out": float(low["output_per_1m_usd"])},
        "med": {"in": float(med["input_per_1m_usd"]), "out": float(med["output_per_1m_usd"])},
        "high": {"in": float(high["input_per_1m_usd"]), "out": float(high["output_per_1m_usd"])},
    })
    return f"""<!DOCTYPE html>
<html lang="en" class="light-theme">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_esc(page["title"])}</title>
  <meta name="description" content="{_esc(desc)}" />
  <link rel="canonical" href="{_esc(canon)}" />
  <script async src="https://www.googletagmanager.com/gtag/js?id={GA4_ID}"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag('js', new Date());
    gtag('config', '{GA4_ID}', {{ anonymize_ip: true }});
    document.addEventListener('click', function(e) {{
      var a = e.target && e.target.closest ? e.target.closest('a[href^="http"]') : null;
      if (a && a.hostname && a.hostname.indexOf('llmcostcomparison.com') === -1) {{
        gtag('event', 'provider_outbound_click', {{ provider_domain: a.hostname, link_url: a.href }});
      }}
    }});
  </script>
  <meta property="og:title" content="{_esc(page["title"])}" />
  <meta property="og:description" content="{_esc(desc)}" />
  <meta property="og:url" content="{_esc(canon)}" />
  <meta property="og:type" content="website" />
  <meta name="twitter:card" content="summary" />
  <script id="seo-ldjson" type="application/ld+json">
{ldjson}
  </script>
  <style>{SUBPAGE_CSS}</style>
</head>
<body class="light-theme">
  <header class="topbar">
    <div class="brand"><a class="brand-link" href="/">🧮 LLMCostComparison<span class="text-accent">.com</span></a><span id="hist-pill-badge" class="lime-badge">NEW · {hist["days"]}-DAY SNAPSHOT ARCHIVE ({_esc(hist["latest_date"])})</span></div>
    <div class="top-actions"><a class="btn" href="/">← All {total_offers} Models</a><button id="theme-btn" class="btn" onclick="toggleTheme()">🌙 Dark Mode</button></div>
  </header>
  <main class="container">
    <nav class="breadcrumb" aria-label="Breadcrumb"><a href="/">Home</a><span>→</span><span>{_esc(page["h1"])}</span></nav>
    <section class="hero"><h1>{_esc(page["h1"])}</h1><p>{_esc(page["lead"])}</p></section>
    <section class="kpi-grid">
      <div class="kcard"><div class="kcard-lbl">Matching Live Endpoints</div><div class="kcard-val">{len(rows)} Models</div><div class="fs-xs text-muted">Across {provs} verified API providers</div></div>
      <div class="kcard"><div class="kcard-lbl">Lowest 3:1 Blended Rate</div><div class="kcard-val">{_fmt_rate(low["blended_per_1m_usd"])} / 1M</div><div class="fs-xs text-muted">{_esc(low["provider_name"])} · {_esc(low["model_name"])}</div></div>
      <div class="kcard"><div class="kcard-lbl">Benchmark Median Rate</div><div class="kcard-val">{_fmt_rate(med["blended_per_1m_usd"])} / 1M</div><div class="fs-xs text-muted">{_esc(med["provider_name"])} · {_esc(med["model_name"])}</div></div>
      <div class="kcard"><div class="kcard-lbl">Multi-Day History Moat</div><div class="kcard-val">{hist["days"]} Daily Snapshots</div><div class="fs-xs text-muted">{_esc(hist["first_date"])} → {_esc(hist["latest_date"])} · {hist["latest_scanned"]:,} catalog entries</div></div>
    </section>
    <section class="panel">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
        <div><strong class="fw-900">💰 Monthly Token Bill Mini-Calculator ({_esc(page["nav_label"])})</strong><div class="fs-xs text-muted">Compare Cheapest vs Median vs Frontier/Upper-Tier monthly spend on this page</div></div>
        <div class="pill-row"><button class="pill-btn" onclick="setMonthly(100,25)">Startup (100M/25M)</button><button class="pill-btn" onclick="setMonthly(500,150)">Scale (500M/150M)</button><button class="pill-btn" onclick="setMonthly(2000,500)">Enterprise (2B/500M)</button></div>
      </div>
      <div class="calc-controls">
        <div><label for="m-in" class="fs-xs fw-800 text-muted">Monthly Input M tokens</label><input id="m-in" class="ctrl-input" type="number" min="1" step="10" value="500" oninput="recalcSub()" /></div>
        <div><label for="m-out" class="fs-xs fw-800 text-muted">Monthly Output M tokens</label><input id="m-out" class="ctrl-input" type="number" min="1" step="10" value="150" oninput="recalcSub()" /></div>
        <div><label for="row-flt" class="fs-xs fw-800 text-muted">Filter {len(rows)} Endpoints Below</label><input id="row-flt" class="ctrl-input" type="text" placeholder="Filter provider, model, FP8, tier..." oninput="filterSubRows()" /></div>
      </div>
      <div class="calc-results">
        <div class="res-box"><div class="kcard-lbl">Cheapest on Page <span id="save-badge" class="badge b-save">Save {save_pct}%</span></div><div id="bill-low" class="kcard-val">{_fmt_usd(low_mo)}/mo</div><div class="fs-xs text-muted">{_esc(low["provider_name"])} · {_esc(low["model_name"])} ({_fmt_rate(low["input_per_1m_usd"])}/{_fmt_rate(low["output_per_1m_usd"])})</div></div>
        <div class="res-box"><div class="kcard-lbl">Median on Page</div><div id="bill-med" class="kcard-val">{_fmt_usd(med_mo)}/mo</div><div class="fs-xs text-muted">{_esc(med["provider_name"])} · {_esc(med["model_name"])} ({_fmt_rate(med["input_per_1m_usd"])}/{_fmt_rate(med["output_per_1m_usd"])})</div></div>
        <div class="res-box"><div class="kcard-lbl">Frontier / Upper Tier on Page</div><div id="bill-high" class="kcard-val">{_fmt_usd(high_mo)}/mo</div><div class="fs-xs text-muted">{_esc(high["provider_name"])} · {_esc(high["model_name"])} ({_fmt_rate(high["input_per_1m_usd"])}/{_fmt_rate(high["output_per_1m_usd"])})</div></div>
      </div>
    </section>
    <div class="table-wrap"><table><thead><tr><th>Provider &amp; Category</th><th>Model &amp; Family</th><th>Tier &amp; License</th><th>Context</th><th>Input $/1M</th><th>Output $/1M</th><th>Blended $/1M (3:1)</th></tr></thead><tbody id="sub-tbody">
          {_render_table_rows(rows)}
    </tbody></table></div>
    <section class="panel">
      <h2 style="margin-top:0;font-size:1.08rem;">Precision, Quantization, Multi-Day Price Trends &amp; ZDR FAQ</h2>
      <p class="fs-sm"><strong>1. What is the lowest $/1M rate for {_esc(page["nav_label"])}?</strong><br/>{_esc(low["provider_name"])} serves <code>{_esc(low["model_name"])}</code> at <strong>{_fmt_rate(low["blended_per_1m_usd"])}/1M blended</strong> ({_fmt_rate(low["input_per_1m_usd"])} input / {_fmt_rate(low["output_per_1m_usd"])} output), versus median {_fmt_rate(med["blended_per_1m_usd"])}/1M and upper-tier {_fmt_rate(high["blended_per_1m_usd"])}/1M across {len(rows)} live endpoints.</p>
      <p class="fs-sm"><strong>2. How have token prices moved across archived daily snapshots?</strong><br/>Across <strong>{hist["days"]} archived daily snapshots</strong> ({_esc(hist["first_date"])} → {_esc(hist["latest_date"])}), audited catalog coverage grew from {hist["first_scanned"]:,} to {hist["latest_scanned"]:,} models; Frontier Reasoning open-weight cloud floors tracked {_fmt_rate(hist["fr_first"])}/1M → {_fmt_rate(hist["fr_last"])}/1M (vs {_fmt_rate(hist["fr_prop"])}/1M proprietary baseline) and Fast 70B–8B cloud floors tracked {_fmt_rate(hist["fa_first"])}/1M → {_fmt_rate(hist["fa_last"])}/1M.</p>
      <p class="fs-sm" style="margin-bottom:0;"><strong>3. Precision, Quantization &amp; Zero-Data-Retention (ZDR) Checklist:</strong><br/>{_esc(page["quantization_note"])}</p>
    </section>
    <section class="panel"><strong class="fw-900">🔗 Explore Related LLM API Token Cost Benchmarks</strong><div class="cross-grid">{"".join(other_links)}</div></section>
    <footer class="footer">Independent open-data LLM API cost index (<a class="provider-link" href="/">LLMCostComparison.com</a>). Public pay-as-you-go $/1M token rates synced every 6 hours with daily history in <code>/history/YYYY-MM-DD.json</code>.</footer>
  </main>
  <script>
    const RATES = {calc_cfg};
    function fmtUsd(v) {{ return v >= 1000 ? "$" + Math.round(v).toLocaleString("en-US") : "$" + v.toLocaleString("en-US", {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
    function applyTheme() {{ const d = (localStorage.getItem("llm_cost_theme") || "light") === "dark"; document.documentElement.classList.toggle("light-theme", !d); document.body.classList.toggle("light-theme", !d); const b = document.getElementById("theme-btn"); if (b) b.textContent = d ? "☀️ Light Mode" : "🌙 Dark Mode"; }}
    function toggleTheme() {{ localStorage.setItem("llm_cost_theme", document.documentElement.classList.contains("light-theme") ? "dark" : "light"); applyTheme(); }}
    function setMonthly(i, o) {{ document.getElementById("m-in").value = String(i); document.getElementById("m-out").value = String(o); recalcSub(); }}
    function recalcSub() {{ const i = Math.max(0, parseFloat(document.getElementById("m-in").value || "0")), o = Math.max(0, parseFloat(document.getElementById("m-out").value || "0")); const lo = i * RATES.low.in + o * RATES.low.out, me = i * RATES.med.in + o * RATES.med.out, hi = i * RATES.high.in + o * RATES.high.out; document.getElementById("bill-low").textContent = fmtUsd(lo) + "/mo"; document.getElementById("bill-med").textContent = fmtUsd(me) + "/mo"; document.getElementById("bill-high").textContent = fmtUsd(hi) + "/mo"; document.getElementById("save-badge").textContent = "Save " + (hi > 0 ? Math.max(0, Math.round((1 - lo / hi) * 100)) : 0) + "%"; }}
    function filterSubRows() {{ const q = (document.getElementById("row-flt").value || "").trim().toLowerCase(); document.querySelectorAll("#sub-tbody tr").forEach(tr => tr.classList.toggle("row-hidden", !!q && !(tr.getAttribute("data-hay") || "").includes(q))); }}
    applyTheme();
  </script>
</body>
</html>
"""


def _inject_homepage_hub(cards: list[dict[str, object]], hist: dict[str, object]) -> None:
    doc = INDEX_PATH.read_text(encoding="utf-8")
    orig_title = re.search(r"<title>.*?</title>", doc, flags=re.DOTALL)
    orig_h1 = re.search(r"<h1[^>]*>.*?</h1>", doc, flags=re.DOTALL)
    items = "".join(
        f'<div class="cquote"><div class="cquote-top"><a class="cquote-name" href="/{_esc(c["slug"])}/">{_esc(c["nav_label"])} →</a>'
        f'<span class="badge b-save">{c["count"]} models</span></div><div class="cquote-cost">From {_fmt_rate(c["low_rate"])}<span class="fs-xs text-muted">/1M</span></div>'
        f'<div class="cquote-model">{_esc(c["low_label"])}</div></div>'
        for c in cards
    )
    hub = (
        '<!-- SEO_HUB_START -->\n    <section class="calc-panel" aria-label="Historical Price Trends and Model Benchmarks">\n'
        '      <div class="calc-header" style="margin-bottom:10px;"><div>\n'
        '        <strong class="fw-900">📈 Multi-Day Historical Token Price Moat &amp; Model-Specific Benchmarks</strong>\n'
        f'        <div class="fs-xs text-muted">Verified across <strong>{hist["days"]} daily snapshots</strong> ({_esc(hist["first_date"])} → {_esc(hist["latest_date"])}) · '
        f'Audited catalog grew {hist["first_scanned"]:,} → {hist["latest_scanned"]:,} models · Frontier cloud floor {_fmt_rate(hist["fr_first"])} → {_fmt_rate(hist["fr_last"])}/1M '
        f'(vs {_fmt_rate(hist["fr_prop"])}/1M Prop) · Fast 70B–8B floor {_fmt_rate(hist["fa_first"])} → {_fmt_rate(hist["fa_last"])}/1M</div></div>\n'
        f'        <span id="hub-history-badge" class="lime-badge">{hist["days"]}-DAY ARCHIVE LIVE</span></div>\n'
        f'      <div class="cloud-quote-grid" style="border-top:none;padding-top:4px;">{items}</div>\n    </section>\n    <!-- SEO_HUB_END -->'
    )
    if "<!-- SEO_HUB_START -->" in doc and "<!-- SEO_HUB_END -->" in doc:
        updated = re.sub(r"<!-- SEO_HUB_START -->.*?<!-- SEO_HUB_END -->", lambda _: hub, doc, count=1, flags=re.DOTALL)
    else:
        updated = re.sub(r'(\s*<section class="calc-panel">)', lambda m: f"\n    {hub}{m.group(1)}", doc, count=1)
    assert orig_title and orig_title.group(0) in updated, "Homepage <title> freeze violated!"
    assert orig_h1 and orig_h1.group(0) in updated, "Homepage <h1> freeze violated!"
    INDEX_PATH.write_text(updated, encoding="utf-8")


def build_all() -> dict[str, object]:
    costs = json.loads(COSTS_PATH.read_text(encoding="utf-8"))
    cfg = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    pages = list(cfg.get("pages") or [])[: int(cfg.get("max_total_pages") or 15)]
    models = list(costs.get("models") or [])
    total_offers = int((costs.get("summary") or {}).get("curated_offers") or len(models))
    hist = _load_history_metrics()
    now_dt = datetime.now(timezone.utc)
    day_str, iso_str = now_dt.strftime("%Y-%m-%d"), now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    cards: list[dict[str, object]] = []
    urls = [(SITE_URL, "1.0")]
    for p in pages:
        rows = _match_models(models, p)
        if not rows:
            raise ValueError(f"Zero matching models for subpage {p.get('slug')}")
        out_dir = PUBLIC_DIR / str(p["slug"])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(_render_subpage_html(p, rows, pages, hist, total_offers, iso_str), encoding="utf-8")
        low = rows[0]
        cards.append({"slug": p["slug"], "nav_label": p["nav_label"], "count": len(rows),
                      "low_rate": float(low["blended_per_1m_usd"]), "low_label": f"{low['provider_name']} · {low['model_name']}"})
        urls.append((f"{SITE_URL}{p['slug']}/", "0.85"))

    _inject_homepage_hub(cards, hist)
    url_xml = "\n".join(f"  <url>\n    <loc>{u}</loc>\n    <lastmod>{day_str}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>{pr}</priority>\n  </url>" for u, pr in urls)
    SITEMAP_PATH.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{url_xml}\n</urlset>\n', encoding="utf-8")
    return {"pages_built": len(cards), "history_days": hist["days"], "sitemap_urls": len(urls), "subpages": cards}


if __name__ == "__main__":
    print(json.dumps(build_all()))
