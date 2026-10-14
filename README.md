# HomeGame

## Prerequisites

- Docker Engine with the Docker Compose plugin
- A configured `.env` file in the repository root

Use `.env.example` as a reference when configuring `.env`. Set the variables required by `docker-compose.yml` before running any Compose commands. Keep `.env` private and do not commit it.

## Usage

From the repository root:

```sh
make up            # Build and start db, backend, and frontend in the background
make migrate       # Apply Django migrations in the running backend container
make test          # Run Django tests in the running backend container
make test-frontend # Run the frontend tests in the running frontend container
```

The backend startup command already applies migrations before starting Daphne. Run `make migrate` to apply migrations explicitly; `make migrate` and `make test` require the backend container to be running, and `make test-frontend` requires the frontend container to be running. The frontend suite runs on Vitest in a Node environment against `react-dom/server`, so it needs no browser and no DOM library.

## Ghost rooms and ghost memberships

A participant that disconnects is not removed immediately: the WebSocket path marks it `reconnecting` and only `inactive` once the 60 second reconnect grace expires, so a page refresh or a short network drop does not cost a player its seat. A membership created over REST does not open its socket in the same request, so it can also sit at `offline` with no disconnection moment. Those rows still hold their room open, so the system reaps them:

- **On the hot paths.** `GET /api/rooms/active/`, room join/create and match start reap before they resolve anything. Once every membership in a room is reapable, the room answers "no active room" instead of being handed to the next player, and a participant that marked ready and closed the tab is never seated in the next match.
- **At boot and on demand.** `python manage.py reap_rooms` removes stale memberships and deletes rooms left without active participants. The default run uses the grace policy; `--startup` is presence-agnostic and reaps every non-left membership in a room without an in-progress match, because nobody can hold a socket to a process that has just started.

The grace policy marks `reconnecting` and `inactive` rows stale once their `disconnected_at` is past the window, and a never-connected `offline` row once its `updated_at` is past the window; a fresh or revived `offline` arrival keeps a full window to open its socket, and `online` rows are never touched. Staleness is decided from persisted columns, never from the in-process connection registry, so the default command is safe to run from a separate process while a server is live (the presence-agnostic `--startup` run is not: it evicts lobby members on purpose and belongs at boot, before the server accepts connections). A room holding an in-progress match is skipped by the reaping, after any seat of that match whose expiry is already recorded is resolved first (see Mid-match disconnection), so reconnecting into a running match keeps working. Deleting an emptied room also deletes that room's match history.

A room snapshot carries `remaining_seconds` for every participant, computed by the server with the same rule as a match seat's window (S8): the whole seconds left before a `reconnecting` member is expelled, and `null` for anyone else. The room list replays that value locally next to the `Reconectando…` badge -- in its own `role="timer"` element, so the changing number is not announced once per second -- instead of waiting for a new frame. A `0` means the window is over, not that the member left at that instant: the removal still arrives as the `inactive` event or from the next reap.

Because the startup sweep is presence-agnostic, it empties every room without an in-progress match on every backend restart: lobby players re-create or re-join their room, and the client heals over REST on the reconnect path. Rooms holding an in-progress match keep their seats.

The `--startup` sweep assumes a single backend replica: a replica joining the deployment would reap memberships that are live on its sibling. Scaling the backend out, or replacing the in-memory channel layer with Redis, therefore requires persisting a last-seen timestamp per participant instead.

Until that timestamp exists, one residual remains accepted: an `online` row left behind by a process that died without running its disconnect handler survives until the next restart, because no lazy path can remove it — without a heartbeat, nothing distinguishes that row from a live socket. The presence-agnostic startup sweep is exactly what clears it at boot. A second, milder bound: writing readiness refreshes `updated_at`, so a socket-less client that keeps sending requests also keeps extending its own window.

## Mid-match disconnection

A player that closes the tab in the middle of a match does not leave the match hanging. The reconnect grace still applies: the socket path marks the seat `reconnecting`, and every other seat of the running match learns it in the match's own messages — `match.snapshot` carries a `seats` list and `match.presence` announces every change — so the game screen says an opponent is disconnected without the game knowing anything about presence, and a player that reconnects inside the window gets its seat and its match back.

Each seat entry also carries `remaining_seconds`, the whole seconds the server still grants that seat's window. The server computes that number so the screen never depends on the browser's clock, and it is `null` unless the seat is reconnecting inside its window. The match screen counts it down locally from that value instead of waiting for a new frame, and renders the ticking number in its own `role="timer"` line, so a screen reader can read it on demand rather than being interrupted once per second. A `0` means the window is over, not that the seat was expelled at that instant: the resolution still arrives as the `inactive` and match-finish events, or from the sweep on the next read.

When the grace expires without a reconnect, the seat is expelled automatically, without a vote. What that expulsion does to the match is the game's own decision: `GameDefinition.abandon` is a required part of the game contract, and the runtime only delegates to it and then reads the resulting state, status and winner. `duelo` declares that the seat that stayed wins by abandonment (`win_by_abandon`); the game view marks that ending with `ended_by_abandon`, so the screen can tell it from a normal finish even when a client only receives a snapshot after reconnecting. A future multi-seat game declares its own resolution there — keep playing without the seat, or fold the abandoned seat's points and resources back in. A definition whose `abandon` does not end the match must tolerate the same seat being abandoned twice, because the two triggers below are independent.

Resolving the seat is what unblocks the room. Once the match is no longer `in_progress`, the reaping of the same read removes the ghost membership, the room resets its readiness for a rematch, and the remaining player is back in a usable lobby.

There are two triggers, and the second exists because the first lives in the process:

- The reconnect grace timer resolves the seat when it expires, while the process that owns the timer is alive.
- The read paths that already reap (`GET /api/rooms/active/` and `python manage.py reap_rooms`) resolve every seat whose expiry is already recorded before they reap, so a backend restart in the middle of the grace window — which loses the timer — cannot leave the match `in_progress` and its room unreapable. The sweep runs before the reap on purpose: finishing the match is what lets that same read clean the ghost membership it just unblocked.

Three limits stay accepted. A process that dies without running its disconnect handler leaves the seat row `online`, so no seat sees a disconnect until that client reconnects or the next restart sweeps it — the same bounded residual the section above describes. `--startup` deliberately does not resolve running matches: at boot no socket can exist, so "nobody is connected" cannot tell an interrupted match from a live one and resolving there would destroy in-progress matches on a rolling restart. And a seat whose membership never held a socket (`offline` from a REST arrival) is left to the pre-existing reaping window instead of being resolved here.

## Lobby countdown

The lobby has no manual start button. A room starts its match automatically once its active roster is exactly the game's seat count (`min_seats <= participants <= max_seats`, 2 for Duelo) and every participant is ready. At that moment the room arms a 10 second countdown and announces it to every socket as `match_countdown`, with the total `seconds` and the `remaining_seconds` still on the clock; a socket that connects or reconnects while the countdown is running receives the same `remaining_seconds`, so a refresh does not reset the clock.

The timer is in-process, like the reconnect grace timer, and carries the same single-replica assumption: scaling the backend out, or replacing the in-memory channel layer with Redis, requires moving the armed countdown into shared state.

The countdown is cancelled and re-armed, never run twice. Any roster change that leaves the lobby no longer fully ready cancels the armed countdown and broadcasts `match_countdown_cancelled` with reason `lobby_changed`; once the roster is fully ready again, a fresh `match_countdown` is announced. When the countdown expires, the room opens the match and each socket receives its own `match.snapshot`.

The countdown is the only way a match starts on every path: the API serves no manual start route, so the room owns the start decision and no single participant can open a match alone. `GET /api/matches/<match_ref>/` (resync) and `POST /api/matches/<match_ref>/actions/` remain the only match endpoints.

## Full rooms and spectators

A room that already holds the game's `max_seats` players, or whose match is already in progress, does not turn a late arrival away and does not let it break the lobby: the new session joins as a **spectator**. The same policy answers both cases, and it is derived from the game contract (`GameDefinition.min_seats`/`max_seats`) plus the room's match state, so every registered game resolves entry the same way. Entry order is: an explicit `as_spectator` request, an in-progress match, a full player roster, otherwise a player. A session that already has a membership keeps the role it was given; the only role change is an explicit promotion.

A spectator is a member of the room with no seat, not a separate connection path. It cannot be marked ready (`PATCH /api/rooms/ready/` answers `409`, `Estás como espectador: no puedes marcarte como listo.`), it is not an expulsion-vote target and never joins the electorate, and it never occupies a seat: `open_match_for_room` builds seats only from ready players. It does see the running match — `resolve_seat_subscription` already projects the public view to a participant with no seat — and it leaves through the ordinary `POST /api/rooms/leave/`.

A spectator can ask for a seat with `POST /api/rooms/play/` (`{'session_id': ...}`). The request is granted only in a lobby: never while a match is `in_progress`, because the seats are fixed when the match opens, and never when the player roster is already at `max_seats`. Otherwise the role becomes `player`, readiness stays `false`, and the room broadcasts `player_promoted`. The room snapshot carries `participants[].role` and a top-level `seat_limits` (`{'min_seats', 'max_seats'}`, or `null` for an unknown game), both on the REST read and on the socket, so the lobby can offer the action only when it can succeed.

On screen, a spectator sees the lobby read-only with the notice `Estás como espectador.` and a `Quiero jugar` button that is enabled only while a seat is free, with the exact reason otherwise; the identity form offers `Entrar como espectador` from both the catalog and the lobby, and the game screen labels a seatless viewer for every game.

## Player identity on the match screen

A running match names each seat with its player, not with a seat number. That identity is owned by the backend: for every seat it resolves the `seat_id`, its `index`, the seated participant's current `display_name` and `game_marker`, and the `game_marker_label` looked up centrally in the game's own `seat_options` catalog (`seat_id`, `index`, `display_name`, `game_marker`, `game_marker_label`). When the marker does not belong to that catalog, or the game is unknown, the raw marker id is exposed instead, so an entry never loses its marker.

The list travels as the additive `roster` field of the match projection. It is a sibling of the presence payload in the `match.snapshot` frame, and both REST responses carry it: `POST /api/matches/<match_ref>/actions/` and `GET /api/matches/<match_ref>/` (resync). The presence payload (`seats`) and the room roster are unchanged. Because the list carries public identity only and no hidden play, a seat and a spectator receive exactly the same `roster`; only the `view` is scoped to the seat.

The game screen renders that roster and derives nothing from it: a seat reads as the server-sent name plus its marker chip, the viewer's own seat carries the `(tú)` suffix, and a seat the roster does not name falls back to the neutral `Jugador` rather than to a fabricated seat number. Sentences, such as the match outcome and the reveal winner, use `display_name (game_marker_label)`, with the viewer's own seat marked `(tú)` there as well.

Two wordings stay generic by design: the disconnection and abandonment notices on the game screen say `Tu rival` / `Un jugador`, because naming the opponent would require the client to work out which roster entry is the rival. A backend-projected opponent field can add that later without a client change.

## Frontend

The frontend is a single-page app with three routes, all served by one React
tree and one WebSocket per session:

| Route | View |
| --- | --- |
| `/` | The game catalog. Choosing a game creates or joins its room. |
| `/rooms/:gameId` | The waiting room: roster, readiness, expulsion vote and the lobby countdown. |
| `/games/:gameId/match` | The game screen: the running (or finished) match and nothing else. |

Navigation is client-side only. `App` mounts `BrowserRouter` around
`CatalogProvider` and `RoomSessionProvider`, which in turn wrap the routes, so
the room session, the match state and the socket live above them and moving
between pages never remounts the providers or closes the socket. The views are guard-driven: a room hands the view to its lobby,
a lobby with a live match hands it to the game screen, the game screen returns
to its room when there is no match, and any unknown path returns to the
catalog. A game without a renderer keeps its "vista de partida no disponible"
notice in the lobby instead, and so does a frame its own parser does not
recognize, so a match can never trap a player on a screen the app cannot draw.

### Adding a game's screen

A game's screen lives in its own folder under `src/games/<game_id>/` and is
registered in `src/games/registry.ts` under its `game_id`:

| File | Responsibility |
| --- | --- |
| `<Game>Match.tsx` | The panel, typed with the game's own view |
| `view.ts` | The game's view type and the parser that recognizes its payload |
| `screen.tsx` | The registry entry: parse the raw view, then render the panel or return `null` |
| `<game>.css` | The game's own stylesheet |

The registry maps a `game_id` to that factory, and it is the only place that
maps a game to its screen. The factory is what keeps the payload honest: the
view arrives unvalidated over REST and the socket, so the game's parser either
recognizes it or the registry returns `null` and the caller renders its own
notice. A game therefore never receives bytes it did not recognize, and a
malformed frame cannot crash the page.

The types are split the same way. `MatchRuntimeView` in `src/games/registry.ts`
holds the fields every view carries, because the match screen reads them for
every game (`finished`, `winner`, `ended_by_abandon`, `you`). A game's view
extends it with its own play payload -- `DueloView` adds `round`, `scores`,
`reveal`, `your_pick`, ... -- so adding a game never widens a shared view and
never asks another game's screen to tolerate fields it does not own.

A parser rejects a payload that is not its game's view, which is what the
notice covers, but past the fields that identify it, it degrades instead of
rejecting: a malformed optional field costs that field, not the whole match
screen. The roster and presence parsers in `src/games/` follow the same rule.

Per-game CSS shares one global stylesheet once Vite bundles it, so a game must
prefix every class it owns with its own id (`.duelo-panel`, `.duelo-heading`,
…) and reuse the theme tokens from `src/index.css` (`--surface`, `--ink`,
`--accent`, …) rather than redefining colors. The game screen itself is styled
by `.match-screen` in `src/App.css`; a game only styles the panel it renders
inside it.
