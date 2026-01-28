## 4) Planned Features (v3.2 Execution Plan + Sprints)

### v3.2 feature catalog (core)
- **Connector SDK + registry**: Standardizes integrations so new connectors are easy to add.
- **Generic HTTP connector**: Provides a baseline connector so any HTTP source/sink can integrate.
- **Tool-calling adapters**: Lets LLMs call tools so agents can act.
- **Agent framework adapters**: Integrates frameworks so users can bring their preferred orchestration.
- **Runtime backends (vLLM, TGI, ONNX)**: Adds deployment options so inference is flexible.
- **Hybrid retrieval + reranking**: Improves relevance so results are higher quality.
- **Eval harness + feedback**: Measures quality so regressions are caught early.
- **Basic permissions**: Enforces tenant scoping so data is isolated.
- **DX bootstrap**: Makes local setup easier so adoption is faster.

### v3.2 feature catalog (pro)
- **Managed connector scheduler**: Runs syncs so connectors stay up to date.
- **Streaming connectors**: Enables real-time data flows so latency is low.
- **ABAC + row-level enforcement**: Protects data so governance is strong.
- **Advanced feedback loops**: Captures usage signals so quality can improve.
- **Cost controls + autoscaling profiles**: Keeps spend predictable so enterprise ops are viable.

### Sprint 01 - Connector SDK + Registry (Core)
- **Connector interfaces + registry loader**: Standardizes connector metadata so config is consistent.
- **CLI commands**: Lists/validates connectors so users can trust configuration.
- **Generic HTTP connector**: Gives a default integration path so onboarding is quick.

### Sprint 02 - Connector Scheduler + Tier 0 Pro connectors
- **Managed scheduler**: Runs and retries connector syncs so data stays fresh.
- **Tier 0 connectors**: Adds core enterprise systems so customers can integrate quickly.
- **Console connector wizard**: Guides setup so configuration is less error-prone.

### Sprint 03 - Tool-calling adapters + DX bootstrap
- **Tool-calling adapters**: Enables LLM tools so agents can act on data.
- **`retikon init` + `retikon doctor` improvements**: Simplifies setup so developers can start fast.
- **Local demo bootstrap**: Seeds data + opens console so demos are easy.

### Sprint 04 - Agent frameworks + runtime backends
- **LangChain + LlamaIndex adapters**: Supports popular frameworks so users can adopt quickly.
- **vLLM + TGI + ONNX Runtime backends**: Adds runtime options so deployment is flexible.

### Sprint 05 - Retrieval quality + evaluation
- **Hybrid retrieval**: Blends keyword + vector so recall is higher.
- **Reranking**: Improves result ordering so precision improves.
- **Eval harness**: Automates evaluation so regressions are caught.
- **Feedback capture**: Collects user signals so quality can improve.

### Sprint 06 - Permissions + Pro cost controls
- **Tenant scoping + metadata rules**: Enforces isolation so data is protected.
- **ABAC + audit logs (Pro)**: Adds governance so access is controlled and provable.
- **Metering + budgets + autoscaling profiles (Pro)**: Controls cost so enterprise usage is sustainable.
