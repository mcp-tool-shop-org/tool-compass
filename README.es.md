<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/lockup.png" alt="Tool Compass Logo" width="480"></p>

**Navegador semántico para herramientas de MCP: encuentre la herramienta adecuada por intención, no por memoria**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
<a href="https://pypi.org/project/tool-compass/"><img src="https://img.shields.io/pypi/v/tool-compass?style=flat-square" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/@mcptoolshop/tool-compass"><img src="https://img.shields.io/npm/v/@mcptoolshop/tool-compass?style=flat-square" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% menos de tokens. Encuentre herramientas describiendo lo que quiere hacer.*

[Instalación](#quick-start) • [Uso](#usage) • [Docker](#option-2-docker) • [Manual](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [Rendimiento](#performance) • [Contribución](#contributing)

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

Tool Compass utiliza la **búsqueda semántica** para encontrar herramientas relevantes a partir de una descripción en lenguaje natural. En lugar de cargar todas las herramientas, Claude llama a `compass()` con una intención y obtiene solo las herramientas relevantes.

## Comienzo rápido

📖 **Documentación completa:** Consulte el [Manual de Tool Compass](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) para obtener información detallada sobre la instalación, la configuración y la arquitectura.

### Opción 1: npm (sin requisitos previos, sin necesidad de instalar Python)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve                 # MCP gateway
npx @mcptoolshop/tool-compass ui                    # Gradio UI
npx @mcptoolshop/tool-compass doctor                # Diagnose setup
npx @mcptoolshop/tool-compass execute fs:read_file '{"path":"README.md"}'  # Smoke-test a proxied call
```

Descarga un binario de plataforma verificado en la primera ejecución (se verifica SHA256 con la versión de GitHub). Se almacena en caché localmente: las ejecuciones posteriores se inician instantáneamente. Consulte [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) en npm.

### Opción 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### Opción 3: Clonación local

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
> `linux/amd64` y `linux/arm64`, por lo que la misma etiqueta funciona en servidores x86_64
> y estaciones de trabajo Apple Silicon / ARM.

## Características

- **Búsqueda híbrida:** semántica (HNSW) + fusión léxica con refuerzo de nombre exacto: describa lo que quiere o pegue el nombre de una herramienta y esta se clasificará como la número 1.
- **Divulgación progresiva del esquema completo:** `compass()` → `describe()` → `execute()`; `describe()` devuelve el `inputSchema` completo (campos obligatorios, descripciones, enumeraciones, valores predeterminados).
- **Backends stdio + HTTP:** servidores MCP de subprocesos locales y servidores remotos/SaaS a través de HTTP con transmisión, con autenticación opcional mediante token de portador.
- **Tiempos de espera y permisos/denegaciones por herramienta:** anule el tiempo de espera predeterminado por backend/herramienta; exponga un subconjunto seguro de un backend amplio.
- **Caché activa y detección de cadena:** las herramientas de uso frecuente se cargan previamente; los flujos de trabajo comunes de las herramientas se descubren automáticamente.
- **Análisis:** realice un seguimiento de los patrones de uso y el rendimiento de las herramientas (con retención/eliminación).
- **Compatibilidad multiplataforma y listo para Docker:** Windows, macOS, Linux; implementación con un solo comando.

## Arquitectura

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
| `compass(intent)` | Búsqueda híbrida semántica + léxica con refuerzo de nombre exacto |
| `describe(tool_name)` | Obtenga el `inputSchema` completo de una herramienta (obligatorios/enumeraciones/valores predeterminados) |
| `execute(tool_name, args)` | Ejecute una herramienta en su backend |
| `compass_categories()` | Enumere las categorías y los servidores |
| `compass_status(active)` | Estado del sistema y configuración; `active=True` ejecuta una prueba de actividad del backend en vivo. |
| `compass_analytics(timeframe)` | Estadísticas de uso |
| `compass_chains(action)` | Administre los flujos de trabajo de las herramientas |
| `compass_sync(force)` | Reconstruya el índice a partir de los backends |
| `compass_audit()` | Informe completo del sistema |

Las mismas acciones están disponibles desde la CLI, incluida `tool-compass execute <tool> '<json>'` para realizar una prueba de humo de una llamada proxy desde la terminal.

### Patrón de divulgación progresiva

Tool Compass utiliza un patrón de divulgación progresiva de tres pasos para minimizar el uso de tokens:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**Por qué esto es importante:**
- Cargar 77 herramientas por adelantado = ~38.500 tokens
- Divulgación progresiva = ~600 tokens por herramienta utilizada
- Ahorro: **95% o más para los flujos de trabajo típicos**

**Ejemplo de flujo de trabajo:**

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

El campo `hint` en los resultados de compass guía este flujo, sugiriendo cuándo usar `describe()`.

## Configuración

| Variable | Descripción | Valor predeterminado |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | Directorio raíz del proyecto | Se detecta automáticamente |
| `TOOL_COMPASS_PYTHON` | Ejecutable de Python | Se detecta automáticamente |
| `TOOL_COMPASS_CONFIG` | Ruta del archivo de configuración | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | Directorio de datos | Específico de la plataforma (consulte a continuación) |
| `OLLAMA_URL` | URL del servidor Ollama | `http://localhost:11434` |
| `COMFYUI_URL` | Servidor ComfyUI | `http://localhost:8188` |
| `PORT` | Establezca para habilitar el transporte HTTP (por ejemplo, para Fly.io) | desactivado (stdio) |
| `TOOL_COMPASS_GATEWAY_AUTH_TOKEN` | Token de portador requerido en el transporte HTTP (opcional; anula el campo de configuración `gateway_auth_token`) | desactivado (sin autenticación) |

**Directorios de datos predeterminados:**
- **Windows:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **Linux:** `~/.config/tool-compass/` (o `$XDG_CONFIG_HOME/tool-compass/`)

La configuración del archivo (en `compass_config.json`) se agregó en la versión 2.5.0: `hybrid_search`,
`exact_name_boost`, `default_timeout` / `tool_timeouts` por backend,
`allow_tools` / `deny_tools`, `analytics_retention_days` y backends HTTP (`type: "http"`)
—se documentan en el [Manual → Configuración](https://mcp-tool-shop-org.github.io/tool-compass/handbook/configuration/).
Consulte [`.env.example`](.env.example) para obtener opciones de variables de entorno.

## Rendimiento

| Métrica | Valor |
|--------|-------|
| Tiempo de compilación del índice | ~5 segundos para 44 herramientas |
| Latencia de la consulta | ~15 ms (incluida la incrustación) |
| Ahorro de tokens | ~95% (38K → 2K) |
| Precisión@3 | ~95% (herramienta correcta en los 3 primeros resultados) |

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

Si los registros de Claude Desktop muestran errores de análisis de JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa:** las declaraciones `print()` corrompen el protocolo JSON-RPC.

**Solución:** utilice el registro o `file=sys.stderr`:
```python
import sys
print("Debug message", file=sys.stderr)
```

### Error de conexión de Ollama

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### Índice no encontrado

```bash
tool-compass sync
```

## Proyectos relacionados

Parte de la **Suite Compass** para el desarrollo con tecnología de IA:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Búsqueda semántica de archivos
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componentes Gradio con incrustaciones vectoriales
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajuste fino de LLM sin interfaz gráfica
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sin la complejidad

## Contribuciones

¡Aceptamos contribuciones! Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para obtener las pautas.

## Seguridad y alcance de los datos

Tool Compass es una herramienta de desarrollo **local-first**. Consulte [SECURITY.md](SECURITY.md) para conocer la política completa.

- **Datos afectados:** descripciones de herramientas indexadas en la base de datos vectorial HNSW local, consultas de búsqueda registradas en SQLite local (`compass_analytics.db`), incrustaciones generadas a través de Ollama local.
- **Datos NO afectados:** ningún código de usuario, ningún contenido de archivo, ninguna credencial. Los argumentos de llamada de la herramienta se hashean, no se almacenan en texto sin formato.
- **Red:** se conecta a Ollama local para las incrustaciones. La interfaz de usuario Gradio opcional se vincula a localhost. No hay telemetría externa.
- **Sin telemetría:** no recopila nada externamente. Los análisis son solo locales.

## Informe

Las puntuaciones por categoría se regeneran después de la ejecución mediante
`bash scripts/regenerate-scorecard.sh` (que envuelve `npx
@mcptoolshop/shipcheck audit`). Consulte [SCORECARD.md](SCORECARD.md) para obtener el
desglose actual y definitivo; la tabla a continuación lo refleja y no está escrita manualmente. Las secciones seleccionadas manualmente (Brechas conocidas,
Historial de correcciones) se encuentran fuera de los marcadores `<!-- SHIPCHECK-AUTO-START/END -->`
en SCORECARD.md y sobreviven a las regeneraciones.

Último `shipcheck audit`: **32 comprobados · 0 sin comprobar · 5 omitidos · 100% de aprobación: todas las barreras obligatorias superadas.**

| Categoría | Puntuación | Notas |
|----------|-------|-------|
| A. Seguridad | ✅ Aprobado | Acciones con hash SHA; imagen base con hash de resumen; procedencia SLSA + SBOM en PyPI + GHCR; análisis de secretos pre-commit; autenticación de puerta de enlace opcional |
| B. Manejo de errores | ✅ Aprobado | Resultados estructurados, degradación gradual, códigos de salida |
| C. Documentación del operador | ✅ Aprobado | README, CHANGELOG, LICENSE, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. Buenas prácticas de envío | ✅ Aprobado | CI consolidado; tiempo de espera en minutos + días de retención en cada trabajo; configuración de pytest en pyproject.toml |
| E. Identidad (suave) | ✅ Aprobado | Logotipo, página de destino, metadatos de GitHub; mantenedores explícitos en pyproject.toml |
| **Total** | **100%** | Todas las barreras obligatorias superadas: regenerar mediante `make scorecard` |

## Licencia

[MIT](LICENSE) - consulte el archivo LICENSE para obtener más detalles.

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

