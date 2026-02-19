from __future__ import annotations

import logging

from dbt_semantic_interfaces.type_enums import DimensionType
from fastapi import APIRouter, Depends, HTTPException, Response, status
from metricflow.engine.metricflow_engine import MetricFlowQueryRequest
from metricflow_semantics.errors.error_classes import (
    CustomerFacingSemanticException,
    ExecutionException,
    MetricNotFoundError,
)

from metricflow_server.auth import verify_api_key
from metricflow_server.engine_manager import engine_manager

from .schemas import (
    DimensionResponse,
    HealthResponse,
    MetricResponse,
    QueryRequest,
    QueryResponse,
    SchemaField,
    SchemaInfo,
    serialize_cell,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


def _require_engine():
    engine = engine_manager.engine
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No manifest loaded – POST /admin/refresh first",
        )
    return engine


def _serialize_dimension(d) -> DimensionResponse:
    """Convert a MetricFlow Dimension to the SDK-compatible response."""
    granularities = []
    if d.type == DimensionType.TIME and d.type_params and d.type_params.time_granularity:
        granularities = [str(d.type_params.time_granularity)]

    return DimensionResponse(
        name=d.name,
        qualified_name=d.qualified_name,
        description=d.description,
        type=str(d.type),
        label=d.label,
        queryable_time_granularities=granularities,
    )


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse)
def health(response: Response):
    if not engine_manager.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="not_ready")
    return HealthResponse(status="ready")


# ------------------------------------------------------------------
# Query
# ------------------------------------------------------------------
@router.post("/query", response_model=QueryResponse, dependencies=[Depends(verify_api_key)])
def query(body: QueryRequest):
    engine = _require_engine()

    mf_request = MetricFlowQueryRequest.create_with_random_request_id(
        metric_names=body.metrics,
        group_by_names=body.group_by,
        where_constraints=body.where,
        order_by_names=body.order_by,
        limit=body.limit,
    )
    try:
        result = engine.query(mf_request)
    except Exception as e:
        if isinstance(e, (CustomerFacingSemanticException, MetricNotFoundError)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        # Unwrap the root cause — MetricFlow often wraps warehouse errors in ExecutionException
        cause = e.__cause__ or e.__context__ or e
        cause_type = type(cause).__name__
        cause_msg = str(cause)
        if isinstance(e, ExecutionException):
            logger.error("Warehouse execution error [%s]: %s", cause_type, cause_msg, exc_info=e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Warehouse error ({cause_type}): {cause_msg}",
            )
        logger.error("Unexpected query error [%s]: %s", cause_type, cause_msg, exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error ({cause_type}): {cause_msg}",
        )

    data_table = result.result_df

    columns = list(data_table.column_names)
    # Build column-oriented data (like pa.Table.to_pydict())
    col_data: dict[str, list] = {col: [] for col in columns}
    for row in data_table.rows:
        for i, col in enumerate(columns):
            col_data[col].append(serialize_cell(row[i]))

    # Infer types from first non-null value per column
    def _infer_type(values: list) -> str:
        for v in values:
            if v is None:
                continue
            if isinstance(v, bool):
                return "bool"
            if isinstance(v, int):
                return "int64"
            if isinstance(v, float):
                return "float64"
            return "string"
        return "string"

    schema = SchemaInfo(
        fields=[SchemaField(name=col, type=_infer_type(col_data[col])) for col in columns]
    )

    return QueryResponse(
        sql=result.sql,
        schema_info=schema,
        data=col_data,
    )


# ------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------
@router.get("/metrics", response_model=list[MetricResponse], dependencies=[Depends(verify_api_key)])
def list_metrics():
    engine = _require_engine()

    results = []
    for m in engine.list_metrics():
        dims = [_serialize_dimension(d) for d in m.dimensions]
        has_metric_time = any(d.qualified_name == "metric_time" for d in dims)

        results.append(MetricResponse(
            name=m.name,
            description=m.description,
            type=str(m.type),
            label=m.label,
            requires_metric_time=has_metric_time,
            queryable_time_granularities=[
                g
                for d in dims
                for g in d.queryable_time_granularities
                if d.qualified_name == "metric_time"
            ],
            dimensions=dims,
        ))
    return results
