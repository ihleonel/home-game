import type { MatchRuntimeView } from '../registry'
import { BOARD_SIZE } from './board'
import { HOTEL_LEVEL } from './deeds'

/**
 * The phases the rules persist (S6 of ``monopoly.md`` plus the bidding phase
 * the auction increment adds, S2 of ``monopoly-auction.md``).
 *
 * The parser only accepts these: a phase it does not know would leave the
 * screen offering actions no transition understands.
 */
export type MonopolyPhase = 'awaiting_roll' | 'awaiting_decision' | 'awaiting_bid' | 'managing'

const PHASES: readonly string[] = ['awaiting_roll', 'awaiting_decision', 'awaiting_bid', 'managing']

/** One seat as the public economy of a match reports it. */
export type MonopolyPlayer = {
  seat: string
  cash: number
  position: number
  properties: number[]
  in_jail: boolean
  jail_turns: number
  /**
   * How many Get Out of Jail Free cards the seat holds (S12).
   *
   * It is a count, never the card ids: which cards a hand holds is the seat's
   * own business, and the table only sees the size of the hand.
   */
  jail_cards: number
  eliminated: boolean
}

/**
 * How many cards remain face down in each deck (S12).
 *
 * The deck *order* is hidden state and never reaches a view. These two counts
 * are all the table learns, and they are what the piles' thickness shows.
 */
export type MonopolyDecks = {
  chance: number
  community_chest: number
}

/** The card turned up last, resolved to the copy a player reads (S12). */
export type MonopolyLastCard = {
  deck: string
  id: string
  title: string
}

/**
 * How much of the finite building stock is left in the bank's box (S8).
 *
 * The game starts with 32 houses and 12 hotels and every build and sell moves
 * one of these counts, so the pair is what makes the printed scarcity visible.
 */
export type MonopolyBank = {
  houses: number
  hotels: number
}

/**
 * One action the server offered this seat.
 *
 * ``options`` is enumerated by the server: the runtime rejects a value it did
 * not offer, so a screen never invents one. An empty list means the action
 * carries no value.
 */
export type MonopolyAction = {
  name: string
  prompt: string
  options: string[]
}

/** The decision a landed space opened and the turn is waiting on. */
export type MonopolyPending = {
  kind: 'purchase' | 'income_tax'
  space: number
}

/**
 * The open auction of a declined property (S7).
 *
 * The bids themselves are not here: they travel as the eligible seats' own
 * ``bid`` and ``pass`` actions. This field is only what the whole table sees --
 * the space, the standing high bid and its holder, and who is still to bid.
 */
export type MonopolyAuction = {
  space: number
  high_bid: number
  high_bidder: string | null
  waiting_for: string[]
}

/**
 * The monopoly play payload, on top of the runtime fields every view carries.
 *
 * ``finished``, ``winner``, ``ended_by_abandon`` and ``you`` stay in
 * :type:`MatchRuntimeView` because the match screen reads them for every game.
 * Everything declared here belongs to ``monopoly`` and nowhere else.
 *
 * The public economy is all of it: what makes a view a *seat's* view is its
 * ``actions``, which only the seat on turn receives. A spectator payload has no
 * ``you`` and an empty ``actions`` list.
 */
export type MonopolyView = MatchRuntimeView & {
  phase: MonopolyPhase
  turn: string | null
  players: MonopolyPlayer[]
  owners: Record<string, string>
  last_roll: number[] | null
  pending: MonopolyPending | null
  decks: MonopolyDecks | null
  last_card: MonopolyLastCard | null
  /**
   * The development level of every built street (S8), keyed by board index as
   * a string because the state is ``jsonb``. An unbuilt street has no key and
   * an empty map means nothing is built anywhere. Read it with
   * ``String(index)``.
   */
  buildings: Record<string, number>
  bank: MonopolyBank | null
  auction: MonopolyAuction | null
  actions: MonopolyAction[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value)
}

/** A board index this screen can actually paint, or ``null``. */
function isBoardIndex(value: unknown): value is number {
  return isInteger(value) && value >= 0 && value < BOARD_SIZE
}

/** Read one seat, or ``null`` when a field the board needs is missing. */
function readPlayer(value: unknown): MonopolyPlayer | null {
  if (!isRecord(value)) return null
  const { seat, cash, position, properties, in_jail, jail_turns, jail_cards, eliminated } = value
  if (typeof seat !== 'string' || seat.length === 0) return null
  if (!isInteger(cash) || !isBoardIndex(position)) return null
  if (!Array.isArray(properties)) return null
  const owned: number[] = []
  for (const index of properties) {
    if (!isBoardIndex(index)) return null
    owned.push(index)
  }
  if (typeof in_jail !== 'boolean') return null
  if (!isInteger(jail_turns) || jail_turns < 0) return null
  if (typeof eliminated !== 'boolean') return null
  // A card count is a small fact next to the seat: losing it costs a number,
  // not the table, and ``0`` is the honest reading of a hand nobody counted.
  const held = isInteger(jail_cards) && jail_cards >= 0 ? jail_cards : 0
  return {
    seat,
    cash,
    position,
    properties: owned,
    in_jail,
    jail_turns,
    jail_cards: held,
    eliminated,
  }
}

/**
 * Read the remaining deck sizes, or ``null``.
 *
 * All-or-nothing by design: half a deck count would show a table a thickness
 * the server never reported, so one bad count drops both piles rather than
 * leaving the other one looking authoritative.
 */
function readDecks(value: unknown): MonopolyDecks | null {
  if (!isRecord(value)) return null
  const { chance, community_chest } = value
  if (!isInteger(chance) || chance < 0) return null
  if (!isInteger(community_chest) || community_chest < 0) return null
  return { chance, community_chest }
}

/**
 * Read the development level of every built street (S12).
 *
 * All-or-nothing, like ``decks``: a key that is not a board index or a level
 * that is not an integer from one to five drops the **whole** map to ``{}``
 * rather than keeping the entries it recognized. A payload without the field
 * is simply unbuilt, which is what an old payload and an untouched board both
 * mean. The keys stay strings because the state is ``jsonb``; the board reads
 * them with ``String(index)``.
 */
function readBuildings(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {}
  const buildings: Record<string, number> = {}
  for (const [key, level] of Object.entries(value)) {
    if (!/^\d+$/.test(key) || !isBoardIndex(Number(key))) return {}
    if (!isInteger(level) || level < 1 || level > HOTEL_LEVEL) return {}
    buildings[key] = level
  }
  return buildings
}

/**
 * Read the building stock left in the bank, or ``null`` (S12).
 *
 * Two integer counts, zero or more; a missing or malformed object is ``null``
 * and the panel omits its block rather than printing a number nobody sent.
 */
function readBank(value: unknown): MonopolyBank | null {
  if (!isRecord(value)) return null
  const { houses, hotels } = value
  if (!isInteger(houses) || houses < 0) return null
  if (!isInteger(hotels) || hotels < 0) return null
  return { houses, hotels }
}

/** Read the last card turned up, or ``null`` when nothing usable was drawn. */
function readLastCard(value: unknown): MonopolyLastCard | null {
  if (!isRecord(value)) return null
  const { deck, id, title } = value
  if (typeof deck !== 'string' || deck.length === 0) return null
  if (typeof id !== 'string' || id.length === 0) return null
  if (typeof title !== 'string') return null
  return { deck, id, title }
}

/**
 * Read the roster, in seat order.
 *
 * Unlike an optional field, a malformed entry here costs the whole view: a
 * board missing one player's token would be a lie about the match, and this
 * parser exists so the screen never renders bytes it did not recognize.
 */
function readPlayers(value: unknown): MonopolyPlayer[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  const players: MonopolyPlayer[] = []
  for (const entry of value) {
    const player = readPlayer(entry)
    if (player === null) return null
    players.push(player)
  }
  return players
}

/**
 * Read the owner map, keyed by board index as a string.
 *
 * A key that is not a board index is dropped rather than kept: the board could
 * never paint it, and keeping it would put an unrenderable owner in the view.
 * A value that is not a seat id is a malformed payload and costs the view,
 * because guessing which seat owns a property is worse than showing nothing.
 */
function readOwners(value: unknown): Record<string, string> | null {
  if (!isRecord(value)) return null
  const owners: Record<string, string> = {}
  for (const [key, owner] of Object.entries(value)) {
    if (typeof owner !== 'string' || owner.length === 0) return null
    if (!/^\d+$/.test(key) || !isBoardIndex(Number(key))) continue
    owners[key] = owner
  }
  return owners
}

/** Read the last throw: exactly two faces from one to six, or nothing. */
function readRoll(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length !== 2) return null
  const faces: number[] = []
  for (const face of value) {
    if (!isInteger(face) || face < 1 || face > 6) return null
    faces.push(face)
  }
  return faces
}

/** Read the pending decision, or ``null`` when there is none to act on. */
function readPending(value: unknown): MonopolyPending | null {
  if (!isRecord(value)) return null
  const { kind, space } = value
  if (kind !== 'purchase' && kind !== 'income_tax') return null
  if (!isBoardIndex(space)) return null
  return { kind, space }
}

/**
 * Read the open auction, or ``null``.
 *
 * All-or-nothing by design: a half-read auction would show a table a standing
 * bid or a waiting list the server never reported, so one bad field drops the
 * whole auction rather than leaving the rest of it looking authoritative. The
 * amounts travel as the seats' own actions, so nothing here computes a bid.
 */
function readAuction(value: unknown): MonopolyAuction | null {
  if (!isRecord(value)) return null
  const { space, high_bid, high_bidder, waiting_for } = value
  if (!isBoardIndex(space)) return null
  if (!isInteger(high_bid) || high_bid < 0) return null
  if (!(high_bidder === null || (typeof high_bidder === 'string' && high_bidder.length > 0))) {
    return null
  }
  if (!Array.isArray(waiting_for)) return null
  const waiting: string[] = []
  for (const seat of waiting_for) {
    if (typeof seat !== 'string' || seat.length === 0) return null
    waiting.push(seat)
  }
  return { space, high_bid, high_bidder, waiting_for: waiting }
}

/** Read one offered action, or ``null`` when it could not be submitted. */
function readAction(value: unknown): MonopolyAction | null {
  if (!isRecord(value)) return null
  const { name, prompt, options } = value
  if (typeof name !== 'string' || name.length === 0) return null
  if (typeof prompt !== 'string') return null
  const offered: string[] = []
  if (options !== undefined) {
    if (!Array.isArray(options)) return null
    for (const option of options) {
      if (typeof option !== 'string') return null
      offered.push(option)
    }
  }
  return { name, prompt, options: offered }
}

/**
 * Read the actions this seat was offered, dropping the ones that are malformed.
 *
 * An action is a small thing next to the board: losing one costs a button, not
 * the match screen, so this degrades field by field where the roster does not.
 */
function readActions(value: unknown): MonopolyAction[] {
  if (!Array.isArray(value)) return []
  const actions: MonopolyAction[] = []
  for (const entry of value) {
    const action = readAction(entry)
    if (action !== null) actions.push(action)
  }
  return actions
}

/**
 * Read the raw payload the runtime projected as a ``monopoly`` view.
 *
 * ``null`` means the payload is **not** a ``monopoly`` view: it is not an
 * object, or it is missing a field that identifies it -- the runtime fields
 * every view carries (``finished``, ``winner``) plus ``monopoly``'s own
 * ``phase``, ``players`` and ``owners``. The caller falls back to its own
 * notice instead of rendering a board over bytes the game never recognized.
 *
 * Past those identifiers it degrades instead of rejecting, exactly as every
 * other parser in this folder does: a malformed optional field costs that
 * field, never the whole screen. ``turn``, ``last_roll``, ``pending``,
 * ``decks``, ``last_card``, ``bank`` and ``auction`` become ``null``,
 * ``buildings`` becomes ``{}``, ``actions`` loses only its bad entries, a
 * seat's ``jail_cards`` becomes ``0``, and an optional field of the wrong type
 * is left out so the component's own fallback covers it.
 */
export function parseMonopolyView(raw: unknown): MonopolyView | null {
  if (!isRecord(raw)) return null

  const finished = raw.finished
  if (typeof finished !== 'boolean') return null

  const winner = raw.winner
  if (!(winner === null || typeof winner === 'string')) return null

  const phase = raw.phase
  if (typeof phase !== 'string' || !PHASES.includes(phase)) return null

  const players = readPlayers(raw.players)
  if (players === null) return null

  const owners = readOwners(raw.owners)
  if (owners === null) return null

  const view: MonopolyView = {
    finished,
    winner,
    phase: phase as MonopolyPhase,
    turn: typeof raw.turn === 'string' && raw.turn.length > 0 ? raw.turn : null,
    players,
    owners,
    last_roll: readRoll(raw.last_roll),
    pending: readPending(raw.pending),
    decks: readDecks(raw.decks),
    last_card: readLastCard(raw.last_card),
    buildings: readBuildings(raw.buildings),
    bank: readBank(raw.bank),
    auction: readAuction(raw.auction),
    actions: readActions(raw.actions),
  }

  if (typeof raw.ended_by_abandon === 'boolean') {
    view.ended_by_abandon = raw.ended_by_abandon
  }
  if (typeof raw.you === 'string' && raw.you.length > 0) view.you = raw.you

  return view
}
