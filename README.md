# PoC 5 — MCP HTTP Server con Auth (deployado)

Migración del Echo server (PoC 1) de transporte `stdio` a **Streamable HTTP**, con
autenticación por bearer token, empaquetado en Docker y listo para Cloud Run.

## Estructura

```
.
├── server.py       # MCP server (FastMCP) sobre Streamable HTTP + /health
├── auth.py         # middleware de bearer token (Starlette)
├── Dockerfile
├── .dockerignore
├── .env.example
├── pyproject.toml
└── .github/workflows/deploy-cloud-run.yml   # CI/CD: build + deploy a Cloud Run por PR aceptada
```

Tools expuestas: `echo(message)`, `add(a, b)`. Resource: `info://server`.
Endpoint MCP: `/mcp`. Endpoint público sin auth (health check): `/health`.

## Fase 1 — Correr local

```bash
uv venv .venv
uv pip install --python .venv -e .
cp .env.example .env
# completar AUTH_TOKEN en .env, por ejemplo:
python -c "import secrets; print(secrets.token_urlsafe(32))"

.venv/Scripts/python.exe server.py   # Windows
# .venv/bin/python server.py         # macOS/Linux
```

Registrar en Claude CLI:

```bash
claude mcp add --transport http poc5 http://localhost:8000/mcp --header "Authorization: Bearer <AUTH_TOKEN>"
claude mcp list   # debe mostrar poc5 ... Connected
```

Sin el header correcto, `/mcp` devuelve 401. `/health` responde 200 sin auth (para health checks de infraestructura).

## Fase 2 — Auth

Implementada en `auth.py` (`BearerAuthMiddleware`, Starlette `BaseHTTPMiddleware`):

- Lee `AUTH_TOKEN` de entorno (nunca hardcodeado).
- Compara con `hmac.compare_digest` (evita timing attacks).
- Sin `AUTH_TOKEN` configurado → 500 (falla cerrado, no abre el server sin querer).
- Header ausente/inválido → 401 + `WWW-Authenticate: Bearer`.
- `/health` queda exento (whitelist explícita) para health checks del orquestador.

### Gotcha: el SDK `mcp` tiene su propia protección anti DNS-rebinding

Además de nuestro `auth.py`, `FastMCP` trae activada por default una protección anti
DNS-rebinding (`mcp/server/transport_security.py`) que valida el header `Host` de cada
request contra una whitelist. **Esa whitelist viene hardcodeada por el SDK solo a
`localhost` / `127.0.0.1` / `[::1]`.** Contra cualquier otro hostname (como el de Cloud
Run), rechaza con `421 Invalid Host header` — *después* de pasar nuestro propio bearer
auth, así que solo se nota con un token válido (sin token, `auth.py` corta antes de
llegar a esa capa, y parece que todo funciona).

Se soluciona pasando el hostname público real vía la variable `MCP_ALLOWED_HOSTS`
(ver `server.py`). Importante: **el formato de la URL de Cloud Run no es siempre el
mismo** — según el proyecto/región puede ser el formato con hash
(`servicio-xxxxx-uc.a.run.app`) o el simplificado (`servicio-<numero-proyecto>.region.run.app`).
No conviene armarlo a mano/adivinarlo — el workflow de CI le pregunta a la propia API
de Cloud Run cuál es la URL real después del deploy y recién ahí setea
`MCP_ALLOWED_HOSTS` con ese valor (ver sección CI/CD abajo).

## Fase 3 — Deployment a Cloud Run

### Build local (ya probado)

```bash
docker build -t poc5-mcp-http-remote:latest .
docker run -d -p 8080:8080 -e PORT=8080 -e AUTH_TOKEN=<token> poc5-mcp-http-remote:latest
curl http://localhost:8080/health   # 200
```

### Deploy — pasos a seguir (requieren gcloud CLI + proyecto GCP)

1. **Instalar y autenticar gcloud** (no está instalado en este entorno):
   ```bash
   gcloud auth login
   gcloud config set project <TU_PROJECT_ID>
   ```

2. **Guardar el token en Secret Manager** (no como env var plana, no en la imagen):
   ```bash
   gcloud services enable secretmanager.googleapis.com run.googleapis.com artifactregistry.googleapis.com

   python -c "import secrets; print(secrets.token_urlsafe(32))" > token.txt
   gcloud secrets create poc5-auth-token --data-file=token.txt
   rm token.txt   # no dejar el token en disco
   ```

3. **Build y push de la imagen** (Artifact Registry vía Cloud Build, sin necesitar Docker local):
   ```bash
   gcloud artifacts repositories create poc-repo --repository-format=docker --location=us-central1

   gcloud builds submit --tag us-central1-docker.pkg.dev/<TU_PROJECT_ID>/poc-repo/poc5-mcp-http-remote:latest .
   ```

4. **Deploy a Cloud Run**, inyectando el secret como variable de entorno:
   ```bash
   gcloud run deploy poc5-mcp-http-remote \
     --image us-central1-docker.pkg.dev/<TU_PROJECT_ID>/poc-repo/poc5-mcp-http-remote:latest \
     --region us-central1 \
     --allow-unauthenticated \
     --set-secrets AUTH_TOKEN=poc5-auth-token:latest
   ```
   - `--allow-unauthenticated`: el endpoint queda público a nivel red (Cloud Run IAM),
     pero sigue exigiendo el bearer token propio vía `auth.py`. Es el modelo esperado
     para un MCP server remoto consumido por distintos clientes.
   - Cloud Run inyecta `$PORT` automáticamente; `server.py` ya lo respeta.
   - Cloud Run da HTTPS por defecto — no hay que gestionar TLS.

   Después del primer deploy, **preguntale a Cloud Run cuál es la URL real** y seteala
   como `MCP_ALLOWED_HOSTS` (no la armes a mano — el formato de URL varía según el
   proyecto/región, ver el gotcha de la sección anterior):
   ```bash
   URL=$(gcloud run services describe poc5-mcp-http-remote --region us-central1 --format='value(status.url)')
   HOST="${URL#https://}"

   gcloud run services update poc5-mcp-http-remote \
     --region us-central1 \
     --update-env-vars MCP_ALLOWED_HOSTS="$HOST"
   ```

5. **Registrar la URL pública en el CLI**:
   ```bash
   gcloud run services describe poc5-mcp-http-remote --region us-central1 --format='value(status.url)'

   claude mcp add --transport http poc5 https://<URL_DE_CLOUD_RUN>/mcp --header "Authorization: Bearer <AUTH_TOKEN>"
   claude mcp list   # Connected
   ```

6. **Verificar rechazo sin token** contra la URL pública:
   ```bash
   curl -i https://<URL_DE_CLOUD_RUN>/mcp   # 401
   curl -i https://<URL_DE_CLOUD_RUN>/health  # 200
   ```

## CI/CD — GitHub Actions (deploy automático por cada PR aceptada)

Workflow: [`.github/workflows/deploy-cloud-run.yml`](.github/workflows/deploy-cloud-run.yml).

Se dispara cuando una Pull Request contra `main` es **mergeada**
(`pull_request.types: closed` + guard `github.event.pull_request.merged == true` — un
cierre sin mergear no dispara nada). Hace: build de la imagen, push a Artifact Registry,
`gcloud run deploy`, le pregunta a la API cuál es la URL real del servicio y la setea
como `MCP_ALLOWED_HOSTS` (ver el gotcha de Fase 2 — el formato de URL de Cloud Run varía
según el proyecto, por eso se pide en runtime en vez de armarlo a mano), y corre tres
smoke tests contra la URL pública (`/health` → 200, `/mcp` sin token → 401, `/mcp` con
token real → 200 con handshake MCP completo).

Los pasos 2 y 3 de la sección anterior (Secret Manager + Artifact Registry repo) son
**setup único**, hacelos una sola vez a mano antes del primer merge. El pipeline asume que
ya existen.

### 1. Crear la Service Account que va a deployar desde CI

```bash
PROJECT_ID=<TU_PROJECT_ID>

gcloud iam service-accounts create poc5-deployer \
  --display-name="PoC5 GitHub Actions Deployer" \
  --project="$PROJECT_ID"

DEPLOYER_SA="poc5-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

# Roles mínimos: deployar en Cloud Run, pushear a Artifact Registry,
# actuar como la service account de runtime del servicio, y leer el secret
# al bindearlo en el deploy.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${DEPLOYER_SA}" --role="roles/run.admin"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${DEPLOYER_SA}" --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${DEPLOYER_SA}" --role="roles/iam.serviceAccountUser"
gcloud secrets add-iam-policy-binding poc5-auth-token \
  --member="serviceAccount:${DEPLOYER_SA}" --role="roles/secretmanager.secretAccessor" \
  --project="$PROJECT_ID"

# poc5-runtime es la SA con la que corre el propio servicio Cloud Run (no la de deploy).
# Solo necesita leer el secret en runtime — nada más.
gcloud iam service-accounts create poc5-runtime \
  --display-name="PoC5 Cloud Run Runtime SA" \
  --project="$PROJECT_ID"

RUNTIME_SA="poc5-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud secrets add-iam-policy-binding poc5-auth-token \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="$PROJECT_ID"
```

### 2. Generar la key JSON y copiarla a GitHub (nunca commitear el archivo)

```bash
gcloud iam service-accounts keys create poc5-deployer-key.json \
  --iam-account="${DEPLOYER_SA}"
```

Copiá el **contenido completo** del `.json` en el secreto `GCP_SA_KEY` de GitHub (paso
siguiente) y después borrá el archivo local:

```bash
rm poc5-deployer-key.json
```

### 3. Configurar los secretos del repositorio en GitHub

`Settings → Secrets and variables → Actions → New repository secret`. Todos los
parámetros del pipeline (credenciales y config) van como secreto, ninguno queda hardcodeado
en el workflow:

| Secreto | Valor |
|---|---|
| `GCP_SA_KEY` | Contenido completo del JSON generado en el paso 2 |
| `GCP_PROJECT_ID` | Tu project id de GCP |
| `GCP_REGION` | Región de Cloud Run / Artifact Registry, ej. `us-central1` |
| `GCP_SERVICE_NAME` | Nombre del servicio Cloud Run, ej. `poc5-mcp-http-remote` |
| `GCP_ARTIFACT_REPO` | Nombre del repo de Artifact Registry, ej. `poc-repo` |
| `GCP_RUNTIME_SA` | Email de la SA de runtime: `poc5-runtime@<PROJECT_ID>.iam.gserviceaccount.com` |
| `GCP_AUTH_TOKEN_SECRET_NAME` | Nombre del secret en Secret Manager, ej. `poc5-auth-token` |

### 4. Probar el pipeline

Abrí una PR contra `main`, mergeala, y mirá la tab **Actions** del repo. El job
`build-and-deploy` corre los smoke tests al final; si `/health` o el 401 de `/mcp` fallan,
el pipeline falla (no queda un deploy roto en verde).

## Seguridad — checklist

- [x] `/mcp` exige auth; sin token válido devuelve 401.
- [x] `AUTH_TOKEN` nunca en el repo ni en la imagen (`.env` gitignored; en Cloud Run vive en Secret Manager).
- [x] Comparación de token con `hmac.compare_digest` (timing-safe).
- [x] `stateless_http=True`: sin estado en memoria del proceso, apto para múltiples réplicas de Cloud Run.
- [x] HTTPS por Cloud Run (no hay transporte MCP en HTTP plano).
- [ ] Rate limiting — no implementado en esta PoC. Próximo paso: Cloud Armor o un middleware
      tipo token-bucket por IP/token si el server pasa a producción real.
- [ ] OAuth 2.1 — el bearer token estático cubre el mínimo del estándar MCP; OAuth 2.1
      completo (authorization code + PKCE, refresh tokens) queda documentado como
      evolución natural, no bloquea esta PoC.
- [ ] CI/CD usa una Service Account JSON Key (`GCP_SA_KEY`) en vez de Workload Identity
      Federation, por simplicidad de setup. Es una credencial de larga duración: rotarla
      periódicamente (`gcloud iam service-accounts keys create` + borrar la vieja con
      `gcloud iam service-accounts keys delete`) y migrar a WIF si esto pasa a ser algo
      más que una PoC.

## Diferencias vs. stdio (PoC 1-4)

| | stdio | Streamable HTTP (esta PoC) |
|---|---|---|
| Transporte | proceso local, stdin/stdout | endpoint de red, JSON-RPC sobre HTTP/SSE |
| Clientes | 1:1 | multi-cliente concurrente |
| Auth | ninguna (confía en el proceso padre) | bearer token obligatorio |
| Estado | vive en el proceso | `stateless_http=True`, sin estado entre requests |
| Deploy | "corre en mi máquina" | contenedor en Cloud Run, HTTPS, escalable |
