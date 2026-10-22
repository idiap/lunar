<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Lunar installation and operations

Lunar serves an authenticated workspace and generic planner against one selected,
user-owned package version. A fresh installation has no domain catalog. Importing
a ZIP validates and stores it; only an explicit runtime preparation installs its
locked dependencies into an isolated worker image.

## Fresh Docker installation

Run from the Lunar repository root. Docker Engine/Compose must be available.
Use an absolute, non-symlink storage path on the same Docker host. Docker Desktop
must share that directory; a Linux host or WSL2 uses its Linux filesystem path.
The backend and Docker daemon must see the same absolute path so worker mounts
resolve correctly.

```sh
cp app/.env.example app/.env
# Edit app/.env: storage path, database password/URL, AUTH_SECRET and mail settings.
mkdir -p /absolute/path/to/lunar-platform/var/packages
python3 scripts/build_worker_image.py --tag lunar-worker:local
docker compose --env-file app/.env -f app/docker-compose.yml config
docker compose --env-file app/.env -f app/docker-compose.yml up -d --build
```

Open the configured `PUBLIC_BASE_URL` (default `http://localhost:8080`). Signup
uses the configured Resend sender and email verification. For local testing, set
`BYPASS_VERIFICATION=true` in `app/.env` and rebuild/recreate the backend. New
accounts skip email and can sign in immediately; they remain verified when the
flag is disabled. The default is `false`; existing unverified accounts are unchanged.
Model credentials are
owned by the signed-in user and encrypted in PostgreSQL; they never enter ZIPs or
worker environments. Set a persistent Fernet `ENCRYPTION_KEY` before production.
`AUTH_SECRET` and the encryption key must be backed up separately from artifacts.
Generate the Fernet key with
`.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
and put the result in `app/.env` as `ENCRYPTION_KEY`. It must be 32 bytes encoded
as URL-safe Base64, not a hexadecimal string. Keep the same key once credentials
have been saved; replacing it makes existing credentials unreadable.

The API waits for PostgreSQL, applies Alembic migrations, ensures application
tables, and reconciles interrupted imports, preparations, runs and reasoning.
There is no startup catalog seed, domain import or sibling checkout dependency.
The trusted API owns Docker lifecycle control; uploaded code receives only its
four read-only collection mounts, one run output directory and scoped callbacks.
The socket and database/provider credentials never enter package workers.

The Compose database volume and `LUNAR_PACKAGE_STORAGE_ROOT` survive ordinary
container recreation. Do not remove volumes when preserving data. After code
changes, rebuild the backend rather than restarting its old image:

```sh
docker compose --env-file app/.env -f app/docker-compose.yml up -d --build --no-deps backend
```

Runtime images are version-specific and can be prepared again if the host loses
its image cache. Preparation uses `LUNAR_WORKER_IMAGE`, never a caller-supplied
image. Dependencies may be fetched during preparation. A failed or interrupted
preparation leaves the package browsable with a visible failure state.

After changing the host-owned worker code (`domain_packages/worker/main.py` or
`prism.py`), prepare each selected package runtime again. An already-ready runtime
refreshes those two files in a new immutable image while retaining its installed
dependencies. Updating the API or the base worker tag alone does not update the
image ID pinned to a prepared package. Existing runs retain their original image.

## Package and report behavior

Import and select a ZIP using the sidebar. Repeated uploads create new versions;
failed uploads preserve the previous selection and versions. The workspace caches
by owner/version and restores a saved chat's original binding before reading it.
Switching selection creates a new conversation context; running work retains its
original owner/version. Tool-free chat needs no package.

Use Prepare runtime before execution. Modes, JSON input schemas, optional graph
assets, source bindings, model requirements and domain policies come from the
selected package. Public network reads require both explicit run authority and
`LUNAR_ALLOW_LIVE_NETWORK=1`. A worker remains offline; authorized external reads
and model calls cross bounded host callbacks.

The Run dialog renders labeled controls from the live-mode input schema (or the
workflow's default schema). It supports text, numbers, booleans, choices, nested
objects and lists, applies schema defaults, and validates before submission.
Dataset IDs are supplied by the dataset picker. The backend remains the final
validator. Frontend checks: `cd app/frontend && npm test && npm run test:ui && npm run build`.

### Package iteration CLI

The repository includes a dependency-free CLI for the same upload, preparation,
and run APIs used by the interface. Set credentials through the environment so
the password does not enter shell history:

```sh
export LUNAR_URL=http://localhost:8080
export LUNAR_EMAIL=developer@example.org
read -rs LUNAR_PASSWORD && export LUNAR_PASSWORD

python3 scripts/lunar_cli.py cycle ./dist/package.zip inventory \
  --inputs @./inputs/inventory.json
```

`cycle` uploads a new version, prepares its isolated runtime, submits the
workflow, waits for a terminal state, and prints one JSON document containing the
version, preparation, and final run. Progress goes to stderr, so stdout can be
redirected to a result file. It returns a nonzero status for a failed workflow.
Use `--no-wait` to return after submission, `--ai-model-id UUID` for a workflow
that requires a configured model, and `--network-authority` to opt into declared
public network reads when the server allows them.

The individual operations are also available for debugging or scripting:

```sh
python3 scripts/lunar_cli.py upload ./dist/package.zip
python3 scripts/lunar_cli.py prepare VERSION_UUID
python3 scripts/lunar_cli.py workflows VERSION_UUID WORKFLOW_ID
python3 scripts/lunar_cli.py run VERSION_UUID WORKFLOW_ID \
  --inputs '{"count": 41}'
```

`workflows` prints the runnable registrations, including each workflow's expected
`input_schema`. `--inputs` is intentionally required for every run and accepts an
inline JSON object, `@file.json`, or `-` for stdin. The server performs the final
schema validation. For automation, an existing cookie value can replace the
email/password exchange through `LUNAR_SESSION_TOKEN`; the default cookie name is
`report_session` and can be changed with `LUNAR_SESSION_COOKIE_NAME`.

Export ZIP takes a read-only database snapshot and verifies all required file
bytes. It includes current reports and revisions, original provenance, attachments,
section/output lineage and required historical run facts. It excludes accounts,
chats, model secrets, editable templates and unrelated runs. Importing the result
allocates new owner/version IDs; original receipts remain historical evidence.
Imported generated reports stay read-only. Manual report edits preserve history.
The Prism page also exports the currently selected workflow as a scoped evidence
ZIP containing its exact source closure, generated visualization, execution
bindings, run summaries, and stored PROV-JSON/JSON-LD documents. Each export
includes the visualization as both structured JSON and a standalone SVG.

Template placeholders occupy their own line (`{{output_key}}`) and bind to a
compatible completed output in the current version, with both provenance formats.
Template execution does not run workflows. Generated reports and sections retain
frozen template/output lineage. The API and UI expose PROV-JSON and JSON-LD;
missing original formats are reported as unavailable, never fabricated.

HTTP/MCP requests use `X-Lunar-Package-Version` or `package_version_id` in protected
links. The Home page provides the selected MCP URL. Stdio requires explicit
`LUNAR_STDIO_USER_ID` and `LUNAR_STDIO_VERSION_ID` and returns publication as
unavailable. See [selection and export contracts](backend/domain_packages/SELECTION.md)
and [worker boundary](backend/domain_packages/worker/README.md).

## Backup, restore and recovery

PostgreSQL contains resource/report content, lineage and file receipts; package
storage contains runtime trees, local datasets, attachments and run artifacts.
Back up both at one quiescent application checkpoint. A database dump alone cannot
restore required bytes. Keep authentication/encryption secrets separately and
retain the worker base/dependency lock declarations.

Run the operator script on the Docker host with permission to read/write all package
files (use `sudo` on Linux). It stops the API and only workers mounting this
installation, copies both stores, verifies a SHA-256 inventory, and resumes the
API. A failed backup retains a private `.partial` directory for inspection and
restarts the API; only the final checkpoint name denotes success.

```sh
python3 scripts/installation_backup.py backup /safe/backups/lunar-2026-09-10 --project-name lunar
```

Restore into a fresh Compose project/database and an empty package directory.
Use the same authentication/encryption secrets and worker image as the original;
set the new absolute package path in its env file. Start **only** its database first:

```sh
docker compose --env-file app/restore.env -p lunar-restored -f app/docker-compose.yml up -d --wait db
python3 scripts/installation_backup.py restore /safe/backups/lunar-2026-09-10 --project-name lunar-restored --env-file app/restore.env
```

Restore verifies all checkpoint files before changing the target, refuses existing
package files or public database tables, and starts the API only after both stores
are restored. On a restore failure the API stays stopped; inspect the failure and
retry using another fresh database and empty directory. Never mix checkpoints.
Backups include private reports, session records and encrypted model credentials;
keep their parent directory private and retain the encryption key separately.
Add `--compose-file app/docker-compose.cloud.yml` for the cloud installation.

 Imports/exports use
private workspaces with PostgreSQL session leases. Leases use the same database
as the installation and do not depend on shared-filesystem lock support. Startup cleans abandoned workspaces and reconciles
staging publication, while preserving complete ready versions. Queued/running
jobs abandoned by a stopped API become failed with partial observed provenance.
No imported historical run is resumed automatically.

## Local development and verification

The Docker app defaults to `ENVIRONMENT=production`. To enable frontend and
backend hot reload, set `ENVIRONMENT=development` in `app/.env` and
rebuild/recreate both services:

```sh
docker compose --env-file app/.env -f app/docker-compose.yml up -d --build --no-deps backend frontend
```

Open the same URL (default `http://localhost:8080`). Vite picks up changes to
`app/frontend/src`, `public`, `index.html`, and `vite.config.js` from the host and
proxies API requests to the backend container. Uvicorn reloads after changes to
`app/backend`, including its `lunar_planner` module. Rebuild after changing dependencies. Set
`ENVIRONMENT=production` and run the same command to return to the built app.

```sh
uv sync --locked --group mcp-backend
npm --prefix app/frontend ci
uv run --group mcp-backend playwright install chromium
uv run --group mcp-backend pytest
npm --prefix app/frontend test
npm --prefix app/frontend run build
uv run --group mcp-backend pytest --run-expensive tests/planner tests/mcp_backend
uv run --group mcp-backend python planner/testing/verify_module.py
uv run --group mcp-backend pytest app/frontend/tests
```

For local API development, set `DATABASE_URL`, `LUNAR_PACKAGE_STORAGE_ROOT` and
`LUNAR_WORKER_IMAGE`, run migrations from `app/backend`, then start
`uvicorn server:app --host 127.0.0.1 --port 8000` with that directory on
`PYTHONPATH`. `npm --prefix app/frontend run dev` proxies to port 8000; override
`VITE_API_PROXY_TARGET` only for a different local API endpoint.

L2 requires `LUNAR_TEST_DATABASE_URL` pointing to a dedicated test database. E0/E1
require `LUNAR_E2E_DATABASE_URL` ending in `_e2e_test`; fixtures reset its public
schema. Never use a normal application database. E0 also requires a built
`LUNAR_WORKER_IMAGE`, an actual authoring ZIP in `LUNAR_E2E_BIOAGENTS_ZIP`, and an
actual report-inclusive source export in `LUNAR_E2E_BIOAGENTS_REPORT_ZIP`.

```sh
uv run --group mcp-backend pytest app/backend/tests  # with LUNAR_TEST_DATABASE_URL
uv run --group mcp-backend pytest --run-e2e tests/e2e
uv run --group mcp-backend pytest --run-e2e --run-prism-llm-e2e tests/e2e/test_prism_llm_workflows.py
```

E1 requires `LUNAR_E2E_MODEL_PROVIDER`, `LUNAR_E2E_MODEL_ID`, and
`LUNAR_E2E_MODEL_API_KEY`; optional settings are `LUNAR_E2E_MODEL_API_BASE`,
`LUNAR_E2E_MODEL_API_VERSION`, and JSON `LUNAR_E2E_MODEL_CONFIG`. Configure secrets
in the invoking environment or CI secret store. Missing prerequisites fail the
required gate; deterministic E0 provider fixtures are not genuine-provider proof.
For Azure, `LUNAR_E2E_MODEL_API_BASE` is the resource base URL used by the
chat-completions adapter, not a complete `/openai/v1/responses` request URL.
Use the E2E key and API version belonging to that same resource.

BioAgents ZIPs are produced by its retained `scripts/repository/export_domain_package.py`
CLI, with explicit catalog/data roots and, for reports, a read-only PostgreSQL
source connection, one source owner and an artifact root. Transfer the ZIP only;
Lunar never accesses that checkout, source database, or source artifact directory.

## Azure template validation

The fresh-install Azure template uses a Linux VM with Docker and persistent disk
storage. Azure Container Instances cannot expose the Docker API required by the
worker boundary. This is a new deployment design, not a migration of an existing
cloud state. Validation and local container evidence do not establish a cloud
deployment; no automatic Terraform apply is part of the verification pipeline.

```sh
terraform -chdir=app/infra init -backend=false
terraform -chdir=app/infra validate
```

## CI runner contract

`.gitlab-ci.yml` runs L0–L5, image/template checks, E0 and the required E1 gate.
Use a dedicated Linux **shell** runner tagged `lunar-docker-host` with Python 3.13,
uv, Node/npm, Docker/Compose, Terraform and Playwright OS libraries installed.
Its Docker daemon must see the runner's absolute checkout and temporary paths.
Configure dedicated L2/E0 test database URLs, the two exported ZIP paths as supplied
CI inputs, and genuine-provider E1 credentials in protected CI variables. ZIPs
are inputs to Lunar CI; no domain repository is checked out by its jobs. The E2E
resource group serializes schema resets. E1 is required and fails when credentials
are absent. There is no implicit deployment, registry push or Terraform apply job.

## Independent portability verification

Build the ordinary backend/frontend and worker images first, then the test-only
image from this checkout:

```sh
docker build -f scripts/verification.Dockerfile -t lunar-verification:local .
python3 scripts/verify_independent.py --output /tmp/lunar-portability-evidence
```

The runner needs `LUNAR_TEST_DATABASE_URL`, `LUNAR_E2E_DATABASE_URL`,
`LUNAR_WORKER_IMAGE`, and the two ZIP input variables described above. The database
URLs must be reachable **inside Docker**. Set `LUNAR_VERIFICATION_NETWORK` when the
databases live on a private Docker network. Use dedicated disposable databases;
the suites reset their schemas. The runner mounts only a fresh shared input/output
directory and the Docker socket. It copies the ZIPs, records their SHA-256 digests
and the verification image ID, and runs L0–L5/E0 without mounting any checkout or
passing model credentials. Per-gate logs and a result manifest remain in the output
directory. `--gate L0`, `--gate L2` or `--gate E0` can repeat an affected gate.

This offline runner does not satisfy E1. Run the separately configured genuine
provider suite for all 13 scientific workflows; its E0 provider fixtures and 73
package-runtime domain assertions remain separate evidence. Missing or skipped
required E1 cases keep the removal/cutover gate incomplete.
