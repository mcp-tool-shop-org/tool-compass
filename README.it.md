<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**Navigatore semantico per strumenti MCP: Trova lo strumento giusto in base all'intento, non alla memoria**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% in meno di token. Trova gli strumenti descrivendo cosa vuoi fare.*

[Installazione](#quick-start) • [Utilizzo](#usage) • [Docker](#option-2-docker) • [Manuale](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Prestazioni](#performance) • [Contributi](#contributing)

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

📖 **Documentazione completa:** Consultare il [Manuale di Tool Compass](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) per l'installazione, la configurazione e un'analisi approfondita dell'architettura.

### Opzione 1: npm (nessun prerequisito, non è necessaria l'installazione di Python)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve     # MCP gateway
npx @mcptoolshop/tool-compass ui        # Gradio UI
npx @mcptoolshop/tool-compass doctor    # Diagnose setup
```

Scarica un binario della piattaforma verificato al primo avvio (controllo SHA256 rispetto alla versione di GitHub). Memorizzato localmente: le successive invocazioni si avviano istantaneamente. Consultare [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) su npm.

### Opzione 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### Opzione 3: Clonazione locale

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

### Opzione 4: Docker

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

L'immagine GHCR (`ghcr.io/mcp-tool-shop-org/tool-compass`) supporta
`linux/amd64` e `linux/arm64`, quindi la stessa versione funziona su server x86_64
e workstation Apple Silicon / ARM.

## Funzionalità

- **Ricerca semantica** - Trova gli strumenti descrivendo cosa vuoi fare
- **Divulgazione progressiva** - `compass()` → `describe()` → `execute()`
- **Cache rapida** - Gli strumenti utilizzati frequentemente vengono precaricati
- **Rilevamento delle catene** - Scopre automaticamente i flussi di lavoro comuni degli strumenti
- **Analisi** - Traccia i modelli di utilizzo e le prestazioni degli strumenti
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

| Strumento | Descrizione |
|------|-------------|
| `compass(intent)` | Ricerca semantica per gli strumenti |
| `describe(tool_name)` | Ottieni lo schema completo di uno strumento |
| `execute(tool_name, args)` | Esegui uno strumento sul suo backend |
| `compass_categories()` | Elenca categorie e server |
| `compass_status()` | Stato e configurazione del sistema |
| `compass_analytics(timeframe)` | Statistiche di utilizzo |
| `compass_chains(action)` | Gestisci i flussi di lavoro degli strumenti |
| `compass_sync(force)` | Ricostruisci l'indice dai backend |
| `compass_audit()` | Rapporto completo del sistema |

### Modello di divulgazione progressiva

Tool Compass utilizza un modello di divulgazione progressiva in tre fasi per ridurre al minimo l'utilizzo dei token:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**Perché questo è importante:**
- Caricare 77 strumenti in anticipo = ~38.500 token
- Divulgazione progressiva = ~600 token per strumento utilizzato
- Risparmi: **95%+ per i flussi di lavoro tipici**

**Esempio di flusso di lavoro:**

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

Il campo `hint` nei risultati di `compass` guida questo flusso, suggerendo quando utilizzare `describe()`.

## Configurazione

| Variabile | Descrizione | Valore predefinito |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Directory del progetto | Rilevato automaticamente |
| `TOOL_COMPASS_PYTHON` | Esecutibile Python | Rilevato automaticamente |
| `TOOL_COMPASS_CONFIG` | Percorso del file di configurazione | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Directory dei dati | Specifico per la piattaforma (vedere di seguito) |
| `OLLAMA_URL` | URL del server Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | Server ComfyUI | `http://localhost:8188` |
| `PORT` | Imposta per abilitare il trasporto HTTP (ad esempio, per Fly.io) | non impostato (stdio) |

**Directory predefiniti per i dati:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/` (o `$XDG_CONFIG_HOME/tool-compass/`)

Consultare il file [`.env.example`](.env.example) per tutte le opzioni.

## Prestazioni

| Metrica | Valore |
|--------|-------|
| Tempo di creazione dell'indice | ~5 secondi per 44 strumenti |
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

### Server MCP non connesso

Se i log di Claude Desktop mostrano errori di analisi JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa:** le istruzioni `print()` corrompono il protocollo JSON-RPC.

**Soluzione:** utilizzare il logging o `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Connessione Ollama fallita

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
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Fine-tuning di LLM senza interfaccia
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI senza la complessità

## Contributi

Accettiamo contributi! Consultare [CONTRIBUTING.md](CONTRIBUTING.md) per le linee guida.

## Sicurezza e ambito dei dati

Tool Compass è uno strumento di sviluppo **locale**. Consultare [SECURITY.md](SECURITY.md) per la politica completa.

- **Dati utilizzati:** descrizioni degli strumenti indicizzate in un database vettoriale HNSW locale, query di ricerca registrate in un database SQLite locale (`compass_analytics.db`), embedding generati tramite Ollama locale.
- **Dati NON utilizzati:** nessun codice utente, nessun contenuto di file, nessuna credenziale. Gli argomenti delle chiamate agli strumenti sono hashati e non memorizzati in testo semplice.
- **Rete:** si connette a Ollama locale per gli embedding. L'interfaccia utente Gradio opzionale si collega a localhost. Nessuna telemetria esterna.
- **Nessuna telemetria:** non raccoglie dati esternamente. L'analisi è locale.

## Scorecard

I punteggi per categoria vengono rigenerati dopo l'esecuzione tramite
`bash scripts/regenerate-scorecard.sh` (che esegue `npx
@mcptoolshop/shipcheck audit`). Consultare [SCORECARD.md](SCORECARD.md) per la
suddivisione dettagliata e aggiornata; la tabella sottostante la riflette ed è
intenzionalmente non scritta manualmente. Le sezioni curate manualmente (Gap Conosciuti,
Cronologia delle correzioni) si trovano al di fuori dei marcatori `<!-- SHIPCHECK-AUTO-START/END -->`
in SCORECARD.md e sopravvivono alle rigenerazioni.

| Categoria | Punteggio | Note |
|----------|-------|-------|
| A. Sicurezza | Da definire | Azioni con pinning SHA; immagine di base con pinning digest; provenienza SLSA + SBOM su PyPI + GHCR; scansione dei segreti pre-commit |
| B. Gestione degli errori | Da definire | Risultati strutturati, degradazione controllata, codici di uscita |
| C. Documentazione per l'operatore | Da definire | README, CHANGELOG, LICENZA, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. Igiene del processo di distribuzione | Da definire | CI consolidato; timeout-minuti + retention-days per ogni job; configurazione pytest in pyproject.toml |
| E. Identità (soft) | Da definire | Logo, pagina di destinazione, metadati di GitHub; manutentori espliciti in pyproject.toml |
| **Total** | **TBD** | Rigenerare tramite `make scorecard` |

## Licenza

[MIT](LICENSE) - consultare il file LICENSE per i dettagli.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

