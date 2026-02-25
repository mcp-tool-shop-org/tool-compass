<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="assets/logo.png" alt="Tool Compass Logo" width="400"></p>

# Brújula de precisión

**Navegador semántico para herramientas MCP: Encuentre la herramienta adecuada según su necesidad, no por memoria.**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*95% menos de elementos. Encuentre herramientas describiendo lo que desea hacer.*

[Instalación](#quick-start) • [Uso](#usage) • [Docker](#option-2-docker) • [Rendimiento](#performance) • [Contribuciones](#contributing)

</div>

---

## El problema

Los servidores de MCP exponen decenas o incluso cientos de herramientas. Cargar todas las definiciones de herramientas en el contexto consume tokens y ralentiza las respuestas.

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## La solución

La herramienta Compass utiliza la **búsqueda semántica** para encontrar herramientas relevantes a partir de una descripción en lenguaje natural. En lugar de cargar todas las herramientas, Claude llama a la función `compass()` con una intención específica y solo recibe las herramientas relevantes.

```text
The company is committed to providing high-quality products and services.
We are constantly working to improve our processes and meet the needs of our customers.
Our team is made up of highly qualified professionals.
We value innovation and creativity.
We are committed to sustainability and environmental protection.
```
## Demostración

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## Inicio rápido

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

- **Búsqueda semántica:** Encuentre herramientas describiendo lo que desea hacer.
- **Revelación progresiva:** `compass()` → `describe()` → `execute()`
- **Caché dinámica:** Las herramientas de uso frecuente se cargan previamente.
- **Detección de cadenas:** Descubre automáticamente los flujos de trabajo comunes de las herramientas.
- **Analítica:** Realice un seguimiento de los patrones de uso y el rendimiento de las herramientas.
- **Compatibilidad multiplataforma:** Windows, macOS, Linux.
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

Devoluciones:
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

| Tool | Descripción. |
| Translate the following English text into Spanish:
"The company is committed to providing high-quality products and services. We strive to meet and exceed customer expectations. Our team is dedicated to innovation and continuous improvement. We value integrity, transparency, and respect in all our interactions."
"La empresa está comprometida con la provisión de productos y servicios de alta calidad. Nos esforzamos por satisfacer y superar las expectativas de nuestros clientes. Nuestro equipo está dedicado a la innovación y la mejora continua. Valoramos la integridad, la transparencia y el respeto en todas nuestras interacciones." | Please provide the English text you would like me to translate. I am ready to translate it into Spanish. |
| `compass(intent)` | Búsqueda semántica de herramientas. |
| `describe(tool_name)` | Obtener el esquema completo de una herramienta. |
| `execute(tool_name, args)` | Ejecute una herramienta en su parte posterior. |
| `compass_categories()` | Enumere las categorías y los servidores. |
| `compass_status()` | Estado y configuración del sistema. |
| `compass_analytics(timeframe)` | Estadísticas de uso. |
| `compass_chains(action)` | Gestionar los flujos de trabajo de las herramientas. |
| `compass_sync(force)` | Reconstruir el índice a partir de las fuentes de datos. |
| `compass_audit()` | Informe completo del sistema. |

## Configuración

| Variable. | Descripción. | Predeterminado. |
| Please provide the English text you would like me to translate. I am ready to translate it into Spanish. | Please provide the English text you would like me to translate. I am ready to translate it into Spanish. | Please provide the English text you would like me to translate. I am ready to translate it into Spanish. |
| `TOOL_COMPASS_BASE_PATH` | Directorio raíz del proyecto. | Detectado automáticamente. |
| `TOOL_COMPASS_PYTHON` | Ejecutable de Python. | Detectado automáticamente. |
| `TOOL_COMPASS_CONFIG` | Ruta del archivo de configuración. | `./compass_config.json` |
| `OLLAMA_URL` | URL del servidor Ollama. | `http://localhost:11434` |
| `COMFYUI_URL` | Servidor de ComfyUI. | `http://localhost:8188` |

Consulte el archivo [` .env.example`](.env.example) para ver todas las opciones disponibles.

## Rendimiento

| Métrica. | Value |
| "The company is committed to providing high-quality products and services."

"We are looking for a motivated and experienced candidate."

"The meeting will be held on Tuesday at 10:00 AM."

"Please submit your application by the end of the week."

"We offer a competitive salary and benefits package."
--------

"La empresa está comprometida a ofrecer productos y servicios de alta calidad."

"Estamos buscando un candidato motivado y con experiencia."

"La reunión se llevará a cabo el martes a las 10:00 AM."

"Por favor, envíe su solicitud antes de que finalice la semana."

"Ofrecemos un salario competitivo y un paquete de beneficios." | Please provide the English text you would like me to translate. I am ready to translate it into Spanish. |
| Tiempo de creación del índice. | Aproximadamente 5 segundos para 44 herramientas. |
| Latencia de las consultas. | Aproximadamente 15 ms (incluyendo el proceso de incrustación). |
| Ahorro en tokens. | Aproximadamente el 95% (de 38.000 a 2.000). |
| Precisión a 3. | Aproximadamente el 95% (la herramienta correcta está entre las 3 mejores). |

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

### El servidor MCP no se está conectando

Si los registros de Claude Desktop muestran errores de análisis JSON:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**Causa**: Las sentencias `print()` corrompen el protocolo JSON-RPC.

**Solución:** Utilice el registro de eventos o la opción `file=sys.stderr`.
```python
import sys
print("Debug message", file=sys.stderr)
```

### Error de conexión con Ollama

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

Parte de la **suite Compass**, diseñada para el desarrollo impulsado por inteligencia artificial:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - Búsqueda semántica de archivos.
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - Componentes de Gradio con incrustaciones vectoriales.
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - Ajuste fino de modelos de lenguaje grandes (LLM) sin interfaz gráfica.
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI sin la complejidad asociada.

## Contribuyendo

¡Aceptamos contribuciones! Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para obtener las pautas.

## Seguridad

Para las vulnerabilidades de seguridad, consulte [SECURITY.md](SECURITY.md). **No abra problemas públicos para los errores de seguridad.**

## Soporte

- **Preguntas / ayuda:** [Discusiones](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
- **Informes de errores:** [Problemas](https://github.com/mcp-tool-shop-org/tool-compass/issues)
- **Seguridad:** [SECURITY.md](SECURITY.md)

## Licencia

[MIT](LICENSE) - consulte el archivo LICENSE para obtener más detalles.

## Créditos

- **HNSW**: Malkov & Yashunin, "Búsqueda eficiente y robusta de vecinos más cercanos aproximados utilizando gráficos de Pequeño Mundo Jerárquicos" (2016)
- **nomic-embed-text**: Modelo de incrustación de código abierto de Nomic AI
- **FastMCP**: Marco MCP de Anthropic
- **Gradio**: Marco web de aprendizaje automático de Hugging Face

---

<div align="center">

*"La sintropía por encima de todo."*

Tool Compass reduce la entropía en el ecosistema MCP al organizar las herramientas por significado semántico.

**[Documentación](https://github.com/mcp-tool-shop-org/tool-compass#readme)** • **[Problemas](https://github.com/mcp-tool-shop-org/tool-compass/issues)** • **[Discusiones](https://github.com/mcp-tool-shop-org/tool-compass/discussions)**

</div>
