<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**MCPツールのためのセマンティックナビゲーター - 目的によって適切なツールを見つけ、記憶に頼らない**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*トークン数を95%削減。実行したい内容を記述することでツールを見つけることができます。*

[インストール](#quick-start) • [使い方](#usage) • [Docker](#option-2-docker) • [ハンドブック](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [パフォーマンス](#performance) • [貢献方法](#contributing)

</div>

---

## 問題点

MCPサーバーは、数十から数百のツールを公開しています。すべてのツールの定義をコンテキストにロードすると、トークンが無駄になり、応答が遅くなります。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解決策

Tool Compassは、**セマンティック検索**を使用して、自然言語による記述から関連するツールを見つけます。すべてのツールをロードする代わりに、Claudeは意図とともに`compass()`を呼び出し、関連するツールのみを取得します。

## クイックスタート

📖 **完全なドキュメント:** インストール、構成、およびアーキテクチャの詳細については、[Tool Compass Handbook](https://mcp-tool-shop-org.github.io/tool-compass/handbook/)を参照してください。

### オプション1：npm（前提条件なし、Pythonのインストール不要）

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve     # MCP gateway
npx @mcptoolshop/tool-compass ui        # Gradio UI
npx @mcptoolshop/tool-compass doctor    # Diagnose setup
```

初回実行時に検証済みのプラットフォームバイナリをダウンロードします（SHA256でGitHubリリースに対してチェックされます）。ローカルにキャッシュされ、その後の呼び出しは瞬時に開始されます。npmの[@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass)を参照してください。

### オプション2：PyPI

```bash
pip install tool-compass
tool-compass --help
```

### オプション3：ローカルクローン

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

### オプション4：Docker

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

> GHCRイメージ（`ghcr.io/mcp-tool-shop-org/tool-compass`）は、
> `linux/amd64`と`linux/arm64`をサポートしているため、同じタグをx86_64サーバーとApple Silicon / ARMワークステーションで実行できます。

## 機能

- **セマンティック検索** - 実行したい内容を記述することでツールを見つける
- **段階的な情報開示** - `compass()` → `describe()` → `execute()`
- **ホットキャッシュ** - よく使用されるツールは事前にロードされる
- **チェーン検出** - 一般的なツールのワークフローを自動的に検出する
- **分析** - 使用パターンとツールのパフォーマンスを追跡する
- **クロスプラットフォーム** - Windows、macOS、Linux
- **Docker対応** - 1つのコマンドでデプロイ可能

## アーキテクチャ

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
| `describe(tool_name)` | ツールの完全なスキーマを取得する |
| `execute(tool_name, args)` | バックエンドでツールを実行する |
| `compass_categories()` | カテゴリとサーバーを一覧表示する |
| `compass_status()` | システムの状態と構成 |
| `compass_analytics(timeframe)` | 使用状況の統計情報 |
| `compass_chains(action)` | ツールのワークフローを管理する |
| `compass_sync(force)` | バックエンドからインデックスを再構築する |
| `compass_audit()` | 完全なシステムレポート |

### 段階的な情報開示パターン

Tool Compassは、トークンの使用量を最小限に抑えるために、3つのステップで構成される段階的な情報開示パターンを使用します。

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**重要な理由：**
- 77個のツールを事前にロードすると、約38,500トークン消費されます。
- 段階的な情報開示では、使用するツールごとに約600トークン消費されます。
- 節約効果：**一般的なワークフローで95%以上**

**例：**

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

`compass()`の結果の`hint`フィールドは、このフローをガイドし、`describe()`を使用するタイミングを示唆します。

## 設定

| 変数 | 説明 | デフォルト値 |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | プロジェクトルート | 自動検出 |
| `TOOL_COMPASS_PYTHON` | Python実行ファイル | 自動検出 |
| `TOOL_COMPASS_CONFIG` | 設定ファイルのパス | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | データディレクトリ | プラットフォーム固有（下記参照） |
| `OLLAMA_URL` | OllamaサーバーのURL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUIサーバー | `http://localhost:8188` |
| `PORT` | HTTPトランスポートを有効にするために設定します（例：Fly.io用）。 | 未設定（stdio） |

**デフォルトのデータディレクトリ:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/`（または `$XDG_CONFIG_HOME/tool-compass/`）

すべてのオプションについては、[`.env.example`](.env.example)を参照してください。

## パフォーマンス

| 指標 | 値 |
|--------|-------|
| インデックスのビルド時間 | 約5秒（44個のツールの場合） |
| クエリのレイテンシー | 約15ミリ秒（埋め込みを含む） |
| トークンの節約 | 約95%（38K → 2K） |
| Accuracy@3 | 約95%（上位3つのツールのうち、正しいツールが1つ含まれる） |

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

Claude DesktopのログにJSON解析エラーが表示される場合：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因:** `print()`ステートメントがJSON-RPCプロトコルを破損させています。

**修正:** ロギングまたは`file=sys.stderr`を使用します。
```python
import sys
print("Debug message", file=sys.stderr)
```

### Ollamaへの接続に失敗しました

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### インデックスが見つかりません

```bash
tool-compass sync
```

## 関連プロジェクト

AIを活用した開発のための**Compass Suite**の一部：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - セマンティックファイル検索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - ベクトル埋め込みされたGradioコンポーネント
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - ヘッドレスLLMのファインチューニング
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 複雑さを排除したComfyUI

## 貢献

ご協力をお待ちしております！[CONTRIBUTING.md](CONTRIBUTING.md)にガイドラインが記載されています。

## セキュリティとデータ範囲

Tool Compassは、**ローカル優先**の開発ツールです。[SECURITY.md](SECURITY.md)に完全なポリシーが記載されています。

- **アクセスされたデータ:** ローカルの HNSW ベクトルデータベースにインデックス登録されているツールの説明、ローカル SQLite (`compass_analytics.db`) に記録される検索クエリ、ローカルの Ollama で生成される埋め込みベクトル。
- **アクセスされていないデータ:** ユーザーコード、ファイルの内容、認証情報。ツールの呼び出し引数はハッシュ化され、プレーンテキストで保存されない。
- **ネットワーク:** ローカルの Ollama に接続して埋め込みベクトルを取得する。オプションで Gradio UI をローカルホストにバインドする。外部へのテレメトリーは行わない。
- **テレメトリーなし:** 外部には何もデータを収集しない。分析はローカルでのみ行う。

## スコアカード

カテゴリごとのスコアは、スワーム処理後に以下のコマンドで再生成される:
`bash scripts/regenerate-scorecard.sh` (これは `npx @mcptoolshop/shipcheck audit` をラップしたもの)。現在の公式な詳細については [SCORECARD.md](SCORECARD.md) を参照してください。以下に示す表は、それを反映したものであり、意図的に手動で作成されていません。手動で編集されたセクション (既知の課題、修正履歴) は、`<!-- SHIPCHECK-AUTO-START/END -->` マーカーの外に SCORECARD.md に存在し、再生成時に保持されます。

| カテゴリ | スコア | 注釈 |
|----------|-------|-------|
| A. セキュリティ | 未定 (TBD) | SHA で固定されたアクション、ダイジェストで固定されたベースイメージ、SLSA プロベナンス + SBOM を PyPI および GHCR に適用、pre-commit によるシークレットスキャン |
| B. エラー処理 | 未定 (TBD) | 構造化された結果、適切なフォールバック、終了コード |
| C. 運用ドキュメント | 未定 (TBD) | README、CHANGELOG、LICENSE、Makefile の `verify` + `verify-metrics` + `scorecard` コマンド |
| D. リリース衛生管理 | 未定 (TBD) | CI を統合、すべてのジョブでタイムアウト時間と保持期間を設定、pytest 設定を pyproject.toml に記述 |
| E. アイデンティティ (ソフト) | 未定 (TBD) | ロゴ、ランディングページ、GitHub メタデータ、pyproject.toml で明示的に指定されたメンテナー |
| **Total** | **TBD** | `make scorecard` コマンドで再生成 |

## ライセンス

[MIT](LICENSE) - 詳細については LICENSE ファイルを参照してください。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

