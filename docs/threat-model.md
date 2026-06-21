| Threat | Example | Mitigation |
|---|---|---|
| Secret leakage | API token in tool arguments | Recursive redaction |
| Unknown tool execution | Agent invents shell.execute | Registry allowlist |
| SSRF | Tool accesses metadata endpoint | Host and IP validation |
| SQL destruction | DROP TABLE query | Deterministic blocking rule |
| Oversized payload | Multi-megabyte tool result | Size and depth limits |
| Prompt injection | Malicious instruction in tool output | Treat output as untrusted |
