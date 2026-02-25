<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="assets/logo.png" alt="Tool Compass Logo" width="400"></p>

# Tool Compass

**Navigatore semantico per strumenti MCP: trova lo strumento giusto in base all'intento, non alla memoria.**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*95% in meno di token. Trova gli strumenti descrivendo cosa vuoi fare.*

[Installazione](#quick-start) • [Utilizzo](#usage) • [Docker](#option-2-docker) • [Prestazioni](#performance) • [Contributi](#contributing)

</div>

---

## Il problema

I server MCP espongono decine o centinaia di strumenti. Caricare tutte le definizioni degli strumenti nel contesto spreca token e rallenta le risposte.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## La soluzione

Tool Compass utilizza la **ricerca semantica** per trovare gli strumenti pertinenti a partire da una descrizione in linguaggio naturale. Invece di caricare tutti gli strumenti, Claude chiama `compass()` con un intento e riceve solo gli strumenti pertinenti.

<!--
## Demo

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## Guida rapida

### Opzione 1: Installazione locale

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

### Opzione 2: Docker

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

## Funzionalità

- **Ricerca semantica** - Trova gli strumenti descrivendo cosa vuoi fare
- **Divulgazione progressiva** - `compass()` → `describe()` → `execute()`
- **Cache dinamica** - Gli strumenti utilizzati frequentemente vengono precaricati
- **Rilevamento delle catene** - Scopre automaticamente i flussi di lavoro comuni degli strumenti
- **Analisi** - Monitora i modelli di utilizzo e le prestazioni degli strumenti
- **Compatibilità multipiattaforma** - Windows, macOS, Linux
- **Pronto per Docker** - Distribuzione con un solo comando

## Architettura

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

## Utilizzo

### Lo strumento `compass()`

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Restituisce:
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

### Strumenti disponibili

| Tool | Descrizione |
| ------ | ------------- |
| `compass(intent)` | Ricerca semantica per strumenti |
| `describe(tool_name)` | Ottieni lo schema completo di uno strumento |
| `execute(tool_name, args)` | Esegui uno strumento sul suo backend |
| `compass_categories()` | Elenca categorie e server |
| `compass_status()` | Stato e configurazione del sistema |
| `compass_analytics(timeframe)` | Statistiche di utilizzo |
| `compass_chains(action)` | Gestisci i flussi di lavoro degli strumenti |
| `compass_sync(force)` | Ricostruisci l'indice dai backend |
| `compass_audit()` | Rapporto completo del sistema |

## Configurazione

| Variabile | Descrizione | Valore predefinito |
| ---------- | ------------- | --------- |
| `TOOL_COMPASS_BASE_PATH` | Directory radice del progetto | Rilevata automaticamente |
| `TOOL_COMPASS_PYTHON` | Eseguibile Python | Rilevato automaticamente |
| `TOOL_COMPASS_CONFIG` | Percorso del file di configurazione | `./compass_config.json` |
| `OLLAMA_URL` | URL del server Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | Server ComfyUI | `http://localhost:8188` |

Consulta il file `[.env.example](.env.example)` per tutte le opzioni.

## Prestazioni

| Metrica | Value |
| -------- | ------- |
| Tempo di costruzione dell'indice | ~5 secondi per 44 strumenti |
| Latenza delle query | ~15 ms (inclusi gli embedding) |
| Risparmio di token | ~95% (38K → 2K) |
| Precisione@3 | ~95% (strumento corretto tra i primi 3) |

## Test

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## Risoluzione dei problemi

### Impossibile connettersi al server MCP

Se i log di Claude Desktop mostrano errori di analisi JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa**: le istruzioni `print()` corrompono il protocollo JSON-RPC.

**Soluzione**: utilizza il logging o `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Connessione a Ollama non riuscita

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Indice non trovato

```bash
python gateway.py --sync
```

## Progetti correlati

Parte della **Compass Suite** per lo sviluppo potenziato dall'intelligenza artificiale:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Ricerca semantica di file
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componenti Gradio con embedding vettoriale
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Fine-tuning headless di modelli linguistici
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI senza la complessità

## Contributi

Accettiamo contributi! Consultare il file [CONTRIBUTING.md](CONTRIBUTING.md) per le linee guida.

## Sicurezza

Per le vulnerabilità di sicurezza, consultare il file [SECURITY.md](SECURITY.md). **Non segnalare pubblicamente problemi di sicurezza.**

## Supporto

- **Domande / assistenza:** [Discussioni](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
- **Segnalazione di bug:** [Problemi](https://github.com/mcp-tool-shop-org/tool-compass/issues)
- **Sicurezza:** [SECURITY.md](SECURITY.md)

## Licenza

[MIT](LICENSE) - consultare il file LICENSE per i dettagli.

## Ringraziamenti

- **HNSW**: Malkov & Yashunin, "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs" (2016)
- **nomic-embed-text**: Modello di embedding open source di Nomic AI
- **FastMCP**: Framework MCP di Anthropic
- **Gradio**: Framework web per il machine learning di Hugging Face

---

<div align="center">

*"Sintropia al di sopra di tutto."*

Tool Compass riduce l'entropia nell'ecosistema MCP organizzando gli strumenti in base al significato semantico.

**[Documentazione](https://github.com/mcp-tool-shop-org/tool-compass#readme)** • **[Problemi](https://github.com/mcp-tool-shop-org/tool-compass/issues)** • **[Discussioni](https://github.com/mcp-tool-shop-org/tool-compass/discussions)**

</div>
