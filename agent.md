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
- User reference images/videos and API-generated images/videos: temporary
  retention (30 days by default; keep `TTL_7D` only as a legacy compatibility
  value for old rows).

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
.\.venv\Scripts\python.exe -m flask init --fresh --yes --skip-storage
```

This command is destructive for the configured `MYSQL_DATABASE`: it drops and
recreates the database, applies the complete Alembic chain, seeds the three
built-in roles and permissions, creates only the `admin` account, and leaves
all provider API keys empty. The department table starts empty because the
reserved `admin` account is not assigned to an ordinary department.

After go-fastdfs is available and configured, upload bundled Skill files with:

```powershell
.\.venv\Scripts\python.exe -m flask init --seed-storage
```

Local MySQL server:

```powershell
.\.venv\Scripts\python.exe -m flask run --host 0.0.0.0 --port 5000
```

Production logging:

- Development uses `LOG_DIR`/`APP_LOG_FILE` and may write to the local
  `logs/` directory.
- Production uses `PEAR_AI_LOG_DIR` and `PEAR_AI_APP_LOG_FILE`; defaults are
  `/var/log/pear-ai` and `/var/log/pear-ai/pear-ai.log`.
- `gunicorn.conf.py` writes `gunicorn-access.log` and `gunicorn-error.log`
  beside the application log.
- `deploy/pear-ai.service` sets the production variables explicitly so an old
  development `.flaskenv` cannot redirect production logs into the checkout.

Default seeded account:

```text
username: admin
password: 123456
```

Set `ADMIN_PASSWORD` in `.flaskenv` before any shared or production deployment;
the value above is only the fallback for an unconfigured local environment.

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

## Long-Term Project Context

This file is the durable working contract for future Codex sessions. Read it
before changing code. The current repository is:

```text
Repository: https://github.com/chenwuping0611-ops/commerce-studio.git
Branch: main
Local project: D:\工作空间\AI项目\pear-admin-flask-master
```

The project is a Pear Admin Flask application for an internal AI ecommerce
studio. It is a working product, not a greenfield demo. Existing business
behavior, database rows, GoFastDFS files, provider keys, JWT/session behavior,
password hashing, and legacy-compatible API fields must be preserved unless
the user explicitly requests a breaking change.

### Complete Repository Map

```text
app.py
applications/
  __init__.py                    Flask app factory and extension wiring
  configs/                       development/production configuration
  extensions/                    Login, ORM, scheduler, upload and error setup
  common/
    admin.py                     Pear Admin compatibility helpers
    admin_log.py                 operation-log writing and redaction
    asset_relations.py           normalized task/product/Skill asset links
    cleanup_lock.py              single-run cleanup lock
    curd.py, helper.py           legacy Pear helpers
    db_session.py                release DB connection before long HTTP calls
    execution_context.py         immutable provider/model/product/Skill snapshots
    logging_config.py            application and production file logging
    scope.py                     identity, RBAC and data-scope enforcement
    skill_storage.py             canonical Skill text loading from GoFastDFS
    script/                      Flask CLI initialization and scaffolding
    storage/
      file_service.py            single application storage facade
      gofastdfs_client.py        GoFastDFS HTTP protocol client
    tasks/                       scheduler events, polling and retention jobs
    utils/                       login/upload/validation compatibility helpers
  models/
    admin_*.py                   users, roles, powers, departments and logs
    studio.py                    Studio settings/providers/models/products/
                                   product assets/Skills/batch prompts/tasks/
                                   comments/assets
    amazon_ai.py                 Amazon AI tasks, sources, dependencies/assets
  schemas/                       Marshmallow/webargs request schemas
  studio/
    bootstrap.py                 Studio menus, roles, departments and providers
    provider_catalog.py          code-owned provider/model catalog
    provider_client.py           OpenAI-compatible and async provider requests
    request_builder.py           model schema to upstream request body
    generation_service.py        normal generation and output asset lifecycle
    product_prompt.py            product-aware prompt composition
    batch_prompt.py              batch document parsing and formatting
    jobs.py                      generation/Amazon/cleanup scheduler functions
    retention.py                 Studio asset retention and failed-delete retry
    feedback_skill.py            shared image/video feedback Skill
  amazon_ai/
    bootstrap.py                 Amazon menu, permissions and bundled Skills
    service.py                   Amazon task execution and text/vision context
    competitor_text.py           Amazon page normalization and visible-text fetch
    file_text.py                 GoFastDFS document download and text extraction
    permissions.py               Amazon permission/session synchronization
    retention.py                 Amazon task/file retention cleanup
    skill_catalog.py             built-in Amazon Skill definitions
    skills/*.md                  code-owned Amazon Skill source files
  view/
    admin/                       Pear Admin system routes
    department/                  department tree and department management
    passport/                    login/logout/password routes
    studio/routes.py             Studio pages and JSON APIs
    amazon_ai/routes.py          Amazon AI pages and JSON APIs
templates/
  admin/                         Pear Admin pages
  studio/                        image, video, product, Skill, provider/history UI
  amazon_ai/                     dashboard, source tasks and Listing UI
static/
  admin/                         Pear Admin assets
  studio/                        shared Studio CSS/JS and batch prompt UI
  amazon_ai/                     Amazon AI CSS/JS
migrations/
  versions/*.py                  complete Alembic schema and data-safe migrations
deploy/
  pear-ai.service                CentOS systemd service
  pear-ai-logrotate              application log rotation
  pear-ai-tmpfiles.conf          /var/log/pear-ai directory policy
  README.md                      production deployment and logging notes
test/
  *_smoke.py, *_unit.py          mock/unit/domain/permission/storage checks
  pear.sql                       legacy fixture only; never deploy or package
```

The application is intentionally split into four layers:

1. Routes authenticate, validate the high-level input, resolve the required
   permission and call a service. Routes must not contain provider protocol
   implementations or direct GoFastDFS calls.
2. Domain services resolve scoped rows, snapshot all data needed for long
   operations, release the SQLAlchemy connection before network calls, and
   persist only bounded metadata and references.
3. Provider/storage adapters perform external HTTP operations and normalize
   their responses. They must be mockable and must not know HTML/template
   details.
4. Templates and static scripts render the current Pear/Layui UI. Frontend
   hiding improves usability only; it is never an authorization boundary.

### Identity and Data Scope

There are exactly three intended business identities:

```text
admin account          -> SUPER_ADMIN / ALL
dept_admin role        -> DEPARTMENT
studio_user role       -> SELF
```

`admin` is a reserved username and the only super administrator. The `admin`
role code is not a general-purpose role that can be granted to another user.
The real department `总项目` is the administrator's organization record; it is
not a virtual provider owner. Default structural departments are
`总项目 -> 三部五组 / 三部二组`, while ordinary users are assigned to a real
business department.

The authoritative helpers are in `applications/common/scope.py`:

- `is_super_admin_user()` checks the reserved username `admin`.
- `data_scope_for_user()` returns `ALL`, `DEPARTMENT` or `SELF`.
- `scope_query()` applies server-side row filtering.
- `can_access_resource()` checks a concrete row.
- `can_access_provider()` and `can_access_model()` protect provider/model
  ownership and API keys.
- `can_assign_role()` prevents normal users from creating or assigning a
  reserved role.
- `can_change_password()` implements the password-change matrix.

Every endpoint that accepts `user_id`, `dept_id`, `department_id`, `product_id`,
`skill_id`, `model_id`, `provider_id`, `asset_id`, task code, or source task
code must resolve the row through the current user's scope. A browser-provided
department or user id is only a selector for a super administrator; it cannot
expand a normal user's scope. Check both the page permission and the row
ownership on reads, writes, deletes, task polling, feedback, uploads and
history APIs.

### Business Data Relationships

The main relationships are:

```text
admin_user <-> admin_role <-> admin_power
admin_dept (parent_id tree) -> admin_user.dept_id

studio_provider (dept_id, api_key)
  -> studio_model (provider_id, media_type, protocol schema)
  -> studio_generation_task.model_id

studio_product (dept_id, facts and product memory)
  -> studio_product_asset -> studio_asset
  -> studio_generation_task.product_id

studio_skill (dept_id, metadata)
  -> studio_asset (canonical Markdown in GoFastDFS)
  -> studio_generation_task.skill_id/snapshot

studio_batch_prompt (product_id, skill_id, planner model, versions)
  -> studio_asset (canonical batch document in GoFastDFS)
  -> studio_generation_task through batch-processing metadata

studio_generation_task
  -> studio_generation_task_asset -> studio_asset
  -> studio_generation_comment -> product field suggestions

amazon_ai_workspace_task
  -> amazon_ai_task_source (URLs/ASINs)
  -> amazon_ai_task_dependency (source task links)
  -> amazon_ai_task_asset (input/result files)
  -> studio_asset (actual GoFastDFS metadata)
```

Large text and binary content belong in GoFastDFS. Database rows hold identity,
ownership, status, bounded snapshots, hashes, filenames, URLs and foreign-key
relations. Do not put generated image/video Base64 or full large AI reports in
database columns. A bounded redacted response snapshot is acceptable for
diagnostics; it must not contain credentials or unnecessarily retain image bytes.

### Provider, Model and Prompt Rules

Provider configuration is separate from model identity:

- Providers own base URL, API key, authentication, timeout, balance paths and
  default endpoint paths.
- Models own media type, upstream model code, endpoint overrides, capabilities
  and request field schema.
- `provider_catalog.py` is the protocol source of truth for known ToAPIs and
  快跑AI models. Database rows preserve department ownership and enabled state.
- Kuaipao image generation uses one visible `gpt-image2` model and maps the
  selected quality to `gpt-image-2-1k`, `gpt-image-2-2k` or
  `gpt-image-2-4k`. The selected preset aspect ratio is converted to a valid
  4K `widthxheight` size before the request.
- A provider API key is required at execution time, is never returned in full
  JSON, and must never appear in logs, tests, Markdown, screenshots or commits.

For image/video creation, the user's creative description is the highest
priority creative instruction. Product facts and product-center reference
images lock the product identity. A selected Skill controls the professional
output constraints. The final prompt is capped at 5000 UTF-8 bytes where the
workflow requires it. If a product or Skill is selected, the page may call the
department's configured global chat model to plan the prompt. Each planning
operation is an independent OpenAI-compatible request with a new input/body;
never reuse a conversation/thread/session id or accidentally carry another
task's messages into the next task.

### Image, Video and Batch Workflows

Normal image/video creation:

1. Load scoped product, Skill, model, provider and reference assets.
2. Build the product-aware prompt and final request through
   `generation_service` and `request_builder`.
3. Create one internal seven-character task code and persist the request
   snapshot without credentials.
4. Submit to the configured provider and store the upstream task id/status.
5. Poll in the bounded scheduler job or explicit task-status endpoint.
6. When the provider returns a URL or Base64, materialize it as a temporary
   local file/stream, upload it to GoFastDFS, create `studio_asset`, link it
   to the task, then remove the local temporary file. History displays the
   GoFastDFS public URL and database metadata, never Base64.

Batch prompt planning:

- The page selects a product, optional Skill, style, quantity, aspect ratio and
  image quality. Quantity `0` normalizes to 10.
- One language-model call produces all requested versions in the strict JSON
  contract of the selected batch Skill. Every image version is below 5000
  UTF-8 bytes and contains its own aspect-ratio and quality markers.
- The document is first staged locally, uploaded to GoFastDFS, and only then
  associated with the database row. Editing follows the same replacement
  protocol: upload replacement successfully, update the database reference,
  then delete the old storage object and local temporary file.

Batch image processing:

- The image page selects an existing completed batch-prompt history.
- It parses exactly the saved versions; two versions mean two generation tasks,
  seven versions mean seven tasks. It must never multiply the count by a model
  `n` field or a UI default.
- It does not call the language model and does not load/apply a Skill during
  this processing step. The saved batch prompt version is the final prompt;
  the product is still resolved for authorized reference image URLs.
- Each version uses its own parsed aspect ratio and quality, is submitted once
  with `count=1`, runs concurrently within bounded workers, and may retry once
  only when the provider did not already accept the request.
- Each output follows the normal URL/Base64 -> temporary file -> GoFastDFS ->
  database asset relation -> local cleanup flow. History shows the resulting
  images only, with task/version metadata available in the detail view.

Amazon AI workflow:

- Supported task types are competitor analysis, keyword analysis, Review
  analysis, differentiation, basic-information correction, Listing creation
  and Listing audit.
- Multiple uploaded files are stored as `AMAZON_INPUT` GoFastDFS assets.
  The service downloads and parses them through a temporary local file, bounds
  text, then deletes the local copy. URLs are normalized and Amazon pages are
  converted to bounded visible-text Markdown.
- A task records source URLs/ASINs, input assets, upstream task dependencies,
  result assets, status and small references. It does not store the full
  generated report in the task row.
- Listing and product extraction may create/update product-center facts only
  from model output that is explicitly supported by the source material.
  Missing fields remain empty; never invent product identity.
- The configured per-file upload ceiling is at most the OpenAI Files API
  single-file limit of 512 MiB. The application also enforces the configured
  input-file count and combined-context limits before calling the model.

Generation feedback:

- Image/video history feedback requires a completed, scoped output asset.
- The feedback Skill and product reference images are sent to a fresh vision
  request. The model may propose `core_selling_points`, `product_profile` and
  `product_memory`; only normalized, evidence-backed fields are applied.
- Feedback comments and automatic product updates are scoped to the same task
  and department. A user must not use a manually supplied task or product id
  to update another user's product.

### Storage and Asset Lifecycle

All persistent files use `FileService`; routes and domain code do not call the
GoFastDFS endpoint directly. The storage client must:

- upload with `output=json2`;
- require both HTTP success and a successful GoFastDFS `status`/`retcode`;
- store the returned normalized path/checksum and build the public URL from
  `GOFASTDFS_PUBLIC_URL`;
- use stream limits for uploads/downloads;
- delete the remote object only after the replacement or database transition
  has succeeded;
- record `DELETE_FAILED`/`CLEANUP_PENDING` rows when deletion fails so the
  scheduler can retry.

Canonical categories are:

```text
images/products, images/references, images/generated
videos/products, videos/references, videos/generated
skills, files/uploads
```

Product assets and Skill files are permanent. User inputs and generated
temporary outputs follow the configured temporary retention policy (currently
30 days by default). Never delete a shared asset while another product, Skill,
batch prompt or generation task still references it. Never treat a URL that is
expired, inactive or marked deleted as usable in an API response.

### Security and Compatibility Rules

- Backend checks are mandatory even when a menu/button is hidden in the UI.
- Never trust client role names, department names, `user_id`, `dept_id`,
  `owner_type`, model/provider selectors or task references.
- Keep `admin` as the sole super administrator. Normal accounts cannot grant,
  create or impersonate the super-admin role.
- Passwords remain one-way hashed. Passwords, API keys, authorization headers,
  tokens, captcha values and secrets are redacted by logging helpers and must
  not be written to operation logs.
- Login no longer uses a captcha field/image/API. Do not restore captcha logic
  while fixing unrelated login behavior.
- Preserve existing Flask-Login/session and password-hash behavior. Do not
  replace authentication, JWT/session contracts, or unrelated modules.
- Do not expose provider API keys to browser JSON. Use `api_key_configured`
  and masked display values only.
- Do not store credentials in source, tests, Skill documents, deployment
  templates or the repository. Real environment values belong only in the
  ignored local/production `.flaskenv`.
- Keep provider calls, GoFastDFS calls and scheduler jobs mockable. Release DB
  connections before network calls and always restore application context in
  worker threads.

### Database and Initialization Rules

Alembic migrations are the physical schema source of truth. Every table,
column, index, constraint, ownership field or data repair needed by a feature
requires a forward migration. Migrations must be idempotent where practical,
preserve existing business rows, and never copy local test data into a shared
environment.

For a brand-new disposable local database only:

```powershell
.\.venv\Scripts\python.exe -m flask init --fresh --yes --skip-storage
.\.venv\Scripts\python.exe -m flask init --seed-storage
```

The first command drops only the configured local MySQL schema, applies the
complete migration chain and seeds the safe base configuration/admin. The
second command uploads bundled Skill Markdown to GoFastDFS. Never use
`--fresh` against production or a local database whose data must be retained.

For an existing environment, use forward-only operations:

```powershell
.\.venv\Scripts\python.exe -m flask db upgrade
.\.venv\Scripts\python.exe -m flask studio-init --seed-storage
.\.venv\Scripts\python.exe -m flask amazon-ai-init --seed-storage
```

These commands must not clear provider keys when `fresh=False`; they may
repair code-owned menus, model catalog rows and bundled Skill files. Always
inspect the migration and bootstrap code before adding a release command.
Never run `flask init --fresh`, `flask db downgrade`, test fixture imports or
database dumps as part of an online code release.

### Development Rules

1. Read the current model, migration, service, route, template and tests before
   editing. Work with user changes already present; never reset or discard
   unrelated working-tree changes.
2. Keep changes narrow and compatible with current Pear Admin/Layui patterns.
   Add a service/helper when it removes real duplication, not a speculative
   framework.
3. Put authorization and scope checks at the service/route boundary. Add
   negative tests for forged ids and cross-department/cross-user access.
4. Keep provider request bodies code/schema-driven and redact request logs.
5. Add a migration for schema changes and explain whether it changes only schema
   or also repairs existing rows. Never silently seed test users or API keys.
6. For storage changes, test URL normalization, URL and Base64 outputs,
   multi-file/multi-output behavior, replacement ordering, local temporary
   cleanup and failed remote deletion.
7. For batch changes, assert exact version count, `count=1` per image version,
   no extra planner call during processing, per-version retry behavior and
   task/asset relation count.
8. Run at least:

   ```powershell
   .\.venv\Scripts\python.exe -m compileall -q applications app.py test
   .\.venv\Scripts\python.exe test/storage_unit.py
   .\.venv\Scripts\python.exe test/studio_smoke.py
   .\.venv\Scripts\python.exe test/studio_domain_smoke.py
   ```

   Run additional focused smoke tests for the changed boundary. Do not point
   tests at production or the shared local test database unless explicitly
   requested and verified.
9. Before committing, run `git diff --check` and the sensitive-information
   scan. Keep `.flaskenv`, local database files, logs, generated media,
   GoFastDFS data and `test/pear.sql` out of commits and release archives.
10. Do not create a release package or push to GitHub during ordinary
    incremental feature work unless the user explicitly requests it or uses
    the release trigger described below.

### Incremental Session and Release Workflow

Feature work may span many conversations. At the start of every new session:

1. Read `agent.md`.
2. Inspect `git status --short --branch`, the current branch and `git remote -v`.
3. Treat the current working tree as the source of truth, including valid
   uncommitted changes made in previous sessions.
4. Do not infer that a feature is ready for production merely because tests
   pass. Keep implementing locally until the user asks for release.

The exact release triggers are the user saying **“准备发布”** or
**“发布线上”** (including an unmistakable equivalent such as “同步线上”).
Only then perform the release checklist:

1. Fetch and compare against the configured repository's current
   `origin/main`; report local commits, working-tree changes and any remote
   divergence. Never force-push and never reset a user's work.
2. Review `git diff`, migrations, API/permission changes, Skill changes,
   storage behavior and tests. Run compile, focused tests, `git diff --check`
   and secret scans.
3. Build a code-only archive named
   `pear-ai-YYYYMMDD-full-code-sync.tar.gz`. The archive must contain the
   application source, migrations, templates, static files, bundled Skills,
   tests that are useful for verification and deployment templates. It must
   exclude `.git`, `.venv`, `.flaskenv`, database dumps/fixtures
   (`test/pear.sql`), logs, `instance/`, caches, temporary files, generated
   media, GoFastDFS storage and all real credentials. The archive layout must
   extract directly into `/opt/pear-ai`; do not add an unexpected nested
   project directory.
4. Produce a SHA-256 checksum and inspect the archive listing. Confirm the
   archive contains no secret or runtime data.
5. Commit the reviewed code to `main` and push with a normal
   `git push origin main`. If `origin/main` advanced, stop and safely
   integrate the remote history; never use `--force`.
6. Report the exact commit hash, archive path, archive checksum, changed files,
   migration status, API/permission changes, tests, and the complete online
   update commands.

Release means code synchronization only. It does not mean copying the local
database, local test records, generated image/video history, Amazon AI history,
custom provider keys, or GoFastDFS objects to production. The only production
database action allowed by a reviewed release is the forward `flask db upgrade`
needed for the shipped migrations. It must not delete or import business rows.
The production `.flaskenv` must remain in place and must never be overwritten
by the archive.

### Standard Release Archive and CentOS Commands

The standard archive is generated from the repository root with direct-root
contents. On Windows PowerShell, after the release review:

```powershell
$repo = "D:\工作空间\AI项目\pear-admin-flask-master"
$archive = "D:\工作空间\AI项目\pear-ai-$(Get-Date -Format yyyyMMdd)-full-code-sync.tar.gz"
tar --exclude=.git --exclude=.venv --exclude=.flaskenv `
    --exclude=instance --exclude=logs --exclude=tmp `
    --exclude=__pycache__ --exclude=*.pyc `
    --exclude=test/pear.sql `
    -czf $archive -C $repo .
Get-FileHash -Algorithm SHA256 $archive
tar -tzf $archive | Select-Object -First 80
```

For the current release requested on September 3, 2026, the exact artifact
name is `pear-ai-20260903-full-code-sync.tar.gz`. If a previous archive with
the same name exists, regenerate it only after the current release review so
its checksum matches the committed code.

The full online update procedure is:

```powershell
scp "D:\工作空间\AI项目\pear-ai-20260903-full-code-sync.tar.gz" root@<服务器IP>:/tmp/
```

Run the following on CentOS 9. It preserves the existing `.flaskenv` and
provider keys, updates code/templates/static/migrations, applies only forward
schema migrations, synchronizes code-owned Skills to GoFastDFS, and restarts
the service:

```bash
set -euo pipefail

cd /opt
sudo systemctl stop pear-ai

release_dir="/tmp/pear-ai-release-$(date +%Y%m%d%H%M%S)"
sudo mkdir -p "$release_dir"
sudo tar -xzf /tmp/pear-ai-20260903-full-code-sync.tar.gz -C "$release_dir"

# The archive contains direct project contents and never contains .flaskenv.
sudo cp -a "$release_dir"/. /opt/pear-ai/

# Refresh service/logging templates only from the shipped code package.
sudo install -m 0644 /opt/pear-ai/deploy/pear-ai.service /etc/systemd/system/pear-ai.service
sudo install -m 0644 /opt/pear-ai/deploy/pear-ai-tmpfiles.conf /etc/tmpfiles.d/pear-ai.conf
sudo install -m 0644 /opt/pear-ai/deploy/pear-ai-logrotate /etc/logrotate.d/pear-ai
sudo systemd-tmpfiles --create
sudo systemctl daemon-reload

cd /opt/pear-ai
source .venv/bin/activate
export FLASK_APP=app.py

python -m flask db current
python -m flask db upgrade
python -m flask db current

# These are idempotent, non-fresh bootstrap operations. They do not clear
# existing provider API keys and update bundled Skill files in GoFastDFS.
python -m flask studio-init --seed-storage
python -m flask amazon-ai-init --seed-storage

deactivate

sudo systemctl restart pear-ai
sudo systemctl status pear-ai --no-pager
sudo tail -n 80 /var/log/pear-ai/pear-ai.log
sudo tail -n 80 /var/log/pear-ai/gunicorn-error.log
```

Never execute these in an online release:

```text
python -m flask init --fresh
python -m flask init --fresh --yes
python -m flask db downgrade
mysql < test/pear.sql
git push --force
```

If a migration or bootstrap is found to change existing business rows beyond
the explicitly reviewed repair, stop the release and report it before running
the command. Always keep a production database backup procedure outside the
code archive and follow the operator's approved backup policy.
