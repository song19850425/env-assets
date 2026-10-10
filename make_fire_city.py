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
        # 合并各市火点时顺带打上「所属市」标记，供详情弹窗做各市分布
        list_expr = ("(function(){ var a=[]; if(d.cities){ for(var k in d.cities){ "
                     "if(k!=='省外' && d.cities[k]){ d.cities[k].forEach(function(f){ f.city=k; }); "
                     "a=a.concat(d.cities[k]); } } } return a; })()")
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

    modal_js = """
<!-- 两张卡片：点击弹出详情大窗口（统计详情 / 图例与读图说明） -->
<script>
(function(){
  // 缩放控件默认在左上，会和左侧卡片重叠 → 移到右上（并已在 CSS 里暗色化）
  try{
    if(typeof map !== 'undefined' && map.zoomControl){
      map.removeControl(map.zoomControl);
      L.control.zoom({ position:'topright' }).addTo(map);
    }
  }catch(e){}

  var modal = document.getElementById('card-modal');
  if(!modal) return;
  var box = document.getElementById('cm-body');
  var ttl = document.getElementById('cm-title');

  function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function num(v,d){ v = Number(v)||0; return v.toFixed(d==null?0:d); }
  function kv(k,v){ return '<div class="cm-kv"><span>'+esc(k)+'</span><b>'+esc(v)+'</b></div>'; }
  function sec(t,inner){ return '<div class="cm-sec"><h4>'+esc(t)+'</h4>'+inner+'</div>'; }
  function bar(name,n,max,color){
    var w = max>0 ? Math.max(3, Math.round(n/max*100)) : 0;
    return '<div class="cm-bar"><span class="cm-bar-name">'+esc(name)+'</span>'
      + '<span class="cm-bar-track"><span class="cm-bar-fill" style="width:'+w+'%'
      + (color ? ';background:'+color : '') + '"></span></span>'
      + '<span class="cm-bar-num">'+n+'</span></div>';
  }
  function dist(key){
    var m = {}, order = [];
    FIRES.forEach(function(f){
      var k = key(f) || '未标注';
      if(m[k]===undefined){ m[k]=0; order.push(k); }
      m[k]++;
    });
    return order.map(function(k){ return [k, m[k]]; }).sort(function(a,b){ return b[1]-a[1]; });
  }
  function maxOf(pairs){ return pairs.reduce(function(a,e){ return Math.max(a, e[1]); }, 0); }

  function statsHtml(){
    var n = FIRES.length, frp = 0, mx = 0, byDate = {};
    FIRES.forEach(function(f){
      var v = Number(f.frp)||0;
      frp += v; if(v > mx) mx = v;
      if(f.date){ byDate[f.date] = (byDate[f.date]||0) + 1; }
    });
    var avg = n ? frp/n : 0;
    var dates = Object.keys(byDate).sort();
    var causes = dist(function(f){ return f.cause; });
    var confs = dist(function(f){
      return f.conf === 'h' ? '高置信 (h)' : (f.conf === 'l' ? '低置信 (l)' : '中置信 (n)');
    });
    var s = '';
    s += sec('数据来源与时效',
      kv('数据源','NASA FIRMS · VIIRS 375m')
      + kv('卫星','Suomi-NPP + NOAA-20')
      + kv('快照时间', FIRES_UPDATED || '–')
      + kv('抓取频率','每 6 小时（云端自动）')
      + '<div class="cm-note">FIRMS 是卫星过境后的近实时(NRT)产品，延迟约 3~4 小时，一天刷新多次，做不到分钟级。'
      + '本页展示的是打开页面时联网读取的最近一版快照。</div>');

    s += sec('火点统计（近 2 天）',
      kv('火点总数', n + ' 个')
      + kv('辐射功率合计 FRP', num(frp,0) + ' MW')
      + kv('最大单点 FRP', num(mx,2) + ' MW')
      + kv('平均单点 FRP', num(avg,2) + ' MW'));

    if(dates.length){
      s += sec('按日期分布', dates.slice(-12).map(function(d){
        return bar(d, byDate[d], maxOf(dates.map(function(x){ return [x, byDate[x]]; })));
      }).join(''));
    }
    var cities = dist(function(f){ return f.city; });
    if(cities.length > 1){
      s += sec('各市分布', cities.map(function(e){ return bar(e[0], e[1], maxOf(cities)); }).join('')
        + '<div class="cm-note">按火点落入的市界归属统计（射线法点落多边形），省外火点不计入。</div>');
    }
    if(causes.length){
      s += sec('成因推测分布',
        causes.map(function(e){ return bar(e[0], e[1], maxOf(causes)); }).join('')
        + '<div class="cm-note">成因是基于「该点位历史复现 + 遥感特征」的推测，卫星遥感无法确证成因。'
        + '点开地图上的火点可以看到该点的具体依据与历史出现日期。</div>');
    }
    if(confs.length){
      s += sec('置信度分布',
        confs.map(function(e){ return bar(e[0], e[1], maxOf(confs)); }).join('')
        + '<div class="cm-note">置信度来自 FIRMS 原始字段：h=高、n=中、l=低。低置信火点可能是热源误判，建议结合现场核实。</div>');
    }
    if(!n){
      s += '<div class="cm-note">当前窗口内没有火点（属正常，火点本身稀疏）。</div>';
    }
    return s;
  }

  function legendHtml(){
    var frps = FIRES.map(function(f){ return Number(f.frp)||0; }).sort(function(a,b){ return a-b; });
    var mn = frps.length ? frps[0] : 0, mx = frps.length ? frps[frps.length-1] : 0;
    var s = '';
    s += sec('火点标记怎么读',
      '<div class="hc-row" style="margin:6px 0"><span class="lg-dot" style="background:#ef4444"></span>'
      + '高置信火点（confidence = h）</div>'
      + '<div class="hc-row" style="margin:6px 0"><span class="lg-dot" style="background:#fb923c"></span>'
      + '中 / 低置信火点（n / l）</div>'
      + '<div class="cm-note">圆点越大、越亮，表示该火点的辐射功率（FRP）越强。</div>');

    s += sec('FRP 火辐射功率量程',
      '<div class="frp-bar"></div><div class="frp-labels"><span>LOW</span><span>HIGH</span></div>'
      + kv('当前视野最小 FRP', num(mn,2) + ' MW')
      + kv('当前视野最大 FRP', num(mx,2) + ' MW')
      + '<div class="cm-note">FRP 越高通常意味着燃烧越剧烈或过火面积越大；低值小火点也可能是农田 / 秸秆焚烧。</div>');

    s += sec('站点标记',
      '<div class="hc-row" style="margin:6px 0"><span class="lg-dot" style="background:#27ae60"></span>'
      + '空气站点（圆内数字为 AQI）</div>'
      + '<div class="cm-note">站点 AQI 目前为模拟演示数据，手动录入后即为真实值。</div>');

    s += sec('图层与交互',
      '<div class="cm-note">'
      + '· 工具栏可开关图层：国控 / 县控 / 乡镇站 / 周边站 / 邻县站 / 火点 / 卫星图 / 气象图层<br>'
      + '· 点击火点：查看成因推测、判定依据、该点位近 60 天历史出现日期<br>'
      + '· 点击站点：查看六参数浓度<br>'
      + '· 拖拽平移、滚轮缩放、双击放大；左下角显示鼠标经纬度<br>'
      + '· 「火点日报」看每日趋势与历史明细；「获取日志」看每次抓取的时间与结果'
      + '</div>');

    s += sec('数据来源与免责',
      '<div class="cm-note">火点：NASA FIRMS VIIRS 375m 近实时卫星火点（原始 WGS-84，已转 GCJ-02 与高德底图对齐）。<br>'
      + '底图：高德地图。气象：Open-Meteo。<br>'
      + '成因列为推测、非确证；本页不构成法定检测报告。</div>');
    return s;
  }

  function open(kind){
    ttl.textContent = (kind === 'legend') ? '图例与读图说明' : '火点统计详情';
    box.innerHTML = (kind === 'legend') ? legendHtml() : statsHtml();
    modal.classList.add('show');
    box.scrollTop = 0;
  }
  function close(){ modal.classList.remove('show'); }

  ['hud-stats','hud-legend'].forEach(function(id){
    var el = document.getElementById(id);
    if(!el) return;
    if(window.L && L.DomEvent){
      L.DomEvent.disableClickPropagation(el);
      L.DomEvent.disableScrollPropagation(el);
    }
    el.addEventListener('click', function(){ open(el.getAttribute('data-modal')); });
  });
  var cl = document.getElementById('cm-close');
  if(cl) cl.addEventListener('click', close);
  modal.addEventListener('click', function(e){ if(e.target === modal) close(); });
  document.addEventListener('keydown', function(e){ if(e.key === 'Escape') close(); });
})();
</script>
"""
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
        "  function loadFires(cb){\n"
        "  fetch('data/fires-henan.json?t=' + Date.now(), {cache:'no-store'})\n"
        "    .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })\n"
        "    .then(function(d){\n"
        "      var list = " + list_expr + ";\n"
        "      if(list && list.length){\n"
        "        var conv = list.map(function(f){\n"
        "          var g = wgs2gcj(f.lng, f.lat);\n"
        "          return {lat:+g[1].toFixed(5), lng:+g[0].toFixed(5), frp:f.frp, conf:f.conf, sat:f.sat,\n"
        "                  date:f.date, time:f.time, dn:f.dn, city:f.city,\n"
        "                  cause:f.cause, cause_conf:f.cause_conf, reasons:f.reasons, hist:f.hist};\n"
        "        });\n"
        "        FIRES.length = 0; conv.forEach(function(f){ FIRES.push(f); });\n"
        "      }\n"
        + history_js +
        "      FIRES_UPDATED = (d.updated_utc||'').slice(5,16).replace('T',' ') + ' UTC';\n"
        "      renderFires(); updateHudStats();\n"
        "      console.log('FIRMS 火点已加载：' + ((list&&list.length)||0) + ' 条（' + CITY + '）');\n"
        "      if(cb) cb(true, (list&&list.length)||0);\n"
        "    })\n"
        "    .catch(function(e){ console.warn('FIRMS 火点加载失败：', e); if(cb) cb(false, 0); });\n"
        "  }\n"
        "  loadFires();\n"
        "  setInterval(function(){ loadFires(); }, 30*60*1000);\n"
        "  window.__loadFires = loadFires;   // 供「📜 获取日志」里的「获取当前数据」按钮调用\n"
        "})();\n"
        "</script>\n"
        + modal_js +
        "\n<!-- 数据获取日志：CI 每次抓取都写 data/fetch-log.json，页面读它显示「几点抓的 / 结果」 -->\n"
        "<script>\n"
        "(function(){\n"
        "  var panel = document.getElementById('log-panel'), btn = document.getElementById('logBtn');\n"
        "  if(!panel || !btn) return;\n"
        "  function esc(s){ return String(s==null?'':s).replace(/[&<>\"]/g, function(c){\n"
        "    return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]; }); }\n"
        "  var TRIG = {schedule:'定时', workflow_dispatch:'手动', push:'推送触发'};\n"
        "  function loadLog(){\n"
        "    fetch('data/fetch-log.json?t=' + Date.now(), {cache:'no-store'})\n"
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
        "  var rf = document.getElementById('lp-refresh'), rmsg = document.getElementById('lp-refresh-msg');\n"
        "  if(rf) rf.addEventListener('click', function(){\n"
        "    var label = rf.textContent;\n"
        "    rf.disabled = true; rf.textContent = '⏳ 获取中…';\n"
        "    if(rmsg){ rmsg.className = 'lp-hint'; rmsg.textContent = ''; }\n"
        "    var t0 = Date.now();\n"
        "    function done(ok, n){\n"
        "      rf.disabled = false; rf.textContent = label;\n"
        "      var sec = ((Date.now() - t0)/1000).toFixed(1);\n"
        "      if(rmsg){\n"
        "        rmsg.className = 'lp-hint' + (ok ? '' : ' err');\n"
        "        rmsg.textContent = ok\n"
        "          ? ('✅ 已获取最新数据 · ' + n + ' 条火点 · 用时 ' + sec + ' 秒 · ' + new Date().toLocaleTimeString('zh-CN'))\n"
        "          : ('❌ 获取失败（' + sec + ' 秒），请检查网络后重试');\n"
        "      }\n"
        "      loadLog();\n"
        "    }\n"
        "    if(window.__loadFires){ window.__loadFires(done); } else { done(true, FIRES.length); }\n"
        "  });\n"
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
        # 工具栏：下移到标题之下（两张卡片已移入地图，不再占头部高度）
        ".toolbar{margin-top:90px!important;padding:10px 14px!important;gap:8px!important;"
        "flex-wrap:wrap!important;align-items:center!important}"
        ".legend-item{font-size:14px!important;padding:7px 14px!important;border-radius:10px!important;"
        "display:inline-flex!important;align-items:center!important;gap:6px!important}"
        ".legend-dot{width:12px!important;height:12px!important}"
        ".stats{font-size:13px!important}"
        # 头部变矮，地图相应变高，避免整页纵向滚动
        "#map{height:calc(100vh - 226px)!important;min-height:360px}"
        "@media(max-width:820px){.toolbar{margin-top:72px!important}"
        "#map{height:calc(100vh - 200px)!important}"
        ".legend-item{font-size:13px!important;padding:6px 10px!important}}"
        # 两张卡片：移到地图左侧、形状大小一致、可点击
        "#hud-stats,#hud-legend{position:absolute!important;left:14px!important;right:auto!important;"
        "width:238px!important;height:150px!important;box-sizing:border-box;"
        "border-radius:14px!important;padding:12px 14px!important;z-index:1100!important;"
        "cursor:pointer;overflow:hidden;display:flex;flex-direction:column;"
        "transition:border-color .15s,box-shadow .15s,transform .15s}"
        # 缩放控件：暗色化（Leaflet 默认是白底，在暗色页里突兀）
        ".leaflet-control-zoom{border:1px solid rgba(34,211,238,.28)!important;"
        "border-radius:10px!important;overflow:hidden;box-shadow:0 4px 14px rgba(0,0,0,.5)!important}"
        ".leaflet-control-zoom a{background:rgba(10,15,25,.9)!important;color:#7dd3fc!important;"
        "border-bottom:1px solid rgba(148,163,184,.18)!important;"
        "width:30px!important;height:30px!important;line-height:30px!important}"
        ".leaflet-control-zoom a:hover{background:rgba(34,211,238,.2)!important;color:#e0f2fe!important}"
        ".leaflet-control-zoom a.leaflet-disabled{background:rgba(10,15,25,.55)!important;color:#334155!important}"
        "#hud-stats{top:14px!important}"
        "#hud-legend{top:176px!important}"
        "#hud-stats:hover,#hud-legend:hover{border-color:rgba(34,211,238,.55)!important;"
        "box-shadow:0 8px 26px rgba(0,0,0,.55);transform:translateY(-1px)}"
        ".hc-main{display:flex;align-items:baseline;gap:6px}"
        ".hc-unit{font-size:11px;color:#64748b}"
        ".hc-row{display:flex;align-items:center;gap:8px;color:#cbd5e1;font-size:12px}"
        ".hc-more{margin-top:auto;font-size:11px;color:#22d3ee;letter-spacing:.5px;padding-top:6px}"
        "#hud-stats .hud-kicker,#hud-legend .hud-kicker{margin-bottom:6px}"
        "#hud-stats .hud-num{font-size:30px}"
        "#hud-stats .hud-label{margin:2px 0 0}"
        "#hud-stats .hud-status{margin-top:7px;padding-top:7px;font-size:10px;"
        "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
        "#hud-legend .frp-bar{margin-top:8px}"
        # 卡片详情大窗口
        "#card-modal{position:fixed;inset:0;z-index:3000;background:rgba(2,6,23,.78);"
        "backdrop-filter:blur(3px);display:none;align-items:center;justify-content:center;padding:24px}"
        "#card-modal.show{display:flex}"
        ".cm-box{background:#0b1120;border:1px solid rgba(34,211,238,.25);border-radius:16px;"
        "width:min(820px,94vw);max-height:86vh;display:flex;flex-direction:column;"
        "box-shadow:0 24px 60px rgba(0,0,0,.6)}"
        ".cm-head{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;"
        "background:linear-gradient(90deg,#0e7490,#155e75);color:#fff;font-size:15px;"
        "border-radius:16px 16px 0 0}"
        "#cm-close{cursor:pointer;font-size:18px;padding:2px 8px;opacity:.85}"
        "#cm-close:hover{opacity:1}"
        ".cm-body{overflow-y:auto;padding:16px 20px 22px;color:#cbd5e1;font-size:13px;line-height:1.75}"
        ".cm-sec{margin-bottom:18px}"
        ".cm-sec h4{font-size:12px;letter-spacing:1.5px;color:#22d3ee;margin-bottom:8px;"
        "border-left:3px solid #0891b2;padding-left:8px;font-weight:700}"
        ".cm-kv{display:flex;justify-content:space-between;gap:12px;padding:5px 0;"
        "border-bottom:1px dashed rgba(148,163,184,.15)}"
        ".cm-kv b{color:#e2e8f0;font-family:ui-monospace,monospace}"
        ".cm-bar{display:flex;align-items:center;gap:10px;margin:6px 0}"
        ".cm-bar-name{width:150px;flex:none;font-size:12px;color:#94a3b8;"
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".cm-bar-track{flex:1;height:16px;background:rgba(148,163,184,.12);border-radius:5px;overflow:hidden}"
        ".cm-bar-fill{display:block;height:100%;border-radius:5px;"
        "background:linear-gradient(90deg,#0891b2,#22d3ee)}"
        ".cm-bar-num{width:52px;flex:none;text-align:right;font-family:ui-monospace,monospace;"
        "font-size:12px;color:#e2e8f0}"
        ".cm-note{font-size:11.5px;color:#64748b;line-height:1.85;margin-top:6px}"
        "@media(max-width:760px){#hud-stats,#hud-legend{display:none!important}"
        "#card-modal{padding:12px}.cm-box{max-height:90vh}}"
        # 数据获取日志面板
        "#log-panel{position:fixed;top:0;right:0;bottom:0;width:min(430px,94vw);background:#0b1120;"
        "color:#e2e8f0;z-index:2100;box-shadow:-4px 0 18px rgba(0,0,0,.5);"
        "transform:translateX(105%);transition:transform .28s ease;display:flex;flex-direction:column}"
        "#log-panel.show{transform:none}"
        ".lp-head{display:flex;justify-content:space-between;align-items:center;padding:14px 16px;"
        "background:#312e81;color:#fff;font-size:15px}"
        "#lp-close{cursor:pointer;font-size:18px;padding:2px 8px}"
        ".lp-body{overflow-y:auto;padding:12px 14px 20px}"
        ".lp-refresh{display:block;width:100%;margin-bottom:8px;padding:10px 12px;"
        "background:linear-gradient(90deg,#0891b2,#0e7490);color:#fff;border:none;"
        "border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;letter-spacing:.5px;"
        "transition:filter .15s,opacity .15s}"
        ".lp-refresh:hover:not(:disabled){filter:brightness(1.15)}"
        ".lp-refresh:disabled{opacity:.6;cursor:default}"
        ".lp-hint{font-size:11.5px;color:#4ade80;margin-bottom:8px;min-height:0;line-height:1.6}"
        ".lp-hint.err{color:#f87171}"
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

    # 5c. 两张卡片：从头部移入地图左侧，统一形状大小，点击弹出详情大窗口
    i0 = html.index('<div id="hud-stats">')
    i1 = html.index('<div id="hud-coords">')
    html = html[:i0] + html[i1:]          # 先把两张旧卡片从头部摘掉
    cards = (
        '<div class="hud-card" id="hud-stats" data-modal="stats" title="点击查看详细统计">\n'
        '    <div class="hud-kicker">SATELLITE FEED · VIIRS 375m</div>\n'
        '    <div class="hc-main"><span class="hud-num" id="hud-count">–</span>'
        '<span class="hc-unit">个火点</span></div>\n'
        '    <div class="hud-label">近2天 · 辐射功率 <span id="hud-frp">–</span> MW</div>\n'
        '    <div class="hud-status"><span class="dot-online"></span>SYSTEM ONLINE · 更新 '
        '<span id="hud-updated">–</span></div>\n'
        '    <div class="hc-more">查看详细统计 ›</div>\n'
        '  </div>\n'
        '  <div class="hud-card" id="hud-legend" data-modal="legend" title="点击查看图例与读图说明">\n'
        '    <div class="hud-kicker">LEGEND · 图例</div>\n'
        '    <div class="hc-row"><span class="lg-dot" style="background:#ef4444"></span>高置信火点'
        '<span class="lg-dot" style="background:#fb923c;margin-left:12px"></span>中/低置信</div>\n'
        '    <div class="frp-bar"></div>\n'
        '    <div class="frp-labels"><span>LOW</span><span>HIGH</span></div>\n'
        '    <div class="hc-row" style="margin-top:6px">'
        '<span class="lg-dot" style="background:#27ae60"></span>站点 AQI（数字为 AQI 值）</div>\n'
        '    <div class="hc-more">查看图例与读图说明 ›</div>\n'
        '  </div>\n'
    )
    html = html.replace('<div id="map"></div>', '<div id="map">\n  ' + cards + '</div>', 1)

    modal_html = (
        '<div id="card-modal">\n'
        '  <div class="cm-box">\n'
        '    <div class="cm-head"><b id="cm-title">详情</b><span id="cm-close">✕</span></div>\n'
        '    <div class="cm-body" id="cm-body"></div>\n'
        '  </div>\n'
        '</div>\n'
    )
    html = html.replace('<div class="toolbar">', modal_html + '<div class="toolbar">', 1)

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
        "🔥火点为 <b>NASA FIRMS 近实时卫星火点</b>（VIIRS 375m，页面联网读取 data/fires-henan.json，每 6 小时更新；"
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
    html = html.replace("每日08:15自动更新", "每 6 小时更新")

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
        '    <button id="lp-refresh" class="lp-refresh">🔄 获取当前数据</button>\n'
        '    <div class="lp-hint" id="lp-refresh-msg"></div>\n'
        '    <div class="lp-sum" id="lp-sum">加载中…</div>\n'
        '    <div id="lp-list"></div>\n'
        '    <div class="lp-note">每次抓取都记一条：<b>几点抓的 + 结果是什么</b>。<br>'
        '失败也会记，并写明原因。<br>云端每 6 小时自动抓取（UTC 00/06/12/18 的 :17）· 数据源 NASA FIRMS VIIRS 375m 近实时<br>'
        '「获取当前数据」= 立刻从服务器拉取已发布的最新一版（绕过缓存），不会触发新的卫星抓取</div>\n'
        '  </div>\n'
        '</div>\n'
    )
    html = html.replace('<div id="data-panel">', log_panel + '<div id="data-panel">', 1)

    # 14b. 日报脚注：更新频率 + 指向获取日志
    html = html.replace("每日自动更新", "每 6 小时自动更新 · 明细见「📜 获取日志」")
    html = html.replace("历史收集中，每日更新后累积", "历史收集中，每次更新后累积")

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
