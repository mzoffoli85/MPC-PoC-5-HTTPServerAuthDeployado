# PoC 5 — MCP HTTP Server con Auth (deployado)

> Inicializador para Claude Code. Quinta y última PoC de la serie "Aprender MCP en profundidad".
> Objetivo: migrar de stdio a **transporte remoto (HTTP streamable)** con **autenticación**, y dejarlo deployado.

---

## Contexto para Claude Code

Soy Marco. Terminé las PoC 1-4: Tools, Resources, Prompts (primitivos del server) y Sampling (primitivo del client). Todas sobre transporte **stdio local**. Manejo la arquitectura MCP completa. Tengo GCP con certificación.

**Cliente de prueba: Claude CLI (Claude Code), NO Claude Desktop.** Registro de servers vía `claude mcp add`, no vía `claude_desktop_config.json`.

**No expliques teoría de MCP a menos que la pida.** Esta PoC es sobre transporte remoto, auth y deployment.

---

## Objetivo de esta PoC

Tomar un server de una PoC anterior (sugerido: el Resource Provider de la PoC 2, o el Echo de la PoC 1 por simplicidad) y **migrarlo de stdio a HTTP remoto**, agregándole **autenticación**, para consumirlo desde el CLI como server remoto — y dejarlo deployado en un host accesible.

### Lo que cambia respecto a todo lo anterior

- **Transporte**: de `stdio` (proceso local) a **Streamable HTTP** (endpoint de red).
- **Multi-cliente**: un server HTTP puede atender varios clientes; stdio es 1:1.
- **Auth**: sin auth, un endpoint remoto es un agujero. Entra OAuth 2.1 / bearer tokens.
- **Deployment**: de "corre en mi máquina" a "corre en un host y se accede por URL".

### Puntos de aprendizaje que cubre
- Transporte **Streamable HTTP** (y contexto del deprecado HTTP+SSE)
- Diferencia stdio vs remoto: sesión, concurrencia, estado
- **Autenticación**: bearer token como mínimo; OAuth 2.1 como estándar MCP
- Deployment real: contenedor, host, variables de entorno, HTTPS
- Consideraciones de **seguridad** de un endpoint MCP expuesto

---

## Stack

- **Python 3.11+**
- SDK oficial `mcp` (soporte de Streamable HTTP)
- Framework ASGI: **Starlette / FastAPI** + **uvicorn** (el SDK expone una app ASGI)
- Auth: bearer token vía middleware (mínimo); dejar OAuth 2.1 documentado como siguiente paso
- Deployment: **Google Cloud Run** (tenés GCP) — contenedor sin gestión de servidor, HTTPS gratis
- Contenerización: Docker
- `uv`

---

## Estructura del proyecto

​```
poc5-mcp-http-remote/
├── README.md
├── pyproject.toml
├── server.py               # el MCP server sobre Streamable HTTP
├── auth.py                 # middleware de autenticación (bearer)
├── Dockerfile
├── .dockerignore
├── .env.example            # AUTH_TOKEN, y config heredada de la PoC base
├── .gitignore              # secrets, .env, credentials
​```

---

## Requisitos de implementación

### Fase 1 — Migración a HTTP (local)
1. Tomar el server base (PoC 1 o 2) y reconfigurar el transporte a **Streamable HTTP**.
2. Exponer la app ASGI con uvicorn. El endpoint MCP típicamente en `/mcp`.
3. Probar localmente con el CLI:
   `claude mcp add --transport http poc5 http://localhost:8000/mcp`
4. Confirmar que las tools/resources responden igual que en stdio.

### Fase 2 — Autenticación
5. `auth.py`: middleware que exige un **bearer token** en el header `Authorization`. Rechaza (401) si falta o no coincide.
6. El token se lee de `.env` (`AUTH_TOKEN`). **Nunca hardcodeado.**
7. Registrar en el CLI pasando el header:
   `claude mcp add --transport http poc5 https://<url>/mcp --header "Authorization: Bearer <token>"`
8. Verificar que sin token correcto, el server rechaza.

### Fase 3 — Deployment (Cloud Run)
9. `Dockerfile`: imagen mínima de Python, instala deps, corre uvicorn. Puerto vía `$PORT` (Cloud Run lo inyecta).
10. Build y deploy a Cloud Run. El `AUTH_TOKEN` como variable de entorno / secret del servicio (Secret Manager, no en la imagen).
11. Cloud Run da HTTPS out-of-the-box — no montar TLS a mano.
12. Registrar la URL pública en el CLI y probar el flujo end-to-end remoto.

---

## Seguridad (revisar y documentar)

- [ ] El endpoint **exige auth** — sin token válido, 401.
- [ ] El `AUTH_TOKEN` vive en Secret Manager / env var, **nunca en el repo ni en la imagen Docker**.
- [ ] **Validación de inputs**: mismo cuidado que en stdio; un endpoint público recibe tráfico no confiable.
- [ ] HTTPS siempre (Cloud Run lo cubre). Nunca MCP remoto sobre HTTP plano.
- [ ] Considerar rate limiting (documentar como mejora, no bloquea la PoC).
- [ ] `.dockerignore`