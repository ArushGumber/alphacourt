# Claude Code

    claude mcp add --transport http alphacourt https://YOUR-ADDRESS/mcp

Or put this in a file and pass it with `--mcp-config`:

    {"mcpServers": {"alphacourt": {"type": "http", "url": "https://YOUR-ADDRESS/mcp"}}}

Then ask: "Find a strategy with a real edge in this market if there is one, and submit it."
Allow the tools with `--allowedTools "mcp__alphacourt__*"` when running non-interactively (`claude -p`).
