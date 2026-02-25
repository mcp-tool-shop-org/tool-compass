<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="assets/logo.png" alt="Tool Compass Logo" width="400"></p>

# ツールコンパス

**MCPツール用セマンティックナビゲーター：記憶ではなく、意図に基づいて最適なツールを見つけましょう。**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

* トークンの使用量が95%削減されました。やりたいことを説明することで、最適なツールを見つけてください。*

[インストール](#quick-start) • [使い方](#usage) • [Dockerの使用](#option-2-docker) • [パフォーマンス](#performance) • [貢献について](#contributing)

</div>

---

## 問題点

MCPサーバーは、数十から数百ものツールを提供しています。すべてのツールの定義をコンテキストに読み込むと、トークンを無駄にし、応答速度を低下させる可能性があります。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解決策

Tool Compassは、**意味検索**を利用して、自然言語で記述された内容に基づいて関連するツールを検索します。すべてのツールを読み込む代わりに、Claudeは`compass()`関数を呼び出し、意図を伝え、その結果として関連するツールのみが返されます。

```
The company is committed to providing high-quality products and services.
```
## デモ

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## クイックスタートガイド

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

### オプション2：Docker（Dockerを使用する）

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

## 特徴

- **セマンティック検索:** どのような作業をしたいかを記述することで、ツールを見つけることができます。
- **段階的な表示:** `compass()` → `describe()` → `execute()` のように、情報を段階的に表示します。
- **ホットキャッシュ:** よく使用されるツールは、あらかじめ読み込まれています。
- **チェーン検出:** 一般的なツールのワークフローを自動的に検出します。
- **分析機能:** ツールの使用状況やパフォーマンスを追跡します。
- **クロスプラットフォーム:** Windows、macOS、Linuxに対応しています。
- **Docker対応:** 1つのコマンドでデプロイできます。

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

## 使用方法

### `compass()` ツールについて

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

返品について：
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

| Tool | 説明 |
| 以下に翻訳します。
```
(No text provided for translation)
``` | 以下に翻訳します。
-------------
申し訳ありませんが、翻訳するテキストが提供されていません。テキストを入力してください。 |
| `compass(intent)` | ツールの意味検索。 |
| `describe(tool_name)` | ツールの完全なスキーマを取得します。 |
| `execute(tool_name, args)` | そのシステムのバックエンドでツールを実行する。 |
| `compass_categories()` | カテゴリとサーバーの一覧を表示します。 |
| `compass_status()` | システムの状態と設定。 |
| `compass_analytics(timeframe)` | 利用状況に関する統計データ。 |
| `compass_chains(action)` | ツールのワークフローを管理する。 |
| `compass_sync(force)` | バックエンドからインデックスを再構築します。 |
| `compass_audit()` | システム全体のレポート。 |

## 設定

| 変数 | 説明 | デフォルト設定 |
| 以下に翻訳します。
----------
The company is committed to providing high-quality products and services.
(当社は、高品質な製品とサービスを提供することに尽力しています。) | 以下に翻訳します。
-------------
申し訳ありませんが、翻訳するテキストが提供されていません。テキストを入力してください。 | 以下に翻訳します。
---------
Please provide the English text you would like me to translate. |
| `TOOL_COMPASS_BASE_PATH` | プロジェクトのルートディレクトリ。 | 自動検出されました。 |
| `TOOL_COMPASS_PYTHON` | Python実行ファイル。 | 自動検出されました。 |
| `TOOL_COMPASS_CONFIG` | 設定ファイルのパス。 | `./compass_config.json` |
| `OLLAMA_URL` | OllamaサーバーのURL。 | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUIサーバー | `http://localhost:8188` |

すべてのオプションについては、`.env.example` ファイルを参照してください。

## パフォーマンス

| メートル法。 | Value |
| 以下に翻訳します。
-------- | The company is committed to providing high-quality products and services.
(会社は、高品質な製品とサービスを提供することに尽力しています。)
------- |
| インデックスのビルドにかかる時間。 | 約5秒で44種類のツールを使用可能。 |
| クエリの応答時間。 | 約15ミリ秒（エンベディング処理を含む）。 |
| トークンによる貯蓄. | 約95% (38,000 → 2,000) |
| 精度@3 (または、精度：上位3件) | 約95%（上位3つのツールの中で、適切なツールが選択されている割合） |

## テスト

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## トラブルシューティング (問題解決)

### MCPサーバーに接続できません

もしClaude DesktopのログにJSONの解析エラーが表示される場合：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因**: `print()` 関数が JSON-RPC プロトコルを破壊している。

**修正方法:** ログ出力を使用するか、`file=sys.stderr` を指定してください。
```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollamaとの接続に失敗しました

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

AIを活用した開発を支援する**Compassスイート**の一部です。

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - 意味に基づいたファイル検索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - ベクトル埋め込み技術を用いたGradioコンポーネント
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - ヘッドレス環境での大規模言語モデルのファインチューニング
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 複雑さを取り除いたComfyUI

## 貢献する

貢献を歓迎します！詳細については、[CONTRIBUTING.md](CONTRIBUTING.md) をご参照ください。

## セキュリティ

セキュリティ上の脆弱性については、[SECURITY.md](SECURITY.md) をご参照ください。**セキュリティに関するバグは、公開の issue として報告しないでください。**

## サポート

- **質問 / ヘルプ:** [Discussions](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
- **バグ報告:** [Issues](https://github.com/mcp-tool-shop-org/tool-compass/issues)
- **セキュリティ:** [SECURITY.md](SECURITY.md)

## ライセンス

[MIT](LICENSE) - 詳細については、LICENSE ファイルをご参照ください。

## クレジット

- **HNSW**: Malkov & Yashunin, "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs" (2016)
- **nomic-embed-text**: Nomic AI のオープン埋め込みモデル
- **FastMCP**: Anthropic の MCP フレームワーク
- **Gradio**: Hugging Face の機械学習ウェブフレームワーク

---

<div align="center">

*"Syntropy above all else."*

Tool Compass は、ツールを意味的な関連性で整理することで、MCP エコシステムにおけるエントロピーを低減します。

**[ドキュメント](https://github.com/mcp-tool-shop-org/tool-compass#readme)** • **[Issue](https://github.com/mcp-tool-shop-org/tool-compass/issues)** • **[Discussions](https://github.com/mcp-tool-shop-org/tool-compass/discussions)**

</div>
