"""PoC 5 — MCP Echo server migrado de stdio a Streamable HTTP, con auth por bearer token.

Base: el Echo server de la PoC 1. Mismo comportamiento, transporte remoto.
"""

import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from auth import BearerAuthMiddleware

load_dotenv()

# stateless_http=True: cada request es independiente, sin sesión en memoria del proceso.
# Necesario para correr en Cloud Run, que puede escalar a múltiples instancias/réplicas.
mcp = FastMCP("poc5-echo-http", stateless_http=True)


@mcp.tool()
def echo(message: str) -> str:
    """Devuelve el mismo mensaje recibido."""
    return message


@mcp.tool()
def add(a: int, b: int) -> int:
    """Suma dos números enteros."""
    return a + b


@mcp.resource("info://server")
def server_info() -> str:
    """Información básica de este server MCP."""
    return "PoC 5 - MCP HTTP Server con Auth (Streamable HTTP + bearer token)"


async def health(request):
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app()
app.add_route("/health", health)
app.add_middleware(BearerAuthMiddleware)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
