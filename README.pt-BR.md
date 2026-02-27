<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

# Bússola de precisão

**Navegador semântico para ferramentas MCP: encontre a ferramenta certa com base na sua necessidade, e não na sua memória.**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*95% menos tokens. Encontre ferramentas descrevendo o que você deseja fazer.*

[Instalação](#quick-start) • [Utilização](#usage) • [Docker](#option-2-docker) • [Desempenho](#performance) • [Contribuições](#contributing)

```
</div>

---

## O problema

Servidores MCP expõem dezenas ou centenas de ferramentas. Carregar todas as definições das ferramentas no contexto desperdiça tokens e torna as respostas mais lentas.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## A solução

A ferramenta Compass utiliza a **busca semântica** para encontrar ferramentas relevantes a partir de uma descrição em linguagem natural. Em vez de carregar todas as ferramentas, o Claude chama a função `compass()` com uma intenção e recebe apenas as ferramentas relevantes.

```text
The company is committed to providing high-quality products and services.
We are constantly innovating to meet the needs of our customers.
Our team is made up of highly skilled professionals.
We value our employees and their contributions.
We are committed to sustainability and environmental responsibility.
```
## Demonstração

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## Início rápido

### Opção 1: Instalação local

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

### Opção 2: Docker

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

## Características

- **Pesquisa Semântica:** Encontre ferramentas descrevendo o que você deseja fazer.
- **Revelação Progressiva:** `compass()` → `describe()` → `execute()`
- **Cache Inteligente:** Ferramentas frequentemente utilizadas são carregadas previamente.
- **Detecção de Cadeias:** Descobre automaticamente fluxos de trabalho comuns de ferramentas.
- **Análise:** Acompanhe padrões de uso e o desempenho das ferramentas.
- **Compatível com Diversas Plataformas:** Windows, macOS, Linux.
- **Pronto para Docker:** Implantação com um único comando.

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

### A ferramenta "compasso"

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Devoluções:
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

| Tool | Descrição. |
| Please provide the English text you would like me to translate. I am ready to translate it into Portuguese. | "Please provide the text you would like me to translate." |
| `compass(intent)` | Pesquisa semântica para ferramentas. |
| `describe(tool_name)` | Obtenha o esquema completo de uma ferramenta. |
| `execute(tool_name, args)` | Execute uma ferramenta em seu sistema interno. |
| `compass_categories()` | Listar categorias e servidores. |
| `compass_status()` | Saúde do sistema e configuração. |
| `compass_analytics(timeframe)` | Estatísticas de uso. |
| `compass_chains(action)` | Gerenciar fluxos de trabalho das ferramentas. |
| `compass_sync(force)` | Reconstruir o índice a partir das fontes de dados. |
| `compass_audit()` | Relatório completo do sistema. |

## Configuração

| Variável. | Descrição. | Padrão. |
| Please provide the English text you would like me to translate. I am ready to translate it into Portuguese. | "Please provide the text you would like me to translate." | Please provide the English text you would like me to translate. I am ready to translate it into Portuguese. |
| `TOOL_COMPASS_BASE_PATH` | Diretório raiz do projeto. | Detectado automaticamente. |
| `TOOL_COMPASS_PYTHON` | Executável do Python. | Detectado automaticamente. |
| `TOOL_COMPASS_CONFIG` | Caminho do arquivo de configuração. | `./compass_config.json` |
| `OLLAMA_URL` | URL do servidor Ollama. | `http://localhost:11434` |
| `COMFYUI_URL` | Servidor ComfyUI. | `http://localhost:8188` |

Consulte o arquivo [` .env.example`](.env.example) para ver todas as opções.

## Desempenho

| Métrica. | Value |
| Please provide the English text you would like me to translate. I am ready to translate it into Portuguese. | Please provide the English text you would like me to translate. I am ready to translate it into Portuguese. |
| Tempo de construção do índice. | Aproximadamente 5 segundos para 44 ferramentas. |
| Latência de consulta. | ~15 ms (incluindo o processo de incorporação). |
| Economia de tokens. | ~95% (38.000 → 2.000) |
| Precisão a 3. | ~95% (ferramenta correta entre as 3 melhores opções). |

## Testes

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## Resolução de problemas

### Servidor MCP não está conectando

Se os logs do Claude Desktop exibirem erros de análise JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa**: As instruções `print()` corrompem o protocolo JSON-RPC.

**Solução:** Utilize o registro de eventos (logging) ou `file=sys.stderr`.
```python
import sys
print("Debug message", file=sys.stderr)
```

### Falha na conexão com o Ollama

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

Parte da **suíte Compass**, para desenvolvimento impulsionado por inteligência artificial:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Busca semântica de arquivos.
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componentes Gradio com incorporação vetorial.
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajuste fino de modelos de linguagem grandes (LLMs) sem interface.
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sem a complexidade.

## Contribuindo

Aceitamos contribuições! Consulte o arquivo [CONTRIBUTING.md](CONTRIBUTING.md) para obter as diretrizes.

## Segurança

Para vulnerabilidades de segurança, consulte o arquivo [SECURITY.md](SECURITY.md). **Não abra problemas públicos para relatar falhas de segurança.**

## Suporte

- **Dúvidas / ajuda:** [Discussões](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
- **Relatórios de bugs:** [Problemas](https://github.com/mcp-tool-shop-org/tool-compass/issues)
- **Segurança:** [SECURITY.md](SECURITY.md)

## Licença

[MIT](LICENSE) - consulte o arquivo LICENSE para obter detalhes.

## Créditos

- **HNSW**: Malkov & Yashunin, "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs" (2016)
- **nomic-embed-text**: Modelo de incorporação de código aberto da Nomic AI
- **FastMCP**: Framework MCP da Anthropic
- **Gradio**: Framework web de aprendizado de máquina da Hugging Face

---

<div align="center">

*"Syntropy acima de tudo."*

O Tool Compass reduz a entropia no ecossistema MCP, organizando as ferramentas por significado semântico.

**[Documentação](https://github.com/mcp-tool-shop-org/tool-compass#readme)** • **[Problemas](https://github.com/mcp-tool-shop-org/tool-compass/issues)** • **[Discussões](https://github.com/mcp-tool-shop-org/tool-compass/discussions)**

</div>
