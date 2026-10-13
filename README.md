# HomeGame

## Prerequisites

- Docker Engine with the Docker Compose plugin
- A configured `.env` file in the repository root

Use `.env.example` as a reference when configuring `.env`. Set the variables required by `docker-compose.yml` before running any Compose commands. Keep `.env` private and do not commit it.

## Usage

From the repository root:

```sh
make up       # Build and start db, backend, and frontend in the background
make migrate  # Apply Django migrations in the running backend container
make test     # Run Django tests in the running backend container
```

The backend startup command already applies migrations before starting Daphne. Run `make migrate` to apply migrations explicitly; `make migrate` and `make test` require the backend container to be running.

## Ghost rooms and ghost memberships

A participant that disconnects is not removed immediately: the WebSocket path marks it `reconnecting` and only `inactive` once the 60 second reconnect grace expires, so a page refresh or a short network drop does not cost a player its seat. A membership created over REST does not open its socket in the same request, so it can also sit at `offline` with no disconnection moment. Those rows still hold their room open, so the system reaps them:

- **On the hot paths.** `GET /api/rooms/active/`, room join/create and match start reap before they resolve anything. Once every membership in a room is reapable, the room answers "no active room" instead of being handed to the next player, and a participant that marked ready and closed the tab is never seated in the next match.
- **At boot and on demand.** `python manage.py reap_rooms` removes stale memberships and deletes rooms left without active participants. The default run uses the grace policy; `--startup` is presence-agnostic and reaps every non-left membership in a room without an in-progress match, because nobody can hold a socket to a process that has just started.

The grace policy marks `reconnecting` and `inactive` rows stale once their `disconnected_at` is past the window, and a never-connected `offline` row once its `updated_at` is past the window; a fresh or revived `offline` arrival keeps a full window to open its socket, and `online` rows are never touched. Staleness is decided from persisted columns, never from the in-process connection registry, so the default command is safe to run from a separate process while a server is live (the presence-agnostic `--startup` run is not: it evicts lobby members on purpose and belongs at boot, before the server accepts connections). A room holding an in-progress match is always skipped, so reconnecting into a running match keeps working. Deleting an emptied room also deletes that room's match history.

Because the startup sweep is presence-agnostic, it empties every room without an in-progress match on every backend restart: lobby players re-create or re-join their room, and the client heals over REST on the reconnect path. Rooms holding an in-progress match keep their seats.

The `--startup` sweep assumes a single backend replica: a replica joining the deployment would reap memberships that are live on its sibling. Scaling the backend out, or replacing the in-memory channel layer with Redis, therefore requires persisting a last-seen timestamp per participant instead.

Until that timestamp exists, one residual remains accepted: an `online` row left behind by a process that died without running its disconnect handler survives until the next restart, because no lazy path can remove it — without a heartbeat, nothing distinguishes that row from a live socket. The presence-agnostic startup sweep is exactly what clears it at boot. A second, milder bound: writing readiness refreshes `updated_at`, so a socket-less client that keeps sending requests also keeps extending its own window.
