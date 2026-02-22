# metricflow-server

**Self-host dbt's MetricFlow semantic layer as a REST API.**

No dbt Cloud contract needed. Push your `semantic_manifest.json`, query metrics from anywhere.

---

## Why?

MetricFlow is great — consistent metric definitions, DRY logic, governed by your dbt project. But the hosted semantic layer requires dbt Cloud Enterprise. This project gives you the same query interface, self-hosted, for free.

The API is intentionally designed to be a drop-in for the [dbt Semantic Layer Python SDK](https://github.com/dbt-labs/semantic-layer-sdk-python): same query parameters, same response shape. If you've built something against the SDK, it should work here with minimal changes.

It's also a solid foundation for AI applications. Expose `/api/v1/metrics` to an LLM agent so it can discover what metrics exist, then let it call `/api/v1/query` to answer questions from your data — all within the guardrails of your semantic layer.

```
POST /admin/refresh   →  load your semantic_manifest.json
GET  /api/v1/metrics  →  browse available metrics
POST /api/v1/query    →  run metric queries against your warehouse
```

---

## How it works

```
POST /admin/refresh (semantic_manifest.json) ──► MetricFlowEngine
                                                        │
GET  /api/v1/metrics                                    │
POST /api/v1/query ────────────────────────────────────►│
                                                        ▼
                                               AdapterBackedSqlClient
                                                   (dbt adapter)
                                                        │
                                                  Data Warehouse
```

The server starts without a manifest and becomes ready once you POST one. This fits naturally into your dbt CI/CD: run `dbt build`, then push the manifest to the server.

---

## Quickstart (local)

**Requirements:** Python 3.11–3.12, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/AlexBoutou/metricflow-server
cd metricflow-server

# Install with your warehouse adapter
uv sync --extra bigquery
# or: uv sync --extra redshift
# or: uv sync --extra snowflake

# Configure
cp .env.example .env
# Edit .env — set MF_API_KEY, MF_ADMIN_KEY, MF_DBT_PROFILE_NAME

# Run
uv run metricflow-server
```

Then push your manifest:

```bash
curl -X POST http://localhost:8080/admin/refresh \
  -H "Authorization: Bearer $MF_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @target/semantic_manifest.json
```

---

## Production (Docker)

**Option 1 — Pull from GHCR (recommended)**

Pre-built images are published to GitHub Container Registry:

```bash
docker pull ghcr.io/alexboutou/metricflow-server:bigquery-latest
# or
docker pull ghcr.io/alexboutou/metricflow-server:redshift-latest
# or
docker pull ghcr.io/alexboutou/metricflow-server:snowflake-latest

docker run -p 8080:8080 \
  -e MF_API_KEY=your-api-key \
  -e MF_ADMIN_KEY=your-admin-key \
  -e MF_DBT_PROFILE_NAME=your-profile-name \
  -e MF_PROFILES_B64=$(base64 -i profiles.yml | tr -d '\n') \
  ghcr.io/alexboutou/metricflow-server:bigquery-latest
```

Versioned tags are also available (e.g. `bigquery-0.1.0`).

**Option 2 — Build from source**

```bash
docker build --build-arg ADAPTER=bigquery -t metricflow-server .
# or
docker build --build-arg ADAPTER=redshift -t metricflow-server .
# or
docker build --build-arg ADAPTER=snowflake -t metricflow-server .

docker run -p 8080:8080 \
  -e MF_API_KEY=your-api-key \
  -e MF_ADMIN_KEY=your-admin-key \
  -e MF_DBT_PROFILE_NAME=your-profile-name \
  -e MF_PROFILES_B64=$(base64 -i profiles.yml | tr -d '\n') \
  metricflow-server
```

### Preparing your profiles.yml

Rather than mounting a file into the container, pass your `profiles.yml` as a base64 string via `MF_PROFILES_B64` — works with Docker, ECS task definitions, Kubernetes secrets, and GitHub Actions.

**Important:** do not use a `keyfile` path in your profiles.yml — that file won't exist inside the container. Instead, use `method: service-account-json` and embed the credentials directly under `keyfile_json`. The fields map 1:1 to your downloaded service account JSON.

**BigQuery example** (`profiles.yml`):

```yaml
my_profile:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: service-account-json
      project: your-gcp-project
      dataset: your_dataset
      location: EU
      threads: 1
      timeout_seconds: 300
      keyfile_json:
        type: service_account
        project_id: your-gcp-project
        private_key_id: "abc123"
        private_key: "-----BEGIN RSA PRIVATE KEY-----\nMII...\n-----END RSA PRIVATE KEY-----\n"
        client_email: "your-sa@your-gcp-project.iam.gserviceaccount.com"
        client_id: "123456789"
        auth_uri: "https://accounts.google.com/o/oauth2/auth"
        token_uri: "https://oauth2.googleapis.com/token"
```

Then encode it and pass it as an env var:

```bash
export MF_PROFILES_B64=$(base64 -i profiles.yml | tr -d '\n')

docker run -p 8080:8080 \
  -e MF_API_KEY=your-api-key \
  -e MF_ADMIN_KEY=your-admin-key \
  -e MF_DBT_PROFILE_NAME=my_profile \
  -e MF_PROFILES_B64=$MF_PROFILES_B64 \
  metricflow-server
```

> The profile name in `MF_DBT_PROFILE_NAME` must match the top-level key in your `profiles.yml` (here `my_profile`).

---

## CI/CD — manifest refresh

Integrate into your dbt pipeline so the server stays in sync automatically:

```bash
# After dbt parse / dbt build
curl -X POST https://your-server/admin/refresh \
  -H "Authorization: Bearer $MF_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @target/semantic_manifest.json
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MF_API_KEY` | yes | — | API key for `/api/v1/*` endpoints |
| `MF_ADMIN_KEY` | yes | — | API key for `/admin/*` endpoints |
| `MF_DBT_PROFILE_NAME` | yes | `metricflow_server` | Profile name in your `profiles.yml` |
| `MF_PROFILES_B64` | * | — | Base64-encoded `profiles.yml` (recommended for prod/CI) |
| `MF_DBT_PROFILES_DIR` | * | `/app/.dbt` | Path to directory containing `profiles.yml` (local dev) |
| `MF_HOST` | no | `0.0.0.0` | Server host |
| `MF_PORT` | no | `8080` | Server port |
| `MF_LOG_LEVEL` | no | `info` | Log level |

*One of `MF_PROFILES_B64` or `MF_DBT_PROFILES_DIR` must be set.

---

## API reference

All `/api/v1/*` endpoints require `Authorization: Bearer <MF_API_KEY>`.

### `GET /api/v1/health`

No auth required. Returns `{ "status": "ready" }` once a manifest has been loaded.

---

### `GET /api/v1/metrics`

List all metrics with their compatible dimensions.

```bash
curl http://localhost:8080/api/v1/metrics \
  -H "Authorization: Bearer $MF_API_KEY"
```

```json
[
  {
    "name": "revenue",
    "description": "Sum of product revenue",
    "type": "MetricType.SIMPLE",
    "label": null,
    "requires_metric_time": true,
    "queryable_time_granularities": ["DAY"],
    "dimensions": [
      {
        "name": "location_name",
        "qualified_name": "location__location_name",
        "description": null,
        "type": "DimensionType.CATEGORICAL",
        "label": null,
        "queryable_time_granularities": []
      }
    ]
  }
]
```

---

### `POST /api/v1/query`

Run a metric query. The request parameters are intentionally identical to those of the [dbt Semantic Layer Python SDK](https://github.com/dbt-labs/semantic-layer-sdk-python) — `metrics`, `group_by`, `where`, `order_by`, `limit` — so the API feels familiar if you've used the SDK before, and makes it straightforward to wrap with an LLM tool call.

**Request body**

| Field | Type | Required | Description |
|---|---|---|---|
| `metrics` | `list[str]` | yes | Metric names to query |
| `group_by` | `list[str]` | no | Dimension names to group by |
| `where` | `list[str]` | no | SQL where clauses |
| `order_by` | `str` | no | Fields to order by. Prefix with `-` for descending |
| `limit` | `int` | no | Max number of rows |

```bash
curl -X POST http://localhost:8080/api/v1/query \
  -H "Authorization: Bearer $MF_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "metrics": ["revenue"],
    "group_by": ["metric_time", "location__location_name"],
    "order_by": ["-metric_time"],
    "limit": 100
  }'
```

**Response** — column-oriented, compatible with `pyarrow.Table.from_pydict()`

```json
{
  "sql": "SELECT ...",
  "schema_info": {
    "fields": [
      { "name": "metric_time", "type": "string" },
      { "name": "location__location_name", "type": "string" },
      { "name": "revenue", "type": "float64" }
    ]
  },
  "data": {
    "metric_time": ["2024-01-01", "2024-01-02"],
    "location__location_name": ["Paris", "Lyon"],
    "revenue": [12345.67, 8901.23]
  }
}
```

Reconstruct a PyArrow table client-side:

```python
import pyarrow as pa
pa.Table.from_pydict(response["data"])
```

---

### `POST /admin/refresh`

Requires `Authorization: Bearer <MF_ADMIN_KEY>`.

Loads or hot-reloads the semantic manifest. The server stays up during the reload — zero downtime.

```bash
curl -X POST http://localhost:8080/admin/refresh \
  -H "Authorization: Bearer $MF_ADMIN_KEY" \
  --data-binary @target/semantic_manifest.json
```

```json
{ "status": "ok" }
```

---

## Supported adapters

| Adapter | Extra |
|---|---|
| BigQuery | `bigquery` |
| Redshift | `redshift` |
| Snowflake | `snowflake` |
