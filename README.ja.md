<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**MCPツール用セマンティックナビゲーター - 記憶ではなく、意図に基づいて適切なツールを見つける**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*トークン使用量が95%削減されます。実行したいことを記述することでツールを見つけられます。*

[インストール](#quick-start) • [使い方](#usage) • [Docker](#option-2-docker) • [マニュアル](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [パフォーマンス](#performance) • [貢献](#contributing)

</div

---

## 問題点

MCPサーバーには数十から数百のツールが公開されています。すべてのツールの定義をコンテキストに読み込むと、トークンが浪費され、応答速度が低下します。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解決策

Tool Compassは、**セマンティック検索**を使用して、自然言語による説明から関連するツールを見つけます。すべてのツールを読み込む代わりに、Claudeは`compass()`を呼び出し、関連するツールのみが返されます。

<!--
## デモ

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## クイックスタート

📖 **詳細なドキュメント:** インストール、設定、アーキテクチャの詳細については、[Tool Compassマニュアル](https://mcp-tool-shop-org.github.io/tool-compass/handbook/)を参照してください。

### オプション1：ローカルインストール

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

### オプション2：Docker

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

> GHCRイメージ (`ghcr.io/mcp-tool-shop-org/tool-compass`) は、`linux/amd64`と`linux/arm64`をサポートしており、同じタグがx86_64サーバーとApple Silicon / ARMワークステーションの両で動作します。

## 機能

- **セマンティック検索:** 実行したいことを記述してツールを見つける
- **段階的な情報開示:** `compass()` → `describe()` → `execute()`
- **ホットキャッシュ:** よく使用されるツールは事前に読み込まれる
- **チェーン検出:** 一般的なツールワークフローを自動的に検出
- **分析:** 使用パターンとツールのパフォーマンスを追跡
- **クロスプラットフォーム:** Windows、macOS、Linux
- **Docker対応:** ワンコマンドでデプロイ可能

## アーキテクチャ

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

## 使い方

### `compass()`ツール

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

戻り値：
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

### 利用可能なツール

| ツール | 説明 |
|------|-------------|
| `compass(intent)` | ツールのセマンティック検索 |
| `describe(tool_name)` | ツールの完全なスキーマを取得 |
| `execute(tool_name, args)` | ツールのバックエンドを実行 |
| `compass_categories()` | カテゴリとサーバーの一覧を表示 |
| `compass_status()` | システムのヘルスと設定 |
| `compass_analytics(timeframe)` | 使用状況統計 |
| `compass_chains(action)` | ツールのワークフローを管理 |
| `compass_sync(force)` | バックエンドからインデックスを再構築 |
| `compass_audit()` | 完全なシステムレポート |

### 段階的な情報開示パターン

Tool Compassは、トークンの使用量を最小限に抑えるために、3段階の段階的な情報開示パターンを使用します。

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**なぜこれが重要なのか:**
- 77のツールを事前に読み込むと、約38,500トークンが必要
- 段階的な情報開示により、使用するツールごとに約600トークン
- 削減効果：**典型的なワークフローで95%以上**

**例：ワークフロー**

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

`compass()`の結果の`hint`フィールドは、`describe()`を使用するタイミングを示唆します。

## 設定

| 変数 | 説明 | デフォルト値 |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | プロジェクトのルートディレクトリ | 自動検出 |
| `TOOL_COMPASS_PYTHON` | Python実行可能ファイル | 自動検出 |
| `TOOL_COMPASS_CONFIG` | 設定ファイルパス | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | データディレクトリ | プラットフォーム固有（下記参照） |
| `OLLAMA_URL` | OllamaサーバーURL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUIサーバー | `http://localhost:8188` |
| `PORT` | HTTPトランスポートを有効にする（例：Fly.ioの場合） | 未設定（標準入力） |

**デフォルトのデータディレクトリ:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/` (または `$XDG_CONFIG_HOME/tool-compass/`)

すべてのオプションについては、[`.env.example`](.env.example)を参照してください。

## パフォーマンス

| 指標 | 値 |
|--------|-------|
| インデックス構築時間 | 44のツールで約5秒 |
| クエリのレイテンシー | ~15ms (埋め込み処理を含む) |
| トークン削減 | 約95% (38K → 2K) |
| 精度@3 | 約95% (上位3つの候補の中から正しいツールが含まれる) |

## テスト

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## トラブルシューティング

### MCPサーバーに接続できない

Claude DesktopのログにJSONの解析エラーが表示される場合：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因**: `print()`文がJSON-RPCプロトコルを破損させている。

**解決策**: ロギングを使用するか、`file=sys.stderr`を指定する。
```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollamaへの接続に失敗

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### インデックスが見つかりません

```bash
python gateway.py --sync
```

## 関連プロジェクト

AIを活用した開発のための**Compass Suite**の一部：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - セマンティックファイル検索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - ベクトル埋め込みGradioコンポーネント
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - ヘッドレスLLMのファインチューニング
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 複雑さを取り除いたComfyUI

## 貢献

貢献を歓迎します！ガイドラインについては、[CONTRIBUTING.md](CONTRIBUTING.md)をご覧ください。

## セキュリティとデータ範囲

Tool Compassは、**ローカルファースト**の開発ツールです。詳細については、[SECURITY.md](SECURITY.md)をご覧ください。

- **扱うデータ**: ツール記述はローカルのHNSWベクトルデータベースにインデックス化されます。検索クエリはローカルのSQLiteデータベース（`compass_analytics.db`）に記録されます。埋め込みはローカルのOllamaを使用して生成されます。
- **扱わないデータ**: ユーザーコード、ファイルの内容、認証情報は一切扱いません。ツールの呼び出し引数はハッシュ化され、プレーンテキストで保存されません。
- **ネットワーク**: 埋め込みのためにローカルのOllamaに接続します。オプションのGradio UIはlocalhostにバインドされます。外部へのテレメトリーは一切ありません。
- **テレメトリーなし**: 外部に何も収集しません。分析はローカルでのみ行われます。

## 評価

| カテゴリ | 評価 | 備考 |
|----------|-------|-------|
| A. セキュリティ | 10/10 | SECURITY.md、ローカルのみ、テレメトリーなし、パラメータ化されたSQL |
| B. エラー処理 | 10/10 | 構造化された結果、Ollamaのフォールバック機能 |
| C. ドキュメント | 10/10 | README、CHANGELOG、CONTRIBUTING、APIドキュメント |
| D. リリースの品質 | 10/10 | CI (lint + テスト + カバレッジ + pip-audit + Docker)、検証スクリプト |
| E. 識別 | 10/10 | ロゴ、翻訳、ランディングページ |
| **Total** | **50/50** | |

## ライセンス

[MIT](LICENSE) - 詳細については、LICENSEファイルをご覧ください。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

