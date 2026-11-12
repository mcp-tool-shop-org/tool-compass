<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="800"></p>

**Navegador semântico para ferramentas MCP – Encontre a ferramenta certa por intenção, não por memória**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
<a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% menos tokens. Encontre ferramentas descrevendo o que você deseja fazer.*

[Instalação](#início-rápido) • [Uso](#uso) • [Docker](#option-2-docker) • [Manual](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Desempenho](#desempenho) • [Contribuição](#contribuições)

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

## Início Rápido

📖 **Documentação completa:** Consulte o [Manual do Tool Compass](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) para obter informações detalhadas sobre instalação, configuração e arquitetura.

### Opção 1: npm (sem pré-requisitos, sem instalação do Python)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve                 # MCP gateway
npx @mcptoolshop/tool-compass ui                    # Gradio UI
npx @mcptoolshop/tool-compass doctor                # Diagnose setup
npx @mcptoolshop/tool-compass execute fs:read_file '{"path":"README.md"}'  # Smoke-test a proxied call
```

Baixa um binário de plataforma verificado na primeira execução (SHA256 verificado em relação ao GitHub Release). Armazenado localmente – invocações subsequentes são iniciadas instantaneamente. Consulte [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) no npm.

### Opção 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### Opção 3: Clone local

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

# Start with Docker Compose (requires Ollama running locally and a UI login)
GRADIO_AUTH=user:pass docker compose up

# Or include Ollama in the stack
GRADIO_AUTH=user:pass docker compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

Ou execute a imagem da interface do usuário publicada diretamente, sem clonar:

```bash
docker run --rm -p 7860:7860 \
  -e GRADIO_AUTH=user:pass \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:ui
```

> **Login da interface do usuário necessário em contêineres.** Como o contêiner vincula `0.0.0.0`,
> a inicialização se recusa a ser executada sem um login. Inicie-o de uma das duas maneiras: defina
> `GRADIO_AUTH=user:pass` (via `.env`, ambiente de shell ou `-e`) ou defina
> `TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1` ao implantar atrás de um proxy reverso que
> aplica seu próprio login (imprime um aviso de inicialização e oculta os controles de execução da interface do usuário).

> **Monte o volume.** O índice semântico está localizado em `/app/tool_compass/db`, e
> construí-lo significa incorporar cada ferramenta em cada servidor configurado. Sem um
> volume, esse trabalho é descartado quando o contêiner é encerrado e repetido na
> próxima inicialização – o que é interpretado como "O Tool Compass é lento", em vez de uma configuração ausente. A imagem avisa se você esquecer. `docker compose up` já monta um
> volume nomeado, portanto, isso se aplica apenas a `docker run`.

> A imagem GHCR (`ghcr.io/mcp-tool-shop-org/tool-compass`) oferece suporte a
> `linux/amd64` e `linux/arm64`, portanto, a mesma tag é executada em servidores x86_64
> e estações de trabalho Apple Silicon / ARM.

Para executar o contêiner do **gateway HTTP MCP** (estágio `mcp-gateway`, porta `8080`), forneça um token de portador – porque o contêiner vincula `HOST=0.0.0.0`, ele se recusa a iniciar sem `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (ou `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1` quando estiver atrás de um proxy reverso de autenticação):

```bash
# Docker Compose (gateway profile)
TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> docker compose --profile gateway up

# Or published gateway image directly
docker run --rm -p 8080:8080 \
  -e TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:gateway
```

## Recursos

- **Busca Híbrida** - Semântica (HNSW) + fusão léxica com reforço de nome exato – descreva o que você deseja ou cole o nome de uma ferramenta e ela será classificada como a primeira.
- **Divulgação Progressiva de Esquema Completo** - `compass()` → `describe()` → `execute()`; `describe()` retorna o `inputSchema` completo (campos obrigatórios, descrições, enumerações, valores padrão)
- **Backends stdio + HTTP** - Servidores MCP locais de subprocesso frontal *e* servidores remotos / SaaS via HTTP transmissível, com autenticação opcional de token de portador
- **Timeouts e permissão/negação por ferramenta** - Substitua o tempo limite padrão por backend/ferramenta; exponha um subconjunto seguro de um backend amplo
- **Cache Quente e Detecção de Cadeia** - Ferramentas frequentemente usadas pré-carregadas; fluxos de trabalho comuns de ferramentas descobertos automaticamente
- **Análise** - Rastreie padrões de uso e desempenho de ferramentas (com retenção/limpeza)
- **Compatível com várias plataformas e pronto para Docker** - Windows, macOS, Linux; implantação com um único comando

## Arquitetura

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

## Uso

### A ferramenta `compass()`

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

### Ferramentas disponíveis

| Ferramenta | Descrição |
|------|-------------|
| `compass(intent)` | Busca híbrida semântica + léxica com reforço de nome exato |
| `describe(tool_name)` | Obtenha o `inputSchema` completo de uma ferramenta (obrigatórios/enumerações/padrões) |
| `execute(tool_name, args)` | Execute uma ferramenta em seu backend |
| `compass_categories()` | Liste categorias e servidores |
| `compass_status(active)` | Saúde e configuração do sistema; `active=True` executa uma sonda de atividade de backend ao vivo |
| `compass_analytics(timeframe)` | Estatísticas de uso |
| `compass_chains(action)` | Gerencie fluxos de trabalho de ferramentas |
| `compass_sync(force)` | Reconstrua o índice a partir dos backends |
| `compass_audit()` | Relatório completo do sistema |

As mesmas ações estão disponíveis na CLI – incluindo `tool-compass execute <tool> '<json>'` para testar uma chamada proxy do terminal.

### Padrão de Divulgação Progressiva

O Tool Compass usa um padrão de divulgação progressiva de três etapas para minimizar o uso de tokens:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**Por que isso é importante:**
- Carregar 77 ferramentas inicialmente = ~38.500 tokens
- Divulgação progressiva = ~600 tokens por ferramenta usada
- Economia: **95% ou mais para fluxos de trabalho típicos**

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

O campo `hint` nos resultados do compass guia esse fluxo, sugerindo quando usar `describe()`.

## Configuração

| Variável | Descrição | Padrão |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Diretório do projeto | Detectado automaticamente |
| `TOOL_COMPASS_PYTHON` | Executável Python | Detectado automaticamente |
| `TOOL_COMPASS_CONFIG` | Caminho do arquivo de configuração | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Diretório de dados | Específico da plataforma (veja abaixo) |
| `OLLAMA_URL` | URL do servidor Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI servidor | `http://localhost:8188` |
| `PORT` | Defina para habilitar o transporte HTTP (por exemplo, para Fly.io) | não definido (stdio) |
| `HOST` | Endereço de vinculação para o transporte HTTP; valores não de loopback exigem `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (ou `gateway_auth_token`), a menos que `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1` seja definido | `127.0.0.1` |
| `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` | Token de portador para o transporte HTTP (substitui `gateway_auth_token` em `compass_config.json`). Obrigatório quando `HOST` não for loopback (`127.0.0.1`, `localhost`, `::1`); opcional em loopback | não definido (recusa em loopback) |
| `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN` | Defina como `1` para permitir a vinculação do gateway HTTP fora do loopback sem um token de portador quando um proxy reverso de autenticação estiver presente (registra um aviso em cada inicialização) | não definido (desativado) |
| `GRADIO_AUTH` | Login da interface do usuário (`user:pass`); aplicado em cada inicialização da interface do usuário quando definido e obrigatório fora do loopback / no Docker / em `--share` | não definido (apenas loopback) |
| `TOOL_COMPASS_UI_ALLOW_NO_LOGIN` | Defina como `1` para permitir que a interface do usuário seja iniciada sem o loopback, sem `GRADIO_AUTH` atrás de um proxy de autenticação (emite avisos e oculta os controles de execução). | desdefinir |

**Diretórios de dados padrão:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/` (ou `$XDG_CONFIG_HOME/tool-compass/`)

Configurações do arquivo de configuração (em `compass_config.json`) adicionadas em v2.5.0 — `hybrid_search`,
`exact_name_boost`, por backend `default_timeout` / `tool_timeouts`,
`allow_tools` / `deny_tools`, `analytics_retention_days` e HTTP (`type: "http"`)
backends — estão documentadas em [Manual → Configuração](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/).
Consulte [`.env.example`](.env.example) para opções de variáveis de ambiente.

## Desempenho

| Métrica | Valor |
|--------|-------|
| Tempo de construção do índice | ~5 segundos para 44 ferramentas |
| Latência da consulta | ~15 ms (incluindo a incorporação) |
| Economia de tokens | ~95% (38 mil → 2 mil) |
| Precisão@3 | ~95% (ferramenta correta nos 3 primeiros resultados) |

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

**Causa**: As instruções `print()` corrompem o protocolo JSON-RPC.

**Correção**: Use o registro ou `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Falha na conexão do Ollama

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Índice não encontrado

```bash
tool-compass sync
```

## Projetos relacionados

Parte do **Compass Suite** para desenvolvimento com tecnologia de IA:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Pesquisa semântica de arquivos
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componentes Gradio com incorporação vetorial
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajuste fino de LLM sem interface gráfica
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sem a complexidade

## Contribuições

Agradecemos as contribuições! Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para obter diretrizes.

## Segurança e escopo de dados

Tool Compass é uma ferramenta de desenvolvimento **local-first**. Consulte [SECURITY.md](SECURITY.md) para obter a política completa.

- **Dados acessados:** descrições de ferramentas indexadas no banco de dados vetorial HNSW local, consultas de pesquisa registradas no SQLite local (`compass_analytics.db`), incorporações geradas por meio do Ollama local.
- **Dados NÃO acessados:** nenhum código de usuário, nenhum conteúdo de arquivo, nenhuma credencial. Os argumentos da chamada de ferramenta são criptografados, não armazenados em texto simples.
- **Rede:** conecta-se ao Ollama local para incorporações. A interface do usuário Gradio opcional é vinculada ao localhost. Sem telemetria externa.
- **Sem telemetria:** não coleta nada externamente. A análise é apenas local.

## Scorecard

As pontuações por categoria são regeneradas após o swarm por meio de `bash scripts/regenerate-scorecard.sh` (que envolve `npx @mcptoolshop/shipcheck audit`). Consulte [SCORECARD.md](SCORECARD.md) para obter a análise atual e definitiva — a tabela abaixo a espelha e não é intencionalmente criada manualmente. As seções criadas manualmente (Lacunas conhecidas, Histórico de correção) estão fora dos marcadores `<!-- SHIPCHECK-AUTO-START/END -->` em SCORECARD.md e sobrevivem às regenerações.

Último `shipcheck audit`: **32 verificados · 0 não verificados · 5 ignorados · 100% de aprovação — todos os critérios obrigatórios são atendidos.**

| Categoria | Pontuação | Observações |
|----------|-------|-------|
| A. Segurança | ✅ Aprovado | Ações com hash SHA; imagem base com hash de digestão; proveniência SLSA + SBOM em PyPI + GHCR; verificação de segredos pré-commit; autenticação de portão opcional. |
| B. Tratamento de erros | ✅ Aprovado | Resultados estruturados, degradação gradual, códigos de saída |
| C. Documentação do operador | ✅ Aprovado | README, CHANGELOG, LICENSE, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. Higiene de envio | ✅ Aprovado | CI consolidado; tempo limite em minutos + retenção em dias em cada tarefa; configuração do pytest em pyproject.toml |
| E. Identidade (suave) | ✅ Aprovado | Logotipo, página de destino, metadados GitHub; mantenedores explícitos em pyproject.toml |
| **Total** | **100%** | Todos os critérios obrigatórios são atendidos — regenere por meio de `make scorecard` |

## Licença

[MIT](LICENSE) — consulte o arquivo LICENSE para obter detalhes.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

