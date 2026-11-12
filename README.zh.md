<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="800"></p>

**用于 MCP 工具的语义导航器——通过意图而非记忆来查找合适的工具**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
<a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*令牌数量减少 95%。只需描述您想要完成的任务，即可找到所需的工具。*

[安装说明](#快速入门) • [使用方法](#使用方法) • [Docker](#option-2-docker) • [使用手册](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [性能](#性能) • [贡献指南](#贡献)

</div>

---

## 问题

MCP 服务器提供了数十甚至数百种工具。将所有工具的定义加载到上下文中会浪费令牌，并降低响应速度。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解决方案

Tool Compass 使用**语义搜索**，根据自然语言描述来查找相关的工具。Claude 不会加载所有工具，而是通过调用 `compass()` 并提供意图，从而仅获取相关的工具。

## 快速入门

📖 **完整文档：** 请参阅 [Tool Compass Handbook](https://mcp-tool-shop-org.github.io/tool-compass/handbook/)，其中包含有关安装、配置和架构的详细信息。

### 选项一：使用 npm（无需任何先决条件，无需安装 Python）

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve                 # MCP gateway
npx @mcptoolshop/tool-compass ui                    # Gradio UI
npx @mcptoolshop/tool-compass doctor                # Diagnose setup
npx @mcptoolshop/tool-compass execute fs:read_file '{"path":"README.md"}'  # Smoke-test a proxied call
```

首次运行时，会下载经过验证的平台二进制文件（与GitHub发布的SHA256进行校验）。该文件会缓存在本地，后续启动速度更快。请参阅 npm 上的 [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass)。

### 选项 2：PyPI

```bash
pip install tool-compass
tool-compass --help
```

### 选项 3：本地克隆

```bash
# Prerequisites: Ollama with nomic-embed-text
ollama pull nomic-embed-text

# Clone and setup
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Build the search index
tool-compass sync

# Run the MCP server
tool-compass serve

# Or launch the Gradio UI
tool-compass ui
```

### 选项 4：Docker

```bash
# Clone the repo
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass

# Start with Docker Compose (requires Ollama running locally and a UI login)
GRADIO_AUTH=user:pass docker compose up

# Or include Ollama in the stack
GRADIO_AUTH=user:pass docker compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

或者，直接运行已发布的 UI 镜像，无需克隆：

```bash
docker run --rm -p 7860:7860 \
  -e GRADIO_AUTH=user:pass \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:ui
```

> **容器中需要进行 UI 登录。** 由于容器绑定了 `0.0.0.0`，因此如果没有登录，启动时会拒绝运行。可以通过以下两种方式启动：设置 `GRADIO_AUTH=user:pass`（通过 `.env`、shell 环境或 `-e`），或者在通过反向代理进行部署时设置 `TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1`，该反向代理会强制执行自己的登录机制（会打印启动警告并隐藏 UI 执行控件）。

**挂载卷。** 语义索引位于 `/app/tool_compass/db`，构建它意味着将每个工具嵌入到每个已配置的服务器中。如果没有卷，当容器退出时，所有工作都会被丢弃，并在下次启动时重新进行——这会给人一种“工具指南针速度慢”的印象，而不是缺少某个标志。镜像会在您忘记时发出警告。`docker compose up` 已经挂载了一个命名卷，因此这仅适用于未命名的 `docker run`。

GHCR 镜像（`ghcr.io/mcp-tool-shop-org/tool-compass`）支持 `linux/amd64` 和 `linux/arm64`，因此相同的标签可以在 x86_64 服务器和 Apple Silicon / ARM 工作站上运行。

要运行 **MCP HTTP 网关**容器（`mcp-gateway` 阶段，端口 `8080`），请提供一个令牌——因为该容器绑定了 `HOST=0.0.0.0`，如果没有提供 `TOOL_COMPASS_GATEWAY_AUTH_TOKEN`（或者在经过身份验证的反向代理之后提供 `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1`），它将拒绝启动：

```bash
# Docker Compose (gateway profile)
TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> docker compose --profile gateway up

# Or published gateway image directly
docker run --rm -p 8080:8080 \
  -e TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:gateway
```

## 特点

- **混合搜索**——语义（HNSW）与词法融合，并对精确名称进行加权——描述您想要的内容，或粘贴工具名称，它将排在第一位。
- **完整模式渐进式显示**——`compass()` → `describe()` → `execute()`；`describe()` 返回完整的 `inputSchema`（必需字段、描述、枚举、默认值）。
- **stdio + HTTP 后端**——前端本地子进程 MCP 服务器*和*通过可流式传输的 HTTP 协议连接的远程/SaaS 服务器，并可选择使用 bearer-token 身份验证。
- **每个工具的超时设置和允许/拒绝**——覆盖每个后端/工具的默认超时设置；公开广泛后端的一个安全子集。
- **热缓存和链检测**——常用工具预加载；自动发现常用的工具工作流程。
- **分析**——跟踪使用模式和工具性能（具有保留/清理功能）。
- **跨平台且支持 Docker**——Windows、macOS、Linux；一键部署。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                       TOOL COMPASS                          │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │   Ollama     │    │   hnswlib    │    │   SQLite     │   │
│  │   Embedder   │───▶│    HNSW      │◀───│   Metadata   │   │
│  │  (nomic)     │    │   Index      │    │   Store      │   │
│  └──────────────┘    └──────────────┘    └──────────────┘   │
│                              │                              │
│                              ▼                              │
│                    ┌───────────────────┐                    │
│                    │ Gateway (9 tools)  │                   │
│                    │ compass, describe  │                   │
│                    │ execute, etc.      │                   │
│                    └───────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

## 使用方法

### `compass()` 工具

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

退货：
```json
{
  "matches": [
    {
      "tool": "comfy:comfy_generate",
      "description": "Generate image from text prompt using AI",
      "category": "ai",
      "confidence": 0.912
    }
  ],
  "total_indexed": 44,
  "tokens_saved": 20500,
  "hint": "Found: comfy:comfy_generate. Use describe() for full schema."
}
```

### 可用的工具

| 工具 | 描述 |
|------|-------------|
| `compass(intent)` | 采用混合语义和词汇搜索，并对完全匹配的名称结果进行优先排序。 |
| `describe(tool_name)` | 获取工具的完整 `inputSchema`（必需/枚举/默认值）。 |
| `execute(tool_name, args)` | 在其后端运行一个工具。 |
| `compass_categories()` | 列出类别和服务器。 |
| `compass_status(active)` | 系统健康状况和配置；`active=True` 会运行一个实时的后端存活检测。 |
| `compass_analytics(timeframe)` | 使用情况统计数据 |
| `compass_chains(action)` | 管理工具的工作流程。 |
| `compass_sync(force)` | 从后端重新构建索引。 |
| `compass_audit()` | 完整系统报告。 |

可以通过命令行界面执行相同的操作，包括使用`tool-compass execute <tool> '<json>'`从终端对代理调用进行快速测试。

### 逐步呈现模式

Tool Compass 采用一种分三步逐步呈现的方式，以最大限度地减少令牌的使用：

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**为什么这很重要：**
- 预先加载 77 个工具，相当于大约 38,500 个令牌。
- 逐步显示，每个使用的工具大约需要 600 个令牌。
- 节省：对于典型的流程，可节省 95% 以上。

**示例工作流程：**

```python
# Step 1: Find the right tool
compass("generate an image from text")
# Returns: comfy:comfy_generate (confidence: 0.91)

# Step 2: Get the schema (only if needed)
describe("comfy:comfy_generate")
# Returns: Full parameter definitions, types, examples

# Step 3: Execute
execute("comfy:comfy_generate", {"prompt": "a sunset over mountains"})
```

在指南针结果中，`hint`字段用于指导此流程，并提示何时使用`describe()`。

## 配置

| 变量 | 描述 | 默认 |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | 项目根目录 | 自动检测。 |
| `TOOL_COMPASS_PYTHON` | Python 可执行文件 | 自动检测。 |
| `TOOL_COMPASS_CONFIG` | 配置文件路径 | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | 数据目录 | 特定于某个平台（详情请参见下文） |
| `OLLAMA_URL` | Ollama 服务器网址 | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI 服务器 | `http://localhost:8188` |
| `PORT` | 启用 HTTP 传输（例如，用于 Fly.io）。 | 取消设置（标准输入/输出） |
| `HOST` | HTTP 传输的绑定地址；如果不是环回地址，则需要设置 `TOOL_COMPASS_GATEWAY_AUTH_TOKEN`（或 `gateway_auth_token`），除非已设置 `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1`。 | `127.0.0.1` |
| `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` | 用于 HTTP 传输的 Bearer 令牌（覆盖 `compass_config.json` 中的 `gateway_auth_token`）。当 `HOST` 不是环回地址（`127.0.0.1`、`localhost`、`::1`）时，此项为必需；在环回地址时，此项为可选。 | 取消设置（拒绝关闭回环模式） |
| `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN` | 设置为 `1`，允许在没有令牌的情况下，将 HTTP 网关绑定到非环回地址，前提是前面有一个用于身份验证的反向代理（每次启动时会记录一条警告）。 | 取消（禁用） |
| `GRADIO_AUTH` | UI 登录（`user:pass`）；如果启用，则会在每次 UI 启动时应用，并且需要在禁用回环模式、在 Docker 容器中或在 `--share` 上进行操作。 | 取消设置（仅适用于环回模式） |
| `TOOL_COMPASS_UI_ALLOW_NO_LOGIN` | 设置为 `1`，以允许在不通过身份验证代理 `GRADIO_AUTH` 的情况下启动 UI，而无需循环回送（会发出警告并隐藏执行控件）。 | 取消设置 |

**默认数据目录：**
- **Windows：**`%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux：**`~/.config/tool-compass/`（或`$XDG_CONFIG_HOME/tool-compass/`）

配置文件设置（位于 `compass_config.json` 中），于 v2.5.0 中添加：`hybrid_search`、`exact_name_boost`、每个后端 `default_timeout` / `tool_timeouts`、`allow_tools` / `deny_tools`、`analytics_retention_days` 和 HTTP（`type: "http"`）后端——详见 [手册 → 配置](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/)。
有关环境变量选项，请参阅 [`.env.example`](.env.example)。

## 性能

| 指标 | 值 |
|--------|-------|
| 索引构建时间 | 对于 44 个工具，约为 5 秒 |
| 查询延迟 | 约为 15 毫秒（包括嵌入） |
| 令牌节省 | 约为 95%（从 38K 减少到 2K） |
| 准确率@3 | 约为 95%（前 3 个结果中包含正确的工具） |

## 测试

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## 故障排除

### MCP 服务器未连接

如果 Claude Desktop 日志显示 JSON 解析错误：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因：** `print()` 语句破坏了 JSON-RPC 协议。

**解决方法：** 使用日志记录或 `file=sys.stderr`。
```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollama 连接失败

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### 未找到索引

```bash
tool-compass sync
```

## 相关项目

作为 AI 驱动开发的 **Compass Suite** 的一部分：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - 语义文件搜索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - 向量嵌入的 Gradio 组件
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - 无头 LLM 微调
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI，但无需复杂的配置

## 贡献

我们欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 以获取指南。

## 安全性和数据范围

Tool Compass 是一种 **本地优先** 的开发工具。有关完整策略，请参阅 [SECURITY.md](SECURITY.md)。

- **涉及的数据：** 索引到本地 HNSW 向量数据库中的工具描述、记录到本地 SQLite（`compass_analytics.db`）的搜索查询、通过本地 Ollama 生成的嵌入。
- **不涉及的数据：** 无用户代码、无文件内容、无凭据。工具调用参数会被哈希处理，而不是以明文形式存储。
- **网络：** 连接到本地 Ollama 以进行嵌入。可选的 Gradio UI 绑定到本地主机。没有外部遥测。
- **无遥测：** 不收集任何外部数据。分析仅限于本地。

## 评估报告

通过 `bash scripts/regenerate-scorecard.sh` 在群集完成后重新生成每个类别的分数（该工具包装了 `npx @mcptoolshop/shipcheck audit`）。有关当前权威的细分，请参阅 [SCORECARD.md](SCORECARD.md)——下表是对其的镜像，并且有意不是手动编写的。手动策划的部分（已知差距、修复历史记录）位于 SCORECARD.md 中的 `<!-- SHIPCHECK-AUTO-START/END -->` 标记之外，并且会在重新生成时保留。

最新的 `shipcheck audit`：**32 个已检查 · 0 个未检查 · 5 个已跳过 · 100% 通过——所有硬性门槛均已通过。**

| 类别 | 分数 | 备注 |
|----------|-------|-------|
| A. 安全性 | ✅ 通过 | SHA 绑定的操作；摘要绑定的基础镜像；SLSA 来源 + SBOM 在 PyPI + GHCR 上；预提交的密钥扫描；可选的网关承载者身份验证 |
| B. 错误处理 | ✅ 通过 | 结构化结果、优雅降级、退出代码 |
| C. 操作文档 | ✅ 通过 | README、CHANGELOG、LICENSE、Makefile `verify` + `verify-metrics` + `scorecard` |
| D. 交付卫生 | ✅ 通过 | CI 整合；每个作业中都有 timeout-minutes + retention-days；pytest 配置在 pyproject.toml 中 |
| E. 身份（软性） | ✅ 通过 | 徽标、登录页面、GitHub 元数据；在 pyproject.toml 中明确指定维护者 |
| **Total** | **100%** | 所有硬性门槛均已通过——通过 `make scorecard` 重新生成 |

## 许可证

[MIT](LICENSE) - 有关详细信息，请参阅 LICENSE 文件。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

