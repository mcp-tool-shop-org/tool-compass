<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="800"></p>

**Strumento di ricerca semantica per gli strumenti MCP: individua lo strumento giusto in base all’obiettivo, non alla memoria.**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
<a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*Riduzione del 95% del numero di token. Trova gli strumenti giusti descrivendo ciò che vuoi realizzare.*

[Installazione](#guida-rapida) • [Utilizzo](#utilizzo) • [Docker](#option-2-docker) • [Manuale](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Prestazioni](#prestazioni) • [Come contribuire](#contributi)

</div>

---

## Il problema

I server MCP offrono decine o centinaia di strumenti. Caricare tutte le definizioni degli strumenti nel contesto comporta un inutile consumo di risorse e rallenta i tempi di risposta.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## La soluzione

Tool Compass utilizza la **ricerca semantica** per individuare gli strumenti pertinenti a partire da una descrizione in linguaggio naturale. Invece di caricare tutti gli strumenti, Claude chiama `compass()` specificando l’intento e riceve in risposta solo gli strumenti rilevanti.

## Guida rapida

📖 **Documentazione completa:** per informazioni dettagliate sull’installazione, la configurazione e l’architettura, consultare il [Tool Compass Handbook](https://mcp-tool-shop-org.github.io/tool-compass/handbook/).

### Opzione 1: npm (nessun prerequisito, non è necessario installare Python)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve                 # MCP gateway
npx @mcptoolshop/tool-compass ui                    # Gradio UI
npx @mcptoolshop/tool-compass doctor                # Diagnose setup
npx @mcptoolshop/tool-compass execute fs:read_file '{"path":"README.md"}'  # Smoke-test a proxied call
```

Scarica un eseguibile della piattaforma verificato alla prima esecuzione (verificato rispetto alla versione GitHub tramite SHA256). Viene memorizzato nella cache localmente, quindi le esecuzioni successive vengono avviate istantaneamente. Per maggiori informazioni, consulta [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) su npm.

### Opzione 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### Opzione 3: copia locale

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

# Start with Docker Compose (requires Ollama running locally and a UI login)
GRADIO_AUTH=user:pass docker compose up

# Or include Ollama in the stack
GRADIO_AUTH=user:pass docker compose --profile with-ollama up

# Access the UI at http://localhost:7860
```

Oppure, esegui direttamente l’immagine dell’interfaccia utente pubblicata, senza effettuare la clonazione:

```bash
docker run --rm -p 7860:7860 \
  -e GRADIO_AUTH=user:pass \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:ui
```

> **È necessario effettuare l’accesso tramite interfaccia utente all’interno dei container.** Poiché il container utilizza `0.0.0.0`,
> l’avvio viene interrotto se non viene effettuato l’accesso. È possibile avviarlo in uno dei due modi seguenti: impostare
> `GRADIO_AUTH=user:pass` (tramite `.env`, ambiente shell o `-e`), oppure impostare
> `TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1` quando si esegue il deployment dietro un proxy inverso che
> impone il proprio sistema di accesso (visualizza un avviso all’avvio e nasconde i controlli di esecuzione dell’interfaccia utente).

> **Monta il volume.** L’indice semantico si trova in `/app/tool_compass/db` e la sua creazione implica l’integrazione di ogni strumento in ogni server configurato. Senza un volume, questo lavoro viene perso quando il container si chiude e deve essere ripetuto all’avvio successivo, il che si traduce in un messaggio del tipo “Tool Compass è lento” anziché in un semplice avviso di errore. L’immagine ti avverte se lo dimentichi. `docker compose up` monta già un volume con nome, quindi questo si applica solo a `docker run` senza configurazione aggiuntiva.

> L’immagine GHCR (`ghcr.io/mcp-tool-shop-org/tool-compass`) è compatibile con
> `linux/amd64` e `linux/arm64`, quindi la stessa versione può essere eseguita su x86_64 server
> e workstation Apple Silicon/ARM.

Per eseguire il container del gateway HTTP MCP (fase `mcp-gateway`, porta `8080`), è necessario fornire un token di autenticazione, poiché il container si associa a `HOST=0.0.0.0` e si rifiuta di avviarsi senza `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (o `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1` quando è posizionato dietro un proxy inverso che effettua l’autenticazione):

```bash
# Docker Compose (gateway profile)
TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> docker compose --profile gateway up

# Or published gateway image directly
docker run --rm -p 8080:8080 \
  -e TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:gateway
```

## Caratteristiche

- **Ricerca ibrida:** ricerca semantica (HNSW) + fusione lessicale con priorità per il nome esatto: descrivi ciò che desideri oppure incolla il nome di uno strumento e questo verrà posizionato al primo posto nei risultati.
- **Rivelazione progressiva dello schema completo:** `compass()` → `describe()` → `execute()`; `describe()` restituisce lo schema completo `inputSchema` (campi obbligatori, descrizioni, enumerazioni, valori predefiniti).
- **Backend stdio + HTTP:** server MCP locali in esecuzione come sottoprocessi *e* server remoti su SaaS, tramite HTTP con streaming, con autenticazione opzionale tramite token.
- **Timeout e autorizzazioni/restrizioni per strumento:** sovrascrivi il timeout predefinito per ciascun backend/strumento; esponi un sottoinsieme sicuro di un backend più ampio.
- **Cache dinamica e rilevamento delle catene:** gli strumenti più utilizzati vengono caricati in anticipo; i flussi di lavoro comuni vengono rilevati automaticamente.
- **Analisi:** monitora i modelli di utilizzo e le prestazioni degli strumenti (con conservazione/eliminazione dei dati).
- **Compatibilità multipiattaforma e pronto per Docker:** Windows, macOS, Linux; distribuzione con un solo comando.

## Architettura

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

Resi:
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
| `compass(intent)` | Ricerca ibrida, che combina elementi semantici e lessicali, con una funzione di potenziamento basata sul nome esatto. |
| `describe(tool_name)` | Ottieni la descrizione completa di `inputSchema` per uno strumento (valori obbligatori/enumerazioni/valori predefiniti). |
| `execute(tool_name, args)` | Esegui uno strumento sul suo sistema di gestione. |
| `compass_categories()` | Elenca le categorie e i server. |
| `compass_status(active)` | Stato e configurazione del sistema; `active=True` esegue un controllo in tempo reale per verificare il corretto funzionamento del backend. |
| `compass_analytics(timeframe)` | Statistiche sull’utilizzo |
| `compass_chains(action)` | Gestire i flussi di lavoro degli strumenti. |
| `compass_sync(force)` | Ricostruisci l’indice a partire dai database sottostanti. |
| `compass_audit()` | Rapporto completo del sistema. |

Le stesse operazioni sono disponibili tramite l’interfaccia a riga di comando (CLI), compreso il comando `tool-compass execute <tool> '<json>'`, che consente di eseguire un test preliminare di una chiamata effettuata tramite un proxy direttamente dalla finestra del terminale.

### Modello di divulgazione progressiva

Tool Compass utilizza un sistema di divulgazione progressiva in tre fasi per ridurre al minimo l’uso dei token:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**Perché è importante:**
- Caricare 77 strumenti all’avvio equivale a circa 38.500 token.
- Caricamento progressivo: circa 600 token per ogni strumento utilizzato.
- Risparmio: **oltre il 95% per i flussi di lavoro tipici**.

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

Il campo `hint` nei risultati di Compass guida questo flusso, indicando quando utilizzare `describe()`.

## Configurazione

| Variabile | Descrizione | Predefinito |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Directory principale del progetto | Rilevato automaticamente |
| `TOOL_COMPASS_PYTHON` | File eseguibile Python | Rilevato automaticamente |
| `TOOL_COMPASS_CONFIG` | Percorso del file di configurazione | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Directory dei dati | Specifico per ciascuna piattaforma (vedere di seguito). |
| `OLLAMA_URL` | URL del server Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | server ComfyUI | `http://localhost:8188` |
| `PORT` | Configurato per abilitare il protocollo di trasporto HTTP (ad esempio, per Fly.io). | annulla (stdio) |
| `HOST` | Indirizzo a cui associare il trasporto HTTP; i valori diversi da quelli di loopback richiedono `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (o `gateway_auth_token`) a meno che non sia impostato `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1`. | `127.0.0.1` |
| `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` | Token di autenticazione per il protocollo HTTP (sovrascrive `gateway_auth_token` in `compass_config.json`). Obbligatorio quando `HOST` non è in modalità loopback (`127.0.0.1`, `localhost`, `::1`); facoltativo in modalità loopback. | disattiva (impedisce l’uscita dal ciclo di loopback) |
| `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN` | Impostare su `1` per consentire il collegamento del gateway HTTP al di fuori del loopback senza un token di autenticazione quando è presente un proxy inverso di autenticazione davanti (viene registrato un avviso ad ogni avvio). | disattivato |
| `GRADIO_AUTH` | Accesso tramite interfaccia utente (`user:pass`); viene applicato ogni volta che l’interfaccia utente viene avviata, se l’impostazione è attiva, ed è obbligatorio in caso di loopback, in ambiente Docker o su `--share`. | disattiva (solo per il loopback) |
| `TOOL_COMPASS_UI_ALLOW_NO_LOGIN` | Impostare su `1` per consentire l'avvio dell'interfaccia utente in modalità loopback senza `GRADIO_AUTH` dietro un proxy di autenticazione (avvisa e nasconde i controlli di esecuzione). | annulla impostazione |

**Directory dati predefinite:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/` (o `$XDG_CONFIG_HOME/tool-compass/`)

Impostazioni del file di configurazione (in `compass_config.json`) aggiunte in v2.5.0: `hybrid_search`, `exact_name_boost`, per backend `default_timeout` / `tool_timeouts`, `allow_tools` / `deny_tools`, `analytics_retention_days` e HTTP (`type: "http"`). I backend sono documentati in [Handbook → Configuration](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/).
Consultare [`.env.example`](.env.example) per le opzioni delle variabili d'ambiente.

## Prestazioni

| Metrica | Valore |
|--------|-------|
| Tempo di creazione dell'indice | ~5 secondi per 44 strumenti |
| Latenza delle query | ~15 ms (inclusa l'incorporazione) |
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

### Il server MCP non si connette

Se i log di Claude Desktop mostrano errori di analisi JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa**: le istruzioni `print()` danneggiano il protocollo JSON-RPC.

**Soluzione**: utilizzare la registrazione o `file=sys.stderr`:
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
tool-compass sync
```

## Progetti correlati

Parte della **Compass Suite** per lo sviluppo basato sull'intelligenza artificiale:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Ricerca semantica di file
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componenti Gradio con incorporazioni vettoriali
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Fine-tuning di LLM senza interfaccia grafica
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI senza complessità

## Contributi

Accogliamo con favore i contributi! Consultare [CONTRIBUTING.md](CONTRIBUTING.md) per le linee guida.

## Sicurezza e ambito dei dati

Tool Compass è uno strumento di sviluppo **local-first**. Consultare [SECURITY.md](SECURITY.md) per la politica completa.

- **Dati elaborati:** descrizioni degli strumenti indicizzati nel database vettoriale HNSW locale, query di ricerca registrate nel SQLite locale (`compass_analytics.db`), incorporazioni generate tramite Ollama locale.
- **Dati NON elaborati:** nessun codice utente, nessun contenuto di file, nessuna credenziale. Gli argomenti delle chiamate agli strumenti vengono sottoposti a hashing, non memorizzati in testo semplice.
- **Rete:** si connette a Ollama locale per le incorporazioni. L'interfaccia utente Gradio opzionale si associa a localhost. Nessun telemetria esterna.
- **Nessuna telemetria:** non raccoglie nulla esternamente. L'analisi è solo locale.

## Valutazione

I punteggi per categoria vengono rigenerati dopo l'esecuzione tramite `bash scripts/regenerate-scorecard.sh` (che racchiude `npx @mcptoolshop/shipcheck audit`). Consultare [SCORECARD.md](SCORECARD.md) per la ripartizione più recente e autorevole: la tabella sottostante la rispecchia e non è intenzionalmente creata manualmente. Le sezioni curate manualmente (Lacune note, Cronologia delle correzioni) si trovano al di fuori dei marcatori `<!-- SHIPCHECK-AUTO-START/END -->` in SCORECARD.md e sopravvivono alle rigenerazioni.

Ultimo `shipcheck audit`: **32 verificati · 0 non verificati · 5 saltati · 100% superati: tutti i controlli rigorosi sono superati.**

| Categoria | Punteggio | Note |
|----------|-------|-------|
| A. Sicurezza | ✅ Superato | Azioni con hash SHA; immagine di base con hash digest; provenienza SLSA + SBOM su PyPI + GHCR; scansione dei segreti pre-commit; autenticazione bearer del gateway facoltativa |
| B. Gestione degli errori | ✅ Superato | Risultati strutturati, degradazione graduale, codici di uscita |
| C. Documentazione per l'operatore | ✅ Superato | README, CHANGELOG, LICENSE, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. Igiene della spedizione | ✅ Superato | CI consolidato; timeout-minutes + retention-days su ogni job; configurazione pytest in pyproject.toml |
| E. Identità (soft) | ✅ Superato | Logo, pagina di destinazione, metadati GitHub; manutentori espliciti in pyproject.toml |
| **Total** | **100%** | Tutti i controlli rigorosi sono superati: rigenerare tramite `make scorecard` |

## Licenza

[MIT](LICENSE) - consultare il file LICENSE per i dettagli.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

