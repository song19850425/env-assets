from __future__ import annotations

import hashlib
import json
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
STANDARDS_DIR = DATA_DIR / "standards"
CATALOG_PATH = DATA_DIR / "catalog.json"
OUTPUT = ROOT / "index.html"


def compact_standard(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "id": data.get("standardId"),
        "file": path.name,
        "name": data.get("name", ""),
        "issuer": data.get("issuer", ""),
        "effectiveDate": data.get("effectiveDate", ""),
        "units": data.get("units", ""),
        "source": data.get("source", {}),
        "coverage": data.get("coverage", {}),
        "columns": data.get("columns", {}),
        "landUseTypes": data.get("landUseTypes", {}),
        "limits": data.get("limits", []),
        "values": data.get("values", {}),
        "methods": data.get("methods", []),
        "qualitative": data.get("qualitative", []),
    }


def validate_catalog(standards: list[dict], catalog: dict) -> None:
    ids_list = [s.get("id") for s in standards]
    if any(not x for x in ids_list) or len(ids_list) != len(set(ids_list)):
        raise ValueError("标准 ID 为空或重复")
    ids = set(ids_list)
    for standard in standards:
        url = (standard.get("source") or {}).get("url", "")
        if url and not url.startswith("https://"):
            raise ValueError(f"标准来源不是 HTTPS: {standard.get('id')} -> {url}")
    history_ids = set((catalog.get("historicalNames") or {}).keys())
    for relation in catalog.get("relations", []):
        if relation.get("from") not in ids:
            raise ValueError(f"关系 from 不在标准数据中: {relation.get('from')}")
        if relation.get("to") not in ids and relation.get("to") not in history_ids:
            raise ValueError(f"关系 to 未登记为现行或历史标准: {relation.get('to')}")
    for section in ("methods", "sampling"):
        item_ids = [x.get("id") for x in catalog.get(section, [])]
        if any(not x for x in item_ids) or len(item_ids) != len(set(item_ids)):
            raise ValueError(f"{section} ID 为空或重复")
        for item in catalog.get(section, []):
            missing = [x for x in item.get("standardIds", []) if x not in ids]
            if missing:
                raise ValueError(f"{section} {item.get('id')} 引用了不存在的标准: {missing}")
    asset_ids_list = [a.get("id") for a in catalog.get("assets", [])]
    if any(not x for x in asset_ids_list) or len(asset_ids_list) != len(set(asset_ids_list)):
        raise ValueError("资产 ID 为空或重复")
    asset_ids = set(asset_ids_list)
    for asset in catalog.get("assets", []):
        if asset.get("path") and not (ROOT.parent / asset["path"]).exists():
            raise ValueError(f"资产路径不存在: {asset.get('path')}")
    for item in catalog.get("sampling", []):
        for path in item.get("links", []):
            if not (ROOT.parent / path).exists():
                raise ValueError(f"采样卡片路径不存在: {path}")
    for chain in catalog.get("chains", []):
        for step in chain.get("steps", []):
            missing_refs = [x for x in step.get("ref", "").split("|") if x and x not in ids]
            if missing_refs:
                raise ValueError(f"链路 {chain.get('id')} 引用了不存在的标准: {missing_refs}")
            if step.get("asset") and step["asset"] not in asset_ids:
                raise ValueError(f"链路 {chain.get('id')} 引用了不存在的资产: {step.get('asset')}")


def build_data() -> tuple[dict, str]:
    standard_files = sorted(
        p for p in STANDARDS_DIR.glob("*.json")
        if p.name not in {"index.json", "pollutant-ids.json"}
    )
    standards = [compact_standard(p) for p in standard_files]
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    validate_catalog(standards, catalog)

    digest = hashlib.sha256()
    for path in [*standard_files, CATALOG_PATH]:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())

    payload = {
        "catalog": catalog,
        "standards": standards,
        "meta": {
            "standardCount": len(standards),
            "sourceFiles": len(standard_files),
            "dataSha256": digest.hexdigest(),
        },
    }
    return payload, digest.hexdigest()


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="EnvStandard 环境标准库：标准、修改单、废止与替代关系、适用范围、检测因子、方法、采样要求，以及标准到实验资产的可追溯链路。">
<meta name="envstandard-data-sha256" content="__DATA_SHA__">
<title>EnvStandard · 环境标准库</title>
<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">
<style>
*{box-sizing:border-box}
:root{color-scheme:dark}
body{margin:0;background:#08111f;color:#e7eef9;font-family:"Noto Sans SC","Microsoft YaHei",-apple-system,sans-serif;line-height:1.65}
a{color:#8bd5ff;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1440px;margin:0 auto;padding:32px 22px 70px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;flex-wrap:wrap}
.eyebrow{font-size:12px;letter-spacing:.14em;color:#69c5f0;text-transform:uppercase;font-weight:700}
h1{font-size:32px;line-height:1.25;margin:5px 0 8px;letter-spacing:.01em}
.lede{max-width:850px;color:#9fb4cf;font-size:15px;margin:0}
.actions{display:flex;gap:8px;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:6px;border:1px solid #294664;border-radius:9px;padding:7px 12px;color:#b6d8f4;background:#0e1d31;font-size:12px;cursor:pointer;font-family:inherit}
.btn:hover,.btn.on{border-color:#55b8ea;color:#e4f6ff;background:#12304b;text-decoration:none}
.hero-note{margin:24px 0 18px;border:1px solid #24415e;background:linear-gradient(115deg,#0e2137,#0b182b);border-radius:14px;padding:16px 18px;color:#aec3dc;font-size:13px}
.hero-note strong{color:#e7f5ff}.hero-note .chain{display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:10px;color:#d5eaff;font-weight:700}.hero-note .chain span{border:1px solid #2b5979;border-radius:999px;padding:3px 9px;background:#102b43}.hero-note .chain i{font-style:normal;color:#5c9ec2}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:18px 0}.stat{border:1px solid #1b3550;background:#0d1b2d;border-radius:11px;padding:12px 14px}.stat-n{font-size:24px;font-weight:800;color:#e5f6ff}.stat-l{font-size:11.5px;color:#7893b1;margin-top:2px}
.toolbar{position:sticky;top:0;z-index:20;background:rgba(8,17,31,.94);backdrop-filter:blur(12px);border-bottom:1px solid #142a43;padding:12px 0 10px;margin:0 0 16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}.search{flex:1 1 270px;position:relative}.search input{width:100%;background:#0d1b2d;border:1px solid #294664;border-radius:9px;padding:10px 13px;color:#e7eef9;font:inherit;font-size:13px;outline:none}.search input:focus{border-color:#59b8e7;box-shadow:0 0 0 3px rgba(89,184,231,.13)}.search input::placeholder{color:#607d9d}.view-tabs{display:flex;gap:5px;flex-wrap:wrap}.tab{border:1px solid #213d5b;background:#0d1b2d;color:#91a9c4;border-radius:8px;padding:7px 10px;font:inherit;font-size:12px;cursor:pointer}.tab:hover,.tab.on{color:#e5f6ff;border-color:#4aa8d8;background:#12304b}
.layout{display:grid;grid-template-columns:330px minmax(0,1fr);gap:16px;align-items:start}.panel{background:#0d1b2d;border:1px solid #1c3650;border-radius:13px}.side{position:sticky;top:68px;max-height:calc(100vh - 90px);overflow:auto}.side-head{padding:14px 15px;border-bottom:1px solid #1b3550;display:flex;justify-content:space-between;gap:8px;align-items:center}.side-head h2{font-size:14px;margin:0}.side-head small{color:#7189a5;font-size:11px}.std-list{padding:8px}.std-card{display:block;width:100%;text-align:left;border:1px solid transparent;background:transparent;border-radius:9px;color:#dbe8f5;padding:10px 10px;margin:2px 0;cursor:pointer;font-family:inherit}.std-card:hover{background:#10263d;border-color:#254c6a}.std-card.on{background:#12304b;border-color:#4aa8d8}.std-code{font-size:12px;font-weight:800;color:#83d8ff}.std-name{font-size:12.5px;margin-top:2px;line-height:1.45}.std-meta{font-size:10.5px;color:#7490ae;margin-top:3px;display:flex;gap:7px;flex-wrap:wrap}.empty{color:#6983a2;font-size:12px;padding:22px 12px;text-align:center}
.content{min-width:0}.overview{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:15px}.overview-card{border:1px solid #1d3b57;background:#0d1b2d;border-radius:12px;padding:14px}.overview-card h3{font-size:13px;margin:0 0 7px;color:#dcedfb}.overview-card p{font-size:12px;color:#8fa7c1;margin:0}.overview-card .tagline{font-size:11px;color:#5fc4ee;font-weight:700;margin-bottom:3px}
.detail{border:1px solid #1d3b57;background:#0d1b2d;border-radius:13px;padding:18px}.detail-head{display:flex;justify-content:space-between;gap:15px;flex-wrap:wrap;border-bottom:1px solid #1a3450;padding-bottom:14px;margin-bottom:15px}.detail-code{font-size:12px;color:#68c7ee;font-weight:800;letter-spacing:.04em}.detail h2{font-size:22px;line-height:1.35;margin:4px 0 7px}.detail-sub{font-size:12px;color:#90a9c3}.badges{display:flex;gap:6px;flex-wrap:wrap;align-items:flex-start}.badge{display:inline-block;border-radius:999px;border:1px solid #2d5873;color:#8ed9fa;background:#0c2a40;padding:3px 9px;font-size:11px;white-space:nowrap}.badge.warn{border-color:#7a5a28;color:#ffd37e;background:#33240d}.badge.gray{border-color:#3b4c62;color:#9aacbf;background:#172334}
.meta-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:17px}.meta-box{border:1px solid #1b3550;border-radius:9px;padding:9px 10px}.meta-box .k{font-size:10.5px;color:#6f89a6}.meta-box .v{font-size:12px;color:#d7e7f6;margin-top:2px;word-break:break-word}
.section{margin:18px 0}.section h3{font-size:14px;margin:0 0 8px;color:#dcedfb;display:flex;align-items:center;gap:8px}.section h3:before{content:"";width:4px;height:16px;background:#45b8e8;border-radius:3px}.section p.note{font-size:12px;color:#849eb9;margin:0 0 8px}.source-box{border:1px dashed #315878;border-radius:9px;padding:10px 12px;background:#0a1728;font-size:12px;color:#a2b8d0}.source-box a{word-break:break-all}.source-box .source-row{margin:3px 0}.source-box b{color:#d4e8f8;font-weight:600}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.mini-card{border:1px solid #1b3a55;background:#0b182a;border-radius:10px;padding:11px 12px}.mini-card h4{font-size:12.5px;margin:0 0 4px;color:#d8edfb}.mini-card p{font-size:11.5px;color:#8da6c0;margin:3px 0}.mini-card .small{font-size:10.5px;color:#6984a3}.mini-card a{font-size:11.5px}.factor-table,.rel-table{width:100%;border-collapse:collapse;font-size:11.5px}.factor-table th,.rel-table th{text-align:left;background:#122b43;color:#9dd9f4;font-size:11px;padding:7px 8px;border-bottom:1px solid #27516d}.factor-table td,.rel-table td{padding:7px 8px;border-bottom:1px solid #18334e;vertical-align:top;color:#b5c9de}.factor-table tr:hover td,.rel-table tr:hover td{background:#10243a}.factor-table .num{color:#f1db94;font-variant-numeric:tabular-nums}.table-wrap{overflow:auto;border:1px solid #1b3a55;border-radius:9px}.muted{color:#718aa6}.small-note{font-size:11px;color:#6e88a5;margin-top:8px}.pill{display:inline-block;color:#8fd9f6;border:1px solid #2b5875;background:#0c263b;border-radius:999px;padding:2px 7px;font-size:10px;margin:2px 3px 2px 0}.pill.amber{color:#ffd47b;border-color:#745b2b;background:#33250f}.pill.green{color:#8ce0ae;border-color:#2c6649;background:#0c2c1d}
.relation-card{border:1px solid #224661;border-radius:10px;background:#0b182a;padding:12px;margin-bottom:9px}.relation-line{display:flex;gap:9px;align-items:center;flex-wrap:wrap;font-size:13px}.relation-line .arrow{color:#62c4e8;font-size:18px}.relation-line .code{font-weight:800;color:#dff3ff}.relation-card p{font-size:11.5px;color:#91a9c1;margin:7px 0}.relation-card .verified{color:#8de0ae}.relation-card .pending{color:#ffd47b}.warning{border-left:3px solid #d69b38;background:#2a210f;padding:11px 13px;border-radius:0 9px 9px 0;color:#f3d394;font-size:12px;margin-bottom:12px}.warning strong{color:#ffe4a8}.chain-card{border:1px solid #234862;background:#0b182a;border-radius:12px;padding:14px;margin-bottom:13px}.chain-head{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.chain-head h3{margin:0;font-size:15px;color:#e1f2ff}.chain-head p{font-size:11.5px;color:#88a4bd;margin:5px 0 10px;max-width:780px}.flow{display:flex;align-items:stretch;gap:6px;overflow:auto;padding-bottom:4px}.flow-step{min-width:150px;flex:1;border:1px solid #2a5570;border-radius:9px;padding:9px 10px;background:#10283e}.flow-step .type{font-size:10px;color:#61c6ee;font-weight:800;letter-spacing:.08em}.flow-step .label{display:block;font-size:12px;color:#e0edf8;margin-top:3px;line-height:1.45}.flow-step a,.flow-step button{display:inline-block;margin-top:6px;font-size:10.5px;color:#8ad8fa;background:none;border:0;padding:0;cursor:pointer;font-family:inherit;text-align:left}.flow-arrow{display:flex;align-items:center;color:#4c9ac0;font-size:18px}.chain-soil .flow-step{border-color:#735a38}.chain-water .flow-step{border-color:#2f5d74}.chain-voc .flow-step{border-color:#6a416b}.chain-air .flow-step{border-color:#5a6537}
.factor-search{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}.factor-search input{flex:1 1 250px;background:#0b182a;border:1px solid #2a4a64;border-radius:8px;color:#e7eef9;padding:8px 10px;font:inherit;font-size:12px}.factor-count{font-size:11px;color:#7892ae;padding:8px 0}.footer{margin-top:30px;border-top:1px solid #1b3550;padding-top:17px;color:#66819e;font-size:11.5px}.footer code{color:#86c7e8}
@media(max-width:1050px){.layout{grid-template-columns:280px minmax(0,1fr)}.stats{grid-template-columns:repeat(3,1fr)}.meta-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:760px){.wrap{padding:24px 13px 55px}h1{font-size:25px}.layout{grid-template-columns:1fr}.side{position:static;max-height:none}.overview{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.detail{padding:14px}.grid2{grid-template-columns:1fr}.flow{margin-right:-5px}.flow-step{min-width:136px}.meta-grid{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <div class="eyebrow">EnvStandard / 环境标准库</div>
      <h1>把标准变成可用的链路</h1>
      <p class="lede">标准、方法、采样、实验和交付资产不再各自孤立。先查清标准出处，再沿着关系链进入可操作页面。</p>
    </div>
    <div class="actions">
      <a class="btn" href="../index.html">← 返回数字资产库</a>
      <button class="btn" id="printBtn" type="button">打印当前页</button>
    </div>
  </header>

  <section class="hero-note">
    <strong>数据边界：</strong>本页读取结构化标准数据，保留标准号、来源、条款/表格出处和收录范围；「修改单」与「废止/替代关系」只显示已登记的证据，未登记不等于不存在。标准引用前请打开官方来源核对。
    <div class="chain" aria-label="标准链路">
      <span>标准</span><i>→</i><span>方法</span><i>→</i><span>实验</span><i>→</i><span>仪器</span><i>→</i><span>SOP</span><i>→</i><span>报告</span>
    </div>
  </section>

  <section class="stats" id="stats"></section>

  <div class="toolbar">
    <div class="search"><input id="q" type="search" placeholder="搜索标准号、名称、检测因子、方法或仪器…" autocomplete="off"></div>
    <div class="view-tabs" id="tabs">
      <button class="tab on" data-view="all" type="button">总览</button>
      <button class="tab" data-view="standards" type="button">标准</button>
      <button class="tab" data-view="relations" type="button">修改单 / 关系</button>
      <button class="tab" data-view="factors" type="button">检测因子</button>
      <button class="tab" data-view="chains" type="button">六段链路</button>
    </div>
  </div>

  <main class="layout">
    <aside class="panel side">
      <div class="side-head"><h2>标准索引</h2><small id="listCount"></small></div>
      <div class="std-list" id="stdList"></div>
    </aside>
    <section class="content">
      <div id="overview"></div>
      <div id="detail"></div>
    </section>
  </main>

  <footer class="footer">
    EnvStandard · 结构化数据指纹 <code id="sha"></code><br>
    数据源文件：<code>EnvStandard/data/standards/*.json</code>；生成器：<code>EnvStandard/build_envstandard.py</code>。页面不构成法定检测报告，标准现行性和适用性以官方发布版本为准。
  </footer>
</div>

<script>
const DATA = __DATA_JSON__;
const STANDARDS = DATA.standards || [];
const CATALOG = DATA.catalog || {};
const byId = Object.fromEntries(STANDARDS.map(s => [s.id, s]));
const assetById = Object.fromEntries((CATALOG.assets || []).map(a => [a.id, a]));
const state = { view: 'all', selected: STANDARDS[0] ? STANDARDS[0].id : '', query: '' };
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = (id) => String(id || '').replace(/^GBT(?=\d)/, 'GB/T ').replace(/^HJT(?=\d)/, 'HJ/T ').replace(/^(GB|HJ)(?=\d)/, '$1 ');
const internalHref = (p) => p ? '../' + p.split('/').map(encodeURIComponent).join('/').replace(/%2F/g, '/') : '';
const standardName = (id) => byId[id] ? byId[id].name : ((CATALOG.historicalNames || {})[id] || pretty(id));
const linkForAsset = (id, label) => {
  const a = assetById[id];
  if (!a) return esc(label || id);
  return a.path ? `<a href="${internalHref(a.path)}" target="_blank" rel="noopener">${esc(label || a.name)} ↗</a>` : esc(label || a.name);
};
const linksForPaths = (paths) => (paths || []).map(p => `<a href="${internalHref(p)}" target="_blank" rel="noopener">${esc(p.split('/').pop())} ↗</a>`).join('、');
const dateLabel = (v) => v || '未填';
const factorRows = (s) => {
  const rows = [];
  (s.limits || []).forEach(x => rows.push({ type: '限值因子', name: x.name, group: x.group || '', seq: x.seq, values: x }));
  Object.entries(s.values || {}).forEach(([key, x]) => rows.push({ type: '规定参数', name: x.name || key, group: key, seq: '', values: { value: x.value, units: x.units, citation: x.citation } }));
  return rows;
};
const allFactorRows = () => STANDARDS.flatMap(s => factorRows(s).map(r => ({...r, standard: s})));

function renderStats() {
  const limitCount = STANDARDS.reduce((n, s) => n + (s.limits || []).length, 0);
  const valueCount = STANDARDS.reduce((n, s) => n + Object.keys(s.values || {}).length, 0);
  const qualCount = STANDARDS.reduce((n, s) => n + (s.qualitative || []).length, 0);
  const methodCount = (CATALOG.methods || []).length + STANDARDS.reduce((n, s) => n + (s.methods || []).length, 0);
  $('#stats').innerHTML = [
    [''+STANDARDS.length, '已结构化标准'],
    [''+limitCount, '表格式检测因子'],
    [''+valueCount, '规定参数'],
    [''+methodCount, '方法索引'],
    [''+(CATALOG.chains || []).length, '可追踪六段链路']
  ].map(x => `<div class="stat"><div class="stat-n">${x[0]}</div><div class="stat-l">${x[1]}</div></div>`).join('');
  $('#sha').textContent = DATA.meta.dataSha256;
}

function matches(s, q) {
  if (!q) return true;
  const hay = [s.id, pretty(s.id), s.name, s.issuer, s.units, CATALOG.scopes && CATALOG.scopes[s.id]];
  factorRows(s).forEach(r => hay.push(r.name, r.group, r.values && r.values.citation));
  (s.methods || []).forEach(m => hay.push(m.indicator, m.method, m.standard));
  return hay.join(' ').toLowerCase().includes(q.toLowerCase());
}

function renderList() {
  const q = state.query.trim();
  const list = STANDARDS.filter(s => matches(s, q));
  $('#listCount').textContent = `${list.length} / ${STANDARDS.length}`;
  if (!list.length) { $('#stdList').innerHTML = '<div class="empty">没有匹配的标准或因子</div>'; return; }
  $('#stdList').innerHTML = list.map(s => {
    const rows = factorRows(s);
    return `<button class="std-card ${state.selected === s.id ? 'on' : ''}" data-id="${esc(s.id)}" type="button">
      <div class="std-code">${esc(pretty(s.id))}</div>
      <div class="std-name">${esc(s.name)}</div>
      <div class="std-meta"><span>${rows.length} 项数据</span><span>${esc(dateLabel(s.effectiveDate))} 实施</span></div>
    </button>`;
  }).join('');
  $$('.std-card').forEach(b => b.addEventListener('click', () => { state.selected = b.dataset.id; state.view = 'standards'; syncTabs(); render(); }));
}

function syncTabs() { $$('.tab').forEach(b => b.classList.toggle('on', b.dataset.view === state.view)); }
function renderOverview() {
  if (state.view !== 'all') { $('#overview').innerHTML = ''; return; }
  $('#overview').innerHTML = `<div class="overview">
    <div class="overview-card"><div class="tagline">01 / 标准</div><h3>查清来源，再看数值</h3><p>每个标准保留官方来源、发布单位、实施日期、表/条款范围与结构化数据量。</p></div>
    <div class="overview-card"><div class="tagline">02 / 关系</div><h3>替代、废止、修改单</h3><p>只展示已登记的关系证据；未接入的修改单明确标为“尚未结构化”，不把未知当成没有。</p></div>
    <div class="overview-card"><div class="tagline">03 / 链路</div><h3>从标准走到工作结果</h3><p>沿六段链路进入现有实验、仪器培训、SOP 和报告出口；没有对应资产的地方显式显示待接入。</p></div>
  </div>`;
}

function sourceBox(s) {
  const src = s.source || {};
  return `<div class="source-box">
    <div class="source-row"><b>官方来源：</b>${src.url ? `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.url)} ↗</a>` : '<span class="muted">未填</span>'}</div>
    <div class="source-row"><b>发布 / 表条款：</b>${esc(src.table || '未填')}</div>
    <div class="source-row"><b>数据复核日期：</b>${esc(src.retrievedAt || '未填')}　<b>发布单位：</b>${esc(s.issuer || '未填')}</div>
    ${s.coverage && (s.coverage.included || s.coverage.excluded) ? `<div class="source-row"><b>收录范围：</b>${esc(s.coverage.included || '')}${s.coverage.excluded ? `；未收录：${esc(s.coverage.excluded)}` : ''}</div>` : ''}
  </div>`;
}

function renderFactorTable(s, max = 24) {
  const rows = factorRows(s);
  const cols = Object.keys(s.columns || {});
  const shown = rows.slice(0, max);
  const head = ['类型','因子 / 参数','分组','序号', ...cols.slice(0, 4)].map(x => `<th>${esc(x)}</th>`).join('');
  const body = shown.map(r => {
    const vals = cols.slice(0, 4).map(k => `<td class="num">${esc(r.values && r.values[k] != null ? r.values[k] : '—')}</td>`).join('');
    const fallback = !cols.length ? `<td class="num">${esc(r.values && r.values.value != null ? r.values.value : '—')} ${esc(r.values && r.values.units || '')}</td>` : '';
    return `<tr><td><span class="pill">${esc(r.type)}</span></td><td><b>${esc(r.name)}</b></td><td>${esc(r.group || '—')}</td><td>${esc(r.seq || '—')}</td>${vals || fallback}</tr>`;
  }).join('');
  if (!rows.length) return '<div class="empty">该标准当前没有结构化因子或参数。</div>';
  return `<div class="table-wrap"><table class="factor-table"><thead><tr>${head}${!cols.length ? '<th>值</th>' : ''}</tr></thead><tbody>${body}</tbody></table></div>${rows.length > max ? `<div class="small-note">默认展示前 ${max} 项，共 ${rows.length} 项；切换到「检测因子」可检索全量。</div>` : ''}`;
}

function methodsFor(id) { return (CATALOG.methods || []).filter(x => (x.standardIds || []).includes(id)); }
function samplingFor(id) { return (CATALOG.sampling || []).filter(x => (x.standardIds || []).includes(id)); }
function relationsFor(id) { return (CATALOG.relations || []).filter(x => x.from === id || x.to === id); }
function assetsFor(id) {
  const ids = new Set();
  methodsFor(id).forEach(m => { (CATALOG.sampling || []).filter(s => (s.standardIds || []).includes(id)).forEach(x => (x.links || []).forEach(p => { const a = (CATALOG.assets || []).find(z => z.path === p); if (a) ids.add(a.id); })); });
  samplingFor(id).forEach(s => (s.links || []).forEach(p => { const a = (CATALOG.assets || []).find(z => z.path === p); if (a) ids.add(a.id); }));
  return Array.from(ids).map(x => assetById[x]).filter(Boolean);
}

function renderStandardDetail() {
  const s = byId[state.selected] || STANDARDS[0];
  if (!s) { $('#detail').innerHTML = '<div class="detail empty">暂无标准数据。</div>'; return; }
  const rows = factorRows(s), methods = methodsFor(s.id), sampling = samplingFor(s.id), relations = relationsFor(s.id), assets = assetsFor(s.id);
  const scope = (CATALOG.scopes || {})[s.id] || '适用范围尚未在导航层补充，请打开标准原文核对。';
  const methodCards = [...methods, ...(s.methods || []).slice(0, 8).map(m => ({name: `${m.indicator || ''}${m.method ? ' · ' + m.method : ''}`, kind:'标准内方法', basis: m.standard || m.params || '', status:'source-data'}))];
  $('#detail').innerHTML = `<article class="detail">
    <div class="detail-head"><div><div class="detail-code">${esc(pretty(s.id))}</div><h2>${esc(s.name)}</h2><div class="detail-sub">${esc(scope)}</div></div><div class="badges"><span class="badge">已结构化</span><span class="badge gray">${esc(s.units || '多量纲')}</span>${s.effectiveDate ? `<span class="badge gray">实施 ${esc(s.effectiveDate)}</span>` : ''}</div></div>
    <div class="meta-grid"><div class="meta-box"><div class="k">表格式检测因子</div><div class="v">${s.limits ? s.limits.length : 0} 项</div></div><div class="meta-box"><div class="k">标量规定参数</div><div class="v">${Object.keys(s.values || {}).length} 项</div></div><div class="meta-box"><div class="k">定性条款</div><div class="v">${(s.qualitative || []).length} 条</div></div><div class="meta-box"><div class="k">关系证据</div><div class="v">${relations.length} 条</div></div></div>
    <section class="section"><h3>标准与来源</h3>${sourceBox(s)}</section>
    <section class="section"><h3>检测因子与规定参数</h3>${renderFactorTable(s)}</section>
    <section class="section"><h3>方法索引</h3>${methodCards.length ? `<div class="grid2">${methodCards.map(m => `<div class="mini-card"><h4>${esc(m.name)}</h4><p>${esc(m.basis || '')}</p><span class="pill ${m.status === 'source-data' ? 'green' : ''}">${esc(m.kind || '方法')}</span></div>`).join('')}</div>` : '<p class="note">本标准数据层暂未登记方法卡片；不根据名称猜补方法标准号。</p>'}</section>
    <section class="section"><h3>采样要求</h3>${sampling.length ? `<div class="grid2">${sampling.map(x => `<div class="mini-card"><h4>${esc(x.name)}</h4><p>${esc(x.detail)}</p><p>${linksForPaths(x.links)}</p></div>`).join('')}</div>` : '<p class="note">本标准当前未登记独立采样卡片；请在标准原文中核对采样要求。</p>'}</section>
    <section class="section"><h3>对应实验 / 仪器 / SOP / 报告</h3>${assets.length ? `<div class="grid2">${assets.map(a => `<div class="mini-card"><h4>${esc(a.type)} · ${esc(a.name)}</h4><p>${(a.tags || []).map(t => `<span class="pill">${esc(t)}</span>`).join('')}</p><p>${linkForAsset(a.id, '打开资产')} ${a.note ? `<br><span class="small">${esc(a.note)}</span>` : ''}</p></div>`).join('')}</div>` : '<p class="note">暂无已登记的对应资产。链路视图会把待接入位置明确显示出来。</p>'}</section>
    ${relations.length ? `<section class="section"><h3>关联标准</h3>${relations.map(relationHtml).join('')}</section>` : ''}
    ${(s.qualitative || []).length ? `<section class="section"><h3>定性条款摘录</h3><div class="grid2">${s.qualitative.slice(0, 8).map(q => `<div class="mini-card"><h4>${esc(q.key || '条款')}</h4><p>${esc(q.text || '')}</p><div class="small">${esc(q.citation || '')}</div></div>`).join('')}</div></section>` : ''}
  </article>`;
}

function relationHtml(r) {
  const status = r.status === 'verified' ? '<span class="verified">已核证</span>' : '<span class="pending">文本证据 / 待持续复核</span>';
  return `<div class="relation-card"><div class="relation-line"><span class="code">${esc(standardName(r.from))}</span><span class="arrow">→</span><span class="code">${esc(standardName(r.to))}</span><span class="pill">${esc(r.type)}</span>${status}</div><p>${esc(r.evidence || '')}</p><a href="${esc(r.source && r.source.url || '#')}" target="_blank" rel="noopener">${esc(r.source && r.source.label || '查看证据')} ↗</a></div>`;
}

function renderRelations() {
  const rels = CATALOG.relations || [];
  const amendments = CATALOG.amendments || [];
  $('#detail').innerHTML = `<div class="detail"><div class="detail-head"><div><div class="detail-code">RELATION REGISTER</div><h2>修改单、废止与替代关系</h2><div class="detail-sub">关系不是从标准号相似度推断，而是保留证据链接和核证状态。</div></div><div class="badges"><span class="badge">${rels.length} 条关系</span><span class="badge warn">修改单待补录</span></div></div>
    ${amendments.map(a => `<div class="warning"><strong>${esc(a.title)}</strong><br>${esc(a.note)}</div>`).join('')}
    <div>${rels.map(relationHtml).join('')}</div>
    <p class="small-note">说明：关系区只登记当前数据层已经写明证据的记录；不要把这里的“尚未结构化”理解成“没有修改单”。</p>
  </div>`;
}

function renderFactors() {
  const q = state.query.trim().toLowerCase();
  const rows = allFactorRows().filter(r => !q || [r.standard.id, pretty(r.standard.id), r.standard.name, r.name, r.group, r.values && r.values.citation].join(' ').toLowerCase().includes(q));
  const shown = rows.slice(0, 160);
  $('#detail').innerHTML = `<div class="detail"><div class="detail-head"><div><div class="detail-code">FACTOR INDEX</div><h2>检测因子与规定参数</h2><div class="detail-sub">来自标准 JSON 的 limits[] 与 values{}；数值旁的引用仍回到对应标准来源。</div></div><div class="badges"><span class="badge">${rows.length} 条匹配</span></div></div>
    <div class="factor-search"><input id="factorQ" value="${esc(state.query)}" placeholder="继续筛选：苯、氨氮、浊度、采样、检出限…"><span class="factor-count">显示 ${shown.length} / ${rows.length}</span></div>
    <div class="table-wrap"><table class="factor-table"><thead><tr><th>标准</th><th>类型</th><th>检测因子 / 参数</th><th>分组</th><th>值摘要</th><th>引用</th></tr></thead><tbody>${shown.map(r => `<tr><td><button class="btn factor-jump" data-id="${esc(r.standard.id)}" type="button">${esc(pretty(r.standard.id))}</button></td><td><span class="pill">${esc(r.type)}</span></td><td><b>${esc(r.name)}</b></td><td>${esc(r.group || '—')}</td><td class="num">${esc(valueSummary(r.values, r.standard))}</td><td class="muted">${esc(r.values && r.values.citation || r.values && r.values.basis || '')}</td></tr>`).join('')}</tbody></table></div>${rows.length > shown.length ? '<div class="small-note">结果超过 160 条，请继续输入标准号、因子名或方法关键词缩小范围。</div>' : ''}
  </div>`;
  const fq = $('#factorQ'); if (fq) fq.addEventListener('input', e => { state.query = e.target.value; render(); });
  $$('.factor-jump').forEach(b => b.addEventListener('click', () => { state.selected = b.dataset.id; state.view = 'standards'; syncTabs(); render(); }));
}
function valueSummary(v, s) {
  if (!v) return '—';
  const keys = Object.keys(s.columns || {}).slice(0, 3).filter(k => v[k] != null);
  if (keys.length) return keys.map(k => `${k}: ${v[k]}`).join(' / ');
  if (v.value != null) return `${v.value} ${v.units || ''}`;
  return '—';
}

function renderChains() {
  $('#detail').innerHTML = `<div class="detail"><div class="detail-head"><div><div class="detail-code">TRACEABLE CHAINS</div><h2>标准 → 方法 → 实验 → 仪器 → SOP → 报告</h2><div class="detail-sub">先做少量可验证样板链，不把没有对应资产的地方伪装成已经完成。</div></div><div class="badges"><span class="badge">${(CATALOG.chains || []).length} 条样板链</span></div></div>
    ${(CATALOG.chains || []).map(c => `<div class="chain-card chain-${esc(c.theme || '')}"><div class="chain-head"><h3>${esc(c.title)}</h3><span class="pill">${esc(c.id)}</span></div><p>${esc(c.note || '')}</p><div class="flow">${(c.steps || []).map((step, i) => `${i ? '<div class="flow-arrow">→</div>' : ''}<div class="flow-step"><span class="type">${esc(step.type)}</span><span class="label">${esc(step.label)}</span>${step.ref ? `<button class="chain-ref" data-ref="${esc(step.ref)}" type="button">查看标准 ↗</button>` : ''}${step.asset ? `<br>${linkForAsset(step.asset, '打开资产')}` : ''}</div>`).join('')}</div></div>`).join('')}
    <p class="small-note">链路中的“报告”目前连接到实验室方案/质控出口页；正式报告生成与自动审查引擎仍是后续接入项。</p>
  </div>`;
  $$('.chain-ref').forEach(b => b.addEventListener('click', () => { const id = b.dataset.ref.split('|')[0]; if (byId[id]) { state.selected = id; state.view = 'standards'; syncTabs(); render(); } }));
}

function render() {
  renderList();
  renderOverview();
  if (state.view === 'relations') renderRelations();
  else if (state.view === 'factors') renderFactors();
  else if (state.view === 'chains') renderChains();
  else renderStandardDetail();
}

$('#q').addEventListener('input', e => { state.query = e.target.value; render(); });
$$('.tab').forEach(b => b.addEventListener('click', () => { state.view = b.dataset.view; syncTabs(); render(); }));
$('#printBtn').addEventListener('click', () => window.print());
renderStats();
render();
</script>
</body>
</html>
'''


def main() -> None:
    payload, digest = build_data()
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Prevent an embedded data string from prematurely closing the script tag.
    data_json = data_json.replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__DATA_SHA__", escape(digest)).replace("__DATA_JSON__", data_json)
    OUTPUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"[envstandard] standards={len(payload['standards'])} bytes={len(html.encode('utf-8'))} sha256={digest}")
    print(f"[envstandard] output={OUTPUT}")


if __name__ == "__main__":
    main()
