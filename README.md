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

A participant that disconnects is not removed immediately: the WebSocket path marks it `reconnecting` and only `inactive` once the 60 second reconnect grace expires, so a page refresh or a short network drop does not cost a player its seat. Those rows still hold their room open, so the system reaps them:

- **On the hot paths.** `GET /api/rooms/active/`, room join/create and match start reap before they resolve anything. A room with nobody left answers "no active room" instead of being handed to the next player, and a participant that marked ready and closed the tab is never seated in the next match.
- **At boot and on demand.** `python manage.py reap_rooms` removes stale memberships and deletes rooms left without active participants. Add `--startup` to ignore the grace window; the Compose backend command runs that sweep before starting the server, because the grace timers live in process memory and do not survive a restart.

Staleness is decided from the persisted `presence` and `disconnected_at` columns, never from the in-process connection registry, so the command is safe to run from a separate process while a server is live. A room holding an in-progress match is always skipped, so reconnecting into a running match keeps working. Deleting an emptied room also deletes that room's match history.

The `--startup` sweep assumes a single backend replica: a replica joining the deployment would reap memberships that are live on its sibling. Scaling the backend out, or replacing the in-memory channel layer with Redis, therefore requires persisting a last-seen timestamp per participant instead.
