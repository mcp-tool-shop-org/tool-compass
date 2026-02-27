<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**Navegador semántico para herramientas MCP: Encuentra la herramienta adecuada según tu intención, no por memoria**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*95% menos de tokens. Encuentra herramientas describiendo lo que quieres hacer.*

[Instalación](#quick-start) • [Uso](#usage) • [Docker](#option-2-docker) • [Rendimiento](#performance) • [Contribuciones](#contributing)

</div

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

### Opción 1: Instalación local

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

### Opción 2: Docker

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

- **Búsqueda semántica** - Encuentra herramientas describiendo lo que quieres hacer
- **Revelación progresiva** - `compass()` → `describe()` → `execute()`
- **Caché activa** - Las herramientas de uso frecuente se cargan previamente
- **Detección de cadenas** - Descubre automáticamente los flujos de trabajo comunes de las herramientas
- **Analítica** - Realiza un seguimiento de los patrones de uso y el rendimiento de las herramientas
- **Multiplataforma** - Windows, macOS, Linux
- **Listo para Docker** - Despliegue con un solo comando

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
| `compass_sync(force)` | Reconstruye el índice a partir de los backends |
| `compass_audit()` | Informe completo del sistema |

## Configuración

| Variable | Descripción | Valor predeterminado |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Raíz del proyecto | Detectado automáticamente |
| `TOOL_COMPASS_PYTHON` | Ejecutable de Python | Detectado automáticamente |
| `TOOL_COMPASS_CONFIG` | Ruta del archivo de configuración | `./compass_config.json` |
| `OLLAMA_URL` | URL del servidor Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | Servidor ComfyUI | `http://localhost:8188` |

Consulta [`.env.example`](.env.example) para todas las opciones.

## Rendimiento

| Métrica | Valor |
|--------|-------|
| Tiempo de construcción del índice | ~5 segundos para 44 herramientas |
| Latencia de la consulta | ~15 ms (incluyendo la incrustación) |
| Ahorro de tokens | ~95% (38K → 2K) |
| Precisión@3 | ~95% (herramienta correcta en los 3 primeros) |

## Pruebas

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## Solución de problemas

### El servidor MCP no se conecta

Si los registros de Claude Desktop muestran errores de análisis JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa**: Las sentencias `print()` corrompen el protocolo JSON-RPC.

**Solución**: Utiliza el registro o `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Conexión a Ollama fallida

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
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajuste fino de LLM sin cabeza
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sin la complejidad

## Contribuciones

¡Aceptamos contribuciones! Consulta [CONTRIBUTING.md](CONTRIBUTING.md) para obtener pautas.

## Seguridad y alcance de los datos

Tool Compass es una herramienta de desarrollo **local-first**. Consulta [SECURITY.md](SECURITY.md) para obtener la política completa.

- **Datos que se utilizan:** descripciones de herramientas indexadas en una base de datos vectorial local HNSW, consultas de búsqueda registradas en una base de datos SQLite local (`compass_analytics.db`), incrustaciones generadas mediante Ollama local.
- **Datos que NO se utilizan:** no se utiliza ningún código del usuario, ni el contenido de ningún archivo, ni credenciales. Los argumentos de las llamadas a las herramientas se codifican, no se almacenan en texto plano.
- **Red:** se conecta a Ollama local para generar incrustaciones. Una interfaz de usuario Gradio opcional se vincula a localhost. No se recopila telemetría externa.
- **Sin telemetría:** no se recopila nada externamente. Los análisis son solo locales.

## Cuadro de evaluación

| Categoría | Puntuación | Notas |
|----------|-------|-------|
| A. Seguridad | 10/10 | `SECURITY.md`, solo local, sin telemetría, SQL parametrizado. |
| B. Manejo de errores | 10/10 | Resultados estructurados, alternativa elegante con Ollama. |
| C. Documentación para operadores | 10/10 | `README`, `CHANGELOG`, `CONTRIBUTING`, documentación de la API. |
| D. Higiene en el despliegue | 10/10 | CI (análisis de código + 413 pruebas + cobertura + `pip-audit` + Docker), script de verificación. |
| E. Identidad | 10/10 | Logotipo, traducciones, página de inicio. |
| **Total** | **50/50** | |

## Licencia

[MIT](LICENSE) - consulte el archivo `LICENSE` para obtener más detalles.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>
