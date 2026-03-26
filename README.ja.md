<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**MCPツール用のセマンティックナビゲーター - 記憶ではなく、意図に基づいて適切なツールを見つける**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*トークン使用量が95%削減されます。実行したいことを説明することでツールを見つけることができます。*

[インストール](#quick-start) • [使い方](#usage) • [Docker](#option-2-docker) • [パフォーマンス](#performance) • [貢献](#contributing)

</div

---

## 問題点

MCPサーバーは数十から数百のツールを公開しています。すべてのツールの定義をコンテキストに読み込むと、トークンを消費し、応答速度が低下します。

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

### オプション1：ローカルインストール

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

### オプション2：Docker

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

## 機能

- **セマンティック検索**：実行したいことを説明してツールを見つける
- **段階的な表示**：`compass()` → `describe()` → `execute()`
- **ホットキャッシュ**：頻繁に使用されるツールは事前に読み込まれている
- **チェーン検出**：一般的なツールワークフローを自動的に検出
- **分析**：使用パターンとツールのパフォーマンスを追跡
- **クロスプラットフォーム**：Windows、macOS、Linux
- **Docker対応**：ワンコマンドでデプロイ

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

## 設定

| 変数 | 説明 | デフォルト値 |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | プロジェクトのルートディレクトリ | 自動検出 |
| `TOOL_COMPASS_PYTHON` | Python実行可能ファイル | 自動検出 |
| `TOOL_COMPASS_CONFIG` | 設定ファイルパス | `./compass_config.json` |
| `OLLAMA_URL` | OllamaサーバーURL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUIサーバー | `http://localhost:8188` |

すべてのオプションについては、[`.env.example`](.env.example)を参照してください。

## パフォーマンス

| 指標 | 値 |
|--------|-------|
| インデックス構築時間 | 44のツールで約5秒 |
| クエリのレイテンシ | 約15ms（エンベディングを含む） |
| トークン削減量 | 約95%（38K → 2K） |
| 精度@3 | 約95%（上位3つのうち正しいツールが含まれる） |

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

### MCPサーバーへの接続ができない

Claude DesktopのログにJSON解析エラーが表示される場合：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因**: `print()`ステートメントがJSON-RPCプロトコルを破壊している。

**解決策**: ログを使用するか、`file=sys.stderr`を使用する。
```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollamaへの接続が失敗する

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### インデックスが見つからない

```bash
python gateway.py --sync
```

## 関連プロジェクト

AIを活用した開発のための**Compass Suite**の一部：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - セマンティックファイル検索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - ベクトル埋め込みGradioコンポーネント
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - ヘッドレスLLMファインチューニング
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 複雑さを排除したComfyUI

## 貢献

貢献を歓迎します！ガイドラインについては、[CONTRIBUTING.md](CONTRIBUTING.md)を参照してください。

## セキュリティとデータ範囲

Tool Compassは、**ローカルファースト**の開発ツールです。詳細については、[SECURITY.md](SECURITY.md)を参照してください。

- **処理されるデータ:** ローカルのHNSWベクトルデータベースにインデックスされたツール記述、ローカルのSQLiteデータベース（`compass_analytics.db`）に記録される検索クエリ、ローカルのOllamaを使用して生成される埋め込みデータ。
- **処理されないデータ:** ユーザーコード、ファイルの内容、認証情報。ツールの呼び出し引数はハッシュ化され、平文で保存されません。
- **ネットワーク:** 埋め込みデータの生成にはローカルのOllamaに接続します。オプションで、Gradio UIがローカルホストにバインドされます。外部のテレメトリは送信されません。
- **テレメトリ:** 外部へのデータ収集は一切行いません。分析はローカルでのみ行われます。

## 評価項目

| カテゴリ | 評価 | 備考 |
|----------|-------|-------|
| A. セキュリティ | 10/10 | `SECURITY.md`、ローカルのみ、テレメトリなし、パラメータ化されたSQL |
| B. エラー処理 | 10/10 | 構造化された結果、Ollamaの代替機能 |
| C. 運用ドキュメント | 10/10 | `README`、`CHANGELOG`、`CONTRIBUTING`、APIドキュメント |
| D. リリース時の品質管理 | 10/10 | CI（lint、413個のテスト、カバレッジ、`pip-audit`、Docker）、検証スクリプト |
| E. 識別 | 10/10 | ロゴ、翻訳、ランディングページ |
| **Total** | **50/50** | |

## ライセンス

[MIT](LICENSE) - 詳細については、LICENSEファイルを参照してください。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>
