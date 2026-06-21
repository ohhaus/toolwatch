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
    assert "409" in paths["/api/v1/tools"]["post"]["responses"]
    assert "422" in paths["/api/v1/tools"]["post"]["responses"]
    assert "RiskLevel" in schema["components"]["schemas"]
    assert "SessionStatus" in schema["components"]["schemas"]
