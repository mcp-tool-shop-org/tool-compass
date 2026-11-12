<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="800"></p>

**Navigateur sémantique pour les outils MCP : trouvez l’outil approprié en fonction de l’intention, et non de la mémoire.**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
<a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95 % de tokens en moins. Trouvez des outils en décrivant ce que vous voulez faire.*

[Installation](#démarrage-rapide) • [Utilisation](#utilisation) • [Docker](#option-2-docker) • [Guide](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Performances](#performance) • [Contribution](#contribution)

</div

---

## Le problème

Les serveurs MCP exposent des dizaines, voire des centaines d’outils. Charger toutes les définitions d’outils dans le contexte gaspille des tokens et ralentit les réponses.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## La solution

Tool Compass utilise la **recherche sémantique** pour trouver les outils pertinents à partir d’une description en langage naturel. Au lieu de charger tous les outils, Claude appelle `compass()` avec une intention et renvoie uniquement les outils pertinents.

## Démarrage rapide

📖 **Documentation complète :** Consultez le [Guide de Tool Compass](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) pour l’installation, la configuration et une analyse approfondie de l’architecture.

### Option 1 : npm (aucune condition préalable, aucune installation de Python)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve                 # MCP gateway
npx @mcptoolshop/tool-compass ui                    # Gradio UI
npx @mcptoolshop/tool-compass doctor                # Diagnose setup
npx @mcptoolshop/tool-compass execute fs:read_file '{"path":"README.md"}'  # Smoke-test a proxied call
```

Télécharge un binaire de plateforme vérifié lors de la première exécution (SHA256 vérifié par rapport à la version GitHub). Mis en cache localement : les exécutions suivantes démarrent instantanément. Voir [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) sur npm.

### Option 2 : PyPI

```bash
pip install tool-compass
tool-compass --help
```

### Option 3 : Clone local

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

### Option 4 : Docker

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

Ou exécutez directement l’image d’interface utilisateur publiée, sans clonage :

```bash
docker run --rm -p 7860:7860 \
  -e GRADIO_AUTH=user:pass \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:ui
```

> **Connexion à l’interface utilisateur requise dans les conteneurs.** Étant donné que le conteneur lie `0.0.0.0`,
> le démarrage refuse de s’exécuter sans connexion. Démarrez-le de l’une des deux manières suivantes : définissez
> `GRADIO_AUTH=user:pass` (via `.env`, l’environnement shell ou `-e`), ou définissez
> `TOOL_COMPASS_UI_ALLOW_NO_LOGIN=1` lors du déploiement derrière un proxy inverse qui
> applique sa propre connexion (affiche un avertissement au démarrage et masque les contrôles d’exécution de l’interface utilisateur).

> **Montez le volume.** L’index sémantique se trouve dans `/app/tool_compass/db`, et
> sa création signifie l’intégration de chaque outil dans chaque serveur configuré. Sans volume, ce travail est perdu lorsque le conteneur se termine et est refait au
> prochain démarrage, ce qui donne l’impression que « Tool Compass est lent » plutôt que d’indiquer un paramètre manquant. L’image vous avertit si vous l’oubliez. `docker compose up` monte déjà un
> volume nommé, de sorte que cela ne s’applique qu’à `docker run`.

> L’image GHCR (`ghcr.io/mcp-tool-shop-org/tool-compass`) prend en charge
> `linux/amd64` et `linux/arm64`, de sorte que le même tag s’exécute sur les serveurs x86_64
> et les postes de travail Apple Silicon / ARM.

Pour exécuter le conteneur de la **passerelle HTTP MCP** (étape `mcp-gateway`, port `8080`), fournissez un jeton de porteur, car le conteneur lie `HOST=0.0.0.0` et refuse de démarrer sans `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (ou `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1` lorsqu’il est placé derrière un proxy inverse d’authentification) :

```bash
# Docker Compose (gateway profile)
TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> docker compose --profile gateway up

# Or published gateway image directly
docker run --rm -p 8080:8080 \
  -e TOOL_COMPASS_GATEWAY_AUTH_TOKEN=<your-token> \
  -v tool-compass-data:/app/tool_compass/db \
  ghcr.io/mcp-tool-shop-org/tool-compass:gateway
```

## Fonctionnalités

- **Recherche hybride** : sémantique (HNSW) + fusion lexicale avec un renforcement du nom exact : décrivez ce que vous voulez, ou collez le nom d’un outil, et il sera classé en première position.
- **Divulgation progressive du schéma complet** : `compass()` → `describe()` → `execute()` ; `describe()` renvoie le schéma `inputSchema` complet (champs obligatoires, descriptions, énumérations, valeurs par défaut)
- **Backends stdio + HTTP** : prend en charge les serveurs MCP locaux en tant que processus et les serveurs distants / SaaS via HTTP diffusible, avec une authentification facultative par jeton de porteur.
- **Délai d’attente et autorisation/refus par outil** : remplacez le délai d’attente par défaut pour chaque backend/outil ; exposez un sous-ensemble sûr d’un backend étendu.
- **Cache dynamique et détection de chaîne** : les outils fréquemment utilisés sont préchargés ; les flux de travail courants sont découverts automatiquement.
- **Analyse** : suivez les modèles d’utilisation et les performances des outils (avec conservation/suppression).
- **Multiplateforme et prêt pour Docker** : Windows, macOS, Linux ; déploiement en une seule commande.

## Architecture

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

## Utilisation

### L’outil `compass()`

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Renvoie :
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
| `compass(intent)` | Recherche sémantique + lexicale hybride avec renforcement du nom exact |
| `describe(tool_name)` | Obtenez le schéma `inputSchema` complet d’un outil (champs obligatoires/énumérations/valeurs par défaut) |
| `execute(tool_name, args)` | Exécutez un outil sur son backend |
| `compass_categories()` | Affichez les catégories et les serveurs |
| `compass_status(active)` | État du système et configuration ; `active=True` exécute une sonde de réactivité du backend en direct |
| `compass_analytics(timeframe)` | Statistiques d’utilisation |
| `compass_chains(action)` | Gérez les flux de travail des outils |
| `compass_sync(force)` | Reconstruisez l’index à partir des backends |
| `compass_audit()` | Rapport système complet |

Les mêmes actions sont disponibles à partir de l’interface de ligne de commande, y compris `tool-compass execute <tool> '<json>'` pour tester un appel proxyé à partir du terminal.

### Modèle de divulgation progressive

Tool Compass utilise un modèle de divulgation progressive en trois étapes pour minimiser l’utilisation des tokens :

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**Pourquoi cela est important :**
- Charger 77 outils au départ = environ 38 500 tokens
- Divulgation progressive = environ 600 tokens par outil utilisé
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

Le champ `hint` dans les résultats de compass guide ce flux, en suggérant quand utiliser `describe()`.

## Configuration

| Variable | Description | Valeur par défaut |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Répertoire du projet | Détecté automatiquement |
| `TOOL_COMPASS_PYTHON` | Exécutable Python | Détecté automatiquement |
| `TOOL_COMPASS_CONFIG` | Chemin du fichier de configuration | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Répertoire des données | Spécifique à la plateforme (voir ci-dessous) |
| `OLLAMA_URL` | URL du serveur Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI serveur | `http://localhost:8188` |
| `PORT` | Définissez pour activer le transport HTTP (par exemple, pour Fly.io) | non défini (stdio) |
| `HOST` | Adresse de liaison pour le transport HTTP ; les valeurs non en boucle nécessitent `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` (ou `gateway_auth_token`) à moins que `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN=1` ne soit défini | `127.0.0.1` |
| `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` | Jeton de porteur pour le transport HTTP (remplace `gateway_auth_token` dans `compass_config.json`). Requis lorsque `HOST` n’est pas en boucle (`127.0.0.1`, `localhost`, `::1`) ; facultatif en boucle | non défini (refusé en boucle) |
| `TOOL_COMPASS_GATEWAY_ALLOW_NO_TOKEN` | Définissez sur `1` pour autoriser la liaison de la passerelle HTTP en dehors de la boucle sans jeton de porteur lorsqu’un proxy inverse d’authentification est placé en amont (affiche un avertissement à chaque démarrage) | non défini (désactivé) |
| `GRADIO_AUTH` | Connexion à l’interface utilisateur (`user:pass`) ; appliquée à chaque démarrage de l’interface utilisateur lorsqu’elle est définie, et requise en dehors de la boucle / dans Docker / sur `--share`. | non défini (uniquement en boucle) |
| `TOOL_COMPASS_UI_ALLOW_NO_LOGIN` | Définir sur `1` pour permettre le démarrage de l’interface utilisateur en dehors de la boucle locale sans `GRADIO_AUTH` derrière un proxy d’authentification (avertit et masque les commandes d’exécution). | annuler |

**Répertoires de données par défaut :**
- **Windows :** `%LOCALAPPDATA%\tool-compass\`
- **macOS :** `~/Library/Application Support/tool-compass/`
- **Linux :** `~/.config/tool-compass/` (ou `$XDG_CONFIG_HOME/tool-compass/`)

Paramètres du fichier de configuration (dans `compass_config.json`) ajoutés dans v2.5.0 : `hybrid_search`, `exact_name_boost`, par backend `default_timeout` / `tool_timeouts`, `allow_tools` / `deny_tools`, `analytics_retention_days` et HTTP (`type: "http"`). Les backends sont documentés dans [Manuel → Configuration](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/). Voir [`.env.example`](.env.example) pour les options de variables d’environnement.

## Performance

| Indicateur | Valeur |
|--------|-------|
| Temps de construction de l’index | ~5 s pour 44 outils |
| Latence des requêtes | ~15 ms (y compris l’intégration) |
| Économie de jetons | ~95 % (38 K → 2 K) |
| Précision@3 | ~95 % (outil correct dans les 3 premiers) |

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

Si les journaux de Claude Desktop affichent des erreurs d’analyse JSON :
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Cause :** Les instructions `print()` corrompent le protocole JSON-RPC.

**Solution :** Utilisez la journalisation ou `file=sys.stderr` :
```python
import sys
print("Debug message", file=sys.stderr)
```

### Échec de la connexion Ollama

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Index introuvable

```bash
tool-compass sync
```

## Projets connexes

Fait partie de la **suite Compass** pour le développement basé sur l’IA :

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Recherche sémantique de fichiers
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Composants Gradio intégrés sous forme de vecteurs
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajustement fin d’un LLM sans interface graphique
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sans la complexité

## Contribution

Nous acceptons les contributions ! Consultez [CONTRIBUTING.md](CONTRIBUTING.md) pour connaître les directives.

## Sécurité et portée des données

Tool Compass est un outil de développement **local-first**. Consultez [SECURITY.md](SECURITY.md) pour connaître la politique complète.

- **Données concernées :** descriptions des outils indexées dans la base de données vectorielle HNSW locale, requêtes de recherche enregistrées dans le fichier journal local SQLite (`compass_analytics.db`), intégrations générées via Ollama local.
- **Données non concernées :** aucun code utilisateur, aucun contenu de fichier, aucun identifiant. Les arguments des appels d’outils sont hachés, et non stockés en texte clair.
- **Réseau :** se connecte à Ollama local pour les intégrations. L’interface utilisateur Gradio facultative se lie à localhost. Aucune télémétrie externe.
- **Aucune télémétrie :** ne collecte rien en externe. Les analyses sont uniquement locales.

## Tableau de bord

Les scores par catégorie sont régénérés après l’exécution du « swarm » via `bash scripts/regenerate-scorecard.sh` (qui encapsule `npx @mcptoolshop/shipcheck audit`). Consultez [SCORECARD.md](SCORECARD.md) pour obtenir la liste détaillée la plus récente. Le tableau ci-dessous est un reflet de celle-ci et n’est pas créé manuellement. Les sections créées manuellement (Lacunes connues, Historique des corrections) se trouvent en dehors des marqueurs `<!-- SHIPCHECK-AUTO-START/END -->` dans SCORECARD.md et survivent aux régénérations.

Dernier `shipcheck audit` : **32 vérifiés · 0 non vérifiés · 5 ignorés · 100 % de réussite — tous les seuils obligatoires sont respectés.**

| Catégorie | Score | Notes |
|----------|-------|-------|
| A. Sécurité | ✅ Réussi | Actions avec empreinte SHA ; image de base avec empreinte de hachage ; provenance SLSA + SBOM sur PyPI + GHCR ; analyse des secrets pré-commit ; authentification de passerelle facultative. |
| B. Gestion des erreurs | ✅ Réussi | Résultats structurés, dégradation progressive, codes de sortie |
| C. Documentation pour les opérateurs | ✅ Réussi | README, CHANGELOG, LICENSE, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. Hygiène de l’expédition | ✅ Réussi | CI consolidé ; timeout-minutes + retention-days sur chaque tâche ; configuration pytest dans pyproject.toml |
| E. Identité (souple) | ✅ Réussi | Logo, page d’accueil, métadonnées GitHub ; mainteneurs explicites dans pyproject.toml |
| **Total** | **100%** | Tous les seuils obligatoires sont respectés — régénérez via `make scorecard` |

## Licence

[MIT](LICENSE) — consultez le fichier LICENSE pour plus de détails.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

