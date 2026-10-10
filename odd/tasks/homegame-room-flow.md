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
- Treat an unexpected WebSocket disconnect as temporary reconnecting presence for 60 seconds. After that, the other connected players may vote unanimously to expel the disconnected participant; the target does not vote. An explicit leave remains immediate. In this placeholder-game slice, inactivity means connection loss; turn-timeout inactivity belongs to future game rules.
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

- [x] **HG-RF-01B — Add catalog and room REST APIs**
  - Add stable fictional catalog data and endpoints for listing games, reading the active room, creating/joining/leaving, and updating readiness.
  - Use a server-issued guest token and server-side atomic room creation; a later request discovers/joins the existing room instead of creating another.
  - Route: same delegated direct writer, sequentially after HG-RF-01A. Trigger evidence: API, serialization, permissions, and tests span multiple paths.
  - Acceptance: no room code/account; guest name/piece are session-scoped; no game logic is added.

- [x] **HG-RF-02 — Build catalog, identity, and lobby UI**
  - Replace the starter counter with fictional game cards, create/join flow, a one-time missing name/piece prompt, and a room roster showing names, pieces, and readiness.
  - Route: same delegated direct writer, sequentially after HG-RF-01B. Trigger evidence: frontend UI, session identity handling, and room API integration span multiple files.
  - Acceptance: guests can browse without identity; identity is requested only when creating/joining; returning participants see their session name prefilled; game piece is the in-room visual marker; no room code or generic avatar step.

- [x] **HG-RF-03 — Add WebSocket presence and 60-second reconnect grace**
  - Add Django Channels/Daphne ASGI routing, room-group membership events, reconnect snapshots, leave/disconnect handling, 60-second reconnect grace, and Vite WebSocket proxying.
  - On an unexpected disconnect, retain the participant for 60 seconds as reconnecting; a reconnect in that window restores the same session. Explicit leave is immediate.
  - Route: same delegated direct writer. Build/restart only through the explicit local Docker socket; use an empty Docker credential config and limit downloads to Docker Hub, Debian package mirrors, and PyPI, as authorized by the user.
  - Acceptance: join/leave/readiness and reconnecting state appear in other clients without refresh; actual game rules remain out of scope.

- [x] **HG-RF-04 — Add unanimous disconnected-player expulsion voting**
  - After the 60-second grace expires, allow the other connected active players to vote on removing the disconnected player. The target does not vote; remove the participant and update the room only after every eligible player approves. Explicit leave remains immediate.
  - Route: same delegated direct writer after HG-RF-03. Trigger evidence: vote persistence/API and lobby controls span backend/frontend files.
  - Acceptance: any rejection prevents removal; only unanimous approval removes the disconnected participant; connection-loss handling does not pretend to detect inactivity during future game turns.

- [ ] **HG-RF-05 — Verify the vertical slice**
  - Run backend tests inside the backend container and frontend build/lint inside the frontend container; the user performs manual checks using two browser sessions on `localhost:36130`.
  - Route: fresh per-action worker for test/build/operational checks.
  - Acceptance: two clients create/join, observe live roster/readiness, test reconnect within grace, and exercise the expulsion vote; report all checks and blockers honestly.

## Verification

- Backend: run `python manage.py test` inside the backend container after required dependencies are installed.
- Frontend: run `npm run build` and `npm run lint` inside the frontend container.
- Manual: the user opens two separate browser sessions at `http://localhost:36130`; creates/joins a room, observes WebSocket updates, and checks the reconnect grace/expulsion flow.
- Run any dependency installation/build through the local Docker daemon with credentials disabled; do not install packages on the host or access unrelated remote sources.

## Progress

- Read-only code mapping completed; HG-RF-01A source changes are committed.
- Standard verification mode was explicitly selected by the user.
- User authorized public Docker Hub, Debian package mirror, and PyPI downloads for the local backend image rebuild, without stored credentials.
- The initial broad backend writer launch aborted before returning a result; `git status` confirmed no source changes. Work continued as smaller sequential writer tasks.
- HG-RF-01A completed: the room model permits only active rows; ending the game deletes the room and cascades participant memberships. Five backend-container tests passed, and `makemigrations --check --dry-run` found no drift.
- Work-unit commit `fb5ebdff46ff51ed5d97614f8d3e333fa1fd1de1` (`feat: add HomeGame room persistence`) assessed medium with `review_due: false` and `review_due_reason: under_budget`; keep the slice pending.
- HG-RF-01B completed: fictional catalog and room REST APIs are in place; 16 backend-container tests passed, including strict UUID-string token validation.
- Work-unit commit `72882cd7069a50df550d5c15beff57ca751a7b90` assessed medium with `review_due: true` and `review_due_reason: slice_budget_reached`. Native review start returned a typed unavailable result before mutation; no review receipt or approval exists. The off-path risk assessment is medium; the writer and parent backend-container tests passed.
- The user explicitly chose to continue with the catalog/WebSocket work despite the unavailable native review. Preserve the unavailable result; do not represent this slice as natively reviewed or approved.
- HG-RF-02 completed: catalog, session identity/marker form, active-room view, roster, ready toggle, and leave action are implemented. Parent readback found and corrected saved-identity room creation; frontend build/lint pass inside the frontend container.
- Work-unit commit `ea7ccbea3745031109d13d780f4236d517e39bbb` (`feat: add HomeGame catalog and lobby UI`) assessed medium with `review_due: true` and `review_due_reason: slice_budget_reached`. Native review remains unavailable; container build/lint and the parent build spot-check passed.
- The user confirmed a 60-second reconnect grace followed by a unanimous expulsion vote among other connected players; explicit leave remains immediate. In this slice, inactivity means connection loss, not a missed game turn.
- HG-RF-03 completed: Channels/Daphne presence events, 60-second reconnect grace, Vite WebSocket proxy, and container integration are implemented. Twenty-one backend tests and frontend build/lint pass inside containers.
- Work-unit commit `5dc6c1038ad11409876472cb8c610a8361b24d0a` (`feat: add HomeGame WebSocket presence`) assessed medium with `review_due: true` and `review_due_reason: slice_budget_reached`. Native review remains unavailable; the off-path assessment and container tests passed, but no native review receipt exists.
- During the backend restart, Compose reported the database container recreated and healthy; no volumes were removed and database contents were not inspected.
- HG-RF-04 completed across the vote/model/migration/API/WebSocket/UI/test paths: fixed ballots preserve unanimity, rejection prevents removal, and a target reconnect or eligible voter's disconnect/leave cancels the vote rather than shrinking the electorate. No vote timeout was added because none was specified.
- Applied `rooms.0003_expulsion_voting` to the existing backend DB (`showmigrations` reports `[X]`); restarted only the backend. The database remained running and was not restarted or volume-touched.
- Verification passed: all 29 backend tests (`python manage.py test`; parent spot-check also passed), plus frontend `npm run build` and `npm run lint` inside the frontend container. HG-RF-05's automated checks passed; its two-browser manual check at `http://localhost:36130` remains pending.
- Native review remains unavailable (`immutable_review_transport_unsupported`); the user chose to continue. No native review receipt or approval exists.
- Runtime remains on localhost; no guest Wi-Fi bind changes are in scope.

## Next Step

Perform the HG-RF-05 manual two-browser verification at `http://localhost:36130`: create/join with two clients, observe live roster/readiness, check reconnect within grace and the expulsion vote, then report results. Keep HG-RF-05 unchecked until complete.
