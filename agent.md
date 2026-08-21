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
  common/storage/     go-fastdfs client and the single FileService facade
  common/             legacy Pear helpers and RBAC compatibility
templates/studio/     page templates
static/studio/        shared studio UI styles and browser helpers
```

Keep these boundaries stable. Do not put provider HTTP calls in route functions and do not put HTML concerns in service modules.

## File Storage Rules

All new persistent files must go through `applications.common.storage.FileService`.
Business routes and provider code must not call go-fastdfs directly and must not
read or write `/data/go-fastdfs/files`.

Configuration is split into two addresses:

- `GOFASTDFS_INTERNAL_URL`: the fileserver address reachable by Flask, for example
  `http://127.0.0.1:<actual-port>`.
- `GOFASTDFS_PUBLIC_URL`: the browser and provider-facing URL,
  `https://your-domain.example/gofastdfs`.

The internal port must be checked on the deployment host before changing the
blank local placeholder. Never guess the port in source code.

For Windows development without a local fileserver, configure the approved
Nginx proxy only in the ignored local `.flaskenv` file.
For CentOS deployment, replace it with the actual loopback listener after
checking `ss -lntp | grep fileserver`.

The go-fastdfs upload request must request `output=json2`. HTTP 200 alone is
not success: inspect the JSON `status` and `retcode`, use the returned
`data.path`/`data.md5`, and build the stored public URL from
`GOFASTDFS_PUBLIC_URL`. Never persist the upstream `data.url` directly because
it can omit the Nginx `/gofastdfs/` prefix.

Use these retention policies:

- Product center uploaded assets: `PERMANENT`, deleted only when the product
  or product asset is manually deleted.
- Imported Skill files: `PERMANENT`, deleted only when the Skill is manually
  disabled/deleted.
- User reference images/videos and API-generated images/videos: `TTL_7D`.

The scheduler retries rows marked `DELETE_FAILED`. A failed remote delete must
remain visible in the database and be logged; it must not be silently discarded.
Expired or deleted assets must not expose a usable public URL in JSON responses.

Storage categories are logical only and must remain stable:

```text
images/products
images/references
images/generated
videos/products
videos/references
videos/generated
skills
files/uploads
```

Use generated names from the storage client rather than user-provided names as
the final path. Keep the original filename only as metadata.

## Function Responsibilities

- `request_builder.build_request_body`: transform model field definitions and runtime values into the final JSON body.
- `product_prompt.compose_prompt`: combine product facts, Product Profile, Product Memory, rules and the user's creative request.
- `product_prompt.product_reference_urls`: collect enabled product assets and one-off reference URLs.
- `provider_client.ProviderClient`: perform authenticated provider requests, timeout handling and retry handling.
- `generation_service.create_generation`: validate inputs, create the seven-digit internal task code, submit the upstream task and persist the request snapshot.
- `generation_service.poll_task`: query one upstream task, normalize status, progress, output URL and errors.
- `generation_service.poll_processing_tasks`: bounded scheduler job for active tasks.
- `retention.cleanup_expired_assets`: remove expired temporary assets and retry failed deletes.
- `provider_client.ProviderClient.chat_completion`: call OpenAI-compatible
  language/vision models through the configured provider.
- `studio.routes.analyze_task`: build the product-aware vision analysis request
  and persist the result as a generation comment.
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

- image, video or chat type
- upstream model code
- generation path
- result path
- arbitrary request field definitions

Each request field definition contains:

- `field`: body key sent upstream; dotted paths such as `metadata.resolution`
  create nested JSON objects
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
- Chat/vision submit: `/v1/chat/completions`
- Image result: `/v1/images/generations/{task_id}`
- Video result: `/v1/videos/generations/{task_id}`
- User balance: `/v1/user/balance`
- Token balance: `/v1/balance`

The API key is never returned in JSON responses. Model fields remain editable because different relays may require different names and values.

The seeded model set also includes:

- Nano Banana 2: `gemini-3.1-flash-image-preview`, image-to-image references,
  `metadata.resolution` and the configured image reference limit.
- GPT-5.5 vision: `gpt-5.5`, used for post-generation image analysis.

Post-generation analysis is synchronous HTTP by default. It is intentionally
kept independent from the image/video task polling loop; a successful response
is persisted as `StudioGenerationComment` and rendered below the image history
item. Do not introduce a WebSocket dependency unless deployment requirements
justify the added runtime and connection management cost.

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
.\.venv\Scripts\python.exe -m flask run --host 0.0.0.0 --port 5000
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
9. Run storage mock tests for URL, base64, multi-output and failed-delete paths.
10. Never commit `.flaskenv`, API keys, local database dumps or uploaded assets.

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
