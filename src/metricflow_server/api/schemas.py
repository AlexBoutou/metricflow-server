from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel


# ------------------------------------------------------------------
# Requests
# ------------------------------------------------------------------
class QueryRequest(BaseModel):
    metrics: list[str]
    group_by: Optional[list[str]] = None
    where: Optional[list[str]] = None
    order_by: Optional[list[str]] = None
    limit: Optional[int] = None


# ------------------------------------------------------------------
# Responses — aligned with dbt Semantic Layer Python SDK
# ------------------------------------------------------------------
class SchemaField(BaseModel):
    name: str
    type: str


class SchemaInfo(BaseModel):
    fields: list[SchemaField]


class QueryResponse(BaseModel):
    sql: str
    schema_info: SchemaInfo
    data: dict[str, list[Any]]


class DimensionResponse(BaseModel):
    name: str
    qualified_name: str
    description: Optional[str] = None
    type: str
    label: Optional[str] = None
    queryable_time_granularities: list[str] = []


class MetricResponse(BaseModel):
    name: str
    description: Optional[str] = None
    type: str
    label: Optional[str] = None
    requires_metric_time: bool = False
    queryable_time_granularities: list[str] = []
    dimensions: list[DimensionResponse] = []


class MetricDetail(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    type: str
    dimensions: list[DimensionResponse]
    time_granularities: list[str]
    tags: Optional[list[str]] = None
    domain: Optional[str] = None
    owner: Optional[str] = None


class HealthResponse(BaseModel):
    status: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def serialize_cell(value: Any) -> Any:
    """Convert MetricFlow CellValue types to JSON-safe values."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value
