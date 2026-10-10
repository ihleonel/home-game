# HomeGame Local Docker Bootstrap

## Objective

Start the basic HomeGame development services with per-instance configuration and make the frontend available at `http://localhost:36130` without changing the reusable example templates.

## Problem

The checkout has `docker-compose.example.yml` and `.env.example` templates, while `.gitignore` excludes per-instance `docker-compose.yml` and `.env` files. The local runtime metadata in `.atl/` also needed to be ignored without changing its contents.

## Why

The user wants to proceed incrementally, keep example templates reusable, create configuration for this HomeGame instance, and ignore `.atl/`.

## Scope

- Keep `docker-compose.example.yml` and `.env.example` at their repository baseline.
- Create instance-specific, ignored `docker-compose.yml` and `.env` files.
- Publish only the frontend at `127.0.0.1:36130`; keep backend and database ports internal.
- Ignore `.atl/` without changing its contents.
- Do not add game functionality, WebSockets, production deployment, or guest Wi-Fi access in this task.
- Use the canonical `docker-compose.yml` filename. The user typed `docker-compos.yml`; the existing ignore rule and Compose convention indicate the canonical spelling.
- Do not access remote image registries or package indexes, or use stored credentials, without explicit authorization.

## Constraints and Current Evidence

- Repository: current `home-game` working tree; implementation branch: `feature/homegame-docker-bootstrap`.
- Docker and Compose are installed. The local daemon was addressed explicitly through `unix:///var/run/docker.sock`; port 36130 was free before startup.
- Both example templates match the local Git baseline. The instance-specific Compose and environment files are ignored; no secret values are recorded here.
- Compose configuration and `git diff --check` pass. The frontend is bound to loopback; backend/database ports are not host-published.
- At planning time `python:3.12-slim` was absent locally. The user subsequently started the services; the assistant did not build images, pull, or access remote package sources.
- Receipt-driven development is on by default. Work-unit commit `488f859142d634d8a155529c472a51c26d71e838` assessed `medium`, `review_due: false`, `review_due_reason: under_budget`; the slice remains pending until a later assessment says review is due.
- No project/session TDD setting or applicable application test runner was found. This was configuration-only work, validated with Compose configuration and a local HTTP/service-state check.
- Delivery strategy: `ask-on-risk`; no remote delivery is in scope. Estimated authored changes were under 400 lines (planning heuristic only).

## Tasks

- [x] **HG-01 — Separate instance configuration from templates**
  - Kept both example templates at their repository baseline.
  - Created `docker-compose.yml` and `.env` with instance-specific values; both remain local and ignored.
  - Route: delegated direct writer. Trigger evidence: reading prepared edits across Compose, environment, and Dockerfiles; the implementation changed multiple non-trivial configuration files.
  - Acceptance: templates unchanged; frontend bound only to `127.0.0.1:36130`; local credentials remain in ignored `.env`; backend/database not host-published.

- [x] **HG-02 — Ignore local runtime metadata**
  - Added `.atl/` to `.gitignore` and preserved the directory contents.
  - Route: direct inline mechanical edit. Trigger evidence: one already-understood pattern in the inspected `.gitignore`.
  - Acceptance: `.atl/` is ignored and existing `.env`/`docker-compose.yml` ignore rules remain intact.

- [x] **HG-03 — Validate the local stack**
  - Validated the per-instance Compose file and checked the diff. Verified the local HTTP endpoint and service health without starting or rebuilding containers.
  - Route: parent direct, read-only local spot check. Trigger evidence: the user reported that services were already running; the parent verified the endpoint and Compose status.
  - Acceptance: HTTP on `127.0.0.1:36130` succeeds; frontend and backend are running; database is healthy.

## Verification

- `docker --host unix:///var/run/docker.sock compose -f docker-compose.yml config --quiet` — passed.
- `git diff --check` — passed.
- `curl --noproxy '*' -sS -I --max-time 5 http://127.0.0.1:36130/` — `HTTP/1.1 200 OK`.
- `docker --host unix:///var/run/docker.sock compose -f docker-compose.yml ps` — frontend/backend running; database healthy; frontend published at `127.0.0.1:36130`.

## Progress

- HG-01 and HG-02 completed; both example templates remain unchanged.
- Work-unit commit: `488f859142d634d8a155529c472a51c26d71e838` (`chore: configure HomeGame local Docker bootstrap`); assessment is `medium/under_budget`, so native review is not currently due.
- HG-03 completed after the user's report that services were up; local HTTP and Compose status checks confirmed it.
- The assistant did not build, pull, or start containers.

## Next Step

The local development stack is ready. Continue with the next HomeGame product slice when the user chooses it; keep `.env` contents private.
