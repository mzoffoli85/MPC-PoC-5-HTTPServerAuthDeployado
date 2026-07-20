"""Middleware de autenticación por bearer token para el endpoint MCP.

El token vive en la variable de entorno AUTH_TOKEN (nunca hardcodeado).
Compara con hmac.compare_digest para evitar timing attacks.
"""

import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Rutas que no requieren token (health check de Cloud Run / load balancer).
PUBLIC_PATHS = {"/health"}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        expected_token = os.environ.get("AUTH_TOKEN")
        if not expected_token:
            return JSONResponse(
                {"error": "server_misconfigured", "detail": "AUTH_TOKEN no está configurado"},
                status_code=500,
            )

        auth_header = request.headers.get("authorization", "")
        scheme, _, presented_token = auth_header.partition(" ")

        if scheme.lower() != "bearer" or not hmac.compare_digest(presented_token, expected_token):
            return JSONResponse(
                {"error": "unauthorized", "detail": "Falta o es inválido el bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
