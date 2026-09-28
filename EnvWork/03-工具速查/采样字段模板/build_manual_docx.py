# -*- coding: utf-8 -*-
"""生成《水和废水采样原始记录表》填表操作手册(.docx)。
依据真实受控空白表结构整理，已脱敏，面向非专业现场采样新人。"""
import os
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = r"c:\Users\jingh\WorkBuddy\20260326095724\环境实验-采样字段模板\水和废水采样填表操作手册.docx"

RED = RGBColor(0xC0, 0x39, 0x2B)
ACC = RGBColor(0x0A, 0x6E, 0x84)
GRAY = RGBColor(0x55, 0x5F, 0x6B)

steps = [
    ("委托编号", "任务单上给你的编号，相当于这批样品的“身份证号”。", "公司下发的《检测任务委托书》，照抄上面印的编号。", "", "WT-2026-0712", "别自己编！必须和任务单一字不差，后面所有样品都挂在这个号下面。"),
    ("采样日期", "你今天去现场采样的日子，年-月-日。", "看手机/手表上的当天日期。", "年-月-日", "2026-07-19", "不能填未来的日期；一般就填今天。"),
    ("天气状况", "采样当时外面的天气。", "抬头看天，如实选。", "", "晴 / 多云 / 阴 / 雨", "下雨会影响部分样品保存，别乱填，后续人要参考。"),
    ("方法依据", "按哪个标准方法测，通常固定填这一句。", "默认就抄下面这句，一般不用改。", "", "《水和废水监测分析方法》（第四版）增补版；透明度用塞氏盘法", "新手照抄默认内容即可，别留空。"),
    ("仪器编号及型号", "你手里这台采水器/采样设备的编号和型号。", "设备身上的铭牌，照抄。", "", "A-202 便携式采水器", "抄错号，这台设备以后溯源就找不到了。"),
    ("采样时间（起—止）", "你从几点开始采、到几点采完这一段。", "看手机计时。", "时:分 — 时:分", "09:00 — 09:15", "要填“起”和“止”两个时间，别只填一个点。"),
    ("样品编号", "给你采的这瓶水贴的标签号，按顺序编。", "按采样顺序自己编。", "", "S-001、S-002……", "每个号唯一、别重复；标签要用防水笔写在瓶身上，实验室就靠这串号找样品。"),
    ("分析项目", "这次这瓶水要化验哪些项目，从清单里勾。", "看任务单上写的要求测什么。", "", "勾 pH、COD、氨氮、石油类……", "你勾了什么，下一步“固定剂”就要对应加什么——系统会帮你核对。"),
    ("现场测定项目", "有些指标现场就能测，当场测当场记。", "手里的便携仪器能测哪些就勾哪些。", "", "pH、水温、DO、电导率、透明度、余氯", "本步可跳过不勾；现场测的别回实验室再补。"),
    ("样品性状", "这瓶水表面上看起来什么状态，如实勾。", "眼睛看、鼻子闻。", "", "微弱气味 / 少量浮油 / 肉眼可见物", "这是样品状态的证据，至少勾一项；没异常也至少勾一个描述。"),
    ("采样容器及固定剂", "装水的瓶子 + 你往里加了什么“保存药水（固定剂）”。", "瓶子看标签；固定剂看你上一步勾的分析项目。", "", "棕色玻璃瓶 + 加硫酸至 pH≤2", "★固定剂加错或漏加=这瓶水直接作废！拿不准就问。"),
    ("样品现场处理（固定剂勾选）", "把“加了哪种固定剂、对应哪些项目”再勾一遍，和上一格一致。", "系统已按你勾的分析项目预选好，你核对一下。", "", "加硫酸：COD、氨氮、总磷…", "和“容器及固定剂”那格要对得上，错一对不上就退回去改。"),
    ("溶解氧(DO)固定", "如果测溶解氧，必须“现场”往瓶里加两样药水并颠倒混匀。", "采样现场操作，看 SOP。", "", "加 1ml 硫酸锰 + 2ml 碱性碘化钾，盖严颠倒混合", "★必须现场固定！回实验室再加就晚了，这瓶 DO 数据作废。"),
    ("采样人员 / 校核 签字", "谁去采的、谁复核的，各签各的名。", "自己和复核人签字。", "", "采样：张三　校核：李四", "两人最好不是同一人；名字要能对应到人，以后溯源用。"),
    ("采样现场情况简述", "现场有什么特殊情况简单记一句，没有可跳过。", "现场观察。", "", "上游 500m 有排污口，水面有少量油污", "可跳过；但有明显异常建议写上，是数据背景。"),
]

red_lines = [
    ("加硫酸（pH≤2）", "测 COD、磷酸盐、总磷、总氮、氨氮、TOC 时必须加。"),
    ("加盐酸", "测 石油类、动植物油 时加。"),
    ("加氢氧化钠", "测 六价铬、氰化物 时加。"),
    ("加硝酸（pH≤2）", "测 硼、钠、钾、铜、锌、铍、镁、钙、锰、铁、镍、砷、镉、铅、银 等金属时加。"),
    ("溶解氧 DO", "现场加 1ml 硫酸锰 + 2ml 碱性碘化钾，盖严颠倒混合——回实验室再加就没用了。"),
    ("挥发酚", "先用磷酸调到合适 pH，再加 0.2g 抗坏血酸 除去水里残余的氯。"),
]

def set_run(r, size=11, color=None, bold=False):
    r.font.size = Pt(size)
    r.font.bold = bold
    if color is not None:
        r.font.color.rgb = color

doc = Document()
# 默认字体
style = doc.styles["Normal"]
style.font.name = "Microsoft YaHei"
style.element.rPr.rFonts.set(__import__("docx.oxml.ns", fromlist=["qn"]).qn("w:eastAsia"), "Microsoft YaHei")
style.font.size = Pt(11)

# 标题
h = doc.add_heading("水和废水采样原始记录表 · 填表操作手册", level=0)
sub = doc.add_paragraph("给现场采样新人的一步步说明——不用懂专业，照着填就能填对")
sub.runs[0].font.color.rgb = GRAY
sub.runs[0].font.size = Pt(10.5)
note = doc.add_paragraph("说明：本手册依据真实环境检测机构《水和废水采样原始记录表》结构整理，已做脱敏处理，作为通用培训模板使用。")
note.runs[0].font.color.rgb = GRAY
note.runs[0].font.size = Pt(9.5)

# 为什么重要
doc.add_heading("一、为什么这张表不能瞎填", level=1)
for t in ["样品靠编号找：实验室不认识你，只认样品编号。编号写错/重复，样品就找不回来了。",
          "固定剂加错=白跑：该加硫酸的没加，水样里的指标会变质，这瓶水直接作废，你得再跑一趟。",
          "它是法律证据：原始记录要存档，乱填后面核查说不清，责任算采样人的。"]:
    p = doc.add_paragraph(style="List Bullet"); set_run(p.add_run(t), 11)

# 红线
doc.add_heading("二、⚠️ 四条红线（固定剂，错一处样品就废）", level=1)
for name, desc in red_lines:
    p = doc.add_paragraph(style="List Bullet")
    r = p.add_run(name + "："); set_run(r, 11, RED, True)
    set_run(p.add_run(desc), 11)

# 分步
doc.add_heading("三、分步填表（共 15 步）", level=1)
for i, (title, what, frm, unit, ex, pit) in enumerate(steps, 1):
    doc.add_heading(f"第 {i} 步　{title}", level=2)
    p = doc.add_paragraph(); r = p.add_run("📝 这格填什么："); set_run(r, 10.5, ACC, True); set_run(p.add_run(what), 10.5)
    if frm:
        p = doc.add_paragraph(); r = p.add_run("🔍 数据从哪来："); set_run(r, 10.5, ACC, True); set_run(p.add_run(frm), 10.5)
    if unit:
        p = doc.add_paragraph(); r = p.add_run("📏 单位："); set_run(r, 10.5, ACC, True); set_run(p.add_run(unit), 10.5)
    if ex:
        p = doc.add_paragraph(); r = p.add_run("💡 举个例子："); set_run(r, 10.5, ACC, True); set_run(p.add_run(ex), 10.5)
    p = doc.add_paragraph(); r = p.add_run("⚠️ 别踩坑："); set_run(r, 10.5, RED, True); set_run(p.add_run(pit), 10.5)

# 填好的样例
doc.add_heading("四、填好的记录长这样（样例）", level=1)
sample = [
    "委托编号：WT-2026-0712", "采样日期：2026-07-19", "天气状况：晴",
    "方法依据：《水和废水监测分析方法》（第四版）增补版；透明度用塞氏盘法",
    "仪器编号及型号：A-202 便携式采水器", "采样时间：09:00 — 09:15", "样品编号：S-001",
    "分析项目：pH、COD、氨氮、石油类、铜、DO、挥发酚",
    "现场测定项目：pH、水温", "样品性状：微弱气味",
    "采样容器及固定剂：棕色瓶+加硫酸至pH≤2；加盐酸；加硝酸至pH≤2；加硫酸锰+碱性碘化钾(DO)；抗坏血酸(挥发酚)",
    "加硫酸项目：COD、氨氮　加盐酸项目：石油类　加氢氧化钠项目：无　加硝酸项目：铜",
    "溶解氧固定：加1ml硫酸锰+2ml碱性碘化钾，盖严颠倒混合",
    "采样人员：张三　　校核：李四", "现场情况：上游 500m 有排污口，水面少量油污",
]
for s in sample:
    p = doc.add_paragraph(style="List Bullet"); set_run(p.add_run(s), 10.5)

doc.save(OUT)
print("saved:", OUT, os.path.getsize(OUT), "bytes")
