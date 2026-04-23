<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**एमसीपी उपकरणों के लिए सिमेंटिक नेविगेटर - सही उपकरण को याद रखने की बजाय, अपने उद्देश्य के आधार पर खोजें।**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% कम टोकन का उपयोग। आप जो करना चाहते हैं, उसका वर्णन करके उपकरण खोजें।*

[इंस्टॉलेशन](#quick-start) • [उपयोग](#usage) • [डॉकर](#option-2-docker) • [निर्देशिका](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [प्रदर्शन](#performance) • [योगदान](#contributing)

</div
>

---

## समस्या।

MCP सर्वर कई या सैकड़ों उपकरण (टूल) प्रदान करते हैं। सभी टूल की परिभाषाओं को संदर्भ में लोड करने से टोकन बर्बाद होते हैं और प्रतिक्रिया देने की गति धीमी हो जाती है।

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## समाधान।

"टूल कंपास" एक **अर्थ-आधारित खोज** तकनीक का उपयोग करता है ताकि प्राकृतिक भाषा में दिए गए विवरण के आधार पर प्रासंगिक उपकरणों को खोजा जा सके। सभी उपकरणों को लोड करने के बजाय, क्लाउड "कंपास()" फ़ंक्शन को एक इरादे के साथ कॉल करता है और केवल प्रासंगिक उपकरणों को ही वापस प्राप्त करता है।

निश्चित रूप से। कृपया वह अंग्रेजी पाठ प्रदान करें जिसका आप हिंदी में अनुवाद करवाना चाहते हैं। मैं उसका सटीक और स्वाभाविक हिंदी में अनुवाद करने की पूरी कोशिश करूंगा।
## प्रदर्शन।

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## शुरुआत कैसे करें।

📖 **पूर्ण दस्तावेज़:** इंस्टॉलेशन, कॉन्फ़िगरेशन और आर्किटेक्चर की विस्तृत जानकारी के लिए [टूल कंपास हैंडबुक](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) देखें।

### विकल्प 1: स्थानीय रूप से स्थापित करना।

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

### विकल्प 2: डॉकर।

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

जीएचसीआर इमेज (`ghcr.io/mcp-tool-shop-org/tool-compass`) `linux/amd64` और `linux/arm64` दोनों को सपोर्ट करती है, इसलिए एक ही टैग का उपयोग करके यह x86_64 सर्वरों और एप्पल सिलिकॉन/एआरएम वर्कस्टेशनों दोनों पर चल सकता है।

## विशेषताएं।

- **अर्थ-आधारित खोज:** आप जो करना चाहते हैं, उसका वर्णन करके टूल खोजें।
- **क्रमिक जानकारी:** `compass()` → `describe()` → `execute()` (यह एक प्रक्रिया का वर्णन करता है)।
- **त्वरित पहुंच:** अक्सर उपयोग किए जाने वाले टूल पहले से ही लोड रहते हैं।
- **श्रृंखला पहचान:** सामान्य टूल उपयोग प्रक्रियाओं को स्वचालित रूप से खोजता है।
- **विश्लेषण:** उपयोग के पैटर्न और टूल के प्रदर्शन को ट्रैक करें।
- **विभिन्न प्लेटफॉर्मों पर चलने योग्य:** विंडोज, macOS, लिनक्स।
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

| उपकरण। | विवरण। |
|------|-------------|
| `compass(intent)` | उपकरणों के लिए अर्थ-आधारित खोज। |
| `describe(tool_name)` | किसी उपकरण के लिए पूरी जानकारी प्राप्त करें। |
| `execute(tool_name, args)` | इसके बैकएंड पर एक टूल चलाएं। |
| `compass_categories()` | श्रेणियों और सर्वरों की सूची बनाएं। |
| `compass_status()` | सिस्टम की स्थिति और कॉन्फ़िगरेशन। |
| `compass_analytics(timeframe)` | उपयोग आँकड़े। |
| `compass_chains(action)` | उपकरणों के कार्यप्रवाहों का प्रबंधन करें। |
| `compass_sync(force)` | बैकएंड से इंडेक्स को फिर से बनाएं। |
| `compass_audit()` | पूरा सिस्टम रिपोर्ट। |

### प्रगतिशील प्रकटीकरण पैटर्न।

टूल कम्पास, टोकन के उपयोग को कम करने के लिए, एक तीन-चरणीय प्रगतिशील प्रकटीकरण (प्रोग्रेसिव डिस्क्लोजर) पद्धति का उपयोग करता है:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**यह क्यों महत्वपूर्ण है:**
- शुरुआत में 77 उपकरणों को लोड करने पर = लगभग 38,500 टोकन
- क्रमिक रूप से जानकारी प्रदान करने पर = प्रति उपयोग किए गए उपकरण लगभग 600 टोकन
- बचत: **सामान्य प्रक्रियाओं के लिए 95% से अधिक**

**उदाहरण के लिए कार्यप्रणाली:**

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

"कम्पास" के परिणामों में मौजूद `hint` फ़ील्ड इस प्रक्रिया को निर्देशित करता है, और यह बताता है कि `describe()` फ़ंक्शन का उपयोग कब करना चाहिए।

## कॉन्फ़िगरेशन।

| चर। | विवरण। | डिफ़ॉल्ट। |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | परियोजना का मूल फ़ोल्डर। | स्वचालित रूप से पता लगाया गया। |
| `TOOL_COMPASS_PYTHON` | पायथन निष्पादन योग्य फ़ाइल। | स्वचालित रूप से पता लगाया गया। |
| `TOOL_COMPASS_CONFIG` | कॉन्फ़िगरेशन फ़ाइल का पथ। | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | डेटा निर्देशिका। | प्लेटफ़ॉर्म-विशिष्ट (नीचे देखें)। |
| `OLLAMA_URL` | ओलामा सर्वर का यूआरएल (URL)। | `http://localhost:11434` |
| `COMFYUI_URL` | ComfyUI सर्वर। | `http://localhost:8188` |
| `PORT` | यह सुविधा एचटीटीपी प्रोटोकॉल का उपयोग करके डेटा भेजने की क्षमता प्रदान करती है (उदाहरण के लिए, Fly.io के लिए)। | अनसेट (stdio) |

**डिफ़ॉल्ट डेटा निर्देशिकाएँ:**
- **विंडोज:** `%LOCALAPPDATA%\tool-compass\`
- **मैकओएस:** `~/Library/Application Support/tool-compass/`
- **लिनक्स:** `~/.config/tool-compass/` (या `$XDG_CONFIG_HOME/tool-compass/`)

सभी विकल्पों के लिए, [` .env.example`](.env.example) फ़ाइल देखें।

## प्रदर्शन।

| मापन प्रणाली। | मूल्य। |
|--------|-------|
| इंडेक्स बनाने में लगने वाला समय। | लगभग 5 सेकंड में 44 उपकरणों का उपयोग। |
| क्वेरी विलंबता। | ~15 मिलीसेकंड (एम्बेडिंग सहित) |
| टोकन बचत | ~95% (38K → 2K) |
| सटीकता@3 | ~95% (शीर्ष 3 में सही टूल) |

## परीक्षण

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Skip integration tests (no Ollama required)
pytest -m "not integration"
```

## समस्या निवारण

### MCP सर्वर कनेक्ट नहीं हो रहा है

यदि क्लाउड डेस्कटॉप लॉग में JSON पार्सिंग त्रुटियां दिखाई देती हैं:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**कारण**: `print()` स्टेटमेंट JSON-RPC प्रोटोकॉल को दूषित करते हैं।

**समाधान**: लॉगिंग या `file=sys.stderr` का उपयोग करें।
```python
import sys
print("Debug message", file=sys.stderr)
```

### ओलामा कनेक्शन विफल

```bash
# Check Ollama is running
curl http://localhost:11434/api/tags

# Pull the embedding model
ollama pull nomic-embed-text
```

### इंडेक्स नहीं मिला

```bash
python gateway.py --sync
```

## संबंधित परियोजनाएं

AI-संचालित विकास के लिए **कम्पास सूट** का हिस्सा:

- [फ़ाइल कम्पास](https://github.com/mcp-tool-shop-org/file-compass) - सिमेंटिक फ़ाइल खोज
- [इंटीग्रैडियो](https://github.com/mcp-tool-shop-org/integradio) - वेक्टर-एम्बेडेड ग्राडियो घटक
- [बैकप्रोपगेट](https://github.com/mcp-tool-shop-org/backpropagate) - हेडलेस LLM फाइन-ट्यूनिंग
- [कम्फी हेडलेस](https://github.com/mcp-tool-shop-org/comfy-headless) - कम्फीUI बिना जटिलता के

## योगदान

हम योगदान का स्वागत करते हैं! दिशानिर्देशों के लिए [CONTRIBUTING.md](CONTRIBUTING.md) देखें।

## सुरक्षा और डेटा दायरा

टूल कम्पास एक **स्थानीय-प्रथम** विकास उपकरण है। पूर्ण नीति के लिए [SECURITY.md](SECURITY.md) देखें।

- **डेटा जिस पर काम किया जाता है:** टूल विवरण स्थानीय HNSW वेक्टर डेटाबेस में अनुक्रमित किए जाते हैं, खोज क्वेरी स्थानीय SQLite (`compass_analytics.db`) में लॉग की जाती हैं, एम्बेडिंग स्थानीय ओलामा के माध्यम से उत्पन्न होते हैं।
- **डेटा जिस पर काम नहीं किया जाता है:** कोई उपयोगकर्ता कोड नहीं, कोई फ़ाइल सामग्री नहीं, कोई क्रेडेंशियल नहीं। टूल कॉल तर्क हैश किए जाते हैं, सादे पाठ में संग्रहीत नहीं किए जाते हैं।
- **नेटवर्क:** एम्बेडिंग के लिए स्थानीय ओलामा से कनेक्ट होता है। वैकल्पिक ग्राडियो UI localhost पर बंधा होता है। कोई बाहरी टेलीमेट्री नहीं।
- **कोई टेलीमेट्री नहीं:** यह बाहरी रूप से कुछ भी एकत्र नहीं करता है। विश्लेषण केवल स्थानीय हैं।

## स्कोरकार्ड

| श्रेणी | स्कोर | टिप्पणियाँ |
|----------|-------|-------|
| A. सुरक्षा | 10/10 | SECURITY.md, केवल स्थानीय, कोई टेलीमेट्री नहीं, पैरामीटराइज़्ड SQL |
| B. त्रुटि प्रबंधन | 10/10 | संरचित परिणाम, शालीन ओलामा बैकअप |
| C. ऑपरेटर दस्तावेज़ | 10/10 | README, CHANGELOG, CONTRIBUTING, API दस्तावेज़ |
| D. शिपिंग स्वच्छता | 10/10 | CI (lint + परीक्षण + कवरेज + pip-audit + Docker), सत्यापन स्क्रिप्ट |
| E. पहचान | 10/10 | लोगो, अनुवाद, लैंडिंग पृष्ठ |
| **Total** | **50/50** | |

## लाइसेंस

[MIT](LICENSE) - विवरण के लिए LICENSE फ़ाइल देखें।

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

