<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**Navigateur sémantique pour les outils MCP : Trouvez le bon outil en fonction de votre intention, et non de votre mémoire.**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95 % de jetons en moins. Trouvez les outils en décrivant ce que vous voulez faire.*

[Installation](#quick-start) • [Utilisation](#usage) • [Docker](#option-2-docker) • [Manuel](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Performances](#performance) • [Contribution](#contributing)

</div

---

## Le problème

Les serveurs MCP exposent des dizaines, voire des centaines d'outils. Charger toutes les définitions d'outils dans le contexte gaspille des jetons et ralentit les réponses.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## La solution

Tool Compass utilise la **recherche sémantique** pour trouver les outils pertinents à partir d'une description en langage naturel. Au lieu de charger tous les outils, Claude appelle `compass()` avec une intention et reçoit uniquement les outils pertinents.

<!--
## Démonstration

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## Démarrage rapide

📖 **Documentation complète :** Consultez le [Manuel de Tool Compass](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) pour l'installation, la configuration et une analyse approfondie de l'architecture.

### Option 1 : Installation locale

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
python gateway.py --sync

# Run the MCP server
python gateway.py

# Or launch the Gradio UI
python ui.py
```

### Option 2 : Docker

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

> L'image GHCR (`ghcr.io/mcp-tool-shop-org/tool-compass`) prend en charge
> `linux/amd64` et `linux/arm64`, de sorte que la même version s'exécute sur les serveurs x86_64
> et les stations de travail Apple Silicon / ARM.

## Fonctionnalités

- **Recherche sémantique** : Trouvez les outils en décrivant ce que vous voulez faire.
- **Divulgation progressive** : `compass()` → `describe()` → `execute()`
- **Cache dynamique** : Les outils fréquemment utilisés sont préchargés.
- **Détection des chaînes** : Découvre automatiquement les flux de travail d'outils courants.
- **Analytique** : Suivez les modèles d'utilisation et les performances des outils.
- **Multiplateforme** : Windows, macOS, Linux
- **Prêt pour Docker** : Déploiement en une seule commande.

## Architecture

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

## Utilisation

### L'outil `compass()`

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Retourne :
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

### Outils disponibles

| Outil | Description |
|------|-------------|
| `compass(intent)` | Recherche sémantique pour les outils |
| `describe(tool_name)` | Obtient le schéma complet d'un outil |
| `execute(tool_name, args)` | Exécute un outil sur son backend |
| `compass_categories()` | Liste les catégories et les serveurs |
| `compass_status()` | État du système et configuration |
| `compass_analytics(timeframe)` | Statistiques d'utilisation |
| `compass_chains(action)` | Gère les flux de travail des outils |
| `compass_sync(force)` | Reconstruit l'index à partir des backends |
| `compass_audit()` | Rapport système complet |

### Modèle de divulgation progressive

Tool Compass utilise un modèle de divulgation progressive en trois étapes pour minimiser l'utilisation des jetons :

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**Pourquoi cela compte :**
- Charger 77 outils à l'avance = ~38 500 jetons
- Divulgation progressive = ~600 jetons par outil utilisé
- Économies : **95 % ou plus pour les flux de travail typiques**

**Exemple de flux de travail :**

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

Le champ `hint` dans les résultats de `compass` guide ce flux, en suggérant quand utiliser `describe()`.

## Configuration

| Variable | Description | Valeur par défaut |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Racine du projet | Détectée automatiquement |
| `TOOL_COMPASS_PYTHON` | Exécutable Python | Détectée automatiquement |
| `TOOL_COMPASS_CONFIG` | Chemin du fichier de configuration | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Répertoire de données | Spécifique à la plateforme (voir ci-dessous) |
| `OLLAMA_URL` | URL du serveur Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | Serveur ComfyUI | `http://localhost:8188` |
| `PORT` | Définir pour activer le transport HTTP (par exemple, pour Fly.io) | non défini (stdio) |

**Répertoires de données par défaut :**
- **Windows :** `%LOCALAPPDATA%\tool-compass\`
- **macOS :** `~/Library/Application Support/tool-compass/`
- **Linux :** `~/.config/tool-compass/` (ou `$XDG_CONFIG_HOME/tool-compass/`)

Consultez le fichier [`.env.example`](.env.example) pour toutes les options.

## Performances

| Métrique | Valeur |
|--------|-------|
| Temps de construction de l'index | ~5 secondes pour 44 outils |
| Latence de la requête | ~15 ms (incluant l'intégration) |
| Économies de tokens | ~95 % (38K → 2K) |
| Précision à 3 | ~95 % (outil correct parmi les 3 premiers) |

## Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## Dépannage

### Le serveur MCP ne se connecte pas

Si les journaux de Claude Desktop affichent des erreurs d'analyse JSON :
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Cause :** Les instructions `print()` corrompent le protocole JSON-RPC.

**Solution :** Utilisez la journalisation ou `file=sys.stderr`.
```python
import sys
print("Debug message", file=sys.stderr)
```

### Connexion Ollama échouée

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Index non trouvé

```bash
python gateway.py --sync
```

## Projets associés

Fait partie de la **suite Compass** pour le développement assisté par l'IA :

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Recherche sémantique de fichiers
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Composants Gradio intégrés vectoriellement
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajustement fin de LLM sans interface graphique
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sans la complexité

## Contributions

Nous accueillons les contributions ! Consultez [CONTRIBUTING.md](CONTRIBUTING.md) pour connaître les directives.

## Sécurité et portée des données

Tool Compass est un outil de développement **fonctionnant localement**. Consultez [SECURITY.md](SECURITY.md) pour connaître la politique complète.

- **Données traitées :** descriptions des outils indexées dans une base de vecteurs HNSW locale, requêtes de recherche enregistrées dans une base de données SQLite locale (`compass_analytics.db`), intégrations générées via Ollama local.
- **Données NON traitées :** aucun code utilisateur, aucun contenu de fichier, aucune identité. Les arguments d'appel des outils sont hachés et ne sont pas stockés en texte brut.
- **Réseau :** se connecte à Ollama local pour les intégrations. L'interface utilisateur Gradio facultative est liée à localhost. Aucune télémétrie externe.
- **Aucune télémétrie :** ne collecte rien à l'extérieur. Les analyses sont locales uniquement.

## Tableau de bord

| Catégorie | Score | Notes |
|----------|-------|-------|
| A. Sécurité | 10/10 | SECURITY.md, uniquement local, aucune télémétrie, SQL paramétré |
| B. Gestion des erreurs | 10/10 | Résultats structurés, repli élégant vers Ollama |
| C. Documentation pour les utilisateurs | 10/10 | README, CHANGELOG, CONTRIBUTING, documentation de l'API |
| D. Qualité du code | 10/10 | CI (lint + tests + couverture + pip-audit + Docker), script de vérification |
| E. Identité | 10/10 | Logo, traductions, page d'accueil |
| **Total** | **50/50** | |

## Licence

[MIT](LICENSE) - voir le fichier LICENSE pour plus de détails.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

