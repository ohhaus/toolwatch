# Contributing

ToolWatch is experimental. Keep changes focused, preserve the deterministic security
boundary, and never add real credentials or external-service calls to tests.

Before opening a pull request:

```bash
uv sync --frozen
make check
make package-check
```

Security fixes require a regression test. PostgreSQL integration tests must not use
SQLite, and local Ollama tests must retain the `local_llm` marker.
