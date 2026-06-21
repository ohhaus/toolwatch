API
 ↓
Application
 ↓
Domain
 ↑
Infrastructure implements ports

- Domain must not import FastAPI, SQLAlchemy or Ollama SDK.
- Security checks happen before tool execution.
- Redaction happens before persistence, logging and tracing.
- Unknown tools are never executed.
- LLM output is always considered untrusted input.
