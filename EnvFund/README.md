# 环保资金申报智能决策系统 V1.0

**政策解析 Agent + JEV 硬规则审查引擎 + 项目申报匹配**

适用范围：国家级 / 省级生态环境资金申报指南。

---

## 快速启动

```bash
pip install -r requirements.txt

# 配置模型（可选，不配则走离线模式）
cp .env.example .env && vi .env     # 填入 ENV_AGENT_API_KEY

# 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- 管理后台：http://localhost:8000
- 接口文档：http://localhost:8000/docs

```bash
# 回归测试
python tests/test_engine.py

# 规则覆盖率分析（用真实指南找漏报）
python tools/rule_coverage.py corpus/ --json data/coverage_report.json

# 命令行解析
python -m app.cli -i samples/某省水污染防治资金申报指南.txt \
    -t "XX省水污染防治资金申报指南" --issuer "XX省生态环境厅" --brief
```

---

## 架构

```
政策 PDF / OCR 文本
   ↓  app/parser          文档解析层（切段编号 P001、P002…）
   ↓  app/llm             LLM 语义抽取（容错解析 + 段号回填校验）
   ↓  app/jev             JEV 硬规则终审（EXCLUDE > FORCE > WEIGHT）
   ↓  证据链               每个领域决策带原文定位与命中规则
   ↓  app/schemas         Pydantic 结构化输出
   ↓  app/rag             BM25 检索 + 项目匹配
   ↓  app/main            FastAPI 接口 + 管理后台
```

**RAG 的定位说明**：单份指南全文能直接进上下文，**不需要 RAG**。RAG 的真实价值在
「一个项目 → 检索多份政策」这一步，因此检索层服务于 matching，不放在单文档抽取前面。

**规则为什么是 JSON 不是 py**：规则是数据不是代码。拆成 `rules_water.py` 之类会让
非技术人员无法维护，也失去"改规则不动代码"的能力。全部声明在 `data/jev_rules.json`。

---

## 目录结构

```
env-fund-agent/
├── app/
│   ├── main.py              FastAPI 入口 + 管理后台
│   ├── services.py          服务编排（解析→抽取→终审→匹配）
│   ├── cli.py               命令行工具
│   ├── parser/
│   │   └── document.py      PDF/文本解析、切段编号、层级闸门
│   ├── llm/
│   │   ├── client.py        OpenAI 兼容调用（零第三方依赖）
│   │   └── parser.py        输出容错解析、段号回填校验
│   ├── jev/
│   │   └── engine.py        规则终审引擎
│   ├── rag/
│   │   ├── store.py         政策知识库 + BM25 检索
│   │   └── matching.py      项目画像 + 匹配打分
│   └── schemas/
│       └── models.py        Pydantic 数据契约
├── data/jev_rules.json      规则库（唯一数据源）
├── prompts/policy_agent.txt 系统提示词
├── corpus/                  真实指南语料库（见 corpus/README.md）
│   ├── central/             中央级
│   └── provincial/          省级
├── tools/rule_coverage.py   规则覆盖率分析器
├── samples/                 样例指南
├── tests/test_engine.py     62 项全链路回归测试
└── requirements.txt
```

---

## 规则池怎么扩

**不要凭常识臆造词表** —— 那只是把幻觉从模型搬进规则文件。必须由真实语料驱动：

```bash
# 1. 把指南放进 corpus/（要求见 corpus/README.md）
# 2. 跑覆盖率分析
python tools/rule_coverage.py corpus/ --json data/coverage_report.json
# 3. 按「未被任何规则覆盖的术语」排行，定向补锚点词
# 4. 回归：两个都过才算改完
python tests/test_engine.py
python tools/rule_coverage.py corpus/
```

**漏报清单要分两类处理：**

| 类型 | 例子 | 处理 |
| --- | --- | --- |
| 领域特征词 | 湖库、石漠化、生物多样性 | ✅ 补进对应标签 |
| 资金机制词 | 补助、绩效、以奖代补、中央 | ❌ **不补** |

机制词所有指南都有，进了领域规则会让规则失去区分度
（"补助"加进 WATER 规则，那所有指南都会命中 WATER）。它们属于字段抽取范畴。

---

## JEV 校验状态（替代"可信度 100%"）

规则引擎只能保证**规则命中确定性**，不能宣称整份政策解析绝对正确。
因此不输出百分比，只输出可核查的状态：

```json
"jev": {
  "status": "PASS",
  "confidence_band": "HIGH",
  "force_rules": ["F-WATER-01", "F-WATER-03", "F-GW-01"],
  "exclude_rules": [],
  "force_rule_count": 3,
  "conflict_count": 0,
  "evidence_count": 5,
  "llm_agreement": true,
  "weight_rule_applied": "W-06"
}
```

| 字段 | 含义 |
| --- | --- |
| `status` | PASS / CONFLICT / REVIEW / FAIL |
| `confidence_band` | 由状态**推导**的区间，非系统自称的百分比 |
| `force_rules` | 命中的强制规则 ID 清单 |
| `exclude_rules` | 命中的排除规则 ID 清单 |
| `conflict_count` | 强制与排除规则冲突条数 |
| `evidence_count` | 原文证据条数 |
| `llm_agreement` | LLM 候选标签集与规则终审集是否一致 |

`confidence_band` 推导规则：`FAIL` → LOW；有冲突或无证据 → MEDIUM；否则 HIGH。

---

## 证据链

每个领域判定都带完整依据，这是可解释、可审计的载体：

```json
{
  "domain": "水生态水环境",
  "domain_code": "WATER",
  "decision": "PRIMARY",
  "evidence": [
    {
      "text": "支持流域水生态环境综合治理、集中式饮用水水源地保护",
      "matched_term": "流域治理",
      "span": "P003",
      "source_type": "policy_original_text"
    }
  ],
  "matched_rules": ["F-WATER-01", "F-WATER-03"],
  "excluded_by_rules": []
}
```

`decision` 取值：`PRIMARY` / `SECONDARY` / `EXCLUDED`。

---

## 项目匹配

```bash
curl -X POST localhost:8000/match -H 'Content-Type: application/json' -d '{
  "project": "某县拟建设农村生活污水治理项目，总投资3200万元。",
  "top_k": 5
}'
```

输出含匹配度、支持方向、申报主体要求、缺失材料、**以及匹配/不匹配的理由**。

匹配因子权重（可调）：

| 因子 | 权重 | 说明 |
| --- | --- | --- |
| domain | 0.40 | 领域契合度，最重要 |
| negative | 0.25 | 负面清单一票否决项 |
| region | 0.15 | 适用地域范围 |
| applicant | 0.10 | 申报主体要求 |
| funding | 0.10 | 资金方式 |

**匹配度不是可信度。** 它是项目与政策的契合程度，由可拆解因子加权得出，
每个因子结论都带依据，便于人工复核。领域完全不搭时直接判不匹配，不给假阳性。

---

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 + 规则库统计 |
| GET | `/rules` | 查看规则库（便于人工核对） |
| POST | `/analyze/text` | 解析文本指南（`store=true` 入库） |
| POST | `/analyze/file` | 上传 .txt / .md / .pdf 解析 |
| GET | `/policies` | 政策库列表 |
| GET | `/policies/{doc_id}` | 政策详情 |
| DELETE | `/policies/{doc_id}` | 删除政策 |
| POST | `/match` | 项目 → 政策匹配 |
| GET | `/` | 管理后台 |

---

## 人工复核触发条件

任一命中即 `needs_human_review = true`：

- 无强制规则命中
- 排除与强制规则冲突
- 语义层给出但规则层无依据的标签
- 多标签无权重规则覆盖且命中条数并列
- 剔除编造段号 / 标签池外标签 / 不符原文的摘录
- 模型未返回必需字段
- 模型输出经裁剪或语法修复

---

## 扩展规则

改 `data/jev_rules.json`，不用动代码：

```json
{
  "id": "F-WATER-05",
  "label": "WATER",
  "any": ["生态缓冲带", "河岸带修复"],
  "note": "滨水缓冲带类"
}
```

排除规则用 `all` / `any` / `none` 三条件组合，`none` 是保护词
（命中则排除规则失效，防止误杀）：

```json
{
  "id": "X-WATER-01",
  "label": "WATER",
  "all": ["管网"],
  "any": [],
  "none": ["黑臭水体", "入河排污口", "水生态", "水质提升", "水体治理"],
  "note": "仅管网建设、无水体治理目标 → 不打水环境主标"
}
```

**锚点词必须可枚举、可 grep。** 别写"无××目标"这类需要语义判断的条件 —— 那等于没校验。

---

## 已知限制

| 项 | 说明 |
| --- | --- |
| 规则池覆盖度 | 27 条强制规则不足以覆盖全部指南，需真实文档回归驱动扩池 |
| 否定作用域 | 按句号/分号/换行截断，复杂嵌套否定仍可能漏判 |
| 同义词 | 有基础同义词表，覆盖有限，需持续补充 |
| OCR 表格 | 指南常以表格列支持方向，表格结构丢失影响抽取 |
| 检索 | BM25 词法检索，语义改写明显的查询召回有限，可替换为向量检索 |
| 存储 | 政策库为内存 + JSON 文件，生产环境需换数据库 |
| 主体识别 | 项目画像靠正则，表达不规范时字段会缺失（已做留空处理，不猜测） |

---

## 下一步方向

真正的壁垒会从 Prompt 转移到 **JEV 规则库 + 政策知识库 + 项目匹配数据 + 历史申报案例**。
建议优先级：

1. **规则池回归** —— 收 20-30 份真实指南，跑出漏报清单后定向补锚点词
2. **政策知识库扩充** —— 中央 + 各省历年指南入库，匹配才有基数
3. **历史申报案例** —— 有了"哪些项目申报成功/失败"的数据，匹配才能从规则走向实证
4. **OCR 表格处理** —— 支持方向大量以表格呈现，这是抽取质量的下一个瓶颈
