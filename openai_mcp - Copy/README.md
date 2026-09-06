# OpenAI MCP utility

This is a separate, read-only MCP server. It exposes model lookup, chat
completion, embedding, moderation, and fine-tuning-status operations to an
MCP-capable client. It is not a replacement for the main assistant's future
`OpenAIProvider`; that provider belongs in `providers/` and remains part of
Package A.

Run after installing this package's dependencies:

```powershell
Push-Location .\openai_mcp
$env:PYTHONPATH = ".."
.\.venv\Scripts\python.exe -m openai_mcp.server
Pop-Location
```

It uses the root project's centralized configuration, including `.env.local`.
Tests are mocked and never send a request to OpenAI.
