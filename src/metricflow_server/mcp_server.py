"""MCP server for MetricFlow — exposes metric discovery and querying as tools.

Mounted at /mcp inside the FastAPI app (Streamable HTTP transport).
Tools use engine_manager directly — no internal HTTP round-trip.
"""
from __future__ import annotations

import json
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from mcp.server.fastmcp import FastMCP
from metricflow.engine.metricflow_engine import MetricFlowQueryRequest
from metricflow_semantics.errors.error_classes import (
    CustomerFacingSemanticException,
    MetricNotFoundError,
)

from metricflow_server.api.routes import _serialize_dimension
from metricflow_server.api.schemas import serialize_cell
from metricflow_server.auth import check_api_key
from metricflow_server.engine_manager import engine_manager

logger = logging.getLogger(__name__)

_mcp = FastMCP("metricflow", streamable_http_path="/")
_bearer = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------
# Auth middleware
# ------------------------------------------------------------------
class _AuthMiddleware:
    """ASGI middleware that guards the MCP endpoint with MF_API_KEY."""

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            credentials = await _bearer(Request(scope, receive))
            if credentials is None or not check_api_key(credentials.credentials):
                await JSONResponse({"detail": "Unauthorized"}, status_code=403)(scope, receive, send)
                return
        await self._app(scope, receive, send)


# Build the Starlette app and wrap it with auth
_mcp_starlette = _mcp.streamable_http_app()
mcp_app = _AuthMiddleware(_mcp_starlette)
mcp_session_manager = _mcp._session_manager


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _require_engine():
    engine = engine_manager.engine
    if engine is None:
        raise RuntimeError("No manifest loaded – POST /admin/refresh first")
    return engine


# ------------------------------------------------------------------
# Tools
# ------------------------------------------------------------------
@_mcp.tool()
def list_metrics() -> str:
    """List all available metrics with their descriptions, types and queryable dimensions.

    Returns a compact JSON array. Each metric includes dimension qualified_names
    only (use get_dimension_values to explore values).
    """
    engine = _require_engine()

    metrics = []
    for m in engine.list_metrics():
        dims = [_serialize_dimension(d) for d in m.dimensions]
        metrics.append({
            "name": m.name,
            "description": m.description,
            "type": str(m.type),
            "dimensions": [
                d.qualified_name
                for d in dims
                if d.qualified_name != "metric_time"
            ],
        })

    return json.dumps(metrics)


@_mcp.tool()
def get_dimension_values(
    metrics: list[str],
    dimension: str,
    limit: int = 100,
) -> str:
    """Get possible values for a dimension by querying the semantic layer.

    Returns a JSON array of values (strings/numbers).

    Args:
        metrics: Metric names that the dimension belongs to (e.g. ["revenue"]).
        dimension: Qualified dimension name (e.g. "location__country").
        limit: Maximum number of values to return (default 100).
    """
    engine = _require_engine()

    mf_request = MetricFlowQueryRequest.create_with_random_request_id(
        metric_names=metrics,
        group_by_names=[dimension],
        order_by_names=[dimension],
        limit=limit,
    )
    try:
        result = engine.query(mf_request)
    except (CustomerFacingSemanticException, MetricNotFoundError) as e:
        raise ValueError(str(e)) from e

    data_table = result.result_df
    columns = list(data_table.column_names)

    if dimension not in columns:
        raise ValueError(f"Dimension '{dimension}' not found in query results.")

    dim_idx = columns.index(dimension)
    values = [
        serialize_cell(row[dim_idx])
        for row in data_table.rows
        if row[dim_idx] is not None
    ]

    return json.dumps(values)


@_mcp.tool()
def query_metrics(
    metrics: list[str],
    group_by: list[str] | None = None,
    where: list[str] | None = None,
    order_by: list[str] | None = None,
    limit: int | None = None,
) -> str:
    """Execute a MetricFlow query and return results as structured JSON.

    Returns {"sql": "...", "rows": [{"col": value, ...}, ...]}.

    Args:
        metrics: List of metric names to query (e.g. ["revenue", "order_count"]).
        group_by: Dimensions to group by using qualified names
                  (e.g. ["metric_time", "location__country"]).
        where: Jinja filter templates
               (e.g. ["{{ Dimension('order__status') }} = 'completed'"]).
        order_by: Fields to order by; prefix with '-' for descending
                  (e.g. ["metric_time", "-revenue"]).
        limit: Maximum number of rows to return.
    """
    engine = _require_engine()

    mf_request = MetricFlowQueryRequest.create_with_random_request_id(
        metric_names=metrics,
        group_by_names=group_by,
        where_constraints=where,
        order_by_names=order_by,
        limit=limit,
    )
    try:
        result = engine.query(mf_request)
    except (CustomerFacingSemanticException, MetricNotFoundError) as e:
        raise ValueError(str(e)) from e

    data_table = result.result_df
    columns = list(data_table.column_names)

    rows = [
        {col: serialize_cell(row[i]) for i, col in enumerate(columns)}
        for row in data_table.rows
    ]

    return json.dumps({"sql": result.sql, "rows": rows})
