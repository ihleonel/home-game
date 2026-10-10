# HomeGame Catalog and Room Flow

## Objective

Implement the first usable HomeGame shell: fictional game catalog, guest identity/piece selection, one discoverable active room, and live lobby membership updates through WebSockets.

## Problem

The current app is a React/Django starter with no catalog, guest identity, room model/API, or realtime transport. The user wants a small home-LAN flow without accounts, room codes, or a privileged human host.

## Why

This establishes the shared session experience before implementing any actual board-game rules.

## Scope

- Show a catalog of fictional placeholder games; no real game rules or assets.
- The first player selecting a game creates the single active room. Other players opening the same HomeGame endpoint discover and join it automatically; no invitation/room code.
- Ask for a display name and current game's marker only when either is missing from the browser session. Reuse a session name across games; do not add a separate generic avatar prompt.
- Show the selected game marker next to the player's name in the room lobby; assign seat/turn order separately on the server.
- Support explicit join/leave and live roster/presence updates through Django Channels WebSockets.
- Keep the room hostless: backend owns room creation, membership, and readiness state; no participant gets admin privileges.
- Preserve the earlier room lifecycle: one room per game, remove it when empty/end is signaled, then return clients to the catalog. Do not implement board-game rules or a next-game vote.
- Keep development access bound to `localhost:36130`; do not publish for Wi-Fi devices in this slice, per the user's current instruction.
- Do not modify `docker-compose.example.yml` or `.env.example`; keep the per-instance `docker-compose.yml` and `.env` convention.
- No branches: work directly on `develop` per the user's project preference.

## Constraints and Current Evidence

- Repository: `home-game`, current branch `develop`.
- Frontend is React/TypeScript/Vite; backend is Django/DRF/PostgreSQL. There are no product models, API endpoints, migrations, or WebSocket dependencies yet.
- Current Vite proxy handles `/api` only. Current local Compose publishes the frontend on `127.0.0.1:36130`; backend/database remain internal.
- User selected standard verification, not strict TDD. Run automated tests, build, and lint only inside their respective Docker containers; do not run host-side Python/Node tests. The user will perform manual browser checks at `localhost:36130`. Django's built-in test runner is available; no frontend test runner is configured, so do not add one without a separate need.
- WebSocket push requires Django Channels and Daphne; neither is installed in the running backend image. `python:3.12-slim` is not present in the local image cache.
- The user authorized unauthenticated public downloads from Docker Hub, Debian package mirrors, and PyPI for the local backend build. Use the explicit local Docker socket and no stored credentials; do not access unrelated registries or services.
- Receipt-driven development is on by default. Assess each work-unit commit and follow the returned `review_due` result; review the accumulated slice when due.
- Delivery strategy: `ask-on-risk`; no remote delivery is in scope. Estimate: under 400 authored lines per task as a planning heuristic, not a hard limit.

## Tasks

- [x] **HG-RF-01A — Add room and participant persistence**
  - Create the Django app, room/participant models, migration, and model tests. Enforce at most one active room globally and track the room's game, state, participants, marker, and readiness.
  - Route: delegated direct writer. Trigger evidence: creating models, migrations, app registration, and tests spans multiple non-trivial files.
  - Acceptance: uniqueness and participant membership constraints are tested using the backend container; ending/deleting a room removes it and its memberships; no host/admin role or game rules are added.

- [ ] **HG-RF-01B — Add catalog and room REST APIs**
  - Add stable fictional catalog data and endpoints for listing games, reading the active room, creating/joining/leaving, and updating readiness.
  - Use a server-issued guest token and server-side atomic room creation; a later request discovers/joins the existing room instead of creating another.
  - Route: same delegated direct writer, sequentially after HG-RF-01A. Trigger evidence: API, serialization, permissions, and tests span multiple paths.
  - Acceptance: no room code/account; guest name/piece are session-scoped; no game logic is added.

- [ ] **HG-RF-02 — Build catalog, identity, and lobby UI**
  - Replace the starter counter with fictional game cards, create/join flow, a one-time missing name/piece prompt, and a room roster showing names, pieces, and readiness.
  - Route: same delegated direct writer, sequentially after HG-RF-01B. Trigger evidence: frontend UI, session identity handling, and room API integration span multiple files.
  - Acceptance: guests can browse without identity; identity is requested only when creating/joining; returning participants see their session name prefilled; game piece is the in-room visual marker; no room code or generic avatar step.

- [ ] **HG-RF-03 — Add WebSocket roster updates**
  - Add Django Channels/Daphne ASGI routing, room-group membership events, reconnect snapshot, leave/disconnect handling, and Vite WebSocket proxying.
  - Route: same delegated direct writer. Build/restart only through the explicit local Docker socket; use an empty Docker credential config and limit downloads to Docker Hub, Debian package mirrors, and PyPI, as authorized by the user.
  - Acceptance: join/leave and readiness changes appear in other open clients without manual refresh; backend validates membership and all-ready state; actual game logic remains out of scope.

- [ ] **HG-RF-04 — Verify the vertical slice**
  - Run backend tests inside the backend container and frontend build/lint inside the frontend container; the user performs manual checks using two browser sessions on `localhost:36130`.
  - Route: fresh per-action worker for test/build/operational checks.
  - Acceptance: a first client creates the room, a second discovers and joins it, both see roster changes and explicit leave; all checks and any environment/network blockers are reported honestly.

## Verification

- Backend: run `python manage.py test` inside the backend container after required dependencies are installed.
- Frontend: run `npm run build` and `npm run lint` inside the frontend container.
- Manual: the user opens two separate browser sessions at `http://localhost:36130`; creates/joins a room and observes WebSocket updates, readiness, and leave.
- Run any dependency installation/build through the local Docker daemon with credentials disabled; do not install packages on the host or access unrelated remote sources.

## Progress

- Read-only code mapping completed; HG-RF-01A source changes are implemented and pending the work-unit commit.
- Standard verification mode was explicitly selected by the user.
- User authorized public Docker Hub, Debian package mirror, and PyPI downloads for the local backend image rebuild, without stored credentials.
- The initial broad backend writer launch aborted before returning a result; `git status` confirmed no source changes. Work continued as smaller sequential writer tasks.
- HG-RF-01A completed: the room model permits only active rows; ending the game deletes the room and cascades participant memberships. Five backend-container tests passed, and `makemigrations --check --dry-run` found no drift.
- HG-RF-01B, HG-RF-02, HG-RF-03, and HG-RF-04 remain pending.
- Runtime remains on localhost; no guest Wi-Fi bind changes are in scope.

## Next Step

Implement HG-RF-01B next: add the fictional catalog and guest room REST APIs on `develop`.
