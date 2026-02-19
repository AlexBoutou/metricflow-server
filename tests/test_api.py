from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Patch init_adapter before importing app so lifespan doesn't try to connect
with patch("metricflow_server.engine_manager.EngineManager.init_adapter"):
    from metricflow_server.main import app

API_KEY = "test-api-key"
ADMIN_KEY = "test-admin-key"


@pytest.fixture
def client():
    with patch("metricflow_server.engine_manager.EngineManager.init_adapter"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture
def mock_engine():
    """A minimal mock MetricFlowEngine."""
    engine = MagicMock()

    # list_metrics
    metric = MagicMock()
    metric.name = "revenue"
    metric.description = "Sum of revenue"
    metric.type = MagicMock(__str__=lambda s: "MetricType.SIMPLE")
    metric.label = None
    dim = MagicMock()
    dim.name = "location_name"
    dim.qualified_name = "location__location_name"
    dim.description = None
    dim.label = None
    from dbt_semantic_interfaces.type_enums import DimensionType
    dim.type = DimensionType.CATEGORICAL
    dim.type_params = None
    metric.dimensions = [dim]
    engine.list_metrics.return_value = [metric]

    # query
    data_table = MagicMock()
    data_table.column_names = ["location__location_name", "revenue"]
    data_table.rows = [("Paris", 1234.56), ("Lyon", 789.01)]
    result = MagicMock()
    result.sql = "SELECT location__location_name, revenue FROM ..."
    result.result_df = data_table
    engine.query.return_value = result

    return engine


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
def test_health_not_ready(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_health_ready(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------
def test_missing_auth(client):
    response = client.get("/api/v1/metrics")
    assert response.status_code == 401


def test_wrong_api_key(client):
    response = client.get("/api/v1/metrics", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_wrong_admin_key(client):
    response = client.post(
        "/admin/refresh",
        headers={"Authorization": "Bearer wrong"},
        content=b"{}",
    )
    assert response.status_code == 401


# ------------------------------------------------------------------
# 503 when no manifest
# ------------------------------------------------------------------
def test_metrics_503_when_not_ready(client):
    response = client.get(
        "/api/v1/metrics",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert response.status_code == 503


def test_query_503_when_not_ready(client):
    response = client.post(
        "/api/v1/query",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"metrics": ["revenue"]},
    )
    assert response.status_code == 503


# ------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------
def test_list_metrics(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get(
            "/api/v1/metrics",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "revenue"
    assert data[0]["type"] == "MetricType.SIMPLE"
    assert any(d["qualified_name"] == "location__location_name" for d in data[0]["dimensions"])


# ------------------------------------------------------------------
# Query
# ------------------------------------------------------------------
def test_query(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.post(
            "/api/v1/query",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"metrics": ["revenue"], "group_by": ["location__location_name"]},
        )
    assert response.status_code == 200
    data = response.json()
    assert "sql" in data
    assert "schema_info" in data
    assert "data" in data
    assert "revenue" in data["data"]
    assert data["data"]["revenue"] == [1234.56, 789.01]


def test_query_missing_metrics(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.post(
            "/api/v1/query",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"group_by": ["location__location_name"]},
        )
    assert response.status_code == 422  # pydantic validation — metrics is required


# ------------------------------------------------------------------
# Admin refresh
# ------------------------------------------------------------------
def test_refresh_empty_body(client):
    response = client.post(
        "/admin/refresh",
        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
        content=b"",
    )
    assert response.status_code == 400


def test_refresh_invalid_json(client):
    response = client.post(
        "/admin/refresh",
        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
        content=b"not-valid-json",
    )
    assert response.status_code == 400


# ------------------------------------------------------------------
# Query error handling
# ------------------------------------------------------------------
def test_query_invalid_query_exception_returns_400(client, mock_engine):
    from metricflow_semantics.errors.error_classes import CustomerFacingSemanticException

    mock_engine.query.side_effect = CustomerFacingSemanticException("unknown metric")
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.post(
            "/api/v1/query",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"metrics": ["does_not_exist"]},
        )
    assert response.status_code == 400


def test_query_execution_exception_returns_502(client, mock_engine):
    from metricflow_semantics.errors.error_classes import ExecutionException

    mock_engine.query.side_effect = ExecutionException("warehouse timeout")
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.post(
            "/api/v1/query",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"metrics": ["revenue"]},
        )
    assert response.status_code == 502


def test_query_unexpected_error_returns_500(client, mock_engine):
    mock_engine.query.side_effect = RuntimeError("unexpected boom")
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.post(
            "/api/v1/query",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"metrics": ["revenue"]},
        )
    assert response.status_code == 500


# ------------------------------------------------------------------
# serialize_cell
# ------------------------------------------------------------------
def test_serialize_cell_decimal():
    from metricflow_server.api.schemas import serialize_cell

    assert serialize_cell(Decimal("3.14")) == pytest.approx(3.14)


def test_serialize_cell_datetime():
    from metricflow_server.api.schemas import serialize_cell

    dt = datetime.datetime(2024, 1, 15, 12, 0, 0)
    assert serialize_cell(dt) == "2024-01-15T12:00:00"


def test_serialize_cell_date():
    from metricflow_server.api.schemas import serialize_cell

    d = datetime.date(2024, 1, 15)
    assert serialize_cell(d) == "2024-01-15"


def test_serialize_cell_none():
    from metricflow_server.api.schemas import serialize_cell

    assert serialize_cell(None) is None


# ------------------------------------------------------------------
# Config — resolve_profiles_dir with base64
# ------------------------------------------------------------------
def test_resolve_profiles_dir_b64():
    import base64
    import tempfile

    from metricflow_server.config import Settings

    content = "my_profile:\n  target: dev\n"
    b64 = base64.b64encode(content.encode()).decode()
    s = Settings(api_key="k", admin_key="a", profiles_b64=b64)
    try:
        profiles_dir = s.resolve_profiles_dir()
        assert (profiles_dir / "profiles.yml").read_text() == content
    finally:
        s.cleanup_profiles_dir()
        assert not profiles_dir.exists()
