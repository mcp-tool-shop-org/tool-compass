<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**Navegador semântico para ferramentas MCP - Encontre a ferramenta certa pela intenção, não pela memória**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% menos tokens. Encontre ferramentas descrevendo o que você quer fazer.*

[Instalação](#quick-start) • [Uso](#usage) • [Docker](#option-2-docker) • [Manual](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Desempenho](#performance) • [Contribuições](#contributing)

</div>

---

## O Problema

Servidores MCP expõem dezenas ou centenas de ferramentas. Carregar todas as definições de ferramentas no contexto desperdiça tokens e diminui a velocidade das respostas.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## A Solução

O Tool Compass usa **busca semântica** para encontrar ferramentas relevantes a partir de uma descrição em linguagem natural. Em vez de carregar todas as ferramentas, o Claude chama `compass()` com uma intenção e recebe apenas as ferramentas relevantes.

<!--
## Demonstração

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## Início Rápido

📖 **Documentação completa:** Consulte o [Manual do Tool Compass](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) para instalação, configuração e informações detalhadas sobre a arquitetura.

### Opção 1: npm (sem pré-requisitos, sem instalação do Python)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve     # MCP gateway
npx @mcptoolshop/tool-compass ui        # Gradio UI
npx @mcptoolshop/tool-compass doctor    # Diagnose setup
```

Baixa um binário da plataforma verificado na primeira execução (verificado com o hash SHA256 em relação à versão do GitHub). Armazenado localmente — as execuções subsequentes são instantâneas. Veja o [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) no npm.

### Opção 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### Opção 3: Clonagem local

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

### Opção 4: Docker

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

> A imagem do GHCR (`ghcr.io/mcp-tool-shop-org/tool-compass`) suporta
> `linux/amd64` e `linux/arm64`, então a mesma tag funciona em servidores x86_64
> e em estações de trabalho Apple Silicon / ARM.

## Recursos

- **Busca Semântica** - Encontre ferramentas descrevendo o que você quer fazer
- **Divulgação Progressiva** - `compass()` → `describe()` → `execute()`
- **Cache Rápido** - Ferramentas frequentemente usadas são pré-carregadas
- **Detecção de Cadeia** - Descobre automaticamente fluxos de trabalho comuns de ferramentas
- **Análise** - Acompanhe padrões de uso e desempenho das ferramentas
- **Compatível com Diversas Plataformas** - Windows, macOS, Linux
- **Pronto para Docker** - Implantação com um único comando

## Arquitetura

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

## Uso

### A Ferramenta `compass()`

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Retorna:
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

### Ferramentas Disponíveis

| Ferramenta | Descrição |
|------|-------------|
| `compass(intent)` | Busca semântica para ferramentas |
| `describe(tool_name)` | Obtém o esquema completo de uma ferramenta |
| `execute(tool_name, args)` | Executa uma ferramenta em seu backend |
| `compass_categories()` | Lista categorias e servidores |
| `compass_status()` | Estado e configuração do sistema |
| `compass_analytics(timeframe)` | Estatísticas de uso |
| `compass_chains(action)` | Gerencia fluxos de trabalho de ferramentas |
| `compass_sync(force)` | Reconstrói o índice a partir dos backends |
| `compass_audit()` | Relatório completo do sistema |

### Padrão de Divulgação Progressiva

O Tool Compass usa um padrão de divulgação progressiva em três etapas para minimizar o uso de tokens:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**Por que isso é importante:**
- Carregar 77 ferramentas inicialmente = ~38.500 tokens
- Divulgação progressiva = ~600 tokens por ferramenta usada
- Economia: **95%+ para fluxos de trabalho típicos**

**Exemplo de fluxo de trabalho:**

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

O campo `hint` nos resultados do `compass` guia esse fluxo, sugerindo quando usar `describe()`.

## Configuração

| Variável | Descrição | Padrão |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Diretório do projeto | Detectado automaticamente |
| `TOOL_COMPASS_PYTHON` | Executável do Python | Detectado automaticamente |
| `TOOL_COMPASS_CONFIG` | Caminho do arquivo de configuração | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Diretório de dados | Específico da plataforma (veja abaixo) |
| `OLLAMA_URL` | URL do servidor Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | Servidor ComfyUI | `http://localhost:8188` |
| `PORT` | Defina para habilitar o transporte HTTP (por exemplo, para Fly.io) | não definido (stdio) |

**Diretórios de dados padrão:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/` (ou `$XDG_CONFIG_HOME/tool-compass/`)

Consulte o arquivo [`.env.example`](.env.example) para todas as opções.

## Desempenho

| Métrica | Valor |
|--------|-------|
| Tempo de construção do índice | ~5s para 44 ferramentas |
| Latência da consulta | ~15ms (incluindo incorporação) |
| Economia de tokens | ~95% (38K → 2K) |
| Precisão@3 | ~95% (ferramenta correta no top 3) |

## Testes

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## Solução de problemas

### Servidor MCP não está se conectando

Se os logs do Claude Desktop mostrarem erros de análise JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa:** As instruções `print()` corrompem o protocolo JSON-RPC.

**Solução:** Use logging ou `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Conexão Ollama falhou

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Índice não encontrado

```bash
python gateway.py --sync
```

## Projetos relacionados

Parte da **Suite Compass** para desenvolvimento com inteligência artificial:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Busca semântica de arquivos
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componentes Gradio com incorporação vetorial
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajuste fino de LLM sem servidor
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sem a complexidade

## Contribuições

Aceitamos contribuições! Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para obter as diretrizes.

## Segurança e Escopo de Dados

Tool Compass é uma ferramenta de desenvolvimento **local-first**. Consulte [SECURITY.md](SECURITY.md) para obter a política completa.

- **Dados acessados:** Descrições de ferramentas indexadas em um banco de dados vetorial HNSW local, consultas de pesquisa registradas em um arquivo SQLite local (`compass_analytics.db`), incorporações geradas via Ollama local.
- **Dados NÃO acessados:** nenhum código do usuário, nenhum conteúdo de arquivo, nenhuma credencial. Os argumentos de chamada da ferramenta são armazenados em hash, não em texto simples.
- **Rede:** Conecta-se ao Ollama local para incorporações. A interface do usuário Gradio opcional é vinculada ao localhost. Sem telemetria externa.
- **Sem telemetria:** Não coleta nada externamente. A análise é apenas local.

## Scorecard

As pontuações por categoria são regeneradas após a análise via
`bash scripts/regenerate-scorecard.sh` (que envolve `npx
@mcptoolshop/shipcheck audit`). Consulte [SCORECARD.md](SCORECARD.md) para obter a
análise detalhada atual — a tabela abaixo a replica e não é escrita manualmente. As seções cuidadosamente selecionadas (Lacunas Conhecidas,
Histórico de Correção) estão localizadas fora dos marcadores `<!-- SHIPCHECK-AUTO-START/END -->` em SCORECARD.md e sobrevivem às regenerações.

| Categoria | Pontuação | Observações |
|----------|-------|-------|
| A. Segurança | A ser definido | Ações com hash fixo; imagem base com hash fixo; rastreabilidade SLSA + SBOM no PyPI + GHCR; verificação de segredos no pre-commit |
| B. Tratamento de Erros | A ser definido | Resultados estruturados, degradação graciosa, códigos de saída |
| C. Documentação para Operadores | A ser definido | README, CHANGELOG, LICENSE, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. Higiene de Distribuição | A ser definido | CI consolidado; tempo limite em minutos + retenção em dias para cada tarefa; configuração pytest em pyproject.toml |
| E. Identidade (suave) | A ser definido | Logo, página inicial, metadados do GitHub; mantenedores explícitos em pyproject.toml |
| **Total** | **TBD** | Regenerar via `make scorecard` |

## Licença

[MIT](LICENSE) - consulte o arquivo LICENSE para obter detalhes.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

