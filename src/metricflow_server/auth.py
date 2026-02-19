import hmac

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from metricflow_server.config import settings

_bearer = HTTPBearer()


def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    if not hmac.compare_digest(credentials.credentials, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return credentials.credentials


def verify_admin_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    if not hmac.compare_digest(credentials.credentials, settings.admin_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key",
        )
    return credentials.credentials
