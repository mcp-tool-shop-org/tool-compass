<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**MCP टूल के लिए सिमेंटिक नेविगेटर - मेमोरी के बजाय, इरादे के आधार पर सही टूल खोजें**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% कम टोकन। यह बताएं कि आप क्या करना चाहते हैं, और टूल खोजें।*

[इंस्टॉलेशन](#quick-start) • [उपयोग](#usage) • [डॉकर](#option-2-docker) • [हैंडबुक](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [प्रदर्शन](#performance) • [योगदान](#contributing)

</div

---

## समस्या

MCP सर्वर में दर्जनों या सैकड़ों टूल उपलब्ध होते हैं। सभी टूल परिभाषाओं को संदर्भ में लोड करने से टोकन की खपत होती है और प्रतिक्रियाएं धीमी हो जाती हैं।

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## समाधान

टूल कॉम्पास, प्राकृतिक भाषा में दिए गए विवरण से प्रासंगिक टूल खोजने के लिए **सिमेंटिक खोज** का उपयोग करता है। सभी टूल लोड करने के बजाय, क्लाउड `compass()` को एक इरादे के साथ कॉल करता है और केवल प्रासंगिक टूल वापस प्राप्त करता है।

<!--
## डेमो

<p align="center">
  <img src="docs/assets/demo.gif" alt="Tool Compass Demo" width="600">
</p>
-->

## क्विक स्टार्ट

📖 **पूर्ण दस्तावेज़:** इंस्टॉलेशन, कॉन्फ़िगरेशन और आर्किटेक्चर के बारे में विस्तृत जानकारी के लिए [टूल कॉम्पास हैंडबुक](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) देखें।

### विकल्प 1: npm (शून्य आवश्यकता, पायथन इंस्टॉलेशन की आवश्यकता नहीं)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve     # MCP gateway
npx @mcptoolshop/tool-compass ui        # Gradio UI
npx @mcptoolshop/tool-compass doctor    # Diagnose setup
```

पहली बार चलाने पर एक सत्यापित प्लेटफॉर्म बाइनरी डाउनलोड करता है (GitHub रिलीज़ के विरुद्ध SHA256 से जांचा गया)। स्थानीय रूप से कैश किया गया - बाद के उपयोग तुरंत शुरू हो जाते हैं। npm पर [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) देखें।

### विकल्प 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### विकल्प 3: लोकल क्लोन

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

### विकल्प 4: डॉकर

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

> GHCR इमेज (`ghcr.io/mcp-tool-shop-org/tool-compass`) `linux/amd64` और `linux/arm64` का समर्थन करती है, इसलिए एक ही टैग x86_64 सर्वरों और Apple Silicon / ARM वर्कस्टेशनों दोनों पर चलता है।

## विशेषताएं

- **सिमेंटिक खोज**: यह बताएं कि आप क्या करना चाहते हैं, और टूल खोजें
- **प्रगतिशील प्रकटीकरण**: `compass()` → `describe()` → `execute()`
- **हॉट कैश**: अक्सर उपयोग किए जाने वाले टूल पहले से लोड किए जाते हैं
- **चेन डिटेक्शन**: सामान्य टूल वर्कफ़्लो को स्वचालित रूप से खोजता है
- **विश्लेषण**: उपयोग पैटर्न और टूल प्रदर्शन को ट्रैक करें
- **क्रॉस-प्लेटफ़ॉर्म**: विंडोज, macOS, लिनक्स
- **डॉकर रेडी**: एक-कमांड डिप्लॉयमेंट

## आर्किटेक्चर

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

### `compass()` टूल

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

### उपलब्ध टूल

| टूल | विवरण |
|------|-------------|
| `compass(intent)` | टूल के लिए सिमेंटिक खोज |
| `describe(tool_name)` | टूल के लिए पूर्ण स्कीमा प्राप्त करें |
| `execute(tool_name, args)` | अपने बैकएंड पर टूल चलाएं |
| `compass_categories()` | श्रेणियां और सर्वर सूचीबद्ध करें |
| `compass_status()` | सिस्टम स्वास्थ्य और कॉन्फ़िगरेशन |
| `compass_analytics(timeframe)` | उपयोग आँकड़े |
| `compass_chains(action)` | टूल वर्कफ़्लो प्रबंधित करें |
| `compass_sync(force)` | बैकएंड से इंडेक्स को फिर से बनाएं |
| `compass_audit()` | पूर्ण सिस्टम रिपोर्ट |

### प्रगतिशील प्रकटीकरण पैटर्न

टूल कॉम्पास टोकन के उपयोग को कम करने के लिए एक तीन-चरणीय प्रगतिशील प्रकटीकरण पैटर्न का उपयोग करता है:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**यह क्यों महत्वपूर्ण है:**
- 77 टूल को पहले से लोड करना = ~38,500 टोकन
- प्रगतिशील प्रकटीकरण = उपयोग किए गए प्रत्येक टूल के लिए ~600 टोकन
- बचत: **सामान्य वर्कफ़्लो के लिए 95%+**

**उदाहरण वर्कफ़्लो:**

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

`compass()` परिणामों में `hint` फ़ील्ड इस प्रवाह का मार्गदर्शन करता है, यह सुझाव देता है कि `describe()` का उपयोग कब करना है।

## कॉन्फ़िगरेशन

| चर | विवरण | डिफ़ॉल्ट |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | प्रोजेक्ट रूट | स्वचालित रूप से पता लगाया गया |
| `TOOL_COMPASS_PYTHON` | पायथन निष्पादन योग्य | स्वचालित रूप से पता लगाया गया |
| `TOOL_COMPASS_CONFIG` | कॉन्फ़िगरेशन फ़ाइल पथ | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | डेटा निर्देशिका | प्लेटफ़ॉर्म-विशिष्ट (नीचे देखें) |
| `OLLAMA_URL` | ओलामा सर्वर URL | `http://localhost:11434` |
| `COMFYUI_URL` | कॉम्फीयूआई सर्वर | `http://localhost:8188` |
| `PORT` | HTTP परिवहन को सक्षम करने के लिए सेट करें (जैसे, Fly.io के लिए) | अनसेट (stdio) |

**डिफ़ॉल्ट डेटा निर्देशिकाएँ:**
- **विंडोज:** `%LOCALAPPDATA%\tool-compass\`
- **macOS:** `~/Library/Application Support/tool-compass/`
- **लिनक्स:** `~/.config/tool-compass/` (या `$XDG_CONFIG_HOME/tool-compass/`)

सभी विकल्पों के लिए [`.env.example`](.env.example) देखें।

## प्रदर्शन

| माप | मान |
|--------|-------|
| इंडेक्स बनाने का समय | 44 उपकरणों के लिए लगभग 5 सेकंड |
| क्वेरी विलंबता | लगभग 15 मिलीसेकंड (एम्बेडिंग सहित) |
| टोकन बचत | लगभग 95% (38K → 2K) |
| सटीकता@3 | लगभग 95% (शीर्ष 3 में सही उपकरण) |

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

यदि क्लाउड डेस्कटॉप लॉग में JSON पार्स त्रुटियां दिखाई देती हैं:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**कारण:** `print()` स्टेटमेंट JSON-RPC प्रोटोकॉल को दूषित करते हैं।

**समाधान:** लॉगिंग या `file=sys.stderr` का उपयोग करें।
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

AI-संचालित विकास के लिए **कंपैस्स सूट** का हिस्सा:

- [फ़ाइल कंपैस्स](https://github.com/mcp-tool-shop-org/file-compass) - सिमेंटिक फ़ाइल खोज
- [इंटीग्रिडियो](https://github.com/mcp-tool-shop-org/integradio) - वेक्टर-एम्बेडेड ग्राडियो घटक
- [बैकप्रोपगेट](https://github.com/mcp-tool-shop-org/backpropagate) - हेडलेस LLM फाइन-ट्यूनिंग
- [कॉम्फी हेडलेस](https://github.com/mcp-tool-shop-org/comfy-headless) - कॉम्फीUI बिना जटिलता के

## योगदान

हम योगदान का स्वागत करते हैं! दिशानिर्देशों के लिए [CONTRIBUTING.md](CONTRIBUTING.md) देखें।

## सुरक्षा और डेटा दायरा

टूल कंपैस्स एक **स्थानीय-प्रथम** विकास उपकरण है। पूर्ण नीति के लिए [SECURITY.md](SECURITY.md) देखें।

- **डेटा जो उपयोग किया जाता है:** स्थानीय HNSW वेक्टर DB में अनुक्रमित टूल विवरण, स्थानीय SQLite (`compass_analytics.db`) में लॉग किए गए खोज क्वेरी, स्थानीय ओलामा के माध्यम से उत्पन्न एम्बेडिंग।
- **डेटा जो उपयोग नहीं किया जाता है:** कोई उपयोगकर्ता कोड नहीं, कोई फ़ाइल सामग्री नहीं, कोई क्रेडेंशियल नहीं। टूल कॉल तर्क को हैश किया जाता है, सादे पाठ में संग्रहीत नहीं किया जाता है।
- **नेटवर्क:** एम्बेडिंग के लिए स्थानीय ओलामा से कनेक्ट होता है। वैकल्पिक ग्राडियो UI localhost पर बंधा होता है। कोई बाहरी टेलीमेट्री नहीं।
- **कोई टेलीमेट्री नहीं:** यह बाहरी रूप से कुछ भी एकत्र नहीं करता है। विश्लेषण केवल स्थानीय हैं।

## स्कोरकार्ड

प्रत्येक श्रेणी के स्कोर स्वार्म के बाद `bash scripts/regenerate-scorecard.sh` के माध्यम से पुन: उत्पन्न होते हैं (जो `npx @mcptoolshop/shipcheck audit` को लपेटता है)। वर्तमान आधिकारिक विवरण के लिए [SCORECARD.md](SCORECARD.md) देखें - नीचे दी गई तालिका इसका प्रतिबिंब है और इसे जानबूझकर मैन्युअल रूप से नहीं लिखा गया है। मैन्युअल रूप से क्यूरेट किए गए अनुभाग (ज्ञात कमियां, निवारण इतिहास) SCORECARD.md में `<!-- SHIPCHECK-AUTO-START/END -->` मार्करों के बाहर रहते हैं और पुन: उत्पन्न होने पर भी बने रहते हैं।

| श्रेणी | स्कोर | टिप्पणियाँ |
|----------|-------|-------|
| A. सुरक्षा | TBD | SHA-पिन किए गए क्रियाएं; डाइजेस्ट-पिन किए गए बेस इमेज; SLSA प्रमाण + SBOM on PyPI + GHCR; प्री-कमिट सीक्रेट स्कैन |
| B. त्रुटि प्रबंधन | TBD | संरचित परिणाम, सुचारू गिरावट, एग्जिट कोड |
| C. ऑपरेटर दस्तावेज़ | TBD | README, CHANGELOG, LICENSE, Makefile `verify` + `verify-metrics` + `scorecard` |
| D. शिपिंग स्वच्छता | TBD | CI समेकित; प्रत्येक कार्य पर टाइमआउट-मिनट + प्रतिधारण-दिन; pyproject.toml में पायटेस्ट कॉन्फ़िगरेशन |
| E. पहचान (सॉफ्ट) | TBD | लोगो, लैंडिंग पृष्ठ, GitHub मेटाडेटा; pyproject.toml में स्पष्ट रखरखावकर्ता |
| **Total** | **TBD** | `make scorecard` के माध्यम से पुन: उत्पन्न करें |

## लाइसेंस

[MIT](LICENSE) - विवरण के लिए LICENSE फ़ाइल देखें।

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

