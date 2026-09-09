<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="640"></p>

**MCPツールのためのセマンティックナビゲーター - 記憶ではなく、意図に基づいて適切なツールを見つける**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
<a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*トークン数を95%削減。実行したい内容を記述してツールを見つけます。*

[インストール](#quick-start) • [使い方](#usage) • [Docker](#option-2-docker) • [ハンドブック](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [パフォーマンス](#performance) • [貢献](#contributing)

</div>

---

## 問題点

MCPサーバーは、数十または数百のツールを公開します。すべてのツールの定義をコンテキストにロードすると、トークンが無駄になり、応答が遅くなります。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解決策

Tool Compassは、**セマンティック検索**を使用して、自然言語による記述から関連するツールを見つけます。すべてのツールをロードする代わりに、Claudeは意図とともに`compass()`を呼び出し、関連するツールのみを取得します。

## クイックスタート

📖 **完全なドキュメント:** インストール、構成、アーキテクチャの詳細については、[Tool Compass Handbook](https://mcp-tool-shop-org.github.io/tool-compass/handbook/)を参照してください。

### オプション1：npm（前提条件なし、Pythonのインストール不要）

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve                 # MCP gateway
npx @mcptoolshop/tool-compass ui                    # Gradio UI
npx @mcptoolshop/tool-compass doctor                # Diagnose setup
npx @mcptoolshop/tool-compass execute fs:read_file '{"path":"README.md"}'  # Smoke-test a proxied call
```

初回実行時に、検証済みのプラットフォームバイナリをダウンロードします（SHA256でGitHubリリースに対してチェックされます）。ローカルにキャッシュされ、その後の呼び出しは瞬時に開始されます。npmの[@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass)を参照してください。

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
> `linux/amd64`と`linux/arm64`をサポートしているため、同じタグをx86_64サーバーとApple Silicon / ARMワークステーションの両方で実行できます。

## 機能

- **ハイブリッド検索** - セマンティック（HNSW）+ 語彙的融合、正確な名前によるブースト - 実行したい内容を記述するか、ツールの名前を貼り付けると、最も関連性の高いツールとしてランク付けされます。
- **完全なスキーマの段階的な開示** - `compass()` → `describe()` → `execute()`。`describe()`は完全な`inputSchema`（必須フィールド、説明、列挙型、デフォルト値）を返します。
- **stdio + HTTPバックエンド** - ローカルのサブプロセスMCPサーバーと、ストリーミング可能なHTTP経由のリモート/SaaSサーバーをフロントエンドで処理し、オプションでベアラー・トークン認証を使用します。
- **ツールごとのタイムアウトと許可/拒否** - バックエンド/ツールごとにデフォルトのタイムアウトをオーバーライドします。広範なバックエンドから安全なサブセットを公開します。
- **ホットキャッシュとチェーン検出** - 頻繁に使用されるツールを事前にロードします。一般的なツールのワークフローを自動的に検出します。
- **分析** - 使用状況のパターンとツールのパフォーマンスを追跡します（保持/削除）。
- **クロスプラットフォームとDocker対応** - Windows、macOS、Linux。ワンコマンドでデプロイできます。

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
| `compass(intent)` | 正確な名前によるブーストを備えたハイブリッドセマンティック+語彙検索 |
| `describe(tool_name)` | ツールの完全な`inputSchema`を取得します（必須/列挙型/デフォルト値）。 |
| `execute(tool_name, args)` | ツールのバックエンドでツールを実行します。 |
| `compass_categories()` | カテゴリとサーバーを一覧表示します。 |
| `compass_status(active)` | システムの状態と構成。`active=True`は、ライブバックエンドの稼働状況をチェックします。 |
| `compass_analytics(timeframe)` | 使用状況の統計 |
| `compass_chains(action)` | ツールのワークフローを管理します。 |
| `compass_sync(force)` | バックエンドからインデックスを再構築します。 |
| `compass_audit()` | 完全なシステムレポート |

同じアクションは、CLIからも利用できます。これには、ターミナルからプロキシされた呼び出しをテストするための`tool-compass execute <tool> '<json>'`も含まれます。

### 段階的な開示パターン

Tool Compassは、トークンの使用量を最小限に抑えるために、3段階の段階的な開示パターンを使用します。

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**重要な理由:**
- 77個のツールを事前にロードすると、約38,500トークンになります。
- 段階的な開示では、使用するツールごとに約600トークンです。
- 節約：**典型的なワークフローでは95%以上**

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

compassの結果の`hint`フィールドは、このフローをガイドし、`describe()`を使用するタイミングを示唆します。

## 構成

| 変数 | 説明 | デフォルト値 |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | プロジェクトのルート | 自動検出 |
| `TOOL_COMPASS_PYTHON` | Python実行可能ファイル | 自動検出 |
| `TOOL_COMPASS_CONFIG` | 構成ファイルのパス | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | データディレクトリ | プラットフォーム固有（下記参照） |
| `OLLAMA_URL` | OllamaサーバーのURL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUIサーバー | `http://localhost:8188` |
| `PORT` | HTTPトランスポートを有効にするには、これを設定します（例：Fly.io用）。 | 設定なし（stdio） |
| `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` | HTTPトランスポートで必要なベアラー・トークン（オプトイン。`gateway_auth_token`構成フィールドをオーバーライドします）。 | 設定なし（認証なし） |

**デフォルトのデータディレクトリ:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/`（または`$XDG_CONFIG_HOME/tool-compass/`）

v2.5.0で追加された構成ファイルの設定（`compass_config.json`内）- `hybrid_search`、
`exact_name_boost`、バックエンドごとの`default_timeout` / `tool_timeouts`、
`allow_tools` / `deny_tools`、`analytics_retention_days`、およびHTTP（`type: "http"`）
バックエンドは、[ハンドブック → 構成](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/)に記載されています。
環境変数オプションについては、[`.env.example`](.env.example)を参照してください。

## パフォーマンス

| メトリック | 値 |
|--------|-------|
| インデックスのビルド時間 | 約5秒（44個のツールの場合） |
| クエリのレイテンシー | 約15ms（埋め込みを含む） |
| トークンの節約 | 約95%（38K → 2K） |
| 上位3件の精度 | 約95%（上位3件に正しいツールが含まれる） |

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

**原因:** `print()`ステートメントがJSON-RPCプロトコルを破損させます。

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

AIを活用した開発のための**Compass Suite**の一部です。

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - 意味に基づいたファイル検索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - ベクトル埋め込みされた Gradio コンポーネント
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - ヘッドレス LLM のファインチューニング
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 複雑さを排除した ComfyUI

## 貢献について

皆様からの貢献をお待ちしております！ 貢献ガイドラインについては、[CONTRIBUTING.md](CONTRIBUTING.md) をご覧ください。

## セキュリティとデータ範囲

Tool Compass は、**ローカル優先**の開発ツールです。 詳細は [SECURITY.md](SECURITY.md) を参照してください。

- **処理されるデータ:** ローカル HNSW ベクトル DB にインデックス化されたツールの説明、ローカル SQLite (`compass_analytics.db`) に記録される検索クエリ、ローカル Ollama を介して生成される埋め込み。
- **処理されないデータ:** ユーザーコード、ファイルの内容、認証情報。 ツールの呼び出し引数はハッシュ化され、プレーンテキストで保存されません。
- **ネットワーク:** ローカル Ollama に接続して埋め込みを生成します。 オプションの Gradio UI は localhost にバインドされます。 外部へのテレメトリは行いません。
- **テレメトリなし:** 外部にデータを収集しません。 分析はローカルでのみ行われます。

## スコアカード

カテゴリごとのスコアは、スワーム後に再生成されます。
`bash scripts/regenerate-scorecard.sh` (これは `npx @mcptoolshop/shipcheck audit` をラップします)。 現在の公式な詳細については、[SCORECARD.md](SCORECARD.md) を参照してください。 下の表はそれを反映しており、手動で作成されていません。 手動で作成されたセクション (既知のギャップ、修正履歴) は、SCORECARD.md 内の `<!-- SHIPCHECK-AUTO-START/END -->` マーカーの外に存在し、再生成時に保持されます。

最新の `shipcheck audit`: **32 個チェック済み · 0 個チェックなし · 5 個スキップ · 100% 合格 — すべての必須条件を満たしています。**

| カテゴリ | スコア | 注記 |
|----------|-------|-------|
| A. セキュリティ | ✅ 合格 | SHA で固定されたアクション、ダイジェストで固定されたベースイメージ、SLSA プロビナンス + SBOM (PyPI + GHCR)、プリコミットのシークレットスキャン、オプトインゲートウェイベアラート認証 |
| B. エラー処理 | ✅ 合格 | 構造化された結果、段階的な機能低下、終了コード |
| C. オペレーターのドキュメント | ✅ 合格 | README、CHANGELOG、LICENSE、Makefile `verify` + `verify-metrics` + `scorecard` |
| D. 配送の衛生管理 | ✅ 合格 | CI の統合、すべてのジョブでのタイムアウト時間 + 保持日数、pyproject.toml 内の pytest 構成 |
| E. ID (ソフト) | ✅ 合格 | ロゴ、ランディングページ、GitHub メタデータ、pyproject.toml 内の明示的なメンテナー |
| **Total** | **100%** | すべての必須条件を満たしています — `make scorecard` を介して再生成 |

## ライセンス

[MIT](LICENSE) - 詳細については、LICENSE ファイルを参照してください。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

