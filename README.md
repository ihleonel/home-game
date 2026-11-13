# HomeGame

HomeGame is a local-network game table: everyone plays from the same house, usually side by side,
and the platform exists so a family can spend an evening on a board game without the bookkeeping --
no score sheet, nobody acting as banker. That premise decides product choices that would look
strange in an online service, and the ones taken so far are recorded rather than left implicit: a
match runs without per-turn clocks, because the people at the table can nudge whoever is idle, and
the automatic endings stay reserved for a seat that really disconnects.

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

## Feature branches and worktrees

A feature is never implemented in the root checkout. Each one gets its own branch `feat/<slug>` in a worktree under `.worktrees/<slug>`, which is git-ignored; the root checkout stays on `develop` for integration. The worktree copies `.env` and `docker-compose.yml`, because both are git-ignored, and it must change `COMPOSE_PROJECT_NAME` and `FRONTEND_PORT`: sharing the pinned `home-game-local` project name makes two checkouts address the same containers, so a test run would silently grade the wrong tree. `AGENTS.md` holds the exact commands, the merge and cleanup sequence, and the artifacts that are deliberately not replicated.

## Registered games

The catalog is served from the game registry, so a game exists in HomeGame exactly when its `GameDefinition` is wired into `GAME_REGISTRY` in `backend/modules/games/composition.py`; the frontend catalog endpoint and the room entry policy both derive from it. Three games are registered:

- **`duelo`** — rock-paper-scissors, best of three, two seats.
- **`ta-te-ti`** — three in a row on a 3x3 board, two seats. The first seat plays `X` and the second plays `O`; the ficha a player chose in the room is identity only and never reaches the board. The opening turn is chosen at random per match, which is why the match composition root threads a real `RandomSource` into `start_match`; a definition whose `start` needs randomness fails loudly instead of defaulting to a fixed seat when it is missing. A full board with no line ends the match as a draw (`finished` with no `winner`), and its `abandon` resolution is the same as `duelo`'s: the seat that stayed wins by abandonment.

- **`monopoly`** — the classic property trading game, two to eight seats, on the classic
  1999-2007 rulebook: $1.500 to start, Income Tax at $200 or 10 % of total worth, Luxury Tax
  at $75. A match plays dice, movement, the GO salary, doubles (the third double in a turn goes
  straight to jail), jail, purchases, rents (a street with the complete colour set doubles its
  unimproved rent, a railroad scales with how many the owner holds and a utility pays four or
  ten times the roll), both taxes, bankruptcy and elimination. Every seat throws for the
  opening turn and the highest total opens (ties re-throw), so its definition requires a real
  `RandomSource` exactly as `ta-te-ti`'s does. Every throw the rules make -- the turn's own roll, a
  roll made from jail, the third double and the fresh throw a utility card forces -- is appended to
  the match state in play order and never truncated, while the projected view publishes only the
  newest 30: the snapshot stays bounded however long the match runs, and the whole history waits in
  the state for the end-of-match statistics that are not built yet.
  Bankruptcy follows the printed rule's creditor split: a debt to another player hands that
  player the debtor's cash and properties, while a debt to the bank takes the cash out of the
  game and returns the properties to the bank unowned -- and that last part is one of the recorded
  deviations below, since the print auctions those properties at once. An unaffordable charge opens
  the raise-cash window instead of ending the seat on the spot, so a debt reaches bankruptcy when
  the seat declares it, never automatically.
  The Chance and Community Chest decks are dealt: landing on either space turns up the top card
  of its own deck, recycles it to the bottom and announces it, and the effect lands only when the
  seat that drew it accepts the card in a dialog. A double that draws a card still gets its extra
  turn after the accept, and a card that lands the token on the other deck turns a second card up
  for its own accept. The classic United States set of 32 cards is transcribed with a test that
  pins it card by card. Everything a card prints is
  implemented: advancing to a named space and paying the GO salary when the lap wraps, the
  nearest railroad with its doubled rent, the nearest utility with its fresh throw and ten times
  the throw, going back three spaces, going to jail, the Get Out of Jail Free card a seat holds
  until it uses it, money in both directions with the bank and with every other player, and the
  repairs formula. An auction follows a declined purchase: the property goes to the bank's open
  outcry, every solvent seat that has not passed may bid -- including the one who declined -- and
  it ends when one bidder is left standing, or with the space back in the bank's hands when nobody
  bids at all. A fresh bid reopens the auction for whoever had passed, and the seat holding the
  high bid can only raise it, because a bid cannot be withdrawn. Bids climb a small ladder over
  the high bid, capped by the bidder's cash, because the runtime only accepts enumerated options
  and the printed rules allow any price.
  Building is in. A seat holding a complete colour group may raise its least developed street one
  level, and the piece comes out of the bank's finite stock of 32 houses and 12 hotels: a house for
  levels one to four, and a hotel once every street of that group carries four houses, which returns
  those four houses to the box. Houses and hotels also come down as evenly as they went up -- only
  the group's most developed street can sell, one level at a time, for half of what it cost -- and
  selling a hotel is the reverse of buying it, so it needs four houses in the bank to leave the
  property at four. A street's rent follows its level, while an unimproved lot of a complete group
  keeps charging double even when a sibling carries houses. Buildings go back to the bank when a
  seat goes bankrupt, and a player creditor also collects half of what they cost, because a property
  is never handed over with buildings on it; that is likewise what makes the repairs cards cost
  something.
  Mortgages are in. A seat may mortgage any of its unimproved properties -- no street of that
  colour group may carry a house, and a railroad or a utility needs no such check -- and collects
  the printed mortgage value from the bank while the space keeps its owner: it stays in the seat's
  estate, it still counts at its printed price for the 10 % Income Tax, and it charges no rent at
  all, so a mortgaged sibling of a complete colour group does not stop the others from charging
  double. Building on a group with a mortgaged street is refused for the same reason. Lifting a
  mortgage costs its value plus a tenth of it, rounded up to the whole dollar, and is offered only
  when the cash covers it. A seat that takes over mortgaged property -- today only through a
  bankruptcy settlement, because trading is still absent -- pays the bank that same tenth of each
  property at once and keeps them mortgaged, and a creditor who cannot afford it goes bankrupt to
  the bank, the cascade the printed rules imply: it cannot keep what it cannot sustain. The
  mortgage is a fact about the owner, not about the space: a property the bank takes back comes
  out from under its mortgage, and a debt whose creditor leaves the match is owed to the bank.
  A charge a seat cannot pay no longer ends it on the spot. The seat enters a raise-cash window
  whose only actions are selling buildings back at half price, mortgaging, paying the whole debt
  or declaring bankruptcy, and the window closes on its own terms: the turn never passes with a
  debt open and a debt never survives a change of turn. Paying resumes the step exactly as it
  would have run with the cash in hand, down to the extra roll a double had already earned and
  the throw the third jail turn was decided with. The printed rules do not cover a debt owed to
  several players at once, so a group payment is paid share by share in seat order from the top;
  the first share the cash cannot cover opens the window with the remaining shares saved, and
  paying it continues the round where it stopped, with that player as the creditor if the seat
  declares bankruptcy there. A seat that is charged while it is not on turn -- the seat on turn
  collects from everyone and some other seat cannot pay -- still goes bankrupt in the act, an
  accepted limit of a window that belongs to the turn.
  Trading is in, and it can happen at any moment. Any seat still in the match may offer another one a
  deal, in any phase, whether or not it is that seat's turn, and several offers can be open at once.
  An offer names what each side hands over -- properties and cash, either side possibly empty, but
  never both -- and the receiver of an offer can only accept it or reject it: there is no
  counteroffer, so countering means rejecting and offering again. The seat that made an offer can
  withdraw it, and an offer never expires on its own. What keeps an old offer honest is that its
  terms are checked again when it is accepted, so an offer whose properties have moved on since it
  was made is shown as no longer acceptable: offering reserves nothing. The printed rules' three
  limits hold: no street of a colour group that carries a house or a hotel can change hands (sell
  them to the bank first), there are no loans between players, and whoever receives a mortgaged
  property pays the bank its tenth of interest at once, which is why an offer that would leave a
  side unable to afford that interest cannot be accepted. A deal is agreed between two seats only:
  no three-way pacts, and the offer is the only way to negotiate, since there is no free-text
  channel. A seat with an open debt does not take part in a trade while that debt is open -- its
  ways out stay the window's four -- and an offer dies with either of its two seats, or with the
  match.
  Three deliberate deviations are recorded rather than left as missing work, because each one is a
  decision someone took and none of them is owed by a future increment: the last houses and hotels
  are not sent to auction -- when the bank's box runs out the build option is simply not offered,
  and while it still holds pieces the first seat that asks takes the piece at its printed price, so
  turn order settles who gets the last house; there is no turn clock, because everyone plays from
  the same house and the table can nudge whoever is idle, and the automatic endings stay reserved for
  a seat that really disconnects; and the properties a bankrupt seat turns over
  to the bank are not auctioned at once, but return unowned and find their owner the way any
  never-bought space does, a difference of moment rather than of economy. All three are listed with
  their decisions in `PENDING.md`.
  Its match screen is built. The board is an 11x11 grid: the 40 spaces are painted from their
  circuit index (GO bottom-right, clockwise), each one a button that announces its name, kind,
  printed price, owner and development level, carries the tokens of the seats standing on it and the
  little houses or the single hotel block a built street holds -- painted with CSS shapes on the
  inner edge of its colour band, like the printed board -- with the turn, the
  last throw, the card turned up last and the detail of the tapped space in the centre 9x9. The
  board is skinned after the printed game, and with CSS only -- no fonts, images or SVG: the
  colour band sits on the inner edge of every space instead of the outer one, the two side columns
  carry their names rotated the way the printed board reads them, every purchasable space prints
  its price, and the corners and the centre draw their own character from borders, gradients and
  type. A **seat** no longer reads that flat board: its `Tablero` is a rendered table -- the board as
  an object with an edge, on a wooden table, seen from the player's own corner at twenty degrees, the
  way the printed game looks from a chair. `three` with `react-three-fiber` draws it, and everything
  it shows is generated at mount from the project's own data: the forty cell faces and the wood are
  painted into canvases from `board.ts`, `deeds.ts` and `display.ts`, so the scene cannot disagree
  with the flat board and nothing is downloaded. The camera, its aim and the three zoom steps are
  arithmetic in `camera.ts` -- a camera moved from an effect cannot be tested, an aim that is a
  number can -- and the seat's corner comes from its seat order, because every seat starts on GO. The
  pieces stand on their cells with their own shadows, a built street carries green houses or a red
  hotel on the edge that faces the centre, and the middle of the board prints the game's name and the
  two deck piles with how many cards are left -- painted on the surface, at the size the cells print
  at, and turned so the seat reads it upright. A throw falls onto that middle as two tumbling dice
  that come to rest showing what the server rolled, and they leave when the turn moves on; the piece
  that throw moved then walks its cells one by one, or leaps once to a cell a card or the jail sent it
  to. The table turns by itself towards the piece of the player whose turn starts, follows that piece
  while it walks, and gives the player the hand back the moment they drag it. The turn,
  the last throw, the card and the tapped space sit in a thin strip under the board, not on it: at
  this angle the far edge is compressed, so a tap is what makes a space legible, and the strip is
  where that detail is read. **The flat board is still there**, for two
  reasons: a spectator gets it as the whole board, and for a seat it is the accessible mirror --
  clipped out of sight, never `display: none`, because a canvas is invisible to a screen reader and
  unreachable by the keyboard, so the forty buttons keep the tab order and the announcements, and
  focusing one selects it in the rendered table too. The loop pauses when the board tab is not the
  one open, and **with it open the scene now draws continuously**, because the pieces breathe: a
  floating token asks for the next frame itself, where the table used to render only on demand. The
  scene costs about 356 kB gzip in the single initial chunk -- the price of a
  renderer, measured rather than estimated, and the reason to code-split it behind the tab if the
  weight ever
  matters. Each piece is the marker its player chose, printed as a **flat token**: a chip of paper with
  an ink rim and the classic black silhouette on it, always facing the screen -- a billboard, so turning
  the table never shows a figure on its side -- hovering a little over its cell with a soft contact
  shadow and a slow bob that `prefers-reduced-motion` turns off. Black on white is what reads on any
  cell, whatever colour it is, which the earlier silver did not. The silhouettes are paths painted into
  a canvas when the scene mounts, so there is still no image asset: eight were traced from the sheet
  that set the look, and the iron, the boot and the neutral counter were drawn in the same weight. The
  room offers **ten markers** for a table of eight seats, because a marker reserves nothing. What it
  does not do, yet: there is no depth of field, and the framing shows the
  whole board instead of cropping it the way the reference photograph does. The board is one of the three views the player switches between, and only one of them is on
  screen at a time: `Tablero` carries the board, `Cartera` the own seat's economy -- its capital as
  a bare money value, with the label clipped out of sight instead of printed, and the jail
  restriction and the jail cards it holds only while the seat has one of them to report, because a
  fact reading "no restriction" says nothing -- then its properties grouped by colour with the level
  of each built one, told by the colour band on the cards and by the block they share, with the group
  name kept for a screen reader alone so colour is never the only channel, and `Mesa` everything the table shares -- the roster of every seat with the swatch of the tone the board paints, and how many houses and hotels are left in the bank's box. The switch is a
  client-side choice: local state that no action carries anywhere, and the same three views for a
  spectator, who still gets no button. On the board view a spectator also reads the match's throws
  in one chronological list, oldest first with the newest at the bottom: each row names the seat
  with the tone the board paints, the two faces, the total and whether the throw was a double, keyed
  by the throw's own sequence number because the published window slides and a key taken from the
  position would end up naming a different throw. The list takes its own column beside the board
  from 900px up and sits under the board on a smaller screen, with one bounded scroll that follows
  the newest throw only while the reader is already at the bottom, so scrolling up to read an older
  throw is not undone; a player never gets the list, since the seat on turn is the one acting and a
  log of everyone's throws would be a fourth thing to read while the turn waits. Above the strip sits the seat's own colour in a chip that
  belongs to no view: the swatch, the initial and the name, pinned to the top edge of the screen, so
  switching view or scrolling the board never takes the reference away -- the roster that spells out
  which tone is whose lives in one view of three, and the owner badge on a cell is too small to be
  the answer. The offered actions and the open debt deliberately stay
  **outside** the views, between the strip and the open one, so they are on screen whichever view
  the player is in and a view change can never hide an obligation the seat still has to answer; the
  `Mesa` tab carries the count of the offers waiting in it and the `Cartera` tab the count of the
  actions waiting on the seat's own properties, so neither an offer nobody has answered nor an
  action waiting on a property can go silently out of sight. On a phone that pair moves to the last
  row of the panel and sticks to the bottom edge of the screen, inside the thumb's reach, so the
  throw is one tap away instead of one scroll away; the move is a stylesheet `order`, so the markup
  order and with it the keyboard and screen-reader path are the ones S5 always had -- a phone draws
  the bar last while the focus order still meets it first, the one difference the trick buys and the
  reason it stays off every other width -- and because the bar stays in the panel's flow, with
  nothing to reserve and no guessed height, the page can still be scrolled far enough to show the
  board's last row and the strip under it, the bar coming to rest on the screen's edge instead of
  jumping off it. The panel is dressed in the game's own bright palette: a sunny
  chrome, the brand red on the open tab, on the offers badge and on every button the player acts
  with, the dollar green on money, and the eight canonical colour groups of the printed board --
  brighter than the muted values this screen used to carry and, at the same time, closer to the
  print -- on the board's bands and on the left edge of each property card, painted from the colour
  key the board itself publishes instead of from a second copy of that table. The four actions that
  act on one property live on that property's card: the server offers `build` and `sell` with the
  streets it will accept and `mortgage` and `unmortgage` with the spaces it will accept, and the
  wallet draws one button per offered option on the card of the space it names, labelled with the
  server's own verb and the money the option moves, because the card already says the property. The
  strip keeps whatever no card claimed -- an option that is not a board index, an index this seat
  does not own, or a `build`/`sell` option that does not name a street -- under the label it always
  had, so an option the client cannot place never leaves the screen. The panel still never decides
  which options are legal nor whether the level being raised is a house or a hotel, and it still
  prices nothing the server did not offer. A mortgaged space wears a diagonal grey stripe over its
  colour band -- or over
  the band strip the cell already reserves when it is a railroad or a utility, which this skin
  leaves band-less -- with its printed price struck through, `Hipotecada` in its accessible name
  and its value and its lift cost in the centre detail; its own property row carries a mortgaged
  badge, and the raise-cash window shows the open debt above the actions, with the amount and the
  creditor by display name. Trading is composed in `Mesa` too: the panel offers the block when the
  server offers `propose`, the seat picks the receiver among the other seats still in the match,
  marks its own properties to give and that receiver's to ask for, sets the two cash amounts within
  the cash the view shows, and one button composes the value the server grades; the open offers are
  listed with their terms, which side each piece belongs to and the validity the server published,
  and accept and reject are offered to the receiver while withdraw is offered to the proposer,
  never a button the server did not offer. The board is read-only on purpose -- buying, building,
  mortgaging and trading belong to the offered actions and to `Mesa` -- and the panel submits the
  actions it was handed and
  never
  decides which ones are legal, so a spectator sees the same board and no buttons at all. The
  board's static data (the 40 spaces and the 22 deeds) is duplicated in TypeScript with a
  fidelity test on each side, so it does not travel in every match frame. What the tests do not
  reach is the CSS itself: the view strip's look, the bright palette and the light tints the wallet
  cards wear, the `hidden` rule that takes the two closed views off the screen -- the tests reach the
  attribute, never the `display` it has to resolve to -- the token wrapping, the colour bands and the
  little houses and hotel block, and the mortgaged stripe and its struck price over them, are
  verified in the markup they hang on, not in a browser; the same goes for the phone's bottom action
  bar, whose `position: sticky`, `order` and compact padding no test resolves, and for the drawn
  card's dialog, whose fixed overlay, dimming and centring no test resolves either -- the tests reach
  its role, its labels and the accept it submits. The palette's
  contrast is the one part of that CSS which is measured instead of looked at: every text/background
  pair it introduces is checked against WCAG AA (36 pairs with the phone bar's debt line on the
  sunny chrome, worst 5.39:1, and that last pair about 14:1), because a bright palette is exactly
  where contrast breaks silently and the value is arithmetic rather than taste.

A finished match reports one of `three_in_a_row`, `draw`, `last_solvent` or `win_by_abandon` as
its outcome reason (`duelo` reports `best_of_three` or `win_by_abandon`; `monopoly` reports
`last_solvent` or `win_by_abandon`).

## Ghost rooms and ghost memberships

A participant that disconnects is not removed immediately: the WebSocket path marks it `reconnecting` and only `inactive` once the 60 second reconnect grace expires, so a page refresh or a short network drop does not cost a player its seat. A membership created over REST does not open its socket in the same request, so it can also sit at `offline` with no disconnection moment. Those rows still hold their room open, so the system reaps them:

- **On the hot paths.** `GET /api/rooms/active/`, room join/create and match start reap before they resolve anything. Once every membership in a room is reapable, the room answers "no active room" instead of being handed to the next player, and a participant that marked ready and closed the tab is never seated in the next match.
- **At boot and on demand.** `python manage.py reap_rooms` removes stale memberships and deletes rooms left without active participants. The default run uses the grace policy; `--startup` is presence-agnostic and reaps every non-left membership in a room without an in-progress match, because nobody can hold a socket to a process that has just started.

The grace policy marks `reconnecting` and `inactive` rows stale once their `disconnected_at` is past the window, and a never-connected `offline` row once its `updated_at` is past the window; a fresh or revived `offline` arrival keeps a full window to open its socket, and `online` rows are never touched. Staleness is decided from persisted columns, never from the in-process connection registry, so the default command is safe to run from a separate process while a server is live (the presence-agnostic `--startup` run is not: it evicts lobby members on purpose and belongs at boot, before the server accepts connections). A room holding an in-progress match is skipped by the reaping, after any seat of that match whose expiry is already recorded is resolved first (see Mid-match disconnection), so reconnecting into a running match keeps working. Deleting an emptied room also deletes that room's match history.

An absent member of a **lobby** no longer waits for a human to start a vote. The same sweep that reaps decides whether the room still has somebody to vote: with at least two connected participants left besides the absent ones it opens **one automatic vote whose subject is all of them at once**, so a single round clears every ghost, and unanimity decides -- one `no` rejects the whole batch. A rejected vote spends that absence, so the next sweep removes the membership anyway, which is why the rejection message no longer promises that the player stays. With fewer than two connected participants there is nothing to vote with and the sweep simply reaps, so a room nobody is watching still empties itself and a room that is watched is decided by the people in it. A never-connected membership is never a vote target -- it never had a socket to lose -- and is only ever reaped; a member whose vote is already pending is left alone until that vote resolves, and a new absence waits for the next sweep rather than joining a vote whose subject is already set; and a room holding a match in progress is skipped exactly as before, so the vote governs the lobby while a match seat keeps its own 60 second rule. Nothing new schedules this: the vote opens on the same hot paths that already reap, and from `reap_rooms`.

A room snapshot carries `remaining_seconds` for every participant, computed by the server with the same rule as a match seat's window (S8): the whole seconds left before a `reconnecting` member is expelled, and `null` for anyone else. The room list replays that value locally next to the `Reconectando…` badge -- in its own `role="timer"` element, so the changing number is not announced once per second -- instead of waiting for a new frame. A `0` means the window is over, not that the member left at that instant: the removal still arrives as the `inactive` event or from the next reap.

Because the startup sweep is presence-agnostic, it empties every room without an in-progress match on every backend restart: lobby players re-create or re-join their room, and the client heals over REST on the reconnect path. Rooms holding an in-progress match keep their seats.

The `--startup` sweep assumes a single backend replica: a replica joining the deployment would reap memberships that are live on its sibling. Scaling the backend out, or replacing the in-memory channel layer with Redis, therefore requires persisting a last-seen timestamp per participant instead.

Until that timestamp exists, one residual remains accepted: an `online` row left behind by a process that died without running its disconnect handler survives until the next restart, because no lazy path can remove it — without a heartbeat, nothing distinguishes that row from a live socket. The presence-agnostic startup sweep is exactly what clears it at boot. A second, milder bound: writing readiness refreshes `updated_at`, so a socket-less client that keeps sending requests also keeps extending its own window.

## Mid-match disconnection

A player that closes the tab in the middle of a match does not leave the match hanging. The reconnect grace still applies: the socket path marks the seat `reconnecting`, and every other seat of the running match learns it in the match's own messages — `match.snapshot` carries a `seats` list and `match.presence` announces every change — so the game screen says an opponent is disconnected without the game knowing anything about presence, and a player that reconnects inside the window gets its seat and its match back. A seat whose membership **never opened a socket** -- somebody who joined and marked ready over REST while the socket never connected -- is resolved by that same window, measured from its last write instead of from a disconnection it never had. Without it the seat would have no way out at all: a ready member cannot leave the room, the reaper skips a room holding a match in progress, and the automatic vote never targets a membership that never connected, so the match would wait forever for somebody who is not there.

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

An explicit `as_spectator` entry may omit both `display_name` and `game_marker`: the platform assigns the missing ones before the participant is created. The name is the first free `Espectador N` in the room, and the marker is the first seat option of the game the room is not using, falling back to the game's first option when every marker is taken. A value the caller does send is kept, so only the missing one is assigned. The room snapshot returns the resolved identity and the client reads it back instead of keeping the empty draft. A player entry still requires both fields (`400` with `{'display_name': ..., 'game_marker': ...}`), and a platform-assigned identity is never stored as the guest's own name and marker for a later room.

A spectator is a member of the room with no seat, not a separate connection path. It cannot be marked ready (`PATCH /api/rooms/ready/` answers `409`, `Estás como espectador: no puedes marcarte como listo.`), it is not an expulsion-vote target and never joins the electorate, and it never occupies a seat: `open_match_for_room` builds seats only from ready players. It does see the running match — `resolve_seat_subscription` already projects the public view to a participant with no seat — and it leaves through the ordinary `POST /api/rooms/leave/`.

A spectator can ask for a seat with `POST /api/rooms/play/` (`{'session_id': ...}`). The request is granted only in a lobby: never while a match is `in_progress`, because the seats are fixed when the match opens, and never when the player roster is already at `max_seats`. Otherwise the role becomes `player`, readiness stays `false`, and the room broadcasts `player_promoted`. The room snapshot carries `participants[].role` and a top-level `seat_limits` (`{'min_seats', 'max_seats'}`, or `null` for an unknown game), both on the REST read and on the socket, so the lobby can offer the action only when it can succeed.

On screen, a spectator sees the lobby read-only with the notice `Estás como espectador.` and a `Quiero jugar` button that is enabled only while a seat is free, with the exact reason otherwise; the identity form offers `Entrar como espectador` from both the catalog and the lobby without asking for a ficha, and the game screen labels a seatless viewer for every game.

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
…) and never redefine a global token in `:root`. It declares its own theme
scope instead: `duelo` sets namespaced custom properties (`--duelo-rock`,
`--duelo-ink-soft`, `--duelo-arena`, …) on its own panel, so custom properties
cascade only inside that panel and each game can look completely different
without a shared design system. Colour is never the only cue a game uses: every
play carries its own silhouette and its own visible label beside its hue, which
is what keeps the panel readable for a player who cannot tell the hues apart.
Motion is additive and the global `prefers-reduced-motion` block in
`src/index.css` neutralises it. The game screen itself is styled
by `.match-screen` in `src/App.css`; a game only styles the panel it renders
inside it.
