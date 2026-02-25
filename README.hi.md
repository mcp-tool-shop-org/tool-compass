<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="assets/logo.png" alt="Tool Compass Logo" width="400"></p>

# उपकरण: कंपास।

**एमसीपी (MCP) उपकरणों के लिए सिमेंटिक नेविगेटर - सही उपकरण को खोजें, याददाश्त के बजाय इरादे के आधार पर।**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>

*95% कम टोकन का उपयोग। आप जो करना चाहते हैं, उसका वर्णन करके उपकरण खोजें।*

[स्थापना](#शुरुआत) • [उपयोग](#उपयोग) • [डॉकर](#विकल्प-2-डॉकर) • [प्रदर्शन](#प्रदर्शन) • [योगदान](#योगदान)

</div

---

## समस्या।

MCP सर्वर कई या सैकड़ों उपकरण (टूल्स) प्रदान करते हैं। सभी उपकरणों की परिभाषाओं को संदर्भ में लोड करने से टोकन की खपत बढ़ती है और प्रतिक्रिया देने में अधिक समय लगता है।

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## समाधान।

"टूल कंपास" एक ऐसा उपकरण है जो प्रासंगिक टूल खोजने के लिए **अर्थ-आधारित खोज** का उपयोग करता है। यह प्राकृतिक भाषा में दिए गए विवरण के आधार पर टूल ढूंढता है। पारंपरिक तरीके से सभी टूल लोड करने के बजाय, क्लाउड "कंपास()" फ़ंक्शन को एक उद्देश्य के साथ कॉल करता है और केवल प्रासंगिक टूल ही वापस प्राप्त करता है।

निश्चित रूप से। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। मैं उसका सटीक और स्वाभाविक हिंदी में अनुवाद करने की पूरी कोशिश करूंगा।
## प्रदर्शन।

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## शुरुआत कैसे करें।

### विकल्प 1: स्थानीय रूप से स्थापित करना।

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

### विकल्प 2: डॉकर।

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

## विशेषताएं।

- **अर्थ-आधारित खोज:** आप जो करना चाहते हैं, उसका वर्णन करके उपकरणों को खोजें।
- **क्रमिक जानकारी:** `compass()` → `describe()` → `execute()` (यह एक प्रक्रिया का वर्णन करता है)।
- **त्वरित पहुंच:** अक्सर उपयोग किए जाने वाले उपकरण पहले से ही लोड रहते हैं।
- **श्रृंखला पहचान:** यह स्वचालित रूप से सामान्य उपकरण उपयोग प्रक्रियाओं का पता लगाता है।
- **विश्लेषण:** उपयोग के पैटर्न और उपकरणों के प्रदर्शन को ट्रैक करें।
- **विभिन्न प्लेटफार्मों पर चलने योग्य:** विंडोज, macOS, लिनक्स।
- **डॉकर के लिए तैयार:** एक ही कमांड से इंस्टॉलेशन।

## आर्किटेक्चर।

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

## उपयोग

### `compass()` टूल।

```python
compass(
    intent="I need to generate an AI image from a text description",
    top_k=3,
    category=None,  # Optional: "file", "git", "database", "ai", etc.
    min_confidence=0.3
)
```

रिटर्न:
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

### उपलब्ध उपकरण।

| Tool | विवरण। |
| "Please provide the English text you would like me to translate into Hindi." | कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। मैं उसका सटीक और उचित अनुवाद करने के लिए तैयार हूं। |
| `compass(intent)` | उपकरणों के लिए अर्थ-आधारित खोज। |
| `describe(tool_name)` | किसी उपकरण के लिए पूरी जानकारी प्राप्त करें। |
| `execute(tool_name, args)` | इसके बैकएंड पर एक टूल चलाएं। |
| `compass_categories()` | श्रेणियों और सर्वरों की सूची बनाएं। |
| `compass_status()` | सिस्टम की स्थिति और कॉन्फ़िगरेशन। |
| `compass_analytics(timeframe)` | उपयोग आँकड़े। |
| `compass_chains(action)` | उपकरणों के कार्यप्रवाहों का प्रबंधन करें। |
| `compass_sync(force)` | बैकएंड से इंडेक्स को फिर से बनाएं। |
| `compass_audit()` | पूरा सिस्टम रिपोर्ट. |

## कॉन्फ़िगरेशन।

| चर। | विवरण। | डिफ़ॉल्ट। |
| ज़रूर, मैं आपकी मदद कर सकता हूँ। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। | कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। मैं उसका सटीक और उचित अनुवाद करने के लिए तैयार हूं। | ज़रूर, मैं आपकी मदद कर सकता हूँ। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। |
| `TOOL_COMPASS_BASE_PATH` | परियोजना का मूल फ़ोल्डर। | स्वचालित रूप से पता लगाया गया। |
| `TOOL_COMPASS_PYTHON` | पायथन निष्पादन योग्य फ़ाइल। | स्वचालित रूप से पता लगाया गया। |
| `TOOL_COMPASS_CONFIG` | कॉन्फ़िगरेशन फ़ाइल का पथ। | `./compass_config.json` |
| `OLLAMA_URL` | ओलामा सर्वर का यूआरएल (URL)। | `http://localhost:11434` |
| `COMFYUI_URL` | कम्फयूआई सर्वर। | `http://localhost:8188` |

सभी विकल्पों के लिए, [` .env.example`](.env.example) फ़ाइल देखें।

## प्रदर्शन

| मापन प्रणाली। | Value |
| ज़रूर, मैं आपकी मदद कर सकता हूँ। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। | "The quick brown fox jumps over the lazy dog."

"यह फुर्तीला भूरा लोमड़ी आलसी कुत्ते के ऊपर से कूदता है।" |
| इंडेक्स बनाने में लगने वाला समय। | लगभग 5 सेकंड में 44 उपकरणों का उपयोग। |
| क्वेरी विलंबता। | लगभग 15 मिलीसेकंड (एम्बेडिंग सहित)। |
| टोकन के माध्यम से बचत। | लगभग 95% (38,000 से 2,000 तक)। |
| सटीकता@3 | लगभग 95% (सही उपकरण शीर्ष 3 में शामिल) |

## परीक्षण।

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## समस्या निवारण।

### MCP सर्वर से कनेक्शन स्थापित नहीं हो पा रहा है।

यदि क्लाउड डेस्कटॉप के लॉग में JSON पार्सिंग त्रुटियां दिखाई देती हैं:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**कारण:** `print()` फ़ंक्शन का उपयोग करने से JSON-RPC प्रोटोकॉल दूषित हो जाता है।

**समाधान:** लॉगिंग का उपयोग करें या `file=sys.stderr` का विकल्प चुनें।
```python
import sys
print("Debug message", file=sys.stderr)
```

### ओलामा से कनेक्शन स्थापित नहीं हो पाया।

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### इंडेक्स नहीं मिला।

```bash
python gateway.py --sync
```

## संबंधित परियोजनाएं।

यह "कंपास सुइट" का एक हिस्सा है, जो कृत्रिम बुद्धिमत्ता (एआई) द्वारा संचालित विकास के लिए बनाया गया है:

- [File Compass](https://github.com/mcp-tool-shop-org/file-compass) - अर्थपूर्ण फ़ाइल खोज
- [Integradio](https://github.com/mcp-tool-shop-org/integradio) - वेक्टर-एम्बेडेड Gradio घटक
- [Backpropagate](https://github.com/mcp-tool-shop-org/backpropagate) - हेडलेस एलएलएम फाइन-ट्यूनिंग
- [Comfy Headless](https://github.com/mcp-tool-shop-org/comfy-headless) - ComfyUI, लेकिन बिना जटिलता के

## योगदान करना।

हम योगदानों का स्वागत करते हैं! दिशानिर्देशों के लिए [CONTRIBUTING.md](CONTRIBUTING.md) देखें।

## सुरक्षा

सुरक्षा संबंधी कमजोरियों के लिए, कृपया [SECURITY.md](SECURITY.md) देखें। **सुरक्षा संबंधी त्रुटियों के लिए सार्वजनिक मुद्दों को न खोलें।**

## सहायता

- **प्रश्न / सहायता:** [चर्चाएँ](https://github.com/mcp-tool-shop-org/tool-compass/discussions)
- **बग रिपोर्ट:** [मुद्दे](https://github.com/mcp-tool-shop-org/tool-compass/issues)
- **सुरक्षा:** [SECURITY.md](SECURITY.md)

## लाइसेंस

[MIT](LICENSE) - विवरण के लिए LICENSE फ़ाइल देखें।

## क्रेडिट

- **HNSW**: माल्कोव और याशुनिन, "पदानुक्रमित नेविगेबल स्मॉल वर्ल्ड ग्राफ का उपयोग करके कुशल और मजबूत अनुमानित निकटतम पड़ोसी खोज" (2016)
- **nomic-embed-text**: नोमिक एआई का ओपन एम्बेडिंग मॉडल
- **FastMCP**: एंथ्रोपिक का MCP फ्रेमवर्क
- **Gradio**: हगिंग फेस का एमएल वेब फ्रेमवर्क

---

<div align="center">

*"सिंक्रोनी सबसे ऊपर।"*

टूल कम्पास, MCP पारिस्थितिकी तंत्र में एंट्रॉपी को कम करता है, उपकरणों को उनके अर्थपूर्ण अर्थ के आधार पर व्यवस्थित करके।

**[दस्तावेज़](https://github.com/mcp-tool-shop-org/tool-compass#readme)** • **[मुद्दे](https://github.com/mcp-tool-shop-org/tool-compass/issues)** • **[चर्चाएँ](https://github.com/mcp-tool-shop-org/tool-compass/discussions)**

</div>
