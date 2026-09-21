# -*- coding: utf-8 -*-
# 单一数据源：定义 环境实验 环境采样字段模板，同时产出
#   sampling_fields.json  (可导入 LIMS 的字段 schema)
#   sampling_fields.html  (环境实验 风格预览/核查页)
# 说明：字段结构依据真实「环境检测机构采样原始记录空白表」抽取整理，
#       机构标识已脱敏，做成通用模板。

import json, os

OUT = os.path.dirname(os.path.abspath(__file__))

# ---------- 公共（跨域）字段 ----------
COMMON = [
    {"key":"entrust_no","label":"委托编号","group":"委托与任务信息","type":"text","required":True,"unit":None,"options":None,"qc":"任务溯源主键，必填"},
    {"key":"method_basis","label":"方法依据","group":"委托与任务信息","type":"text","required":True,"unit":None,"options":None,"qc":"填标准/规范号，如 HJ/T 166、GB 3096"},
    {"key":"sample_date","label":"采样/监测日期","group":"现场时空与环境","type":"date","required":True,"unit":None,"options":None,"qc":"年-月-日，必填"},
    {"key":"weather","label":"天气状况","group":"现场时空与环境","type":"select","required":True,"unit":None,"options":["晴","多云","阴","小雨","中雨","雷阵雨","雪","雾"],"qc":"现场必填，影响样品保存与工况判断"},
    {"key":"sample_no","label":"样品编号","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":"唯一编号，串联采样-交接-分析全链"},
    {"key":"instrument_model","label":"仪器型号","group":"仪器与校准溯源","type":"text","required":True,"unit":None,"options":None,"qc":"设备溯源，必填"},
    {"key":"sampler","label":"采样/监测人","group":"签字与归档","type":"text","required":True,"unit":None,"options":None,"qc":"责任人签字"},
    {"key":"reviewer","label":"校核","group":"签字与归档","type":"text","required":True,"unit":None,"options":None,"qc":"二级审核签字"},
]

# ---------- 四域字段 ----------
DOMAINS = {
  "water": {
    "label":"水和废水采样",
    "emoji":"💧","accent":"#2563eb",
    "formRef":"水和废水采样原始记录表",
    "qc_title":"样品保存与固定（核心质控）",
    "qc_points":[
      "按分析项目加固定剂：加硫酸(COD/磷酸盐/总磷/总氮/氨氮/TOC)、加盐酸(油类)、加氢氧化钠(六价铬)、加硝酸(金属类 B/Na/K/Cu/Zn/Be/Mg/Ca/Mn/Fe/Ni/As/Cd/Pb/Ag)",
      "溶解氧 DO：现场加硫酸锰+碱性碘化钾固定，盖严颠倒混合",
      "挥发酚：磷酸调 pH 后加 0.2g 抗坏血酸除去残余氯",
      "样品性状必记：气味(微弱/明显)、浮油(少量/大量)、臭和味、肉眼可见物"
    ],
    "fields":[
      {"key":"sample_date_w","label":"采样日期","group":"现场时空与环境","type":"date","required":True,"unit":None,"options":None,"qc":"含年/月/日"},
      {"key":"weather_w","label":"天气状况","group":"现场时空与环境","type":"select","required":True,"unit":None,"options":["晴","多云","阴","雨"],"qc":None},
      {"key":"instrument_no_w","label":"仪器编号及型号","group":"仪器与校准溯源","type":"text","required":True,"unit":None,"options":None,"qc":"溯源"},
      {"key":"sample_time","label":"采样时间","group":"现场时空与环境","type":"time_range","required":True,"unit":None,"options":None,"qc":"记录起止时间"},
      {"key":"container_fixative","label":"采样容器及固定剂","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":"容器材质+固定剂对应项目"},
      {"key":"analysis_items","label":"分析项目","group":"样品与检测项目","type":"multiselect","required":True,
        "options":["pH","SS","CODCr","BOD5","色度","氨氮","磷酸盐","总磷","总氮","石油类","动植物油","DO","CODMn","LAS","总铬","六价铬","铜","锌","铅","镉","镍","银","汞","砷","硼","铁","亚铁","锰","钾","钠","钙","镁","锡","硒","铝","铍","硅","氟化物","氰化物","苯系物","VOCs","硝酸盐","亚硝酸盐","挥发酚","硫化物","硫酸盐","甲醛","苯胺","氯化物","总硬度","总碱度","粪大肠菌群","总大肠菌群","大肠杆菌","菌落总数","臭和味","肉眼可见物","其他"],
        "qc":"勾选项目，决定固定剂与容器"},
      {"key":"onsite_items","label":"现场测定项目","group":"样品与检测项目","type":"multiselect","required":False,"options":["pH","水温","DO","电导率","透明度(塞氏盘)","余氯"],"qc":"现场即时测定"},
      {"key":"sample_trait","label":"样品性状","group":"现场性状/记录","type":"multiselect","required":True,"options":["微弱气味","明显气味","少量浮油","大量浮油","臭和味","肉眼可见物"],"qc":"描述性必填"},
      {"key":"fix_sulfuric","label":"加硫酸项目","group":"样品保存与固定(QC)","type":"multiselect","required":False,"options":["COD","磷酸盐","总磷","总氮","氨氮","TOC"],"qc":"硫酸固定 pH≤2"},
      {"key":"fix_hcl","label":"加盐酸项目","group":"样品保存与固定(QC)","type":"multiselect","required":False,"options":["油类"],"qc":"盐酸固定"},
      {"key":"fix_naoh","label":"加氢氧化钠项目","group":"样品保存与固定(QC)","type":"multiselect","required":False,"options":["六价铬"],"qc":"NaOH 固定"},
      {"key":"fix_hno3","label":"加硝酸项目","group":"样品保存与固定(QC)","type":"multiselect","required":False,"options":["硼","钠","钾","铜","锌","铍","镁","钙","锰","铁","镍","砷","镉","铅","银"],"qc":"硝酸固定 pH≤2"},
      {"key":"fix_do","label":"溶解氧固定","group":"样品保存与固定(QC)","type":"text","required":False,"unit":None,"options":None,"qc":"硫酸锰+碱性碘化钾，现场固定"},
      {"key":"situation","label":"采样现场情况简述","group":"现场性状/记录","type":"textarea","required":False,"unit":None,"options":None,"qc":None},
      {"key":"sketch","label":"采样布点示意图","group":"现场性状/记录","type":"file","required":False,"unit":None,"options":None,"qc":"附图"}
    ]
  },
  "air": {
    "label":"大气采样及现场检测",
    "emoji":"🌬️","accent":"#06b6d4",
    "formRef":"大气采样及现场检测原始记录表",
    "qc_title":"采样体积与吸收液（核心质控）",
    "qc_points":[
      "采样体积 = 吸收液体积 × 采样流量(L/min) × 采样时间(min)，三项须同时记录且可追溯",
      "环境条件必记：晴/阴、风速(m/s)、风向、气压(kPa)、气温 —— 用于标况体积换算",
      "多台采样仪器按 A/B/C/D 分别编号溯源",
      "采样布点示意图 + 现场情况简述必附"
    ],
    "fields":[
      {"key":"entrust_unit","label":"委托单位","group":"委托与任务信息","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"apply_no","label":"申请单号","group":"委托与任务信息","type":"text","required":False,"unit":None,"options":None,"qc":None},
      {"key":"inspected_unit","label":"受检单位","group":"委托与任务信息","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"sample_site","label":"采样地点","group":"现场时空与环境","type":"text","required":True,"unit":None,"options":None,"qc":"具体点位"},
      {"key":"env_cond","label":"环境条件","group":"现场时空与环境","type":"composite","required":True,"unit":None,"options":["晴","阴"],"qc":"含风速(m/s)/风向/气压(kPa)/气温"},
      {"key":"wind_speed","label":"风速","group":"现场时空与环境","type":"number","required":True,"unit":"m/s","options":None,"qc":None},
      {"key":"wind_dir","label":"风向","group":"现场时空与环境","type":"text","required":False,"unit":None,"options":None,"qc":None},
      {"key":"pressure","label":"气压","group":"现场时空与环境","type":"number","required":False,"unit":"kPa","options":None,"qc":None},
      {"key":"air_temp","label":"气温","group":"现场时空与环境","type":"number","required":False,"unit":"℃","options":None,"qc":None},
      {"key":"instrument_air","label":"采样仪器","group":"仪器与校准溯源","type":"text","required":True,"unit":None,"options":["A","B","C","D"],"qc":"多台分编号"},
      {"key":"measure_item","label":"测量项目","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"sample_pos","label":"采样位置","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"sample_period","label":"采样时段","group":"现场时空与环境","type":"time_range","required":True,"unit":None,"options":None,"qc":"起止时间"},
      {"key":"absorb_vol","label":"吸收液体积","group":"样品与检测项目","type":"number","required":True,"unit":"mL","options":None,"qc":"计算采样体积三要素之一"},
      {"key":"flow_rate","label":"采样流量","group":"样品与检测项目","type":"number","required":True,"unit":"L/min","options":None,"qc":"现场流量计读数"},
      {"key":"sample_time_min","label":"采样时间","group":"样品与检测项目","type":"number","required":True,"unit":"min","options":None,"qc":"累计采样时长"},
      {"key":"situation_air","label":"采样现场情况简述","group":"现场性状/记录","type":"textarea","required":False,"unit":None,"options":None,"qc":None},
      {"key":"sketch_air","label":"采样布点示意图","group":"现场性状/记录","type":"file","required":False,"unit":None,"options":None,"qc":"附图"}
    ]
  },
  "soil": {
    "label":"土壤采样",
    "emoji":"🌱","accent":"#d97706",
    "formRef":"土壤采样原始记录表",
    "qc_title":"土壤性状描述（核心质控）",
    "qc_points":[
      "方法依据：土壤环境监测技术规范 HJ/T 166-2004",
      "土壤性状必填四项：颜色 / 湿度 / 植物根系 / 土壤质地（均有标准选项）",
      "采样点及所在区域污染源、敏感人群、水域分布须画示意图",
      "样品编号 + 检测项目逐点对应，避免混样"
    ],
    "fields":[
      {"key":"sample_date_s","label":"采样日期","group":"现场时空与环境","type":"date","required":True,"unit":None,"options":None,"qc":None},
      {"key":"sample_period_s","label":"采样时段","group":"现场时空与环境","type":"time_range","required":False,"unit":None,"options":None,"qc":None},
      {"key":"weather_s","label":"天气状况","group":"现场时空与环境","type":"select","required":True,"unit":None,"options":["晴","多云","阴","雨"],"qc":None},
      {"key":"air_temp_s","label":"气温","group":"现场时空与环境","type":"number","required":False,"unit":"℃","options":None,"qc":None},
      {"key":"pressure_s","label":"气压","group":"现场时空与环境","type":"number","required":False,"unit":"kPa","options":None,"qc":None},
      {"key":"seq_no","label":"采样序号","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":"逐点序号"},
      {"key":"point_name","label":"采样点名称","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"test_items","label":"检测项目","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"soil_color","label":"颜色","group":"土壤性状描述","type":"select","required":True,"unit":None,"options":["红棕","黄棕","浅棕","暗栗","暗棕","暗灰","黑"],"qc":"性状四要素之一"},
      {"key":"soil_moist","label":"湿度","group":"土壤性状描述","type":"select","required":True,"unit":None,"options":["干","潮","湿","重潮","极潮"],"qc":"性状四要素之一"},
      {"key":"soil_root","label":"植物根系","group":"土壤性状描述","type":"select","required":True,"unit":None,"options":["无根系","少量","中量","多量","根密集"],"qc":"性状四要素之一"},
      {"key":"soil_texture","label":"土壤质地","group":"土壤性状描述","type":"select","required":True,"unit":None,"options":["砂土","沙壤土","轻壤土","中壤土","重壤土","粘土"],"qc":"性状四要素之一"},
      {"key":"sketch_soil","label":"污染源/敏感点/水域分布示意图","group":"现场性状/记录","type":"file","required":True,"unit":None,"options":None,"qc":"必附"}
    ]
  },
  "noise": {
    "label":"环境噪声监测",
    "emoji":"🔊","accent":"#8b5cf6",
    "formRef":"环境噪声监测原始记录表",
    "qc_title":"声级计前后校准（核心质控红线）",
    "qc_points":[
      "监测前后均须用校准器校准声级计，记录前后校准值(dB(A))，LIMS 应校验两者一致（一般偏差≤0.5dB）",
      "方法依据：GB 3096-2008 声环境质量标准",
      "监测目的二选一：声环境功能区监测 / 敏感建筑物监测",
      "声源及运行工况须说明（防止工况不符导致数据无效）"
    ],
    "fields":[
      {"key":"monitor_date","label":"监测日期","group":"现场时空与环境","type":"date","required":True,"unit":None,"options":None,"qc":None},
      {"key":"weather_n","label":"天气","group":"现场时空与环境","type":"select","required":True,"unit":None,"options":["晴","多云","阴","雨","雪","雾"],"qc":None},
      {"key":"wind_dir_n","label":"风向","group":"现场时空与环境","type":"text","required":False,"unit":None,"options":None,"qc":None},
      {"key":"wind_speed_n","label":"风速","group":"现场时空与环境","type":"number","required":True,"unit":"m/s","options":None,"qc":None},
      {"key":"monitor_purpose","label":"监测目的","group":"委托与任务信息","type":"select","required":True,"unit":None,"options":["声环境功能区监测","敏感建筑物监测"],"qc":None},
      {"key":"point_name_n","label":"监测点名称","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"main_sound","label":"主要声源","group":"样品与检测项目","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"sample_period_n","label":"采样时段","group":"现场时空与环境","type":"time_range","required":True,"unit":None,"options":None,"qc":None},
      {"key":"sound_meter","label":"声级计型号","group":"仪器与校准溯源","type":"text","required":True,"unit":None,"options":None,"qc":"设备溯源"},
      {"key":"cal_model","label":"校准器型号","group":"仪器与校准溯源","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"cal_no","label":"校准器编号","group":"仪器与校准溯源","type":"text","required":True,"unit":None,"options":None,"qc":None},
      {"key":"cal_before","label":"监测前校准值","group":"仪器与校准溯源","type":"number","required":True,"unit":"dB(A)","options":None,"qc":"前后比对红线"},
      {"key":"cal_after","label":"监测后校准值","group":"仪器与校准溯源","type":"number","required":True,"unit":"dB(A)","options":None,"qc":"前后比对红线"},
      {"key":"anemo_model","label":"风向风速仪型号","group":"仪器与校准溯源","type":"text","required":False,"unit":None,"options":None,"qc":None},
      {"key":"anemo_no","label":"风向风速仪编号","group":"仪器与校准溯源","type":"text","required":False,"unit":None,"options":None,"qc":None},
      {"key":"sketch_noise","label":"测点分布示意图","group":"现场性状/记录","type":"file","required":False,"unit":None,"options":None,"qc":None},
      {"key":"sound_source_desc","label":"声源及运行工况说明","group":"现场性状/记录","type":"textarea","required":True,"unit":None,"options":None,"qc":"工况必说明"}
    ]
  }
}

TYPE_LABEL = {"text":"文本","date":"日期","time_range":"时段","number":"数值","select":"单选","multiselect":"多选","composite":"复合","textarea":"长文本","file":"附件"}

# 汇总：生成 JSON
schema = {
  "meta":{
    "title":"环境实验 环境采样原始记录字段模板",
    "version":"1.0",
    "source":"环境检测机构采样原始记录空白表（真实结构抽取，机构标识已脱敏）",
    "domains":list(DOMAINS.keys()),
    "domain_labels":{k:v["label"] for k,v in DOMAINS.items()},
    "note":"字段可直接映射为 LIMS 采样模块录入表单；required=true 为必填项，qc 为质控要点"
  },
  "common":COMMON,
  "domains":{k:{"label":v["label"],"formRef":v["formRef"],"qc_title":v["qc_title"],"qc_points":v["qc_points"],"fields":v["fields"]} for k,v in DOMAINS.items()}
}
with open(os.path.join(OUT,"sampling_fields.json"),"w",encoding="utf-8") as f:
    json.dump(schema,f,ensure_ascii=False,indent=2)
print("JSON written:", os.path.join(OUT,"sampling_fields.json"))

# 生成 HTML
def field_rows(fields):
    out=[]
    for fld in fields:
        req = '<span class="req">必填</span>' if fld["required"] else '<span class="opt">选填</span>'
        unit = f' <i>({fld["unit"]})</i>' if fld.get("unit") else ''
        typ = TYPE_LABEL.get(fld["type"],fld["type"])
        if fld.get("options"):
            if fld["type"] in ("select","multiselect"):
                opts = "、".join(str(o) for o in fld["options"][:14])
                if len(fld["options"])>14: opts += " …"
            else:
                opts = "、".join(str(o) for o in fld["options"][:10])
        else:
            opts = "—"
        qc = f'<div class="qc">{fld["qc"]}</div>' if fld.get("qc") else ''
        out.append(f'<tr><td class="k">{fld["label"]}{unit}</td><td>{typ}</td><td>{req}</td><td class="o">{opts}</td><td>{qc}</td></tr>')
    return "\n".join(out)

def group_section(domain):
    v = DOMAINS[domain]
    a = v["accent"]
    # 按 group 分组
    groups={}
    for fld in v["fields"]:
        groups.setdefault(fld["group"],[]).append(fld)
    parts=[]
    for gname,fs in groups.items():
        is_qc = "QC" in gname
        cls = ' class="qcgrp"' if is_qc else ''
        parts.append(f'<div class="grp"{cls}><h4>{gname}</h4><table class="ft"><thead><tr><th>字段</th><th>类型</th><th>必填</th><th>选项/单位</th><th>质控要点</th></tr></thead><tbody>{field_rows(fs)}</tbody></table></div>')
    qc_cards="".join(f'<li>{p}</li>' for p in v["qc_points"])
    return f'''
<section class="dom" id="{domain}" style="--a:{a}">
  <div class="dom-h"><span class="em">{v["emoji"]}</span><div><h2>{v["label"]}</h2><div class="sub">依据空白表：{v["formRef"]}</div></div><span class="cnt">{len(v["fields"])} 字段</span></div>
  <div class="callout"><b>{v["qc_title"]}</b><ul>{qc_cards}</ul></div>
  {''.join(parts)}
</section>'''

common_rows = field_rows(COMMON)

# 跨域对比表
cmp_rows = ""
cmp_map = {
  "water":"样品保存与固定（固定剂按项目添加）",
  "air":"采样体积三要素（吸收液/流量/时间）",
  "soil":"土壤性状四要素（颜色/湿度/根系/质地）",
  "noise":"声级计监测前后校准值比对"
}
for k,v in DOMAINS.items():
    cmp_rows += f'<tr><td><span class="dot" style="background:{v["accent"]}"></span>{v["label"]}</td><td>{cmp_map[k]}</td><td>{v["qc_title"]}</td></tr>'

html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>环境实验 环境采样字段模板</title>
<style>
:root{{--bg:#0a0e17;--card:#121826;--line:#23304a;--ink:#e7eefc;--mut:#8aa0c0;--a:#2563eb;}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#16203a 0,var(--bg) 60%);color:var(--ink);font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.55}}
.wrap{{max-width:1080px;margin:0 auto;padding:34px 22px 80px}}
header.hero{{padding:30px 0 18px;border-bottom:1px solid var(--line);margin-bottom:26px}}
.tag{{display:inline-block;font-size:12px;letter-spacing:.12em;color:var(--mut);border:1px solid var(--line);padding:4px 10px;border-radius:999px}}
h1{{font-size:30px;margin:14px 0 6px}}
.lead{{color:var(--mut);max-width:760px}}
.chips{{margin-top:16px;display:flex;gap:10px;flex-wrap:wrap}}
.chip{{padding:7px 13px;border-radius:10px;background:var(--card);border:1px solid var(--line);font-size:13px;cursor:pointer;text-decoration:none;color:var(--ink)}}
.chip:hover{{border-color:var(--a)}}
h2{{font-size:22px;margin:0}}
h3{{font-size:17px;margin:34px 0 10px}}
.dom{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin:22px 0;overflow:hidden}}
.dom-h{{display:flex;align-items:center;gap:14px;border-left:5px solid var(--a);padding-left:14px;margin-bottom:14px}}
.dom-h .em{{font-size:30px}}
.dom-h .sub{{color:var(--mut);font-size:13px}}
.dom-h .cnt{{margin-left:auto;font-size:12px;color:var(--mut);border:1px solid var(--line);padding:4px 10px;border-radius:999px}}
.callout{{background:color-mix(in srgb,var(--a) 14%,#0b1020);border:1px solid color-mix(in srgb,var(--a) 40%,var(--line));border-radius:12px;padding:12px 16px;margin:6px 0 18px;font-size:14px}}
.callout b{{color:var(--a)}}
.callout ul{{margin:8px 0 0;padding-left:20px;color:var(--ink)}}
.callout li{{margin:3px 0}}
.grp{{margin:14px 0}}
.grp.qcgrp{{border:1px dashed color-mix(in srgb,var(--a) 50%,var(--line));border-radius:12px;padding:10px 14px;background:rgba(255,255,255,.02)}}
.grp h4{{margin:4px 0 8px;font-size:14px;color:var(--a)}}
table.ft{{width:100%;border-collapse:collapse;font-size:13px}}
.ft th{{text-align:left;color:var(--mut);font-weight:600;border-bottom:1px solid var(--line);padding:7px 8px}}
.ft td{{border-bottom:1px solid #1a2236;padding:8px;vertical-align:top}}
.ft td.k{{font-weight:600;min-width:130px}}
.ft td.o{{color:var(--mut);max-width:240px}}
.ft td .qc{{color:#cfe0ff;font-size:12px}}
.req{{color:#ff6b8a;font-size:11px;border:1px solid #ff6b8a55;border-radius:6px;padding:1px 6px}}
.opt{{color:var(--mut);font-size:11px;border:1px solid var(--line);border-radius:6px;padding:1px 6px}}
section.common{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 22px;margin:22px 0}}
.cmp{{width:100%;border-collapse:collapse;margin-top:10px;font-size:14px}}
.cmp th{{text-align:left;color:var(--mut);border-bottom:1px solid var(--line);padding:8px}}
.cmp td{{border-bottom:1px solid #1a2236;padding:9px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;vertical-align:middle}}
footer{{margin-top:40px;padding-top:18px;border-top:1px solid var(--line);color:var(--mut);font-size:12px;text-align:center}}
</style></head>
<body><div class="wrap">
<header class="hero">
  <span class="tag">环境实验 · 采样字段模板 v1.0</span>
  <h1>环境采样原始记录 · 字段清单 / 模板</h1>
  <p class="lead">依据真实「环境检测机构采样原始记录空白表」抽取整理，覆盖 <b>水 / 气 / 土 / 噪声</b> 四大域。机构标识已脱敏，字段可直接映射为 LIMS 采样模块录入表单；标注「必填」为关键项，标注质控要点为红线项。</p>
  <div class="chips">
    <a class="chip" href="#water">💧 水和废水</a>
    <a class="chip" href="#air">🌬️ 大气</a>
    <a class="chip" href="#soil">🌱 土壤</a>
    <a class="chip" href="#noise">🔊 噪声</a>
    <a class="chip" href="#common">📋 公共字段</a>
  </div>
</header>

<section class="common" id="common">
  <h3>📋 跨域公共字段（四域通用）</h3>
  <table class="ft"><thead><tr><th>字段</th><th>类型</th><th>必填</th><th>选项/单位</th><th>质控要点</th></tr></thead><tbody>{common_rows}</tbody></table>
</section>

{group_section("water")}
{group_section("air")}
{group_section("soil")}
{group_section("noise")}

<h3>四域质控红线速览</h3>
<table class="cmp"><thead><tr><th>域</th><th>核心动作</th><th>质控主题</th></tr></thead><tbody>{cmp_rows}</tbody></table>

<footer>环境实验 采样字段模板 · 依据真实空白表脱敏整理 · 配套 sampling_fields.json 可导入 LIMS</footer>
</div></body></html>'''

with open(os.path.join(OUT,"sampling_fields.html"),"w",encoding="utf-8") as f:
    f.write(html)
print("HTML written:", os.path.join(OUT,"sampling_fields.html"))
print("domains:", {k:len(v["fields"]) for k,v in DOMAINS.items()}, "common:", len(COMMON))
