# Tool Compass

## What This Does

Discovers and catalogs MCP servers and tools. Maps the ecosystem of available
tools and helps navigate what's available in your environment.

## MCP Tools Available

| Tool | Purpose |
|------|---------|
| `discover_tools` | Find available MCP servers and tools |
| `catalog_tools` | Build catalog of tools in environment |
| `search_tools` | Search for tools by name or capability |
| `describe_tool` | Get detailed info about specific tool |

## Architecture

- Tool discovery via process inspection and config files
- Capability cataloging and classification
- Searchable tool registry
- Integration with Claude Code tool ecosystem

## Dependencies

- Python >= 3.10
- mcp >= 1.0.0

## Key Notes

- Scans ~/.claude/plugins for installed plugins
- Reads claude_desktop_config.json for registered servers
- Maintains local tool cache
