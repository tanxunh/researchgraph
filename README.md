# ResearchGraph

> 面向技术论文的可追溯 AI 研究助手
>
> Evidence-grounded AI Research Assistant

ResearchGraph 是一个面向技术论文的全栈研究助手。上传 PDF 后，你可以建立可版本追踪的论文库，搜索原文 Evidence、提出问题，或比较多篇论文的方法与发现。回答和研究报告中的 Citation 可打开对应证据；引用或证据归属验证失败时，系统会 fail closed，拒绝将未经验证的内容作为可信结果返回。

### 核心能力

- **论文库**：异步导入、持久化索引任务、文档详情与版本。
- **混合检索**：在全部、单篇或多篇论文中寻找相关 Evidence。
- **证据化问答**：从回答中的 `[C1]` 打开 Evidence Panel，核对原文。
- **跨论文 Research**：生成结构化 Comparison，展示覆盖情况、引用和执行记录。

## 30 秒理解 ResearchGraph

```mermaid
flowchart LR
    PDF[上传 PDF] --> Index[异步解析与索引]
    Index --> Search[Search]
    Search --> Evidence[版本化 Evidence]
    Evidence --> QA[Grounded QA]
    Evidence --> Research[跨论文 Research]
    QA --> Validation[Citation Validation]
    Research --> Validation
    Validation -->|通过| Result[带 Citation 的回答 / 报告]
    Validation -->|失败| Closed[Fail Closed]
    Result -->|点击引用| Panel[Evidence Panel]
    Evidence -.-> Panel
```

## 为什么做这个项目？

研究者需要知道结论来自哪篇论文、哪个版本、哪段原文。仅有引用标记还不够：引用可能不存在，多论文分析可能混淆证据归属，论文重新处理后旧引用也可能失效。

因此，ResearchGraph 将 Evidence 作为一等对象，用不可变版本保留证据身份，用 Citation 验证和 Fact ownership 约束引用关系。生成结果必须经过验证才能成为可信报告；失败会明确呈现，而不是隐藏在一段看似正常的回答中。

## 你可以用它做什么？

**管理与搜索论文。** 在 Library 上传 PDF，查看 Jobs 的索引阶段、失败原因和文档版本。在 Search 限定单篇或多篇论文，打开 Top matching Evidence。检索结果按相关性排序，不保证每条都能回答问题。

**提问与比较。** 在 Ask 输入问题，从 Answer 的 `[C1]` 回到 Evidence Panel。在 Research 选择多篇论文，提出“比较方法、优化目标与主要发现”等问题，查看结构化报告、Comparison 和证据。引用可定位到具体版本与 Chunk，而不只是论文标题。

## 使用流程

1. 在 Library 上传有权处理的论文。
2. 等待 Index Job `succeeded`，确认文档为 `Ready`。
3. 在 Search 检查能否找到相关 Evidence。
4. 在 Ask 提出单次问题，获取带 Citation 的回答。
5. 在 Research 选择多篇论文，执行跨论文分析。
6. 点击 Citation 核对原文、版本和 locator；检查缺失覆盖及失败状态。

<a id="architecture"></a>

## 系统架构

```mermaid
flowchart TB
    subgraph Product[Product]
        UI[React 工作区]
    end
    subgraph Application[Application]
        API[FastAPI]
        Index[文档 / 异步索引]
    end
    subgraph AI[AI]
        Retrieval[BM25 + BGE + RRF]
        Evidence[Evidence 层]
        QA[Grounded QA]
        Research[LangGraph Research]
        Harness[Agent Harness]
        LLM[统一 LLM Client]
    end
    subgraph Data[Data]
        SQL[(MySQL 权威数据源)]
        Chroma[(Chroma 派生向量索引)]
    end
    UI -->|REST API| API
    API --> Index
    API --> Retrieval
    API --> QA
    API --> Research
    Index --> SQL
    Index --> Chroma
    SQL --> Retrieval
    Chroma --> Retrieval
    Retrieval --> Evidence
    Evidence --> QA
    Evidence --> Research
    Research --> Harness
    Harness --> LLM
    QA --> LLM
```

MySQL 保存 Document、DocumentVersion、Chunk、IndexJob 和 Evidence metadata，是权威数据源。Chroma 只服务当前活跃版本，是可重建的向量索引。系统通过最终一致性、权威候选校验和 reconciliation 处理跨存储失败；原始文件单独持久化，历史证据保留在 MySQL。

### 关键设计选择

| 组件 / 决策 | 职责与原因 |
|---|---|
| MySQL 权威、Chroma 派生 | 保留证据身份，同时允许重建搜索索引 |
| 普通 QA 使用直接服务调用 | 避免不必要的 Agent 编排 |
| RRF 融合排名 | 避免直接相加不同尺度的检索分数 |
| LangGraph + Harness | 分开管理工作流状态与受约束执行 |
| 单进程 Index Worker | 复用索引管线，以 MySQL 持久化任务；当前无需分布式队列 |
| Reranker 可选、Graph 条件启用 | 保留实验观察到的收益，同时控制延迟和适用范围 |

## Evidence-first 设计

Evidence 可沿 **Document → Document Version → Chunk → Page / Section → Snippet** 追溯，页码与章节取决于解析结果。稳定 locator 为 `document_id + document_version_id + chunk_id`；`C1` 只是单次回答内的显示标识。

不可变版本使旧引用在论文重新处理后仍可解析。当前 Citation validation 验证结构、引用关系和证据归属，**不等于完整的 semantic entailment verification**：引用存在，并不意味着原文完全支持整句话。

## 混合检索：产品配置与冻结评估配置

BM25 匹配词项，Dense Retrieval 提供语义候选，RRF 融合排名，cross-encoder 对候选 Evidence 重排。**Frozen V2 evaluation configuration 不是当前 production default**；Quick Start 启动的是产品默认配置。

| 参数 | 产品默认配置 | Frozen V2 evaluation configuration |
|---|---|---|
| Dense | BAAI/bge-small-zh-v1.5，512 维，CPU | BAAI/bge-m3，1024 维 |
| Candidate depth | 产品当前配置 | BM25 200 + Dense 200 |
| Fusion | RRF，k=60 | Weighted RRF，BM25=1.25 / Dense=1.0，k=20 |
| Reranker | optional，默认 OFF | BAAI/bge-reranker-base |
| Reranker input / output | 显式请求配置 | Top20 → Top10 |
| Chunking | TextChunker | target_chars=700，overlap=100，page-contained |

模型 revision、索引身份和冻结哈希见 [final retrieval manifest](benchmarks/real_research/v2/final_retrieval_manifest.json)。其 `PRODUCTION_DEFAULT=false`；只更换模型名称不足以复现 V2。

Search 按相关性排名，不使用未经校准的 relevance threshold。Graph 保留条件检索架构，默认关闭抽取；真实语料 Graph/Auto 尚未验证。

## Grounded QA

Question → Scoped Retrieval → Evidence → LLM → Citation Validation → Answer / Fail Closed。

回答必须绑定 Evidence，只返回实际使用的引用；没有 Evidence 时不调用 LLM，非法 Citation 和模型失败不会被包装成可信回答。普通 Search / QA 不经过 Agent workflow。

## 跨论文 Research

只有 Research 使用 LangGraph，管理计划、状态、覆盖检查和受限补充检索。

```mermaid
flowchart LR
    Plan --> Retrieve --> Extract[Extract Facts] --> Coverage[Coverage Check]
    Coverage -->|缺失且预算允许| Refine[Refine Query]
    Refine --> Retrieve
    Coverage -->|充分或允许的部分结果| Synthesize
    Synthesize --> Validate[Validate Citation]
    Validate -->|通过| Report[Report]
    Validate -->|失败| Closed[Fail Closed]
```

这是 bounded workflow：补充检索与执行次数受预算限制，不是无限循环。支持的部分结果会明确标记覆盖不足；违反证据约束的结果不能成为可信报告。

## Agent Harness

LangGraph 决定“下一步做什么”；Harness 约束“如何执行模型和 Tool 调用”。它统一管理 timeout、受限 retry、schema validation、tool allowlist、execution budget 和 trace。执行记录用于解释步骤与故障，不代表模型的私有推理过程。

## 关键正确性设计：跨文档证据归属

单篇论文的 Fact 必须由同一文档、同一版本的 Evidence 支持。ResearchGraph 按文档与版本隔离 Fact extraction 的输入，并通过 `fact_document_mismatch` 校验拒绝跨文档误绑定，确保每项事实的来源边界明确。

跨论文组合只发生在 Synthesis 层。Comparison 的 Citation 由后端从已验证的 Fact supports 确定性绑定，而非由模型自由选择。这项由真实评估驱动的设计使证据归属可核对，但不替代人工语义审核。

## 快速开始

> [!TIP]
> 如果只想体验论文上传、索引和 Search，可以暂不配置 LLM API Key。Ask 和 Research 需要配置 OpenAI-compatible LLM；默认示例使用 DeepSeek。

### 1. 环境要求与克隆

推荐 Git + Docker Desktop（Linux containers）或 Docker Engine + Compose v2。Docker 路径不要求本机单独安装 Python / Node；首次构建和模型下载需要网络。

仓库发布并获得访问权限后：

```sh
git clone https://github.com/tanxunh/researchgraph.git
cd researchgraph
```

### 2. 配置环境

在仓库根目录复制模板，不覆盖已有 `.env`。

Windows PowerShell：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

macOS / Linux：

```sh
test -f .env || cp .env.example .env
```

编辑 `.env`：必须替换两个数据库密码占位符。`MYSQL_PASSWORD` 会拼入连接 URL，按模板要求使用 URL-safe 字母数字密码。以下 LLM 配置可先保持 Key 为空：

```dotenv
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
GRAPH_EXTRACTION_ENABLED=false
```

| 变量 | 是否必须 | 默认 / 模板值 | 说明 |
|---|---|---|---|
| `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD` | 必须设置 | 占位符，需替换 | 数据库初始化与应用连接 |
| `MYSQL_USER` / `MYSQL_DATABASE` | 保留即可 | `lifeflow` / `lifeflow_researchgraph` | 当前真实默认名称 |
| `MYSQL_HOST` / `MYSQL_PORT` | 保留即可 | `mysql` / `3306` | 容器内连接地址 |
| `CHROMA_HOST` / `CHROMA_PORT` | 保留即可 | `chroma` / `8000` | 容器内向量服务 |
| `LLM_API_KEY` | Ask / Research 必须 | 空 | Library / Search 不需要 |
| `LLM_BASE_URL` / `LLM_MODEL` | 使用 LLM 时需要 | 上方示例 | OpenAI-compatible 接口，无 `LLM_PROVIDER` 变量 |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` | 保留即可 | `bge` / `BAAI/bge-small-zh-v1.5` | CPU embedding |
| `GRAPH_EXTRACTION_ENABLED` | 保留即可 | `false` | 基础产品无需 Graph 抽取 |
| `VITE_API_BASE_URL` | Docker 保留 | `/` | nginx 同源代理，构建时生效 |

其余配置见 [.env.example](.env.example)。Ask / Research 会发送必要 Evidence 片段至配置的 LLM，请确认拥有相应数据发送权限。

### 3. 构建、迁移、启动

首次启动在仓库根目录依次执行：

```sh
docker compose config --quiet
docker compose build
docker compose run --rm backend python -m scripts.migrate_all
docker compose up -d
```

迁移命令会启动并等待 MySQL、Chroma 健康，再依次执行证据版本、异步任务和任务创建时间迁移。迁移失败时先处理错误，不要继续启动应用。已有数据库升级前应备份 MySQL 与原始文件并停止写入，详见[部署说明](docs/deployment.md)。

## 验证是否启动成功

```sh
docker compose ps
```

预期 `frontend`、`backend`、`mysql`、`chroma` 均运行，并在初始化完成后显示 healthy。

- 前端：http://127.0.0.1:5173 ，侧栏显示 Backend Online。
- Backend health：http://127.0.0.1:8000/health ，预期 `code=0`、`data.status="ok"`。
- 前端代理健康接口：http://127.0.0.1:5173/health 。
- Swagger：http://127.0.0.1:8000/docs 。

健康检查不代表 BGE 已加载。模型采用 lazy loading，首次索引或检索可能下载权重并额外等待；`/api/system/status` 提供 loaded / ready / error 状态。

## 第一次使用

打开 Library 上传 PDF → 等待 Jobs `succeeded` 和文档 `Ready` → Search 查询并核对 Evidence → 配置 LLM 后使用 Ask → 准备至少两篇 Ready 论文再进入 Research。暂不配置 LLM 时，先完成论文导入与搜索即可。

## 常见问题

1. **Backend Offline**：运行 `docker compose ps` 和 `docker compose logs --tail=100 backend`，检查依赖健康状态、迁移和启动错误。
2. **LLM configuration error**：确认根 `.env` 的 Key、URL、模型名；修改后执行 `docker compose up -d` 更新容器配置。
3. **BGE 首次加载慢**：检查模型下载网络和 backend 日志；缓存会保留，健康接口不会提前加载模型。
4. **MySQL / migration 失败**：查看 `docker compose logs --tail=100 mysql`；已有 volume 的账户密码不会因修改 `.env` 自动改变，勿删除数据来绕过错误。
5. **端口冲突**：调整 `FRONTEND_PORT`、`BACKEND_PORT`、`MYSQL_PUBLISHED_PORT`、`CHROMA_PUBLISHED_PORT`，默认分别为 5173、8000、3307、8001；容器内地址保持不变。
6. **停止与重置**：MySQL、Chroma、原始文件和模型缓存使用 named volumes。`docker compose down` 保留它们；**`docker compose down -v` 会删除本项目持久数据**，不要用于普通排障。更换 Compose 项目名也会选用另一组 volumes。

> [!WARNING]
> `docker compose down -v` 会删除本项目的本地持久化数据。

## 本地开发

需要 Python / Node 的本地开发步骤见 [Backend](backend/README.md) 和 [Frontend](frontend/README.md)；Docker 是推荐复现路径。

<details>
<summary>测试命令</summary>

配置环境后，从根目录运行隔离的后端测试：

```sh
docker compose --profile test run --build --rm --no-deps backend-tests
```

前端测试与构建：

```sh
cd frontend
npm ci
npm test -- --run
npm run build
```

自动化测试使用 Fake Embedding 与 mocked LLM；真实存储测试边界见[测试说明](docs/testing_ci.md)。这些测试不等于真实模型质量评估。

</details>

<a id="evaluation"></a>

## V2 Frozen TEST

30 篇真实论文，35 DEV / 40 TEST。DEV 用于配置选择；retrieval stack was frozen before TEST；**TEST was evaluated once；no post-TEST retrieval tuning**。Evidence 指标按 Gold locator 计算，多 Gold 使用真正 Recall，不能用 Document Hit 替代。

| Route | R@10 | MRR@10 | CR@20 | CR@50 |
|---|---:|---:|---:|---:|
| BM25 | 39.58% | 0.2900 | 51.04% | 72.29% |
| Dense | 42.92% | 0.3087 | 52.92% | 71.88% |
| Hybrid | 46.25% | 0.2830 | 62.50% | 79.38% |
| Final reranked | 59.17% | 0.3802 | — | — |

Final reranked：R@5 **45.83%**，Hit@5 **55.00%**。相对 Hybrid Top10，reranker recovered **6 Gold evidence units and lost 1**。CR 是重排输入前候选覆盖，不从最终 Top10 重新计算。**Cross-document TEST remains a severe limitation**；这些是固定小样本上的观察，不是统计泛化结论。

## End-to-End Research Workflow POC

Workflow runtime = **RECONSTRUCTED_EVALUATION_RUNTIME**，不是 historical production runtime。Review method = **MODEL_ASSISTED_SEMANTIC_REVIEW**，不是 independent human evaluation。

| Track | Complete | Partial | Incorrect | Correctly cited complete |
|---|---:|---:|---:|---:|
| A — FROZEN_CONTEXT | 23/40 (57.50%) | 9/40 (22.50%) | 8/40 (20.00%) | 23/40 (57.50%) |
| B-R — RECONSTRUCTED_RESEARCH_AGENT | 28/40 (70.00%) | 9/40 (22.50%) | 3/40 (7.50%) | 28/40 (70.00%) |

Paired：**9 improved / 30 unchanged / 1 regressed**；A incomplete → B complete = 6，A complete → B incomplete = 1。B-R 的两个执行失败保留在 40 个任务分母中；执行 completed 不等于语义正确。

| Strict FULL | Track A | Track B-R |
|---|---:|---:|
| Cross-document | 0/8 | 1/8 |
| Multi-hop | 2/6 | 1/6 |

POC readiness 为 **PARTIAL**。不宣称 production readiness 或 reliable cross-document Research Agent；unsupported-count 为零不等于零幻觉率。

详见 [V2 评估方法与结果](docs/evaluation_v2.md)、[完整 POC 报告](docs/V2_POC_FINAL_REPORT.md)及[公开数据政策](docs/evaluation_data_policy.md)。V1 历史结果单独保留在 [历史评估](docs/evaluation.md)，不与 V2 不同语料/协议直接比较为算法提升。

## 技术栈

| 层 | 技术 |
|---|---|
| Frontend | React 18 / Vite / Ant Design |
| Backend | Python / FastAPI / SQLAlchemy |
| Workflow | LangGraph / Agent Harness |
| Retrieval | BM25 / BGE / RRF |
| Storage | MySQL / Chroma / 原始文件存储 |
| Infra / LLM | Docker Compose / OpenAI-compatible API（默认 DeepSeek） |

## 项目结构

- `backend/`：API、索引、检索、QA、Research、迁移与测试。
- `frontend/`：产品工作区、共享 Evidence viewer 与前端测试。
- `benchmarks/`：安全的查询定义与 locator，不含论文 PDF。
- `docs/`：系统设计、评估、部署和设计决策。
- `scripts/`：显式运行的产品验证工具。
- `docker-compose.yml`：本地服务与隔离测试配置。

## 当前限制

- Research API 同步执行；索引 worker 为单节点、进程内执行。
- 产品默认 BGE 偏中文；冻结 V2 评估使用 M3，真实跨文档证据召回仍有瓶颈。
- Citation 验证不提供完整 semantic entailment 判断。
- Reranker CPU 延迟较高，默认关闭。
- Graph 抽取默认关闭，真实语料验证延期。

## License

[MIT](LICENSE) 覆盖本仓库自身代码。第三方论文、模型及依赖遵循各自许可证；仓库不分发论文 PDF、模型权重或运行数据。
