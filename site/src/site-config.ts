import type { SiteConfig } from '@mcptoolshop/site-theme';

export const config: SiteConfig = {
  title: 'Tool Compass',
  description: 'Semantic MCP tool discovery gateway — find tools by intent, not memory.',
  logoBadge: 'TC',
  brandName: 'Tool Compass',
  repoUrl: 'https://github.com/mcp-tool-shop-org/tool-compass',
  footerText: 'MIT Licensed — built by <a href="https://github.com/mcp-tool-shop-org" style="color:var(--color-muted);text-decoration:underline">mcp-tool-shop-org</a>',

  hero: {
    badge: 'MCP Gateway',
    headline: 'Find tools by',
    headlineAccent: 'intent, not memory.',
    description: 'Semantic search for MCP tools. Load 3 relevant tools instead of 77 — 95% fewer tokens, ~15ms latency, ~95% accuracy.',
    primaryCta: { href: '#quick-start', label: 'Quick Start' },
    secondaryCta: { href: '#tools', label: 'API Reference' },
    previews: [
      {
        label: 'Setup',
        code: 'ollama pull nomic-embed-text\npip install -r requirements.txt\npython gateway.py --sync',
      },
      {
        label: 'compass()',
        code: 'compass(\n  intent="generate an AI image",\n  top_k=3\n)',
      },
      {
        label: 'Result',
        code: '# comfy:comfy_generate  0.91\n# tokens_saved: 20,500\n# total_indexed: 44',
      },
    ],
  },

  sections: [
    {
      kind: 'features',
      id: 'features',
      title: 'Features',
      subtitle: 'Stop loading all 77 tools into context. Find the right one.',
      features: [
        {
          title: 'Semantic Discovery',
          desc: 'compass(intent) finds tools by meaning. Describe what you want to do — get the right tool, not a list of all of them.',
        },
        {
          title: '95% Token Savings',
          desc: '38,500 tokens → 2,000 per request. HNSW vector index, nomic-embed-text, ~15ms query latency, ~95% accuracy@3.',
        },
        {
          title: 'Progressive Disclosure',
          desc: 'compass() → describe() → execute(). Load only the schema you need, only when you actually need it.',
        },
      ],
    },
    {
      kind: 'code-cards',
      id: 'quick-start',
      title: 'Quick Start',
      cards: [
        {
          title: 'Install & Index',
          code: '# Prerequisites: Ollama running locally\nollama pull nomic-embed-text\n\n# Clone and install\ngit clone https://github.com/mcp-tool-shop-org/tool-compass\ncd tool-compass\npip install -r requirements.txt\n\n# Build the search index\npython gateway.py --sync\n\n# Start the MCP gateway\npython gateway.py',
        },
        {
          title: 'Query by Intent',
          code: 'compass(\n  intent="I need to generate an AI image from a text description",\n  top_k=3,\n  min_confidence=0.3\n)\n\n# Returns:\n# {\n#   "matches": [{\n#     "tool": "comfy:comfy_generate",\n#     "confidence": 0.912\n#   }],\n#   "tokens_saved": 20500\n# }',
        },
      ],
    },
    {
      kind: 'data-table',
      id: 'tools',
      title: 'Gateway Tools',
      subtitle: 'Nine tools — one semantic entry point for your entire MCP ecosystem.',
      columns: ['Tool', 'Description'],
      rows: [
        ['compass(intent)', 'Semantic search — find the right tool by describing your intent'],
        ['describe(tool)', 'Get full JSON schema for a specific tool before calling it'],
        ['execute(tool, args)', 'Run any indexed tool directly through the gateway'],
        ['compass_categories()', 'List all tool categories and connected MCP servers'],
        ['compass_status()', 'System health — index size, model status, config'],
        ['compass_analytics(timeframe)', 'Usage statistics, accuracy metrics, and performance data'],
        ['compass_chains(action)', 'Discover and manage common multi-tool workflows'],
        ['compass_sync(force)', 'Rebuild the HNSW search index from connected backends'],
        ['compass_audit()', 'Full system diagnostic — index integrity, server health'],
      ],
    },
  ],
};
