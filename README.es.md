<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**Navegador semántico para herramientas MCP: Encuentra la herramienta adecuada según la intención, no por memoria**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% menos de tokens. Encuentra herramientas describiendo lo que quieres hacer.*

[Instalación](#quick-start) • [Uso](#usage) • [Docker](#option-2-docker) • [Manual de usuario](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Rendimiento](#performance) • [Contribuciones](#contributing)

</div>

---

## El problema

Los servidores MCP exponen decenas o cientos de herramientas. Cargar todas las definiciones de herramientas en el contexto desperdicia tokens y ralentiza las respuestas.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## La solución

Tool Compass utiliza la **búsqueda semántica** para encontrar herramientas relevantes a partir de una descripción en lenguaje natural. En lugar de cargar todas las herramientas, Claude llama a `compass()` con una intención y recibe solo las herramientas relevantes.

<!--
## Demostración

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## Comienzo rápido

📖 **Documentación completa:** Consulta el [Manual de usuario de Tool Compass](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) para obtener información sobre la instalación, la configuración y la arquitectura.

### Opción 1: npm (sin requisitos previos, no requiere instalación de Python)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve     # MCP gateway
npx @mcptoolshop/tool-compass ui        # Gradio UI
npx @mcptoolshop/tool-compass doctor    # Diagnose setup
```

Descarga un binario de plataforma verificado en la primera ejecución (verificado con SHA256 contra el lanzamiento de GitHub). Se guarda en caché localmente; las invocaciones posteriores se ejecutan instantáneamente. Consulta [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) en npm.

### Opción 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### Opción 3: Clon local

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

### Opción 4: Docker

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

> La imagen de GHCR (`ghcr.io/mcp-tool-shop-org/tool-compass`) es compatible con
> `linux/amd64` y `linux/arm64`, por lo que la misma etiqueta se ejecuta en servidores x86_64
> y estaciones de trabajo Apple Silicon / ARM.

## Características

- **Búsqueda semántica:** Encuentra herramientas describiendo lo que quieres hacer.
- **Divulgación progresiva:** `compass()` → `describe()` → `execute()`
- **Caché rápido:** Las herramientas de uso frecuente se cargan previamente.
- **Detección de cadenas:** Descubre automáticamente los flujos de trabajo comunes de las herramientas.
- **Analítica:** Realiza un seguimiento de los patrones de uso y el rendimiento de las herramientas.
- **Multiplataforma:** Windows, macOS, Linux.
- **Listo para Docker:** Despliegue con un solo comando.

## Arquitectura

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

### La herramienta `compass()`

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

Devuelve:
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

### Herramientas disponibles

| Herramienta | Descripción |
|------|-------------|
| `compass(intent)` | Búsqueda semántica de herramientas |
| `describe(tool_name)` | Obtén el esquema completo de una herramienta |
| `execute(tool_name, args)` | Ejecuta una herramienta en su backend |
| `compass_categories()` | Lista categorías y servidores |
| `compass_status()` | Estado y configuración del sistema |
| `compass_analytics(timeframe)` | Estadísticas de uso |
| `compass_chains(action)` | Administra los flujos de trabajo de las herramientas |
| `compass_sync(force)` | Reconstruye el índice desde los backends |
| `compass_audit()` | Informe completo del sistema |

### Patrón de divulgación progresiva

Tool Compass utiliza un patrón de divulgación progresiva de tres pasos para minimizar el uso de tokens:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**¿Por qué esto es importante?**
- Cargar 77 herramientas por adelantado = ~38.500 tokens
- Divulgación progresiva = ~600 tokens por herramienta utilizada
- Ahorro: **95%+ para flujos de trabajo típicos**

**Flujo de trabajo de ejemplo:**

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

El campo `hint` en los resultados de `compass` guía este flujo, sugiriendo cuándo usar `describe()`.

## Configuración

| Variable | Descripción | Valor predeterminado |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Raíz del proyecto | Detectado automáticamente |
| `TOOL_COMPASS_PYTHON` | Ejecutable de Python | Detectado automáticamente |
| `TOOL_COMPASS_CONFIG` | Ruta del archivo de configuración | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Directorio de datos | Específico de la plataforma (ver más abajo) |
| `OLLAMA_URL` | URL del servidor Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | Servidor ComfyUI | `http://localhost:8188` |
| `PORT` | Establece para habilitar el transporte HTTP (por ejemplo, para Fly.io) | no definido (stdio) |

**Directorios de datos predeterminados:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/` (o `$XDG_CONFIG_HOME/tool-compass/`)

Consulte el archivo [`.env.example`](.env.example) para todas las opciones.

## Rendimiento

| Métrica | Valor |
|--------|-------|
| Tiempo de construcción del índice | ~5 segundos para 44 herramientas |
| Latencia de la consulta | ~15 ms (incluyendo la incrustación) |
| Ahorro de tokens | ~95% (38K → 2K) |
| Precisión@3 | ~95% (herramienta correcta en las 3 primeras posiciones) |

## Pruebas

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## Resolución de problemas

### El servidor MCP no se conecta

Si los registros de Claude Desktop muestran errores de análisis JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa:** Las declaraciones `print()` corrompen el protocolo JSON-RPC.

**Solución:** Utilice el registro o `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Conexión de Ollama fallida

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Índice no encontrado

```bash
python gateway.py --sync
```

## Proyectos relacionados

Parte de la **Suite Compass** para el desarrollo impulsado por IA:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Búsqueda semántica de archivos
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componentes de Gradio con incrustaciones vectoriales
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajuste fino de LLM sin interfaz
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sin la complejidad

## Contribuciones

¡Aceptamos contribuciones! Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para obtener las pautas.

## Seguridad y alcance de los datos

Tool Compass es una herramienta de desarrollo que funciona **principalmente en local**. Consulte [SECURITY.md](SECURITY.md) para obtener la política completa.

- **Datos accedidos:** Descripciones de herramientas indexadas en una base de datos vectorial HNSW local, consultas de búsqueda registradas en una base de datos SQLite local (`compass_analytics.db`), incrustaciones generadas mediante Ollama local.
- **Datos NO accedidos:** ningún código de usuario, ningún contenido de archivo, ninguna credencial. Los argumentos de la llamada a la herramienta se codifican hash, no se almacenan en texto plano.
- **Red:** se conecta a Ollama local para las incrustaciones. La interfaz de usuario Gradio opcional se vincula a localhost. No hay telemetría externa.
- **Sin telemetría:** no recopila nada externamente. Los análisis son solo locales.

## Cuadro de puntuación

Las puntuaciones por categoría se regeneran después del proceso de evaluación a través de
`bash scripts/regenerate-scorecard.sh` (que envuelve `npx
@mcptoolshop/shipcheck audit`). Consulte [SCORECARD.md](SCORECARD.md) para obtener el desglose autorizado actual; la tabla a continuación lo refleja y está intencionalmente no escrita a mano. Las secciones curadas manualmente (Brechas conocidas, Historial de corrección) se encuentran fuera de los marcadores `<!-- SHIPCHECK-AUTO-START/END -->` en SCORECARD.md y sobreviven a las regeneraciones.

| Categoría | Puntuación | Notas |
|----------|-------|-------|
| A. Seguridad | Por determinar | Acciones con pines SHA; imagen base con pines de resumen; procedencia SLSA + SBOM en PyPI + GHCR; análisis de secretos pre-commit |
| B. Manejo de errores | Por determinar | Resultados estructurados, degradación gradual, códigos de salida |
| C. Documentación para el operador | Por determinar | README, CHANGELOG, LICENSE, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. Higiene de la implementación | Por determinar | CI consolidado; tiempo de espera máximo + días de retención en cada trabajo; configuración de pytest en pyproject.toml |
| E. Identidad (suave) | Por determinar | Logotipo, página de inicio, metadatos de GitHub; mantenedores explícitos en pyproject.toml |
| **Total** | **TBD** | Regenerar con `make scorecard` |

## Licencia

[MIT](LICENSE) - consulte el archivo LICENSE para obtener más detalles.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

