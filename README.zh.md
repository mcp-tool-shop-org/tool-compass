<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**MCP 工具的语义导航器——通过意图而非记忆来查找合适的工具**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*令牌数量减少 95%。 通过描述您想要执行的操作来查找工具。*

[安装](#quick-start) • [用法](#usage) • [Docker](#option-2-docker) • [手册](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [性能](#performance) • [贡献](#contributing)

</div>

---

## 问题

MCP 服务器提供数十甚至数百个工具。 将所有工具定义加载到上下文中会浪费令牌并降低响应速度。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解决方案

Tool Compass 使用**语义搜索**从自然语言描述中查找相关工具。 与其加载所有工具，不如让 Claude 调用 `compass()` 并提供意图，然后仅返回相关的工具。

## 快速入门

📖 **完整文档：** 请参阅 [Tool Compass 手册](https://mcp-tool-shop-org.github.io/tool-compass/handbook/)，了解有关安装、配置和架构的详细信息。

### 选项 1：npm（零先决条件，无需安装 Python）

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve     # MCP gateway
npx @mcptoolshop/tool-compass ui        # Gradio UI
npx @mcptoolshop/tool-compass doctor    # Diagnose setup
```

首次运行时，它会下载经过验证的平台二进制文件（与 GitHub 发布中的 SHA256 值进行检查）。 本地缓存——后续调用可以立即启动。 请参阅 npm 上的 [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass)。

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

# Start with Docker Compose (requires Ollama running locally)
docker-compose up

# Or include Ollama in the stack
docker-compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

> GHCR 镜像 (`ghcr.io/mcp-tool-shop-org/tool-compass`) 支持 `linux/amd64` 和 `linux/arm64`，因此相同的标签可以在 x86_64 服务器和 Apple Silicon / ARM 工作站上运行。

## 特性

- **语义搜索** - 通过描述您想要执行的操作来查找工具
- **逐步呈现** - `compass()` → `describe()` → `execute()`
- **热缓存** - 常用工具会预加载
- **链检测** - 自动发现常见的工具工作流程
- **分析** - 跟踪使用模式和工具性能
- **跨平台** - Windows、macOS、Linux
- **Docker Ready** - 一键部署

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

## 用法

### `compass()` 工具

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

返回值：
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

### 可用工具

| 工具 | 描述 |
|------|-------------|
| `compass(intent)` | 用于搜索工具的语义搜索 |
| `describe(tool_name)` | 获取工具的完整模式 |
| `execute(tool_name, args)` | 在后端上运行工具 |
| `compass_categories()` | 列出类别和服务器 |
| `compass_status()` | 系统健康状况和配置 |
| `compass_analytics(timeframe)` | 使用情况统计信息 |
| `compass_chains(action)` | 管理工具工作流程 |
| `compass_sync(force)` | 从后端重新构建索引 |
| `compass_audit()` | 完整的系统报告 |

### 逐步呈现模式

Tool Compass 使用三步逐步呈现模式来最大限度地减少令牌使用：

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**为什么这很重要：**
- 预先加载 77 个工具 = ~38,500 个令牌
- 逐步呈现 = 每个使用的工具 ~600 个令牌
- 节省：**对于典型的流程，可节省 95% 以上的令牌**

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

`compass()` 结果中的 `hint` 字段指导此流程，并建议何时使用 `describe()`。

## 配置

| 变量 | 描述 | 默认值 |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | 项目根目录 | 自动检测 |
| `TOOL_COMPASS_PYTHON` | Python 可执行文件 | 自动检测 |
| `TOOL_COMPASS_CONFIG` | 配置文件路径 | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | 数据目录 | 特定于平台（如下所示） |
| `OLLAMA_URL` | Ollama 服务器 URL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI 服务器 | `http://localhost:8188` |
| `PORT` | 设置为启用 HTTP 传输（例如，用于 Fly.io） | 未设置 (stdio) |

**默认数据目录：**
- **Windows：** `%LOCALAPPDATA%\tool-compass\`
- **macOS：** `~/Library/Application Support/tool-compass/`
- **Linux：** `~/.config/tool-compass/`（或 `$XDG_CONFIG_HOME/tool-compass/`）

请参阅 [`.env.example`](.env.example) 以获取所有选项。

## 性能

| 指标 | 值 |
|--------|-------|
| 索引构建时间 | ~5 秒，用于 44 个工具 |
| 查询延迟 | ~15 毫秒（包括嵌入） |
| 令牌节省 | ~95%（38K → 2K） |
| @3 的准确率 | ~95%（前 3 个工具中包含正确的工具） |

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

### 无法连接到 MCP 服务器

如果 Claude Desktop 日志显示 JSON 解析错误：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因：** `print()` 语句会破坏 JSON-RPC 协议。

**解决方法：** 使用日志记录或 `file=sys.stderr`：
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

### 找不到索引

```bash
tool-compass sync
```

## 相关项目

作为 AI 驱动开发的 **Compass Suite** 的一部分：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - 语义文件搜索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - 基于向量嵌入的 Gradio 组件
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - 无头 LLM 微调
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 没有复杂性的 ComfyUI

## 贡献

我们欢迎贡献！ 请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 以获取指南。

## 安全性和数据范围

Tool Compass 是一种**本地优先**的开发工具。 有关完整策略，请参阅 [SECURITY.md](SECURITY.md)。

- **涉及的数据：**本地 HNSW 向量数据库中索引的工具描述，记录到本地 SQLite 数据库（`compass_analytics.db`）中的搜索查询，通过本地 Ollama 生成的嵌入数据。
- **未涉及的数据：**不涉及用户代码、文件内容或凭据。工具调用参数会被哈希处理，而不是以明文形式存储。
- **网络：**连接到本地 Ollama 以获取嵌入数据。可选的 Gradio 用户界面绑定到 localhost。没有外部遥测数据传输。
- **无遥测数据：**不收集任何外部数据。分析仅限于本地。

## 评估报告

每个类别得分会在集群运行后通过以下命令重新生成：`bash scripts/regenerate-scorecard.sh`（该脚本封装了 `npx @mcptoolshop/shipcheck audit`）。请参阅 [SCORECARD.md](SCORECARD.md) 以获取当前权威的详细信息——下表是对其的镜像，并且有意不是手动编写的。经过人工整理的部分（已知问题、修复历史记录）位于 SCORECARD.md 文件中的 `<!-- SHIPCHECK-AUTO-START/END -->` 标记之外，并在重新生成时保留。

| 类别 | 得分 | 备注 |
|----------|-------|-------|
| A. 安全性 | 待定 | SHA 哈希验证的动作；摘要哈希验证的基础镜像；SLSA 溯源 + PyPI 和 GHCR 上的 SBOM；预提交阶段的密钥扫描。 |
| B. 错误处理 | 待定 | 结构化结果、优雅降级、退出代码 |
| C. 操作文档 | 待定 | README 文件、CHANGELOG 文件、LICENSE 文件、Makefile 中的 `verify` + `verify-metrics` + `scorecard` 命令。 |
| D. 发布规范 | 待定 | 统一的 CI 流程；每个任务中都设置了 `timeout-minutes` 和 `retention-days`；pytest 配置位于 pyproject.toml 文件中。 |
| E. 身份（软性） | 待定 | 徽标、登录页面、GitHub 元数据；在 pyproject.toml 文件中明确列出的维护者。 |
| **Total** | **TBD** | 通过 `make scorecard` 命令重新生成 |

## 许可证

[MIT](LICENSE) - 详情请参阅 LICENSE 文件。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

