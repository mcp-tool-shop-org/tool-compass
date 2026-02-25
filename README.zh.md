<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="assets/logo.png" alt="Tool Compass Logo" width="400"></p>

# 工具罗盘

**语义导航器，助力 MCP 工具选择——通过意图而非记忆，找到最合适的工具。**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*减少了95%的令牌使用量。通过描述您想要完成的任务来查找相关工具。*

[安装](#quick-start) • [使用方法](#usage) • [Docker](#option-2-docker) • [性能](#performance) • [贡献](#contributing)

</div>

---

## 问题

MCP服务器会暴露数十甚至数百种工具。将所有工具定义加载到上下文中会浪费令牌，并降低响应速度。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解决方案

Tool Compass 利用**语义搜索**技术，根据自然语言描述来查找相关的工具。与一次性加载所有工具不同，Claude 会调用 `compass()` 函数，并提供一个意图，然后只返回相关的工具。

当然。请提供您需要翻译的英文文本。
## 演示

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## 快速入门指南

### 选项 1：本地安装

```bash
# Prerequisites: Ollama with nomic-embed-text
ollama pull nomic-embed-text

# Clone and setup
git clone https://github.com/mcp-tool-shop-org/tool-compass.git
cd tool-compass/tool_compass

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
cd tool-compass/tool_compass

# Start with Docker Compose (requires Ollama running locally)
docker-compose up

# Or include Ollama in the stack
docker-compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

## 功能特点

- **语义搜索** - 通过描述您想要完成的任务来查找工具。
- **逐步揭示** - `compass()` → `describe()` → `execute()`
- **热缓存** - 常用工具会被预先加载。
- **链式检测** - 自动发现常见的工具工作流程。
- **分析** - 跟踪使用模式和工具性能。
- **跨平台** - Windows、macOS、Linux
- **Docker 兼容** - 一键部署。

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

退货政策：
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

| Tool | 描述。 |
| 好的，请提供需要翻译的英文文本。 | 好的，请提供需要翻译的英文文本。 |
| `compass(intent)` | 工具的语义搜索。 |
| `describe(tool_name)` | 获取工具的完整结构信息。 |
| `execute(tool_name, args)` | 在它的后端运行一个工具。 |
| `compass_categories()` | 列出类别和服务器。 |
| `compass_status()` | 系统健康状况和配置。 |
| `compass_analytics(timeframe)` | 使用统计数据。 |
| `compass_chains(action)` | 管理工具工作流程。 |
| `compass_sync(force)` | 从后端重新构建索引。 |
| `compass_audit()` | 完整系统报告。 |

## 配置

| 变量 | 描述。 | 默认设置。 |
| 好的，请提供需要翻译的英文文本。 | 好的，请提供需要翻译的英文文本。 | 好的，请提供需要翻译的英文文本。 |
| `TOOL_COMPASS_BASE_PATH` | 项目根目录。 | 自动检测。 |
| `TOOL_COMPASS_PYTHON` | Python 可执行文件。 | 自动检测。 |
| `TOOL_COMPASS_CONFIG` | 配置文件路径。 | `./compass_config.json` |
| `OLLAMA_URL` | Ollama 服务器的 URL 地址。 | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI 服务器。 | `http://localhost:8188` |

请参考 `.env.example` 文件，其中包含了所有可用的配置选项。

## 性能

| 公制。 | Value |
| 好的，请提供需要翻译的英文文本。 | 好的，请提供需要翻译的英文文本。 |
| 索引构建时间。 | 约5秒即可完成44个工具的操作。 |
| 查询延迟。 | 约15毫秒（包括嵌入过程）。 |
| 令牌储蓄。 | 约95% (38千 → 2千) |
| 准确率@3 (或 Top 3 准确率) | 约95%的场景中，该工具排名前三。 |

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

如果 Claude Desktop 的日志显示 JSON 解析错误：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因：** `print()` 函数会破坏 JSON-RPC 协议。

**解决方法：** 使用日志记录功能，或者将错误信息输出到标准错误流（`file=sys.stderr`）。
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
python gateway.py --sync
```

## 相关项目

“Compass”系列产品，专为人工智能驱动的开发而设计，其中一部分是：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - 基于语义的 文件搜索工具
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - 集成向量嵌入的 Gradio 组件
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - 无头（headless）的大语言模型微调工具
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 简化版的 ComfyUI

## 贡献

我们欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 文件以获取指南。

## 安全性

对于安全漏洞，请参阅 [SECURITY.md](SECURITY.md) 文件。**请不要在公开问题中报告安全漏洞。**

## 支持

- **问题/帮助：** [讨论](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
- **错误报告：** [问题](https://github.com/mcp-tool-shop-org/tool-compass/issues)
- **安全：** [SECURITY.md](SECURITY.md)

## 许可证

[MIT](LICENSE) - 详情请参阅 LICENSE 文件。

## 鸣谢

- **HNSW**: Malkov & Yashunin, "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs" (2016)
- **nomic-embed-text**: Nomic AI 的开源嵌入模型
- **FastMCP**: Anthropic 的 MCP 框架
- **Gradio**: Hugging Face 的机器学习 Web 框架

---

<div align="center">

*"和谐共生，至关重要。"*

Tool Compass 通过根据语义含义对工具进行分类，从而降低 MCP 生态系统的熵值。

**[文档](https://github.com/mcp-tool-shop-org/tool-compass#readme)** • **[问题](https://github.com/mcp-tool-shop-org/tool-compass/issues)** • **[讨论](https://github.com/mcp-tool-shop-org/tool-compass/discussions)**

</div>
