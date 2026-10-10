# -*- coding: utf-8 -*-
"""由「洛阳火点监测-暗色版.html」模板，生成河南省的市页与全省总览页。

用法：
    python make_fire_city.py            # 生成 18 个市 + 全省总览页
    python make_fire_city.py 南阳 郑州    # 只生成指定市
    python make_fire_city.py 河南         # 只生成全省总览页

改造要点（合规/数据）：
- 底图只留「高德 + 腾讯」（合规白名单）；去 CARTO(OSM)/OSM；CSS 滤镜做暗色。
- 边界：运行时从 geo/ 拉取（市页拉 <市>市_县.geojson，全省页拉 henan-cities.geojson），
  WGS-84 → GCJ-02 与高德对齐。
- 火点：运行时从 data/fires-henan.json 拉取（CI 抓的 NASA FIRMS 近实时），
  市页取本市，全省页合并除「省外」外的全部。
- 站点：示例（市页 = 国控1 + 各县区1；全省页 = 18 市各自派生后汇总）。
- 个人邮箱沿用仓库 elmail 混淆。
"""
import json
import re
import pathlib

REPO = pathlib.Path(__file__).resolve().parent
TEMPLATE = pathlib.Path(r"D:/文献/洛阳火点监测-暗色版.html")
_REPO_GEO = REPO / "EnvData/火点监测/geo"
GEO_DIR = _REPO_GEO if _REPO_GEO.exists() else pathlib.Path(r"D:/文献/13-GIS数据")
OUT_DIR = REPO / "EnvData/火点监测"

CITY_NAMES = ["郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳",
              "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源"]

GRID_RE = (r"for\(let r=0;r<4;r\+\+\)for\(let q=0;q<5;q\+\+\)\{ lats\.push\(\([^)]*\)\.toFixed\(2\)\); "
           r"lngs\.push\(\([^)]*\)\.toFixed\(2\)\); \}")


# ---------------- 几何工具 ----------------
def geom_bbox(geom):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for k in c:
                walk(k)

    walk(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def city_bbox(geo):
    xs, ys = [], []
    for f in geo["features"]:
        b = geom_bbox(f["geometry"])
        xs += [b[0], b[2]]; ys += [b[1], b[3]]
    return min(xs), min(ys), max(xs), max(ys)


def derive_stations(city, geo):
    """国控 1（市中心）+ 乡镇/县区各 1（县区中心）。全部标注示例待核实。"""
    xs, ys, st = [], [], []
    for f in geo["features"]:
        b = geom_bbox(f["geometry"])
        xs += [b[0], b[2]]; ys += [b[1], b[3]]
        nm = f["properties"].get("name", "")
        st.append({"name": nm + "站", "level": "乡镇", "layer": "xz",
                   "lng": round((b[0] + b[2]) / 2, 4), "lat": round((b[1] + b[3]) / 2, 4),
                   "detail": f"{nm}（示例待核实）", "vendor": "中国铁塔", "device": "六参数"})
    cx, cy = round((min(xs) + max(xs)) / 2, 4), round((min(ys) + max(ys)) / 2, 4)
    st.insert(0, {"name": f"{city}市环境监测站", "level": "国控", "layer": "gk",
                  "lng": cx, "lat": cy, "detail": f"{city}市中心（示例待核实）",
                  "vendor": "示例", "device": "六参数国标法"})
    return st


def zoom_for(bbox):
    span = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    return 9 if span < 1.2 else (8 if span < 2.4 else 7)


def grid_js(bbox):
    w, s, e, n = bbox
    dlat, dlng = (n - s) / 4.0, (e - w) / 5.0
    return ("for(let r=0;r<4;r++)for(let q=0;q<5;q++){ "
            f"lats.push(({s + dlat * 0.5:.3f}+r*{dlat:.3f}).toFixed(2)); "
            f"lngs.push(({w + dlng * 0.5:.3f}+q*{dlng:.3f}).toFixed(2)); }}")


# ---------------- 页面注入脚本 ----------------
def build_inject(name, boundary_expr, fire_mode):
    if fire_mode == "province":
        list_expr = ("(function(){ var a=[]; if(d.cities){ for(var k in d.cities){ "
                     "if(k!=='省外' && d.cities[k]) a=a.concat(d.cities[k]); } } return a; })()")
        history_js = (
            "      if(d.history){\n"
            "        var byDate={}; for(var k in d.history){ if(k==='省外') continue;"
            " (d.history[k]||[]).forEach(function(e){ byDate[e.date]=(byDate[e.date]||0)+e.count; }); }\n"
            "        FIRE_HISTORY.length=0;\n"
            "        Object.keys(byDate).sort().forEach(function(dt){ FIRE_HISTORY.push({date:dt, count:byDate[dt], hi:0, day:0, night:0, types:{}, fires:[]}); });\n"
            "      }\n")
    else:
        list_expr = "(d.cities && d.cities[CITY]) || []"
        history_js = (
            "      if(d.history && d.history[CITY]){\n"
            "        FIRE_HISTORY.length = 0;\n"
            "        d.history[CITY].forEach(function(e){ FIRE_HISTORY.push({date:e.date, count:e.count, hi:0, day:0, night:0, types:{}, fires:[]}); });\n"
            "      }\n")

    return (
        "\n<!-- 行政边界：运行时从 geo/ 拉取（公开 GeoJSON，WGS-84 → GCJ-02） -->\n"
        "<script>\n"
        "(function(){\n"
        "  var CITY = '" + name + "';\n"
        "  function tGj(g){\n"
        "    if(g.type==='FeatureCollection'){ g.features.forEach(function(f){ tGj(f.geometry); }); return g; }\n"
        "    var conv=function(ring){ ring.forEach(function(c){ var r=wgs2gcj(c[0],c[1]); c[0]=+r[0].toFixed(5); c[1]=+r[1].toFixed(5); }); };\n"
        "    if(g.type==='MultiPolygon'){ g.coordinates.forEach(function(p){ p.forEach(conv); }); }\n"
        "    else if(g.type==='Polygon'){ g.coordinates.forEach(conv); }\n"
        "    return g;\n"
        "  }\n"
        "  fetch(" + boundary_expr + ", {cache:'no-store'})\n"
        "    .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })\n"
        "    .then(function(gj){\n"
        "      var b = L.geoJSON(tGj(gj), {style:{color:'#38bdf8',weight:1.6,opacity:.9,fillColor:'#38bdf8',fillOpacity:0.05}}).addTo(map);\n"
        "      map.fitBounds(b.getBounds(), {padding:[24,24]});\n"
        "    })\n"
        "    .catch(function(e){ console.warn('边界加载失败：', e); });\n"
        "})();\n"
        "</script>\n"
        "<script>(function(){var a=document.querySelectorAll(\"a.elmail\");for(var i=0;i<a.length;i++){var u=a[i].getAttribute(\"data-u\"),d=a[i].getAttribute(\"data-d\");if(!u||!d)continue;var e=u+\"@\"+d;a[i].href=\"mailto:\"+e;a[i].textContent=e;}})();</script>\n"
        "\n<!-- FIRMS 近实时火点 + 历史：CI 抓取 → 静态 JSON，页面联网读取（每 10 分钟自动刷新） -->\n"
        "<script>\n"
        "(function(){\n"
        "  var CITY = '" + name + "';\n"
        "  function loadFires(){\n"
        "  fetch('data/fires-henan.json', {cache:'no-store'})\n"
        "    .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })\n"
        "    .then(function(d){\n"
        "      var list = " + list_expr + ";\n"
        "      if(list && list.length){\n"
        "        var conv = list.map(function(f){\n"
        "          var g = wgs2gcj(f.lng, f.lat);\n"
        "          return {lat:+g[1].toFixed(5), lng:+g[0].toFixed(5), frp:f.frp, conf:f.conf, sat:f.sat,\n"
        "                  date:f.date, time:f.time, dn:f.dn,\n"
        "                  cause:f.cause, cause_conf:f.cause_conf, reasons:f.reasons, hist:f.hist};\n"
        "        });\n"
        "        FIRES.length = 0; conv.forEach(function(f){ FIRES.push(f); });\n"
        "      }\n"
        + history_js +
        "      FIRES_UPDATED = (d.updated_utc||'').slice(5,16).replace('T',' ') + ' UTC';\n"
        "      renderFires(); updateHudStats();\n"
        "      console.log('FIRMS 火点已加载：' + ((list&&list.length)||0) + ' 条（' + CITY + '）');\n"
        "    })\n"
        "    .catch(function(e){ console.warn('FIRMS 火点加载失败：', e); });\n"
        "  }\n"
        "  loadFires();\n"
        "  setInterval(loadFires, 10*60*1000);\n"
        "})();\n"
        "</script>\n"
        "\n<!-- 数据获取日志：CI 每次抓取都写 data/fetch-log.json，页面读它显示「几点抓的 / 结果」 -->\n"
        "<script>\n"
        "(function(){\n"
        "  var panel = document.getElementById('log-panel'), btn = document.getElementById('logBtn');\n"
        "  if(!panel || !btn) return;\n"
        "  function esc(s){ return String(s==null?'':s).replace(/[&<>\"]/g, function(c){\n"
        "    return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]; }); }\n"
        "  var TRIG = {schedule:'定时', workflow_dispatch:'手动', push:'推送触发'};\n"
        "  function loadLog(){\n"
        "    fetch('data/fetch-log.json', {cache:'no-store'})\n"
        "      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })\n"
        "      .then(function(log){\n"
        "        if(!Array.isArray(log) || !log.length){\n"
        "          document.getElementById('lp-sum').textContent = '暂无抓取记录。';\n"
        "          document.getElementById('lp-list').innerHTML = ''; return; }\n"
        "        var last = log[log.length-1], lastOk = null, okN = 0;\n"
        "        for(var i=0;i<log.length;i++){ if(log[i].ok){ okN++; lastOk = log[i]; } }\n"
        "        var s = '<b>共 ' + log.length + ' 次抓取</b>（成功 ' + okN + ' · 失败 ' + (log.length-okN) + '）<br>';\n"
        "        s += '最近一次：<b style=\"color:' + (last.ok?'#4ade80':'#f87171') + '\">' + esc(last.bj||last.t) + ' · ' + (last.ok?'成功':'失败') + '</b>';\n"
        "        if(last.ok) s += '（快照 ' + (last.count||0) + ' 条）';\n"
        "        else s += '<br><span style=\"color:#f87171\">原因：' + esc(last.error||last.stage||'未知') + '</span>';\n"
        "        if(lastOk) s += '<br>最近一次成功：' + esc(lastOk.bj||lastOk.t) + '（快照 ' + (lastOk.count||0) + ' 条 · 点位档案 ' + (lastOk.cells||0) + ' 个）';\n"
        "        document.getElementById('lp-sum').innerHTML = s;\n"
        "        document.getElementById('lp-list').innerHTML = log.slice(-30).reverse().map(function(e){\n"
        "          var txt;\n"
        "          if(e.ok){\n"
        "            var nc = e.cities ? Object.keys(e.cities).length : 0;\n"
        "            txt = '成功 · 快照 <b>' + (e.count||0) + '</b> 条 · 覆盖 ' + nc + ' 市 · 原始 ' + (e.raw||0) + ' 条 · 点位档案 ' + (e.cells||0) + ' 个'\n"
        "                + (e.sec ? ' · ' + e.sec + 's' : '');\n"
        "          } else {\n"
        "            txt = '失败 · ' + esc(e.error || e.stage || '未知原因');\n"
        "          }\n"
        "          var tag = TRIG[e.trigger] || (e.trigger ? esc(e.trigger) : '');\n"
        "          return '<div class=\"lp-row\"><span class=\"lp-t\">' + esc(e.bj||e.t||'') + '</span>'\n"
        "               + '<span class=\"' + (e.ok?'lp-ok':'lp-bad') + '\">' + txt\n"
        "               + (tag ? ' <span class=\"lp-tag\">[' + tag + ']</span>' : '') + '</span></div>';\n"
        "        }).join('');\n"
        "      })\n"
        "      .catch(function(e){ document.getElementById('lp-sum').textContent = '获取日志加载失败：' + e.message; });\n"
        "  }\n"
        "  btn.addEventListener('click', function(){ panel.classList.add('show'); loadLog(); });\n"
        "  document.getElementById('lp-close').addEventListener('click', function(){ panel.classList.remove('show'); });\n"
        "  loadLog();\n"
        "})();\n"
        "</script>\n"
        "\n<!-- 访问计数器（不蒜子，纯前端统计；4 秒内未加载则隐藏，不留占位） -->\n"
        "<script async src=\"//busuanzi.ibruce.info/busuanzi/2.3/busuanzi.pure.mini.js\"></script>\n"
        "<script>setTimeout(function(){var e=document.getElementById('busuanzi_value_page_pv');"
        "if(e&&(!e.textContent||e.textContent==='–')){var b=document.getElementById('visit-badge');if(b)b.style.display='none';}},4000);</script>\n"
    )


# ---------------- 通用改造 ----------------
def apply_page(template, cfg):
    name = cfg["name"]
    cy, cx = cfg["center"]
    zoom = cfg["zoom"]
    bbox = cfg["bbox"]
    stations = cfg["stations"]
    n_town = sum(1 for s in stations if s["layer"] == "xz")
    n_all = len(stations)

    html = template

    # 1. 标题 / HUD
    html = html.replace("<title>洛阳火点监测 · 空气站点</title>",
                        f"<title>{name}火点监测 · 空气站点</title>")
    html = html.replace("<b>洛阳火点监测</b>", f"<b>{name}火点监测</b>")

    # 2. 地图中心
    html = html.replace("L.map('map', { zoomControl:true }).setView([34.42, 112.43], 10);",
                        f"L.map('map', {{ zoomControl:true }}).setView([{cy}, {cx}], {zoom});")

    # 3. 气象：单点 + 网格
    html = html.replace("latitude=34.42&longitude=112.43&current=",
                        f"latitude={cy}&longitude={cx}&current=")
    html = re.sub(GRID_RE, lambda m: grid_js(bbox), html, count=1)

    # 4. 底图：高德 + 腾讯（合规白名单）
    new_providers = (
        "const providers = [\n"
        "  { name:'高德', url:'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',\n"
        "    sub:'1234', attr:'© 高德地图 AutoNavi', tms:false, cls:'gj-dark' },\n"
        "  { name:'腾讯', url:'https://rt{s}.map.gtimg.com/realtimerender?z={z}&x={x}&y={y}&type=vector&style=0',\n"
        "    sub:'0123', attr:'© 腾讯地图 Tencent', tms:true, cls:'gj-dark' },\n"
        "];"
    )
    html = re.sub(r"const providers = \[[\s\S]*?\n\];", lambda m: new_providers, html, count=1)
    html = html.replace(
        "const ly = L.tileLayer(p.url, { subdomains:p.sub, maxZoom:18, attribution:p.attr, tms:p.tms });",
        "const ly = L.tileLayer(p.url, { subdomains:p.sub, maxZoom:18, attribution:p.attr, tms:p.tms, className: p.cls||'' });")

    # 5. 暗色滤镜 + 访问计数器样式 + HUD 卡片/工具栏可用性调整
    dark_css = (
        "<style>"
        ".gj-dark{filter:invert(1) hue-rotate(180deg) brightness(.92) contrast(.95) saturate(.65)!important}"
        ".hud-visits{font-family:ui-monospace,monospace;font-size:12px;color:#7dd3fc;"
        "border-left:1px solid rgba(148,163,184,.25);padding-left:10px;white-space:nowrap}"
        # HUD 统计卡：更紧凑，避免遮挡下方工具栏
        "#hud-stats{width:232px;padding:11px 14px}"
        ".hud-kicker{font-size:9px;letter-spacing:1px;margin-bottom:6px;white-space:nowrap}"
        ".hud-num{font-size:30px}"
        ".hud-num2{font-size:16px;margin-top:5px}"
        ".hud-label{font-size:9px;margin:2px 0 4px}"
        ".hud-status{margin-top:8px;padding-top:8px;font-size:10px}"
        ".hud-sync{font-size:9px;margin-top:4px;line-height:1.5}"
        # 工具栏：下移到卡片之下（不遮挡），并放大选项卡，更好点按
        ".toolbar{margin-top:200px!important;padding:10px 14px!important;gap:8px!important;"
        "flex-wrap:wrap!important;align-items:center!important}"
        ".legend-item{font-size:14px!important;padding:7px 14px!important;border-radius:10px!important;"
        "display:inline-flex!important;align-items:center!important;gap:6px!important}"
        ".legend-dot{width:12px!important;height:12px!important}"
        ".stats{font-size:13px!important}"
        # 头部变高，地图相应缩短，避免整页纵向滚动
        "#map{height:calc(100vh - 336px)!important;min-height:360px}"
        "@media(max-width:820px){.toolbar{margin-top:96px!important}"
        "#map{height:calc(100vh - 232px)!important}"
        ".legend-item{font-size:13px!important;padding:6px 10px!important}}"
        # 数据获取日志面板
        "#log-panel{position:fixed;top:0;right:0;bottom:0;width:min(430px,94vw);background:#0b1120;"
        "color:#e2e8f0;z-index:2100;box-shadow:-4px 0 18px rgba(0,0,0,.5);"
        "transform:translateX(105%);transition:transform .28s ease;display:flex;flex-direction:column}"
        "#log-panel.show{transform:none}"
        ".lp-head{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;"
        "background:#312e81;color:#fff;font-size:15px}"
        "#lp-close{cursor:pointer;font-size:18px;padding:2px 8px}"
        ".lp-body{overflow-y:auto;padding:12px 14px 20px}"
        ".lp-sum{font-size:12px;color:#cbd5e1;background:rgba(30,41,59,.6);"
        "border:1px solid rgba(148,163,184,.2);border-radius:10px;padding:10px 12px;"
        "margin-bottom:12px;line-height:1.8}"
        ".lp-row{display:flex;gap:8px;font-size:11.5px;padding:6px 2px;"
        "border-bottom:1px dashed rgba(148,163,184,.15);line-height:1.6}"
        ".lp-t{font-family:ui-monospace,monospace;color:#94a3b8;white-space:nowrap;flex:none}"
        ".lp-ok{color:#4ade80}.lp-bad{color:#f87171}.lp-tag{color:#64748b;font-size:10px}"
        ".lp-note{font-size:11px;color:#475569;line-height:1.8;text-align:center;padding:10px 0}"
        "@media(min-width:900px){#log-panel{top:120px;bottom:24px;right:16px;border-radius:14px;"
        "transform:translateX(calc(100% + 24px));border:1px solid rgba(148,163,184,.2)}"
        "#log-panel.show{transform:none}.lp-head{border-radius:14px 14px 0 0}}"
        "</style>\n</head>"
    )
    html = html.replace("</head>", dark_css, 1)

    # 5a. HUD 文案精简（卡片更矮，不遮挡）
    html = html.replace("SATELLITE FEED · VIIRS SNPP 375m", "SATELLITE FEED · VIIRS 375m")

    # 5b. UI：经纬度移到左下角；底图状态移到右下；标题栏加访问计数器
    html = html.replace(
        "#hud-coords { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); z-index:1500;",
        "#hud-coords { position:fixed; bottom:18px; left:14px; z-index:1500;")
    html = html.replace("#hud-coords { bottom:8px; font-size:11px; }",
                        "#hud-coords { bottom:8px; left:8px; font-size:11px; }")
    html = html.replace("const tileStatus = L.control({ position:'bottomleft' });",
                        "const tileStatus = L.control({ position:'bottomright' });")
    html = html.replace(
        'id="hud-clock">--:--:--</div>',
        'id="hud-clock">--:--:--</div>\n'
        '  <div class="hud-visits" id="visit-badge" title="页面访问量（不蒜子统计）">👁 <span id="busuanzi_value_page_pv">–</span></div>')

    # 6. 站点数组
    stations_js = "const stations = " + json.dumps(stations, ensure_ascii=False) + ";"
    html = re.sub(r"const stations = \[[\s\S]*?\n\];", lambda m: stations_js, html, count=1)

    # 7. 火点/历史留空，运行时填充
    html = re.sub(r"const FIRES = \[.*?\];", "const FIRES = [];", html, count=1)
    html = re.sub(r"const FIRES_UPDATED = '[^']*';",
                  "let FIRES_UPDATED = '待联网加载（FIRMS）';", html, count=1)
    html = re.sub(r"const FIRE_HISTORY = \[.*?\];", "const FIRE_HISTORY = [];", html, count=1)

    # 8. guessFire / fireType：优先用服务端成因推测
    html = re.sub(
        r"function guessFire\(f\)\{[\s\S]*?\n\}",
        "function guessFire(f){\n"
        "  if (f.cause) {\n"
        "    var s = f.cause + (f.cause_conf ? '（置信度 ' + f.cause_conf + '）' : '');\n"
        "    if (f.reasons && f.reasons.length)\n"
        "      s += '<br><span style=\"color:#94a3b8;font-size:11px;\">依据：' + f.reasons.join('；') + '</span>';\n"
        "    if (f.hist && f.hist.dates && f.hist.dates.length)\n"
        "      s += '<br><span style=\"color:#64748b;font-size:11px;\">该点位近' + (f.hist.win||60) + '天出现日期：' + f.hist.dates.join('、') + '</span>';\n"
        "    return s;\n"
        "  }\n"
        "  if (f.frp >= 30) return '火点强度很高，疑似较大火情';\n"
        "  if (f.dn === 'N') return '夜间火点，疑似持续燃烧或工业热源';\n"
        "  if (f.frp < 3) return '白天小火点，疑似农田/秸秆焚烧';\n"
        "  if (f.conf === 'l') return '低置信火点，建议结合现场核实';\n"
        "  return '火点强度中等，需结合现场核实';\n"
        "}", html, count=1)
    html = re.sub(
        r"function fireType\(f\)\{[\s\S]*?\n\}",
        "function fireType(f){\n"
        "  if (f.cause) return f.cause;\n"
        "  if (f.frp >= 30) return '较大火情';\n"
        "  if (f.dn === 'N') return '夜间火点';\n"
        "  if (f.frp < 3) return '秸秆焚烧疑似';\n"
        "  return '待核实';\n"
        "}", html, count=1)
    html = html.replace(
        "  const order = ['秸秆焚烧疑似','山火疑似','夜间火点','较大火情','待核实'];\n"
        "  document.getElementById('fp-types').innerHTML = order.filter(t=>types[t])",
        "  document.getElementById('fp-types').innerHTML = Object.keys(types).sort((a,b)=>types[b]-types[a])")

    # 9. 日报范围
    html = html.replace("范围：洛阳市界外扩50km", f"范围：{cfg['range_text']}")

    # 10. 免责声明
    new_disclaimer = (
        '<div class="disclaimer">\n'
        "  注：底图为高德地图（需联网加载）；站点坐标为示例整理（GCJ-02），<b>真实站点清单待核实接入</b>；"
        "行政边界依据公开 GeoJSON 绘制（示意，不可用于边界认定）。<br>"
        "运维单位、设备信息为示例，具体以主管部门公布为准。<br>"
        "<b>数据口径：</b>站点 AQI 为<b>模拟演示数据</b>（手动录入后即为真实值）；"
        "🔥火点为 <b>NASA FIRMS 近实时卫星火点</b>（VIIRS 375m，页面联网读取 data/fires-henan.json，每小时更新；"
        "WGS-84 已转 GCJ-02 与高德对齐）；成因列为<b>基于历史复现与遥感特征的推测</b>，非确证；"
        "🌬气象为 Open-Meteo 实时数据。\n"
        "</div>"
    )
    html = re.sub(r'<div class="disclaimer">[\s\S]*?</div>', lambda m: new_disclaimer, html, count=1)

    # 11. 模拟徽标说明
    html = html.replace(
        "title=\"站点AQI为模拟演示数据（六参数模拟，暂无公开实时接口）；火点为NASA FIRMS真实数据；气象为Open-Meteo实时数据\"",
        "title=\"站点AQI为模拟演示数据（手动录入后为真实值）；火点为NASA FIRMS近实时数据；气象为Open-Meteo实时数据\"")

    # 12. HUD 同步文字
    html = html.replace("每日08:15自动更新", "每小时更新")

    # 12b. HUD 统计 IIFE → 可重入函数
    html = re.sub(
        r"\(function\(\)\{\s*\n\s*document\.getElementById\('hud-count'\)[\s\S]*?\}\)\(\);",
        "function updateHudStats(){\n"
        "  document.getElementById('hud-count').textContent = FIRES.length.toLocaleString();\n"
        "  const frp = FIRES.reduce((a,f)=>a+(f.frp||0),0);\n"
        "  document.getElementById('hud-frp').textContent = Math.round(frp).toLocaleString();\n"
        "  document.getElementById('hud-updated').textContent = FIRES_UPDATED || '–';\n"
        "}\n"
        "updateHudStats();", html, count=1)

    # 13. 计数标签
    html = html.replace("乡镇站(14)", f"乡镇站({n_town})")
    html = html.replace("邻县乡镇(9)<span style=\"font-size:10px;color:#999;\">示意</span>",
                         "邻县乡镇(0)<span style=\"font-size:10px;color:#999;\">示意</span>")
    html = html.replace("共 <b id=\"total\">42</b> 站", f"共 <b id=\"total\">{n_all}</b> 站")

    # 14. 数据获取日志：工具栏按钮 + 侧栏面板（渲染逻辑在 build_inject 里注入）
    html = html.replace(
        '<div class="legend-item" id="fpBtn"',
        '<div class="legend-item" id="logBtn" style="background:#eef2ff;color:#3730a3;font-weight:700;">'
        '📜 获取日志</div>\n  <div class="legend-item" id="fpBtn"', 1)
    log_panel = (
        '<div id="log-panel">\n'
        '  <div class="lp-head"><b>📜 数据获取日志</b><span id="lp-close">✕</span></div>\n'
        '  <div class="lp-body">\n'
        '    <div class="lp-sum" id="lp-sum">加载中…</div>\n'
        '    <div id="lp-list"></div>\n'
        '    <div class="lp-note">每次抓取都记一条：<b>几点抓的 + 结果是什么</b>。<br>'
        '失败也会记，并写明原因。<br>云端每小时 :17 自动抓取 · 数据源 NASA FIRMS VIIRS 375m 近实时</div>\n'
        '  </div>\n'
        '</div>\n'
    )
    html = html.replace('<div id="data-panel">', log_panel + '<div id="data-panel">', 1)

    # 14b. 日报脚注：更新频率 + 指向获取日志
    html = html.replace("每日自动更新", "每小时自动更新 · 明细见「📜 获取日志」")

    # 15. 邮箱混淆
    html = html.replace(
        '<div class="contact-mail">📧 <a href="mailto:jinghao.song@gmail.com">jinghao.song@gmail.com</a></div>',
        '<div class="contact-mail">📧 <a class="elmail" href="#" data-u="jinghao.song" data-d="gmail.com">载入中…</a></div>')

    # 16. 注入
    html = html.replace("</body>", build_inject(name, cfg["boundary_expr"], cfg["fire_mode"]) + "</body>", 1)
    return html


# ---------------- 单市 / 全省 ----------------
def build_city(city, template):
    geo = json.loads((GEO_DIR / f"{city}市_县.geojson").read_text(encoding="utf-8"))
    bbox = city_bbox(geo)
    cfg = {
        "name": city,
        "center": (round((bbox[1] + bbox[3]) / 2, 4), round((bbox[0] + bbox[2]) / 2, 4)),
        "zoom": zoom_for(bbox),
        "bbox": bbox,
        "stations": derive_stations(city, geo),
        "range_text": f"{city}市界外扩50km",
        "boundary_expr": "'geo/' + encodeURIComponent(CITY + '市_县.geojson')",
        "fire_mode": "city",
    }
    html = apply_page(template, cfg)
    out = OUT_DIR / f"{city}市火点监测-暗色版.html"
    out.write_text(html, encoding="utf-8", newline="\n")
    left = 0 if city == "洛阳" else html.count("洛阳")
    return {"name": city, "file": out.name, "bytes": len(html.encode("utf-8")),
            "stations": len(cfg["stations"]), "left": left, "osm": html.count("openstreetmap")}


def build_province(template):
    stations, xs, ys = [], [], []
    for c in CITY_NAMES:
        geo = json.loads((GEO_DIR / f"{c}市_县.geojson").read_text(encoding="utf-8"))
        b = city_bbox(geo)
        xs += [b[0], b[2]]; ys += [b[1], b[3]]
        stations += derive_stations(c, geo)
    bbox = (min(xs), min(ys), max(xs), max(ys))
    cfg = {
        "name": "河南",
        "center": (round((bbox[1] + bbox[3]) / 2, 4), round((bbox[0] + bbox[2]) / 2, 4)),
        "zoom": 7,
        "bbox": bbox,
        "stations": stations,
        "range_text": "河南省界外扩50km",
        "boundary_expr": "'geo/henan-cities.geojson'",
        "fire_mode": "province",
    }
    html = apply_page(template, cfg)
    out = OUT_DIR / "河南省火点监测-暗色版.html"
    out.write_text(html, encoding="utf-8", newline="\n")
    return {"name": "河南(全省)", "file": out.name, "bytes": len(html.encode("utf-8")),
            "stations": len(stations), "left": 0, "osm": html.count("openstreetmap")}


def main():
    import sys
    args = sys.argv[1:]
    template = TEMPLATE.read_text(encoding="utf-8")
    targets = args or (CITY_NAMES + ["河南"])
    print(f"[fire] 模板 {TEMPLATE.name}；生成 {len(targets)} 个页面")
    bad = []
    for t in targets:
        try:
            r = build_province(template) if t == "河南" else build_city(t, template)
            flag = "" if (r["left"] == 0 and r["osm"] == 0) else "  <== 检查!"
            print(f"[fire] {r['name']:<8} {r['bytes']:>7}B  站{r['stations']:<4} 残留洛阳{r['left']} OSM{r['osm']}{flag}")
            if flag:
                bad.append(t)
        except Exception as e:
            print(f"[fire] {t} 失败：{e}")
            bad.append(t)
    print(f"[fire] 完成；异常 {len(bad)} 个：{bad}")


if __name__ == "__main__":
    main()
