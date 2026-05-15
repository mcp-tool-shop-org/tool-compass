"""Frozen golden-set tool corpus.

The corpus is deliberately small (~17 tools, 7 categories) and hand-curated so
the benchmark stays reproducible across runs and across Python/numpy versions.
The tools listed here MUST stay aligned with the `expected` field of every
entry in queries.yaml — adding a tool here without updating queries.yaml is a
fixture drift; the test will surface it as missing-relevant.

Tool names use the `<server>:<verb>` convention to match production patterns.
"""

from tool_manifest import ToolDefinition


GOLDEN_TOOLS: list[ToolDefinition] = [
    # File operations
    ToolDefinition(
        name="fs:read_file",
        description="Read the contents of a file from disk",
        category="file",
        server="fs",
        parameters={"path": "str"},
        examples=["read a file", "open file", "view file contents", "load document"],
        is_core=True,
    ),
    ToolDefinition(
        name="fs:write_file",
        description="Write content to a file on disk, creating or overwriting it",
        category="file",
        server="fs",
        parameters={"path": "str", "content": "str"},
        examples=["write file", "save content", "create file", "save to disk"],
        is_core=True,
    ),
    ToolDefinition(
        name="fs:delete_file",
        description="Delete a file from the filesystem",
        category="file",
        server="fs",
        parameters={"path": "str"},
        examples=["delete file", "remove file", "unlink"],
    ),
    ToolDefinition(
        name="fs:list_directory",
        description="List the contents of a directory",
        category="file",
        server="fs",
        parameters={"path": "str"},
        examples=["list directory", "show files in folder", "ls", "directory contents"],
    ),
    # Git operations
    ToolDefinition(
        name="git:status",
        description="Show the git working tree status with changes and staged files",
        category="git",
        server="git",
        parameters={"repo_path": "str?"},
        examples=["git status", "show working tree changes", "list modifications"],
        is_core=True,
    ),
    ToolDefinition(
        name="git:commit",
        description="Create a git commit with the staged changes and a message",
        category="git",
        server="git",
        parameters={"message": "str"},
        examples=["git commit", "save changes to repository", "record changes"],
    ),
    ToolDefinition(
        name="git:push",
        description="Push commits to a remote git repository",
        category="git",
        server="git",
        parameters={"remote": "str?", "branch": "str?"},
        examples=["git push", "upload commits to remote", "publish branch"],
    ),
    ToolDefinition(
        name="git:pull",
        description="Pull upstream changes from a remote git repository",
        category="git",
        server="git",
        parameters={"remote": "str?", "branch": "str?"},
        examples=["git pull", "fetch upstream changes", "sync with origin"],
    ),
    # Search operations
    ToolDefinition(
        name="search:grep",
        description="Search for a text pattern across files in a codebase",
        category="search",
        server="search",
        parameters={"pattern": "str", "path": "str?"},
        examples=["grep through codebase", "search for text", "find pattern in code"],
    ),
    ToolDefinition(
        name="search:find",
        description="Find files by name in a directory tree",
        category="search",
        server="search",
        parameters={"name": "str", "path": "str?"},
        examples=["find files by name", "locate file in directory tree", "filesystem find"],
    ),
    ToolDefinition(
        name="search:docs",
        description="Search documentation pages for relevant entries",
        category="search",
        server="search",
        parameters={"query": "str"},
        examples=["search documents", "lookup documentation", "find docs"],
    ),
    # AI operations
    ToolDefinition(
        name="ai:generate_image",
        description="Generate an image from a text prompt using AI",
        category="ai",
        server="ai",
        parameters={"prompt": "str", "size": "str?"},
        examples=["generate image from text", "text to image", "create artwork from prompt"],
    ),
    ToolDefinition(
        name="ai:transcribe_audio",
        description="Transcribe audio recordings to text using speech recognition",
        category="ai",
        server="ai",
        parameters={"audio_path": "str"},
        examples=["transcribe audio to text", "speech to text", "audio transcription"],
    ),
    ToolDefinition(
        name="ai:summarize",
        description="Summarize a long document into a concise summary",
        category="ai",
        server="ai",
        parameters={"text": "str", "max_length": "int?"},
        examples=["summarize document", "create summary of text", "tldr text"],
    ),
    # Database operations
    ToolDefinition(
        name="db:query",
        description="Execute a SQL query against a database",
        category="database",
        server="db",
        parameters={"sql": "str"},
        examples=["run sql query", "execute database query", "select from table"],
    ),
    ToolDefinition(
        name="db:insert",
        description="Insert a new row into a database table",
        category="database",
        server="db",
        parameters={"table": "str", "values": "dict"},
        examples=["insert row into database", "create database record", "add row"],
    ),
    # HTTP operations
    ToolDefinition(
        name="http:request",
        description="Send an HTTP request to a URL with method, headers, and body",
        category="http",
        server="http",
        parameters={"url": "str", "method": "str?"},
        examples=["send http request", "make api call", "http call"],
    ),
    ToolDefinition(
        name="http:fetch",
        description="Fetch a URL and return its contents as text",
        category="http",
        server="http",
        parameters={"url": "str"},
        examples=["fetch url contents", "download web page", "get url body"],
    ),
]


def all_tool_names() -> list[str]:
    """Return the list of all canonical tool names in the golden fixture."""
    return [t.name for t in GOLDEN_TOOLS]
