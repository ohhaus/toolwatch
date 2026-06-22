"""OpenAPI contract tests for milestone 2 endpoints."""

from toolwatch.main import create_app


def test_openapi_documents_registry_and_session_contracts() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]

    assert "/api/v1/tools" in paths
    assert "/api/v1/tools/{tool_id}" in paths
    assert "/api/v1/sessions" in paths
    assert "/api/v1/sessions/{session_id}" in paths
    assert "/api/v1/sessions/{session_id}/complete" in paths
    assert "/api/v1/tool-calls" in paths
    assert "/api/v1/tool-calls/{call_id}" in paths
    assert "/api/v1/sessions/{session_id}/tool-calls" in paths
    assert "/api/v1/rules" in paths
    assert "/api/v1/rules/{rule_id}" in paths
    assert "/api/v1/audit-events" in paths
    assert "/api/v1/sessions/{session_id}/audit-events" in paths
    assert "/api/v1/tool-calls/{call_id}/audit-events" in paths
    assert "/metrics" in paths
    assert "/health/telemetry" in paths
    assert "409" in paths["/api/v1/tools"]["post"]["responses"]
    assert "422" in paths["/api/v1/tools"]["post"]["responses"]
    execute = paths["/api/v1/tool-calls"]["post"]
    assert any(parameter["name"] == "Idempotency-Key" for parameter in execute["parameters"])
    assert {"403", "409", "422", "502", "504"} <= set(execute["responses"])
    assert "RiskLevel" in schema["components"]["schemas"]
    assert "SessionStatus" in schema["components"]["schemas"]
    assert "ToolCallStatus" in schema["components"]["schemas"]
    assert "X-Correlation-ID" in paths["/api/v1/tool-calls"]["post"]["responses"]["200"]["headers"]
