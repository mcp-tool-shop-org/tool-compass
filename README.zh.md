<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**MCP 工具的语义导航器 - 通过意图查找工具，而不是依赖记忆**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*减少 95% 的令牌使用量。通过描述您想要执行的操作来查找工具。*

[安装](#quick-start) • [使用方法](#usage) • [Docker](#option-2-docker) • [手册](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [性能](#performance) • [贡献](#contributing)

</div>

---

## 问题

MCP 服务器暴露了数十或数百个工具。将所有工具定义加载到上下文中会浪费令牌并降低响应速度。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解决方案

Tool Compass 使用**语义搜索**，通过自然语言描述来查找相关的工具。与加载所有工具不同，Claude 调用 `compass()` 函数，并仅返回相关的工具。

<!--
## 演示

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## 快速入门

📖 **完整文档：** 请参阅 [Tool Compass 手册](https://mcp-tool-shop-org.github.io/tool-compass/handbook/)，了解安装、配置和架构的详细信息。

### 选项 1：本地安装

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
python gateway.py --sync

# Run the MCP server
python gateway.py

# Or launch the Gradio UI
python ui.py
```

### 选项 2：Docker

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

> GHCR 镜像 (`ghcr.io/mcp-tool-shop-org/tool-compass`) 支持
> `linux/amd64` 和 `linux/arm64`，因此相同的镜像标签可以在 x86_64 服务器
> 和 Apple Silicon / ARM 工作站上运行。

## 特性

- **语义搜索：** 通过描述您想要执行的操作来查找工具。
- **分步展示：** `compass()` → `describe()` → `execute()`
- **热缓存：** 常用工具会被预加载。
- **链检测：** 自动发现常见的工具工作流程。
- **分析：** 跟踪使用模式和工具性能。
- **跨平台：** Windows、macOS、Linux
- **支持 Docker：** 一键部署

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     TOOL COMPASS                            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │   Ollama     │    │   hnswlib    │    │   SQLite     │  │
│  │   Embedder   │───▶│    HNSW      │◀───│   Metadata   │  │
│  │  (nomic)     │    │   Index      │    │   Store      │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                              │                              │
│                              ▼                              │
│                    ┌──────────────────┐                    │
│                    │  Gateway (9 tools)│                   │
│                    │  compass, describe│                   │
│                    │  execute, etc.    │                   │
│                    └──────────────────┘                    │
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
| `compass(intent)` | 用于工具的语义搜索 |
| `describe(tool_name)` | 获取工具的完整模式 |
| `execute(tool_name, args)` | 在工具的后端运行 |
| `compass_categories()` | 列出类别和服务器 |
| `compass_status()` | 系统健康状况和配置 |
| `compass_analytics(timeframe)` | 使用统计信息 |
| `compass_chains(action)` | 管理工具工作流程 |
| `compass_sync(force)` | 从后端重建索引 |
| `compass_audit()` | 完整的系统报告 |

### 分步展示模式

Tool Compass 使用一种分步展示模式，以最大限度地减少令牌的使用量：

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**原因：**
- 预加载 77 个工具 = ~38,500 个令牌
- 分步展示 = 每个使用的工具 ~600 个令牌
- 节省：**典型工作流程可节省 95% 以上**

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

`compass()` 函数的结果中的 `hint` 字段会引导此流程，提示何时使用 `describe()` 函数。

## 配置

| 变量 | 描述 | 默认值 |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | 项目根目录 | 自动检测 |
| `TOOL_COMPASS_PYTHON` | Python 解释器 | 自动检测 |
| `TOOL_COMPASS_CONFIG` | 配置文件路径 | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | 数据目录 | 平台特定（见下文） |
| `OLLAMA_URL` | Ollama 服务器 URL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI 服务器 | `http://localhost:8188` |
| `PORT` | 设置为启用 HTTP 传输（例如，用于 Fly.io） | 未设置 (stdio) |

**默认数据目录：**
- **Windows：** `%LOCALAPPDATA%\tool-compass\`
- **macOS：** `~/Library/Application Support/tool-compass/`
- **Linux：** `~/.config/tool-compass/` (或 `$XDG_CONFIG_HOME/tool-compass/`)

请参阅 [`.env.example`](.env.example)，了解所有选项。

## 性能

| 指标 | 值 |
|--------|-------|
| 索引构建时间 | 44 个工具，约 5 秒 |
| 查询延迟 | ~15毫秒（包括嵌入） |
| 令牌节省 | ~95% (38K → 2K) |
| 准确率@3 | ~95% (在排名前3中，正确工具的比例) |

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

### MCP服务器无法连接

如果Claude Desktop日志显示JSON解析错误：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因：** `print()`语句破坏了JSON-RPC协议。

**解决方法：** 使用日志记录或 `file=sys.stderr`。
```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollama连接失败

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### 索引未找到

```bash
python gateway.py --sync
```

## 相关项目

它是**Compass套件**中用于AI驱动开发的工具：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - 语义文件搜索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - 向量嵌入的Gradio组件
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - 无头LLM微调
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 简化版的ComfyUI

## 贡献

我们欢迎贡献！请参阅[CONTRIBUTING.md](CONTRIBUTING.md)以获取指南。

## 安全与数据范围

Tool Compass是一个**本地优先**的开发工具。请参阅[SECURITY.md](SECURITY.md)以获取完整策略。

- **涉及的数据：** 工具描述被索引到本地HNSW向量数据库，搜索查询被记录到本地SQLite数据库（`compass_analytics.db`），嵌入通过本地Ollama生成。
- **未涉及的数据：** 不包括用户代码、文件内容或凭据。工具调用参数被哈希，而不是以明文存储。
- **网络：** 连接到本地Ollama以生成嵌入。可选的Gradio UI绑定到localhost。没有外部遥测。
- **无遥测：** 不收集任何外部数据。分析仅在本地进行。

## 评分卡

| 类别 | 评分 | 备注 |
|----------|-------|-------|
| A. 安全性 | 10/10 | SECURITY.md，仅本地，无遥测，参数化SQL |
| B. 错误处理 | 10/10 | 结构化结果，优雅的Ollama回退 |
| C. 操作文档 | 10/10 | README，CHANGELOG，CONTRIBUTING，API文档 |
| D. 发布质量 | 10/10 | CI（lint + tests + coverage + pip-audit + Docker），验证脚本 |
| E. 标识 | 10/10 | Logo，翻译，主页 |
| **Total** | **50/50** | |

## 许可证

[MIT](LICENSE) - 详情请参阅LICENSE文件。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

