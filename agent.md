# Commerce Studio Agent Rules

## Project Positioning

This repository is a Flask 2.x based B2B administration system for AI ecommerce image and video generation. Pear Admin provides the login, RBAC, menu, department, role, user, audit log and Layui shell. The `applications/studio` package owns the product and generation domain.

Infinite Canvas is intentionally not part of this implementation.

## Runtime Stack

- Python 3.11 for local development; keep CentOS deployment compatible with the selected Python runtime.
- Flask 2.0.2
- Flask-SQLAlchemy 2.5.1
- SQLAlchemy 1.4.x
- MySQL with PyMySQL in local development, testing and production
- `requests.Session` for upstream API calls
- Flask-APScheduler for asynchronous task polling
- Layui and the existing Pear Admin shell for the UI

The application is MySQL-only. There is no SQLite fallback, local SQLite file,
or `STUDIO_USE_SQLITE` switch. Use a separate MySQL schema for tests.

## Module Boundaries

```text
applications/
  models/             SQLAlchemy entities, one model per business boundary
  studio/             provider client, prompt composition, request builder, jobs
  view/studio/        authenticated HTTP routes and JSON endpoints
  common/             legacy Pear helpers and RBAC compatibility
templates/studio/     page templates
static/studio/        shared studio UI styles and browser helpers
```

Keep these boundaries stable. Do not put provider HTTP calls in route functions and do not put HTML concerns in service modules.

## Function Responsibilities

- `request_builder.build_request_body`: transform model field definitions and runtime values into the final JSON body.
- `product_prompt.compose_prompt`: combine product facts, Product Profile, Product Memory, rules and the user's creative request.
- `product_prompt.product_reference_urls`: collect enabled product assets and one-off reference URLs.
- `provider_client.ProviderClient`: perform authenticated provider requests, timeout handling and retry handling.
- `generation_service.create_generation`: validate inputs, create the seven-digit internal task code, submit the upstream task and persist the request snapshot.
- `generation_service.poll_task`: query one upstream task, normalize status, progress, output URL and errors.
- `generation_service.poll_processing_tasks`: bounded scheduler job for active tasks.
- `bootstrap.initialize_studio`: create tables and seed the administrator, RBAC menu, ToAPIs provider and starter model definitions.

## Provider and Model Rules

Provider configuration and model configuration must remain separate.

Provider fields:

- base URL
- API key
- authentication header and prefix
- balance path
- token balance path
- timeout
- default generation and result paths

Model fields:

- image or video type
- upstream model code
- generation path
- result path
- arbitrary request field definitions

Each request field definition contains:

- `field`: body key sent upstream
- `runtime_key`: optional key bound to a creation form value
- `value`: default value
- `value_type`: `string`, `number`, `boolean` or `json`
- `enabled`
- optional label and hint

Empty strings, `None`, empty arrays and empty objects must not be sent upstream. Never hard-code a model's complete request body inside a route.

## ToAPIs Defaults

The seeded provider uses `https://toapis.com`.

- Image submit: `/v1/images/generations`
- Video submit: `/v1/videos/generations`
- Image result: `/v1/images/generations/{task_id}`
- Video result: `/v1/videos/generations/{task_id}`
- User balance: `/v1/user/balance`
- Token balance: `/v1/balance`

The API key is never returned in JSON responses. Model fields remain editable because different relays may require different names and values.

## Task Lifecycle

Internal task codes are always seven digits and are the primary user-facing lookup value.

```text
PENDING -> SUBMITTED -> PROCESSING -> SUCCEEDED
                              \-> FAILED
```

Persist the final request body, upstream task ID, upstream response, output URL and error message. Polling must run inside Flask application context and must be bounded. Do not use an unbounded loop in a web request.

## RBAC

Every page and JSON endpoint must be protected by an existing Pear authorization decorator or an equivalent authenticated permission check.

Studio page permissions:

- `studio:dashboard`
- `studio:image`
- `studio:video`
- `studio:products`
- `studio:skills`
- `studio:history`
- `studio:providers`

When an endpoint serves both media types, check the required permission after reading `media_type`.

## UI Rules

- Use the shared `templates/studio/base.html` and `static/studio/studio.css`.
- Keep one page header, one content hierarchy and one primary action area.
- Use cards only for actual modules or repeated items.
- Keep image and video creation pages separate.
- Keep provider connection editing separate from model field editing.
- Use modal forms for provider and model editing.
- Preserve the seven-digit task code visibly in history and output views.

## Local Commands

Install:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirement\requirement-dev.txt
```

MySQL initialization:

```powershell
.\.venv\Scripts\python.exe -m flask init
.\.venv\Scripts\python.exe -m flask studio-init
```

Local MySQL server:

```powershell
.\.venv\Scripts\python.exe -m flask run --host 127.0.0.1 --port 5000
```

Default seeded account:

```text
username: admin
password: 123456
```

Change this password before any shared or production deployment.

## Change and Verification Workflow

1. Read the existing model, route and template before changing it.
2. Add or update a focused service function before wiring a route.
3. Keep provider requests mockable and never require a real paid generation request for a unit test.
4. Run `python -m compileall -q applications app.py`.
5. Run an app-factory test using `create_app("testing")`.
6. Run `studio-init` against a disposable MySQL test schema and render every studio page.
7. Verify the request builder for both image and video payloads.
8. Verify scheduler jobs execute inside Flask application context.
9. Never commit `.flaskenv`, API keys, local database dumps or uploaded assets.

## Model Form Contract

The image and video creation pages expose a small set of common fields for operators,
then render all additional enabled fields from the selected model schema. New model
parameters must declare a stable `field`, a human-readable `label`, an optional
`runtime_key`, a `value_type`, and an optional `hint`. The server remains the source
of truth and must build the final JSON body again before making the upstream request.

Provider connection editing and model field editing remain separate modal workflows.
Changing a provider must not silently rewrite a model's parameter schema. A provider
API key is never returned to the browser; only `api_key_configured` and a masked value
may be returned.
