<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.md">English</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<div align="center">

<p align="center"><img src="https://raw.githubusercontent.com/mcp-tool-shop-org/brand/main/logos/tool-compass/readme.png" alt="Tool Compass Logo" width="400"></p>

**एमसीपी टूल के लिए सिमेंटिक नेविगेटर - स्मृति के बजाय इरादे से सही उपकरण खोजें**

<a href="https://github.com/mcp-tool-shop-org/tool-compass/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mcp-tool-shop-org/tool-compass/ci.yml?branch=main&style=flat-square&label=CI" alt="CI"></a>
<a href="https://codecov.io/gh/mcp-tool-shop-org/tool-compass"><img src="https://img.shields.io/codecov/c/github/mcp-tool-shop-org/tool-compass?style=flat-square" alt="Codecov"></a>
<img src="https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<a href="LICENSE"><img src="https://img.shields.io/github/license/mcp-tool-shop-org/tool-compass?style=flat-square" alt="License"></a>
<img src="https://img.shields.io/badge/docker-ready-blue?style=flat-square&logo=docker&logoColor=white" alt="Docker">
<a href="https://mcp-tool-shop-org.github.io/tool-compass/"><img src="https://img.shields.io/badge/Landing_Page-live-blue?style=flat-square" alt="Landing Page"></a>


*95% कम टोकन। आप जो करना चाहते हैं, उसका वर्णन करके उपकरण खोजें।*

[इंस्टॉलेशन](#क्विक-स्टार्ट) • [उपयोग](#उपयोग) • [डॉकर](#ऑप्शन-2-डॉकर) • [हैंडबुक](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) • [प्रदर्शन](#प्रदर्शन) • [योगदान](#योगदान)

</div>

---

## समस्या

एमसीपी सर्वर दर्जनों या सैकड़ों उपकरण प्रदान करते हैं। सभी टूल परिभाषाओं को संदर्भ में लोड करने से टोकन बर्बाद होते हैं और प्रतिक्रिया धीमी हो जाती है।

```
Before: 77 tools × ~500 tokens = 38,500 tokens per request
After:  1 compass tool + 3 results = ~2,000 tokens per request

Savings: 95%
```

## समाधान

टूल कम्पास प्रासंगिक उपकरणों को खोजने के लिए **सिमेंटिक खोज** का उपयोग करता है, जो प्राकृतिक भाषा विवरण पर आधारित होता है। सभी टूल लोड करने के बजाय, क्लाउड एक इरादे के साथ `compass()` को कॉल करता है और केवल प्रासंगिक उपकरण प्राप्त करता है।

## त्वरित शुरुआत

📖 **पूर्ण दस्तावेज़:** इंस्टॉलेशन, कॉन्फ़िगरेशन और आर्किटेक्चर की गहन जानकारी के लिए [टूल कम्पास हैंडबुक](https://mcp-tool-shop-org.github.io/tool-compass/handbook/) देखें।

### विकल्प 1: एनपीएम (शून्य पूर्वापेक्षा, कोई पायथन इंस्टॉलेशन नहीं)

```bash
npx @mcptoolshop/tool-compass --help
npx @mcptoolshop/tool-compass serve     # MCP gateway
npx @mcptoolshop/tool-compass ui        # Gradio UI
npx @mcptoolshop/tool-compass doctor    # Diagnose setup
```

पहली बार चलाने पर एक सत्यापित प्लेटफ़ॉर्म बाइनरी डाउनलोड करता है (GitHub रिलीज़ के विरुद्ध SHA256-जांच)। स्थानीय रूप से कैश किया गया - बाद के आह्वान तुरंत शुरू होते हैं। एनपीएम पर [@mcptoolshop/tool-compass](https://www.npmjs.com/package/@mcptoolshop/tool-compass) देखें।

### विकल्प 2: PyPI

```bash
pip install tool-compass
tool-compass --help
```

### विकल्प 3: स्थानीय क्लोन

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

> GHCR छवि (`ghcr.io/mcp-tool-shop-org/tool-compass`) निम्नलिखित का समर्थन करती है:
> `linux/amd64` और `linux/arm64`, इसलिए समान टैग x86_64 सर्वर और Apple सिलिकॉन / ARM वर्कस्टेशन पर चलता है।

## विशेषताएं

- **सिमेंटिक खोज** - आप जो करना चाहते हैं, उसका वर्णन करके उपकरण खोजें
- **प्रगतिशील प्रकटीकरण** - `compass()` → `describe()` → `execute()`
- **हॉट कैश** - अक्सर उपयोग किए जाने वाले टूल पहले से लोड होते हैं
- **चेन डिटेक्शन** - स्वचालित रूप से सामान्य टूल वर्कफ़्लो की पहचान करता है
- **विश्लेषण** - उपयोग पैटर्न और टूल प्रदर्शन को ट्रैक करें
- **क्रॉस-प्लेटफ़ॉर्म** - विंडोज, मैकओएस, लिनक्स
- **डॉकर रेडी** - एक-कमांड परिनियोजन

## आर्किटेक्चर

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

### उपलब्ध उपकरण

| टूल | विवरण |
|------|-------------|
| `compass(intent)` | उपकरणों के लिए सिमेंटिक खोज |
| `describe(tool_name)` | किसी टूल के लिए पूर्ण स्कीमा प्राप्त करें |
| `execute(tool_name, args)` | इसके बैकएंड पर एक टूल चलाएं |
| `compass_categories()` | श्रेणियों और सर्वरों की सूची बनाएं |
| `compass_status()` | सिस्टम स्वास्थ्य और कॉन्फ़िगरेशन |
| `compass_analytics(timeframe)` | उपयोग आँकड़े |
| `compass_chains(action)` | टूल वर्कफ़्लो प्रबंधित करें |
| `compass_sync(force)` | बैकएंड से इंडेक्स को फिर से बनाएं |
| `compass_audit()` | पूर्ण सिस्टम रिपोर्ट |

### प्रगतिशील प्रकटीकरण पैटर्न

टूल कम्पास टोकन उपयोग को कम करने के लिए तीन-चरणीय प्रगतिशील प्रकटीकरण पैटर्न का उपयोग करता है:

```
1. compass("your intent")     → Get tool name + short description (~100 tokens)
2. describe("tool:name")      → Get full parameter schema (~500 tokens)
3. execute("tool:name", args) → Run the tool
```

**यह क्यों मायने रखता है:**
- 77 टूल को पहले से लोड करना = ~38,500 टोकन
- प्रगतिशील प्रकटीकरण = प्रति उपयोग किए गए टूल ~600 टोकन
- बचत: **विशिष्ट वर्कफ़्लो के लिए 95% +**

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

कम्पास परिणामों में `hint` फ़ील्ड इस प्रवाह का मार्गदर्शन करता है, यह सुझाव देता है कि `describe()` का उपयोग कब करें।

## कॉन्फ़िगरेशन

| चर | विवरण | डिफ़ॉल्ट |
|----------|-------------|---------|
| `TOOL_COMPASS_BASE_PATH` | प्रोजेक्ट रूट | स्वचालित रूप से पता लगाया गया |
| `TOOL_COMPASS_PYTHON` | पायथन निष्पादन योग्य | स्वचालित रूप से पता लगाया गया |
| `TOOL_COMPASS_CONFIG` | कॉन्फ़िगरेशन फ़ाइल पथ | `~/.config/tool-compass/compass_config.json` |
| `TOOL_COMPASS_DATA_DIR` | डेटा निर्देशिका | प्लेटफ़ॉर्म-विशिष्ट (नीचे देखें) |
| `OLLAMA_URL` | ओलामा सर्वर यूआरएल | `http://localhost:11434` |
| `COMFYUI_URL` | कॉम्फीयूआई सर्वर | `http://localhost:8188` |
| `PORT` | HTTP परिवहन को सक्षम करने के लिए सेट करें (जैसे, Fly.io के लिए)। | असेट (stdio) |

**डिफ़ॉल्ट डेटा निर्देशिकाएँ:**
- **विंडोज:** `%LOCALAPPDATA%\tool-compass\`
- **मैकओएस:** `~/Library/Application Support/tool-compass/`
- **लिनक्स:** `~/.config/tool-compass/` (या `$XDG_CONFIG_HOME/tool-compass/`)

सभी विकल्पों के लिए [`.env.example`](.env.example) देखें।

## प्रदर्शन

| मीट्रिक | मान |
|--------|-------|
| इंडेक्स निर्माण समय | ~5 सेकंड, 44 टूल के लिए |
| क्वेरी विलंबता | ~15ms (एम्बेडिंग सहित) |
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

### एमसीपी सर्वर कनेक्ट नहीं हो रहा है

यदि क्लाउड डेस्कटॉप लॉग JSON पार्स त्रुटियां दिखाते हैं:
```
Unexpected token 'S', "Starting T"... is not valid JSON
```

**कारण**: `print()` कथन JSON-RPC प्रोटोकॉल को दूषित करते हैं।

**समाधान**: लॉगिंग या `file=sys.stderr` का उपयोग करें:
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
tool-compass sync
```

## संबंधित परियोजनाएं

एआई-संचालित विकास के लिए **कम्पास सूट** का हिस्सा:

- [फ़ाइल कम्पास](https://github.com/mcp-tool-shop-org/file-compass) - सिमेंटिक फ़ाइल खोज
- [इंटीग्रैडियो](https://github.com/mcp-tool-shop-org/integradio) - वेक्टर-एम्बेडेड ग्रैडियो घटक
- [बैकप्रोपगेट](https://github.com/mcp-tool-shop-org/backpropagate) - हेडलेस एलएलएम फाइन-ट्यूनिंग
- [कॉम्फी हेडलेस](https://github.com/mcp-tool-shop-org/comfy-headless) - कॉम्फीयूआई बिना जटिलता के

## योगदान

हम योगदान का स्वागत करते हैं! दिशानिर्देशों के लिए [CONTRIBUTING.md](CONTRIBUTING.md) देखें।

## सुरक्षा और डेटा दायरा

टूल कम्पास एक **स्थानीय-प्रथम** विकास उपकरण है। पूर्ण नीति के लिए [SECURITY.md](SECURITY.md) देखें।

- **उपयोग किया गया डेटा:** स्थानीय एचएनएसडब्ल्यू वेक्टर डेटाबेस में अनुक्रमित टूल विवरण, स्थानीय एसक्यूलाइट (`compass_analytics.db`) में लॉग की गई खोज क्वेरी, स्थानीय ओलामा के माध्यम से उत्पन्न एम्बेडिंग।
- **उपयोग नहीं किया गया डेटा:** कोई उपयोगकर्ता कोड नहीं, कोई फ़ाइल सामग्री नहीं, कोई क्रेडेंशियल नहीं। टूल कॉल तर्क हैश किए जाते हैं, उन्हें सादे पाठ में संग्रहीत नहीं किया जाता है।
- **नेटवर्क:** एम्बेडिंग के लिए स्थानीय ओलामा से जुड़ता है। वैकल्पिक ग्रेडियो यूआई लोकलहोस्ट से बंधा होता है। कोई बाहरी टेलीमेट्री नहीं।
- **कोई टेलीमेट्री नहीं:** बाहर से कुछ भी एकत्र नहीं करता है। एनालिटिक्स केवल स्थानीय स्तर पर होते हैं।

## स्कोरकार्ड

श्रेणी के अनुसार स्कोर, स्वार्म के बाद निम्न के माध्यम से पुन: उत्पन्न किए जाते हैं:
`bash scripts/regenerate-scorecard.sh` (जो `npx @mcptoolshop/shipcheck audit` को रैप करता है)। वर्तमान आधिकारिक विवरण के लिए [SCORECARD.md](SCORECARD.md) देखें - नीचे दी गई तालिका इसे दर्शाती है और जानबूझकर हाथ से नहीं लिखी गई है। हाथ से तैयार किए गए अनुभाग (ज्ञात कमियां, सुधार इतिहास) `<!-- SHIPCHECK-AUTO-START/END -->` मार्करों के बाहर SCORECARD.md में मौजूद हैं और पुन: उत्पन्न होने पर भी बने रहते हैं।

| श्रेणी | स्कोर | टिप्पणियाँ |
|----------|-------|-------|
| ए. सुरक्षा | निर्धारित किया जाना है | एसएचए-पिन्ड क्रियाएं; डाइजेस्ट-पिन्ड बेस इमेज; पायपी पर एसएलएसए प्रोवेनैंस + एसबीओएम + जीएचसीआर; प्री-कमिट सीक्रेट स्कैन |
| बी. त्रुटि प्रबंधन | निर्धारित किया जाना है | संरचित परिणाम, सहज गिरावट, निकास कोड |
| सी. ऑपरेटर दस्तावेज़ | निर्धारित किया जाना है | रीडमी, चेंजलॉग, लाइसेंस, मेकफ़ाइल `verify` + `verify-metrics` + `scorecard` |
| डी. शिपिंग स्वच्छता | निर्धारित किया जाना है | सीआई समेकित; प्रत्येक नौकरी पर टाइमआउट-मिनट + प्रतिधारण-दिन; pyproject.toml में पायटेस्ट कॉन्फ़िगरेशन |
| ई. पहचान (नरम) | निर्धारित किया जाना है | लोगो, लैंडिंग पेज, गिटहब मेटाडेटा; pyproject.toml में स्पष्ट अनुरक्षक |
| **Total** | **TBD** | `make scorecard` के माध्यम से पुन: उत्पन्न करें |

## लाइसेंस

[एमआईटी](LICENSE) - विवरण के लिए लाइसेंस फ़ाइल देखें।

---

<p align="center">
  Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>
</p>

