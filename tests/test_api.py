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
    metric.tags = None
    metric.domain = None
    metric.owner = None
    metric.config = MagicMock(meta={
        "tags": ["finance"],
        "domain": "sales",
        "owner": "analytics-team",
    })
    dim = MagicMock()
    dim.name = "location_name"
    dim.qualified_name = "location__location_name"
    dim.description = None
    dim.label = None
    from dbt_semantic_interfaces.type_enums import DimensionType
    dim.type = DimensionType.CATEGORICAL
    dim.type_params = None
    time_dim = MagicMock()
    time_dim.name = "metric_time"
    time_dim.qualified_name = "metric_time"
    time_dim.description = "Time of the metric"
    time_dim.label = "Metric time"
    time_dim.type = DimensionType.TIME
    time_dim.type_params = MagicMock(time_granularity="DAY")
    metric.dimensions = [dim, time_dim]
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


def test_list_metrics_still_works_alongside_metric_detail(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        list_response = client.get(
            "/api/v1/metrics",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        detail_response = client.get(
            "/api/v1/metrics/revenue",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    assert list_response.status_code == 200
    assert isinstance(list_response.json(), list)
    assert list_response.json()[0]["name"] == "revenue"
    assert detail_response.status_code == 200


def test_get_metric_detail_with_complete_metadata(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get(
            "/api/v1/metrics/revenue",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "name": "revenue",
        "label": None,
        "description": "Sum of revenue",
        "type": "MetricType.SIMPLE",
        "dimensions": [
            {
                "name": "location_name",
                "qualified_name": "location__location_name",
                "description": None,
                "type": "DimensionType.CATEGORICAL",
                "label": None,
                "queryable_time_granularities": [],
            },
            {
                "name": "metric_time",
                "qualified_name": "metric_time",
                "description": "Time of the metric",
                "type": "DimensionType.TIME",
                "label": "Metric time",
                "queryable_time_granularities": ["DAY"],
            },
        ],
        "time_granularities": ["DAY"],
        "tags": ["finance"],
        "domain": "sales",
        "owner": "analytics-team",
    }


def test_get_metric_detail_with_partial_metadata(client, mock_engine):
    metric = mock_engine.list_metrics.return_value[0]
    metric.config = MagicMock(meta={})

    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get(
            "/api/v1/metrics/revenue",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    assert response.status_code == 200
    assert response.json()["tags"] is None
    assert response.json()["domain"] is None
    assert response.json()["owner"] is None


def test_get_metric_detail_ignores_malformed_optional_metadata(client, mock_engine):
    metric = mock_engine.list_metrics.return_value[0]
    metric.tags = {"finance": True}
    metric.domain = ["sales"]
    metric.owner = 123

    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get(
            "/api/v1/metrics/revenue",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    assert response.status_code == 200
    assert response.json()["tags"] is None
    assert response.json()["domain"] is None
    assert response.json()["owner"] is None


def test_get_unknown_metric_detail_returns_stable_404(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get(
            "/api/v1/metrics/unknown",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Metric 'unknown' not found"}


def test_get_metric_detail_requires_api_key(client):
    response = client.get("/api/v1/metrics/revenue")

    assert response.status_code == 401


def test_get_metric_detail_rejects_invalid_api_key(client):
    response = client.get(
        "/api/v1/metrics/revenue",
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401


def test_get_metric_detail_serializes_dimensions_and_time_granularities(client, mock_engine):
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get(
            "/api/v1/metrics/revenue",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    detail = response.json()
    time_dimension = next(d for d in detail["dimensions"] if d["qualified_name"] == "metric_time")
    assert time_dimension["type"] == "DimensionType.TIME"
    assert time_dimension["queryable_time_granularities"] == ["DAY"]
    assert detail["time_granularities"] == ["DAY"]


def test_unknown_metric_404_does_not_leak_internal_exceptions(client, mock_engine):
    mock_engine.list_metrics.return_value = []
    with patch("metricflow_server.engine_manager.engine_manager._engine", mock_engine):
        response = client.get(
            "/api/v1/metrics/unknown",
            headers={"Authorization": f"Bearer {API_KEY}"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Metric 'unknown' not found"}
    assert "RuntimeError" not in response.text
    assert "warehouse secret" not in response.text


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
