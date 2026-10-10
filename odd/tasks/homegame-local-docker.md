# HomeGame Local Docker Bootstrap

## Objective

Start the basic HomeGame development services with per-instance configuration and make the frontend available at `http://localhost:36130` without changing the reusable example templates.

## Problem

The current checkout has `docker-compose.example.yml` and `.env.example` templates, while `.gitignore` already excludes per-instance `docker-compose.yml` and `.env` files. A prior setup attempt edited the templates instead of creating local instance files. The existing `.atl/` runtime metadata is untracked and is not yet ignored.

## Why

The user wants to proceed incrementally, keep example templates reusable, create configuration for this HomeGame instance, and ignore `.atl/`.

## Scope

- Restore `docker-compose.example.yml` and `.env.example` to their repository baseline.
- Create instance-specific, ignored `docker-compose.yml` and `.env` files.
- Publish only the frontend at `127.0.0.1:36130`; keep backend and database ports internal.
- Add `.atl/` to `.gitignore` without changing the contents of `.atl/`.
- Do not add game functionality, WebSockets, production deployment, or guest Wi-Fi access in this task.
- Use the canonical `docker-compose.yml` filename. The user typed `docker-compos.yml`; the existing ignore rule and Compose convention indicate the canonical spelling.
- Do not access remote image registries or package indexes, use stored credentials, or start a build until the user explicitly authorizes the destination and access method.

## Constraints and Current Evidence

- Repository: current `home-game` working tree; implementation branch: `feature/homegame-docker-bootstrap`.
- Before implementation, `git status` showed only tracked edits from the prior setup attempt and the pre-existing untracked `.atl/` directory. Preserve all `.atl/` contents.
- Docker and Compose are installed. The local daemon was addressed explicitly through `unix:///var/run/docker.sock`; port 36130 is free.
- Compose configuration and `git diff --check` passed for the prior attempt, but that attempt edited the wrong files and its template changes must be reverted.
- `python:3.12-slim` is absent locally. Dockerfiles invoke apt, pip, and npm package installation. No image build or service startup has been authorized over the network.
- Receipt-driven development is on by default. Native review previously requested a schema-bound selection for pre-existing `.atl/` files; after adding the ignore rule, rerun the canonical status/assessment and do not fabricate a selection.
- No project/session TDD setting or applicable application test runner was found. This is configuration-only work: use Compose validation and local runtime checks; do not claim an application TDD mode. If scope expands to application behavior, resolve TDD before proceeding.
- Delivery strategy: `ask-on-risk`; no remote delivery is in scope. Estimated authored changes are under 400 lines (planning heuristic only).

## Tasks

- [x] **HG-01 — Separate instance configuration from templates**
  - Restore both example templates to their repository baseline.
  - Create `docker-compose.yml` and `.env` with values specific to this instance; keep both local and ignored.
  - Route: delegated direct writer. Trigger evidence: reading prepares edits across Compose, environment, Dockerfiles, and ignore conventions; the implementation changes multiple non-trivial configuration files.
  - Acceptance: the example templates are unchanged from the repository baseline; the local Compose stack exposes only `127.0.0.1:36130`; local database credentials and Django secret stay in ignored `.env`; the backend/database are not host-published.

- [x] **HG-02 — Ignore local runtime metadata**
  - Add `.atl/` to `.gitignore` and preserve the directory contents.
  - Route: direct inline mechanical edit. Trigger evidence: one already-understood pattern in the inspected `.gitignore`.
  - Acceptance: `.atl/` is ignored and existing `.env`/`docker-compose.yml` ignore rules remain intact.

- [ ] **HG-03 — Validate and start the local stack**
  - Validate the per-instance Compose file and check the diff; start and smoke-test only after required remote dependency access is explicitly authorized and the native review gate is resolved.
  - Route: fresh per-action worker for build/start verification. Trigger evidence: build/start is a bounded operational action and must not inherit writer context.
  - Acceptance: Compose parses successfully; once authorized, the services become healthy and `http://localhost:36130` serves the frontend. If remote access remains unauthorized, record startup as blocked without attempting downloads.

## Verification

- `docker compose -f docker-compose.yml config --quiet`
- `git diff --check`
- After explicit download authorization: `docker compose -f docker-compose.yml up --build -d`
- After startup: a local HTTP smoke check of `http://127.0.0.1:36130/` and Compose service status.

## Progress

- HG-01 completed: both example templates match the repository baseline; ignored per-instance `docker-compose.yml` and `.env` exist; Compose validation passes.
- HG-02 completed: `.atl/` was added to `.gitignore`; `git check-ignore` confirms both existing `.atl` files are ignored. Their contents were not changed.
- HG-03 is blocked pending explicit authorization for public image/package downloads and completion of native review preflight.
- No containers have been built or started.

## Next Step

Resolve the native review preflight, then request explicit download authorization before building or starting containers. Keep the `.env` contents private.
