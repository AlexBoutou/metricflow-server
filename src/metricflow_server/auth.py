import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from metricflow_server.config import settings

_bearer = HTTPBearer()


def _check_bearer(token: str, expected: str) -> bool:
    return bool(token) and hmac.compare_digest(token, expected)


def check_api_key(token: str) -> bool:
    return _check_bearer(token, settings.api_key)


def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    if not _check_bearer(credentials.credentials, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return credentials.credentials


def verify_admin_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    if not _check_bearer(credentials.credentials, settings.admin_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key",
        )
    return credentials.credentials
