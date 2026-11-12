<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="800"></p>

**MCPツールのセマンティックナビゲーター：目的別に最適なツールを見つけましょう。ツールの機能を暗記する必要はありません。**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
<a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*トークンの使用量を95%削減。やりたいことを説明することで、必要なツールを見つけられます。*

[インストール](#クイックスタート) • [使い方](#使用方法) • [Docker](#option-2-docker) • [ハンドブック](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [パフォーマンス](#パフォーマンス) • [貢献方法](#貢献)

</div>

---

## 問題点

MCPサーバーには、数十から数百ものツールが用意されています。すべてのツールの定義を読み込んでおくことは、トークンの消費を増やし、応答速度を低下させるため、非効率です。

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## 解決策

Tool Compassは、自然言語による説明から関連するツールを検索するために、**セマンティック検索**を使用します。すべてのツールを読み込む代わりに、Claudeは意図を`compass()`に送信し、関連するツールのみを取得します。

## クイックスタート

📖 **詳細なドキュメント:** インストール、設定、およびアーキテクチャの詳細については、[Tool Compass Handbook](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) を参照してください。

### オプション1：npm（前提条件なし、Pythonのインストールは不要）

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve                 # MCP gateway
npx @mcptoolshop/tool-compass ui                    # Gradio UI
npx @mcptoolshop/tool-compass doctor                # Diagnose setup
npx @mcptoolshop/tool-compass execute fs:read_file '{"path":"README.md"}'  # Smoke-test a proxied call
```

初回実行時に、検証済みのプラットフォームバイナリをダウンロードします（SHA256で、GitHubのリリースに対してチェックされます）。ローカルにキャッシュされるため、その後の実行はすぐに開始されます。npmの[@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass)を参照してください。

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

# Start with Docker Compose (requires Ollama running locally and a UI login)
GRADIO_AUTH=user:pass docker compose up

# Or include Ollama in the stack
GRADIO_AUTH=user:pass docker compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

または、クローンせずに、公開されているUIイメージを直接実行します。

```bash
docker run --rm -p 7860:7860 \
  -e GRADIO_AUTH=user:pass \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:ui
```

> **コンテナーでは、UIへのログインが必要です。** コンテナーが`0.0.0.0`にバインドされるため、ログインなしでは起動できません。次の2つの方法のいずれかで起動してください。`GRADIO_AUTH=user:pass`を設定します（`.env`、シェル環境、または`-e`を使用）。または、独自のログインを強制するリバースプロキシの背後でデプロイする場合は、`TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1`を設定します（起動時に警告が表示され、UIの実行コントロールが非表示になります）。

**ボリュームをマウントします。** セマンティックインデックスは`/app/tool_compass/db`に存在し、これをビルドすることは、すべてのツールをすべての設定済みのサーバーに組み込むことを意味します。ボリュームがない場合、コンテナーが終了するとその作業は破棄され、次の起動時に再度実行されることになります。これは、「ツールコンパスの動作が遅い」という問題として現れ、フラグが不足しているという問題とは異なります。イメージは、もし忘れてしまった場合に警告を表示します。`docker compose up`はすでに名前付きボリュームをマウントしているので、これはプレーンな`docker run`にのみ適用されます。

> GHCRイメージ（`ghcr.io/mcp-tool-shop-org/tool-compass`）は、`linux/amd64`と`linux/arm64`をサポートしているため、同じタグがx86_64サーバーとApple Silicon / ARMワークステーションで実行できます。

**MCP HTTPゲートウェイ**コンテナ（ステージ`mcp-gateway`、ポート`8080`）を実行するには、ベアラートークンを渡してください。コンテナは`HOST=0.0.0.0`にバインドされるため、`TOOL_COMPASS_GATEWAY_AUTH_TOKEN`（または認証を行うリバースプロキシの背後にある場合は`TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1`）がないと起動しません。

```bash
# Docker Compose (gateway profile)
TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> docker compose --profile gateway up

# Or published gateway image directly
docker run --rm -p 8080:8080 \
  -e TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:gateway
```

## 特徴

- **ハイブリッド検索** - セマンティック（HNSW）と語彙的融合を組み合わせ、完全一致する名前を優先的に表示 — 必要な情報を記述するか、ツールの名前を貼り付けると、最も関連性の高い結果が最初に表示されます。
- **完全なスキーマによる段階的な情報開示** - `compass()` → `describe()` → `execute()`；`describe()` は完全な `inputSchema` を返します（必須フィールド、説明、列挙型、デフォルト値）。
- **stdio + HTTP バックエンド** - ローカルのサブプロセス MCP サーバーと、ストリーミング可能な HTTP を介したリモートの / SaaS サーバーをフロントエンドで使用。オプションでベアラー・トークン認証を使用。
- **ツールごとのタイムアウトと許可/拒否** - バックエンド/ツールごとにデフォルトのタイムアウトを上書きします。広範なバックエンドから安全なサブセットを抽出します。
- **ホットキャッシュとチェーン検出** - よく使用されるツールを事前に読み込みます。一般的なツールのワークフローを自動的に検出します。
- **分析** - 使用状況のパターンとツールのパフォーマンスを追跡します（保持期間/削除機能付き）。
- **クロスプラットフォーム対応 & Docker 対応** - Windows、macOS、Linux。ワンコマンドでデプロイできます。

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

## 使用方法

### `compass()`ツール

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

返品：
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

| 道具 | 説明 |
|------|-------------|
| `compass(intent)` | 正確な名称による検索を重視した、意味的および語彙的なハイブリッド検索 |
| `describe(tool_name)` | ツールの完全な `inputSchema`（必須項目／列挙型／デフォルト値）を取得します。 |
| `execute(tool_name, args)` | バックエンドでツールを実行する。 |
| `compass_categories()` | カテゴリとサーバーのリスト |
| `compass_status(active)` | システムの健全性と構成状況。`active=True`は、稼働中のバックエンドに対して、稼働状況を監視するプログラムを実行します。 |
| `compass_analytics(timeframe)` | 利用状況に関する統計データ |
| `compass_chains(action)` | ツールのワークフローを管理する。 |
| `compass_sync(force)` | バックエンドからインデックスを再構築する。 |
| `compass_audit()` | システム全体のレポート |

同じ操作をコマンドラインインターフェース（CLI）から実行できます。具体的には、ターミナルからプロキシ経由の呼び出しを簡易テストするための操作（`tool-compass execute <tool> '<json>'`など）が含まれます。

### 段階的な情報開示パターン

Tool Compassは、トークンの使用量を最小限に抑えるために、段階的に情報を開示する3段階のプロセスを採用しています。

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**なぜこれが重要なのか：**
- 77個のツールを事前に読み込むと、約38,500トークンを消費する。
- プログレッシブ・ディスクロージャー（段階的な情報開示）を採用すると、使用するツールごとに約600トークンが消費される。
- 削減効果：**一般的なワークフローでは95%以上**

**ワークフローの例:**

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

コンパスの結果に表示される「`hint`」の項目は、この処理の流れを制御し、いつ「`describe()`」を使用すべきかを示します。

## 設定

| 変数 | 説明 | デフォルト |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | プロジェクトのルートディレクトリ | 自動検出 |
| `TOOL_COMPASS_PYTHON` | Python実行ファイル | 自動検出 |
| `TOOL_COMPASS_CONFIG` | 設定ファイルのパス | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | データディレクトリ | プラットフォーム固有の機能（下記参照） |
| `OLLAMA_URL` | OllamaサーバーのURL | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUIサーバー | `http://localhost:8188` |
| `PORT` | HTTPトランスポートを有効にする（例：Fly.ioで使用する場合） | （stdio）の設定を解除する。 |
| `HOST` | HTTPトランスポートで使用するバインドアドレスを指定します。ループバックアドレス以外の値を指定する場合は、`TOOL_COMPASS_GATEWAY_AUTH_TOKEN`（または`gateway_auth_token`）を設定する必要があります。ただし、`TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1`が設定されている場合は例外です。 | `127.0.0.1` |
| `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` | HTTPトランスポート用のベアラートークン（`compass_config.json`の`gateway_auth_token`を上書きします）。`HOST`がループバックでない場合（`127.0.0.1`、`localhost`、`::1`）に必須であり、ループバックの場合はオプションです。 | ループバックを無効にする（拒否する）。 |
| `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN` | 値を `1` に設定すると、認証を行うリバースプロキシが前面に配置されている場合に、ベアラートークンなしで HTTP ゲートウェイをループバック外にバインドできるようになります（起動時に警告が記録されます）。 | 無効化（または、設定解除） |
| `GRADIO_AUTH` | UIログイン（`user:pass`）；設定されている場合、UIの起動時に毎回適用され、ループバック、Docker環境、または`--share`上で実行する場合に必須となります。 | 設定解除（ループバックのみ） |
| `TOOL_COMPASS_UI_ALLOW_NO_LOGIN` | `1` に設定すると、認証プロキシの背後で `GRADIO_AUTH` なしにループバック以外でUIを起動できます（警告を表示し、実行コントロールを非表示にします）。 | 設定解除 |

**デフォルトのデータディレクトリ:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/`（または`$XDG_CONFIG_HOME/tool-compass/`）

設定ファイルの設定（`compass_config.json`内）は、v2.5.0で追加されました。
`hybrid_search`、`exact_name_boost`、バックエンドごとの`default_timeout` / `tool_timeouts`、`allow_tools` / `deny_tools`、`analytics_retention_days`、およびHTTP（`type: "http"`）バックエンドに関する情報は、[ハンドブック → 構成](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/)に記載されています。
環境変数オプションについては、[`.env.example`](.env.example)を参照してください。

## パフォーマンス

| 指標 | 値 |
|--------|-------|
| インデックスのビルド時間 | 44個のツールで約5秒 |
| クエリのレイテンシー | 約15ミリ秒（埋め込みを含む） |
| トークンの削減 | 約95%（38K → 2K） |
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

### MCPサーバーへの接続に失敗

Claude DesktopのログにJSON解析エラーが表示される場合：
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**原因:** `print()`ステートメントがJSON-RPCプロトコルを破損させています。

**修正:** ログまたは`file=sys.stderr`を使用します。
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
tool-compass sync
```

## 関連プロジェクト

AIを活用した開発のための**Compass Suite**の一部：

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - セマンティックファイル検索
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - ベクトル埋め込みGradioコンポーネント
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - ヘッドレスLLMのファインチューニング
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - 複雑さを排除したComfyUI

## 貢献

貢献を歓迎します！ガイドラインについては、[CONTRIBUTING.md](CONTRIBUTING.md)を参照してください。

## セキュリティとデータ範囲

Tool Compassは、**ローカル優先**の開発ツールです。完全なポリシーについては、[SECURITY.md](SECURITY.md)を参照してください。

- **アクセスされるデータ:** ローカルHNSWベクトルDBにインデックス化されたツールの説明、ローカルのSQLite（`compass_analytics.db`）に記録された検索クエリ、ローカルのOllamaによって生成された埋め込み。
- **アクセスされないデータ:** ユーザーコード、ファイルの内容、認証情報。ツールの呼び出し引数はハッシュ化され、プレーンテキストで保存されません。
- **ネットワーク:** ローカルのOllamaに接続して埋め込みを行います。オプションのGradio UIは、localhostにバインドされます。外部のテレメトリは行いません。
- **テレメトリなし:** 外部に何も収集しません。分析はローカルでのみ行われます。

## スコアカード

カテゴリごとのスコアは、スワーム後に`bash scripts/regenerate-scorecard.sh`によって再生成されます（`npx @mcptoolshop/shipcheck audit`をラップします）。現在の公式な詳細については、[SCORECARD.md](SCORECARD.md)を参照してください。以下の表はその内容を反映しており、手動で作成されていません。手動で作成されたセクション（既知のギャップ、修正履歴）は、SCORECARD.md内の`<!-- SHIPCHECK-AUTO-START/END -->`マーカーの外に存在し、再生成時に保持されます。

最新の`shipcheck audit`：**32個チェック済み · 0個チェックなし · 5個スキップ · 100%パス — すべてのハードゲートをパス。**

| カテゴリ | スコア | 注記 |
|----------|-------|-------|
| A. セキュリティ | ✅ パス | SHAで固定されたアクション、ダイジェストで固定されたベースイメージ、SLSAプロビナンス + SBOM on PyPI + GHCR、プリコミットのシークレットスキャン、オプトインゲートウェイベアラート認証 |
| B. エラー処理 | ✅ パス | 構造化された結果、正常なデグラデーション、終了コード |
| C. 運用ドキュメント | ✅ パス | README、CHANGELOG、LICENSE、Makefile `verify` + `verify-metrics` + `scorecard` |
| D. 配送の衛生管理 | ✅ パス | CIの統合、すべてのジョブでタイムアウト分と保持期間を設定、pyproject.tomlのpytest設定 |
| E. アイデンティティ（ソフト） | ✅ パス | ロゴ、ランディングページ、GitHubメタデータ、pyproject.tomlに明示的に記載されたメンテナー |
| **Total** | **100%** | すべてのハードゲートをパス — `make scorecard`で再生成 |

## ライセンス

[MIT](LICENSE) - 詳細については、LICENSEファイルを参照してください。

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

