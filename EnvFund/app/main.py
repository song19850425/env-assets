#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 接口层

启动：
    uvicorn app.main:app --reload --port 8000
    # 或 python -m app.main

文档：http://localhost:8000/docs
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from app.jev.engine import JEVEngine
from app.parser.document import ParsedDocument, parse_text
from app.rag.matching import MatchOptions
from app.rag.store import PolicyStore
from app.schemas.models import (
    AnalysisResponse,
    MatchResponse,
    PolicyAnalysis,
    PolicyMatch,
)
from app.services import analyze_document, match

app = FastAPI(
    title="环保资金申报智能决策系统",
    description="政策解析 + JEV 规则终审 + 项目申报匹配",
    version="1.0.0",
)

# 进程内知识库（生产环境换持久化存储）
STORE = PolicyStore(Path(__file__).resolve().parent.parent / "data" / "policy_store.json")
ENGINE = JEVEngine()


# --------------------------------------------------------------------------
# 健康检查
# --------------------------------------------------------------------------

@app.get("/health", tags=["系统"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "policy_count": len(STORE),
        "rule_counts": {
            "force": len(ENGINE.force_rules),
            "exclude": len(ENGINE.exclude_rules),
            "weight": len(ENGINE.weight_cfg.get("rules", [])),
        },
    }


@app.get("/rules", tags=["系统"])
def list_rules() -> dict[str, Any]:
    """查看规则库，便于人工核对与维护"""
    return {
        "labels": ENGINE.label_names,
        "force_rules": [
            {"id": r["id"], "label": r["label"], "any": r.get("any", []), "note": r.get("note", "")}
            for r in ENGINE.force_rules
        ],
        "exclude_rules": [
            {"id": r["id"], "label": r["label"], "all": r.get("all", []),
             "any": r.get("any", []), "none": r.get("none", []), "note": r.get("note", "")}
            for r in ENGINE.exclude_rules
        ],
        "weight_rules": ENGINE.weight_cfg.get("rules", []),
    }


# --------------------------------------------------------------------------
# 政策解析
# --------------------------------------------------------------------------

@app.post("/analyze/text", response_model=AnalysisResponse, tags=["政策解析"])
def analyze_text(
    payload: dict[str, Any],
    store: bool = Query(False, description="解析后是否存入政策知识库"),
) -> AnalysisResponse:
    """
    解析纯文本政策指南。

    请求体：
        { "text": "指南全文", "title": "标题", "issuer": "发文单位",
          "allow_municipal": false, "use_llm": true }
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")

    try:
        analysis = analyze_document(
            parse_text(text, title=payload.get("title", ""), parser="api_text"),
            title=payload.get("title", ""),
            issuer=payload.get("issuer", ""),
            allow_municipal=bool(payload.get("allow_municipal", False)),
            use_llm=bool(payload.get("use_llm", True)),
            engine=ENGINE,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(502, f"模型调用失败：{e}") from e

    if store:
        STORE.add_from_analysis(analysis, text)
        STORE.save()

    return AnalysisResponse(data=analysis)


@app.post("/analyze/file", response_model=AnalysisResponse, tags=["政策解析"])
async def analyze_file(
    file: UploadFile = File(..., description="指南文件（.txt / .md / .pdf）"),
    title: str = Query(""),
    issuer: str = Query(""),
    store: bool = Query(False),
) -> AnalysisResponse:
    """上传文件解析政策指南"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".txt", ".md", ".pdf"):
        raise HTTPException(400, f"不支持的格式 {suffix}，仅支持 .txt / .md / .pdf")

    content = await file.read()

    if suffix == ".pdf":
        from app.parser.document import parse_pdf
        tmp = Path("/tmp") / f"upload_{file.filename}"
        tmp.write_bytes(content)
        try:
            doc = parse_pdf(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        doc = parse_text(
            content.decode("utf-8", errors="replace"),
            title=title or Path(file.filename or "").stem,
            source_file=file.filename or "",
        )

    doc.title = title or doc.title
    doc.issuer = issuer or doc.issuer

    try:
        analysis = analyze_document(doc, allow_municipal=False, engine=ENGINE)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

    if store:
        STORE.add_from_analysis(analysis, doc.full_text)
        STORE.save()

    return AnalysisResponse(data=analysis)


# --------------------------------------------------------------------------
# 政策知识库
# --------------------------------------------------------------------------

@app.get("/policies", tags=["政策库"])
def list_policies() -> dict[str, Any]:
    return {
        "count": len(STORE),
        "items": [
            {
                "doc_id": r.doc_id,
                "doc_title": r.doc_title,
                "level": r.level,
                "primary_track": r.primary_track,
                "labels": r.labels,
                "applicable_region": r.applicable_region,
            }
            for r in STORE.all()
        ],
    }


@app.get("/policies/{doc_id}", tags=["政策库"])
def get_policy(doc_id: str) -> dict[str, Any]:
    rec = STORE.get(doc_id)
    if not rec:
        raise HTTPException(404, f"政策不存在：{doc_id}")
    return {
        "doc_id": rec.doc_id,
        "doc_title": rec.doc_title,
        "level": rec.level,
        "primary_track": rec.primary_track,
        "secondary_tracks": rec.secondary_tracks,
        "support_directions": rec.support_directions,
        "key_project_types": rec.key_project_types,
        "excluded_scope": rec.excluded_scope,
        "applicant_requirements": rec.applicant_requirements,
        "funding_rules": rec.funding_rules,
        "performance_targets": rec.performance_targets,
        "applicable_region": rec.applicable_region,
    }


@app.delete("/policies/{doc_id}", tags=["政策库"])
def delete_policy(doc_id: str) -> dict[str, str]:
    if doc_id not in {r.doc_id for r in STORE.all()}:
        raise HTTPException(404, f"政策不存在：{doc_id}")
    # PolicyStore 未提供删除接口时，重建索引
    remaining = [r for r in STORE.all() if r.doc_id != doc_id]
    STORE._records = {r.doc_id: r for r in remaining}
    STORE._reindex()
    STORE.save()
    return {"deleted": doc_id}


# --------------------------------------------------------------------------
# 项目匹配
# --------------------------------------------------------------------------

@app.post("/match", response_model=MatchResponse, tags=["项目匹配"])
def match_endpoint(payload: dict[str, Any]) -> MatchResponse:
    """
    项目描述 → 政策匹配。

    请求体：
        { "project": "某县拟建设农村生活污水治理项目，总投资3200万元。",
          "top_k": 5, "min_score": 0.15 }
    """
    project = (payload.get("project") or "").strip()
    if not project:
        raise HTTPException(400, "project 不能为空")
    if not len(STORE):
        raise HTTPException(409, "政策知识库为空，请先调用 /analyze/text 并 store=true 入库")

    result = match(
        project,
        STORE,
        options=MatchOptions(
            top_k=int(payload.get("top_k", 5)),
            min_score=float(payload.get("min_score", 0.15)),
            include_unmatched=bool(payload.get("include_unmatched", True)),
        ),
    )
    return MatchResponse(data=result)


# --------------------------------------------------------------------------
# 简易管理后台
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, tags=["后台"])
def admin() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>环保资金申报智能决策系统</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:960px;margin:32px auto;padding:0 20px;color:#2C2C2A;line-height:1.6}
h1{font-size:20px;font-weight:500;margin-bottom:4px}
h2{font-size:15px;font-weight:500;margin-top:28px;border-bottom:1px solid #e5e5e5;padding-bottom:6px}
.sub{color:#5F5E5A;font-size:13px;margin-bottom:20px}
textarea{width:100%;min-height:140px;padding:10px;border:1px solid #d5d5d5;border-radius:8px;font-family:inherit;font-size:13px;box-sizing:border-box}
input{width:100%;padding:8px 10px;border:1px solid #d5d5d5;border-radius:8px;font-size:13px;box-sizing:border-box;margin-bottom:8px}
button{background:#185FA5;color:#fff;border:none;padding:9px 20px;border-radius:8px;font-size:13px;cursor:pointer;margin-right:8px}
button:hover{background:#0C447C}
pre{background:#F1EFE8;padding:14px;border-radius:8px;overflow:auto;font-size:12px;max-height:420px}
.stat{display:inline-block;background:#E6F1FB;color:#0C447C;padding:3px 10px;border-radius:6px;font-size:12px;margin-right:8px}
</style></head><body>
<h1>环保资金申报智能决策系统</h1>
<div class="sub">政策解析 + JEV 规则终审 + 项目申报匹配</div>
<div id="stats"></div>

<h2>1. 政策解析</h2>
<input id="title" placeholder="文档标题（含「省」或「国家」以通过层级闸门）">
<textarea id="policy" placeholder="粘贴政策指南全文……"></textarea>
<div style="margin-top:8px">
<button onclick="analyze(true)">解析并入库</button>
<button onclick="analyze(false)">仅解析</button>
</div>

<h2>2. 项目匹配</h2>
<textarea id="project" style="min-height:80px" placeholder="例：某县拟建设农村生活污水治理项目，总投资3200万元。"></textarea>
<div style="margin-top:8px"><button onclick="doMatch()">匹配政策</button></div>

<h2>结果</h2>
<pre id="out">就绪</pre>

<script>
const $ = id => document.getElementById(id);
const show = o => $('out').textContent = JSON.stringify(o, null, 2);
fetch('/health').then(r=>r.json()).then(h=>{
  $('stats').innerHTML = `<span class="stat">政策 ${h.policy_count} 份</span>
    <span class="stat">强制规则 ${h.rule_counts.force}</span>
    <span class="stat">排除规则 ${h.rule_counts.exclude}</span>
    <span class="stat">权重规则 ${h.rule_counts.weight}</span>`;
}).catch(()=>{});

async function analyze(store){
  show('解析中……');
  try{
    const r = await fetch('/analyze/text?store=' + store, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text:$('policy').value, title:$('title').value})
    });
    const d = await r.json();
    if(!r.ok){ show({error:d.detail || d}); return; }
    const a = d.data;
    show({
      主赛道: a.primary_track, 协同赛道: a.secondary_tracks,
      JEV校验: a.jev, 证据链: a.evidence_chain,
      需人工复核: a.needs_human_review, 原因: a.review_reasons
    });
  }catch(e){ show({error:String(e)}); }
}

async function doMatch(){
  show('匹配中……');
  try{
    const r = await fetch('/match', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({project:$('project').value, top_k:5})
    });
    const d = await r.json();
    show(r.ok ? d.data : (d.detail || d));
  }catch(e){ show({error:String(e)}); }
}
</script>
</body></html>"""


@app.exception_handler(Exception)
async def unhandled(request, exc):  # pragma: no cover
    return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
