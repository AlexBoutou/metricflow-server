from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from metricflow_server.auth import verify_admin_key
from metricflow_server.engine_manager import engine_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


@router.post("/refresh", dependencies=[Depends(verify_admin_key)])
async def refresh_manifest(request: Request):
    body = await request.body()
    content = body.decode()
    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty body — send the semantic_manifest.json via --data-binary @file.json",
        )
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON: {e}",
        )
    try:
        engine_manager.load_manifest(content)
    except ValueError as e:
        # MetricFlow rejected the manifest content (e.g. missing required fields).
        logger.warning("Invalid manifest rejected: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid manifest: {e}",
        )
    except Exception as e:
        # Unexpected server-side failure while parsing or building the engine.
        logger.error("Failed to load manifest", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error while loading manifest",
        )
    return {"status": "ok"}
