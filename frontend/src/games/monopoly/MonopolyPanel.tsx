import { useState } from 'react'
import type { ReactElement, ReactNode } from 'react'
import type { MatchRendererProps, MatchState } from '../registry'
import { BOARD_SIZE, isPurchasable, spaceAt } from './board'
import type { ColorGroup, Space } from './board'
import {
  HOTEL_LEVEL,
  MAX_HOUSE_LEVEL,
  RAILROAD_RENTS,
  UTILITY_DICE_MULTIPLIERS,
  deedFor,
  developmentCost,
  levelLabel,
  mortgageLiftCost,
  mortgageValue,
  purchasePrice,
  rentForLevel,
  sellBack,
} from './deeds'
import type { Deed } from './deeds'
import { GROUP_LABELS, DECK_LABELS, formatMoney, seatName } from './display'
import { MonopolyBoard } from './MonopolyBoard'
import { MonopolyTableCentre } from './MonopolyTableCentre'
import { MonopolyTable3D } from './three/MonopolyTable3D'
import './monopoly.css'
import type { MonopolyAction, MonopolyAuction, MonopolyPlayer, MonopolyView } from './view'

/**
 * The three views of a match screen (S1 of ``monopoly-view-switcher.md``).
 *
 * The player moves between them and only one is on screen at a time. They split
 * the table's information the way a player uses it: the board, the seat's own
 * estate, and the state the whole table shares.
 */
export type MonopolyPane = 'tablero' | 'cartera' | 'mesa'

/** The tab strip, in the order it is drawn (S1). */
const PANES: readonly { key: MonopolyPane; label: string }[] = [
  { key: 'tablero', label: 'Tablero' },
  { key: 'cartera', label: 'Cartera' },
  { key: 'mesa', label: 'Mesa' },
]

/**
 * The view a match opens on: the board.
 *
 * A turn starts by reading the board and every other view is a detour from it,
 * so the board is what the player comes back to.
 */
const OPENING_PANE: MonopolyPane = 'tablero'

/** The id of a view's tab, and the one its panel points back to (S1). */
function paneTabId(pane: MonopolyPane): string {
  return `monopoly-tab-${pane}`
}

/** The id of a view's panel, and the one its tab controls (S1). */
function panePanelId(pane: MonopolyPane): string {
  return `monopoly-pane-${pane}`
}

/**
 * The accessible name of a view's tab, or ``undefined`` when the tab needs no
 * more than its own label (S6/S16).
 *
 * Two views can have something waiting in them, and they wait for different
 * things: the table waits on the offers nobody has answered, and the wallet waits
 * on the actions the server offered on the seat's own properties, which are the
 * buttons its cards hold. Both are returned the same way, so the tab's visible
 * count and its announced one are built from a single value and cannot disagree.
 *
 * A bare count read aloud is a number with no meaning, so the strip keeps the
 * visible badge decorative and states the fact in the tab's name instead, where
 * a screen reader reaches it without reading a stray digit.
 */
type PaneWaiting = { count: number; noun: string }

function paneWaiting(
  pane: MonopolyPane,
  openOffers: number,
  propertyActions: number,
): PaneWaiting | null {
  if (pane === 'mesa' && openOffers > 0) {
    return { count: openOffers, noun: openOffers === 1 ? 'oferta abierta' : 'ofertas abiertas' }
  }
  if (pane === 'cartera' && propertyActions > 0) {
    return {
      count: propertyActions,
      noun:
        propertyActions === 1 ? 'acción sobre tus propiedades' : 'acciones sobre tus propiedades',
    }
  }
  return null
}

/**
 * The view an arrow, Home or End key moves to, or ``null`` for a key the strip
 * does not handle (S1).
 *
 * The two arrows wrap around the ends so the last view never dead-ends. The
 * strip deliberately does not move focus itself: the roving ``tabIndex`` leaves
 * exactly the open view's tab reachable, so the view on screen and the tab the
 * keyboard reaches can never disagree.
 */
function paneForKey(current: MonopolyPane, key: string): MonopolyPane | null {
  const index = PANES.findIndex((pane) => pane.key === current)
  switch (key) {
    case 'ArrowRight':
      return PANES[(index + 1) % PANES.length].key
    case 'ArrowLeft':
      return PANES[(index - 1 + PANES.length) % PANES.length].key
    case 'Home':
      return PANES[0].key
    case 'End':
      return PANES[PANES.length - 1].key
    default:
      return null
  }
}

/**
 * The draft the negotiation block composes (S11).
 *
 * It is only the client's draft of one ``propose`` value: the receiver, the
 * properties to hand over and to ask for, and the two amounts. It never decides
 * whether the trade is legal -- S4 does that on the server -- and it is thrown
 * away once the composed value is submitted.
 */
export type MonopolyTradeDraft = {
  receiver: string | null
  give: number[]
  want: number[]
  giveCash: number
  wantCash: number
}

/** The draft a screen opens on: no receiver, nothing marked, no cash. */
const EMPTY_TRADE_DRAFT: MonopolyTradeDraft = {
  receiver: null,
  give: [],
  want: [],
  giveCash: 0,
  wantCash: 0,
}

/**
 * The actions the negotiation block draws next to each offer (S5/S11).
 *
 * Their options are offer ids, so an offer's terms are the only place they make
 * sense; the generic renderer leaves them to the block instead of drawing a
 * bare ``prompt: id`` button. They are never freeform, so they would otherwise
 * be drawn twice.
 */
const TRADE_RESPONSES = new Set(['accept', 'reject', 'withdraw'])

/**
 * The four actions that act on one property, and therefore belong on its card
 * (S14 of ``monopoly-view-switcher.md``).
 *
 * They are named here so the strip and the card agree on which options are the
 * card's business, and so a fifth one cannot be added to one side only.
 */
const PROPERTY_ACTIONS = new Set(['build', 'sell', 'mortgage', 'unmortgage'])

/** Board indexes in board order, without repeats (S3). */
function boardIndexList(indexes: number[]): string {
  return [...new Set(indexes)].sort((left, right) => left - right).join(',')
}

/**
 * Compose the canonical ``propose`` value (S3) from a draft, or ``null`` when
 * no receiver was picked yet.
 *
 * The grammar is the server's contract, not a rule this panel enforces:
 * comma-separated board indexes in board order with no spaces, integer amounts
 * never below zero, and the two sides joined by ``|``. The block composes
 * exactly this string and the server is free to reject it (S4).
 */
function composeTradeValue(draft: MonopolyTradeDraft): string | null {
  if (draft.receiver === null) return null
  const giveCash = Math.max(0, Math.trunc(draft.giveCash))
  const wantCash = Math.max(0, Math.trunc(draft.wantCash))
  return (
    `to=${draft.receiver};give=${boardIndexList(draft.give)};cash=${giveCash}` +
    `|want=${boardIndexList(draft.want)};cash=${wantCash}`
  )
}

/** Add or remove one board index from a draft selection. */
function toggleIndex(indexes: number[], index: number): number[] {
  return indexes.includes(index)
    ? indexes.filter((candidate) => candidate !== index)
    : [...indexes, index]
}

/** An amount from a number input, clamped to ``[0, max]``; empty reads ``0``. */
function clampedCash(raw: string, max: number): number {
  const parsed = Number.parseInt(raw, 10)
  if (Number.isNaN(parsed)) return 0
  return Math.min(Math.max(parsed, 0), Math.max(max, 0))
}

/** The printed names of a set of board indexes, or ``nada`` when there are none. */
function propertyNames(indexes: number[]): string {
  if (indexes.length === 0) return 'nada'
  return indexes.map((index) => spaceAt(index).name).join(', ')
}

/** The values the server offered for one action, or an empty set. */
function offeredOptions(actions: MonopolyAction[], name: string): Set<string> {
  const action = actions.find((candidate) => candidate.name === name)
  return new Set(action ? action.options : [])
}

function winnerLine(view: MonopolyView, match: MatchState<MonopolyView>): string {
  if (!view.winner) return 'La partida ha terminado.'
  if (view.winner === view.you) return 'Has ganado la partida.'
  return `Ha ganado ${seatName(match, view.winner)}.`
}

type OwnGroup = {
  key: string
  label: string
  spaces: Space[]
  /**
   * The colour key of a street group, or ``null`` for a railroad or a utility
   * (S12 of ``monopoly-view-switcher.md``).
   */
  group: ColorGroup | null
  /**
   * The kind of a group that has no colour, or ``null`` for a street (S12).
   *
   * Exactly one of ``group`` and ``kind`` is set. That is what lets the
   * wallet's stylesheet paint a group from a single rule and stops a group
   * from ever matching two of them at once.
   */
  kind: 'railroad' | 'utility' | null
}

function groupKey(space: Space): string {
  if (space.kind === 'street' && space.group) return `group:${space.group}`
  if (space.kind === 'railroad') return 'railroad'
  return 'utility'
}

function groupLabel(space: Space): string {
  if (space.kind === 'street' && space.group) return GROUP_LABELS[space.group]
  if (space.kind === 'railroad') return 'Ferrocarriles'
  return 'Servicios'
}

/** The kind of a purchasable space that has no colour (S12). */
function colourlessKind(space: Space): 'railroad' | 'utility' {
  return space.kind === 'railroad' ? 'railroad' : 'utility'
}

/**
 * The seat's own properties, grouped by colour and then by the two
 * property-only groups, in board order.
 *
 * A railroad and a utility have no colour, but they are still properties of the
 * seat; grouping them under their own labels keeps them visible instead of
 * silently dropping everything that is not a street.
 */
function ownPropertyGroups(player: MonopolyPlayer): OwnGroup[] {
  const groups = new Map<string, OwnGroup>()
  const owned = [...player.properties].sort((left, right) => left - right)
  for (const index of owned) {
    const space = spaceAt(index)
    if (!isPurchasable(space)) continue
    const key = groupKey(space)
    const isStreet = space.kind === 'street'
    const existing = groups.get(key)
    if (existing) existing.spaces.push(space)
    else
      groups.set(key, {
        key,
        label: groupLabel(space),
        spaces: [space],
        group: isStreet ? space.group : null,
        kind: isStreet ? null : colourlessKind(space),
      })
  }
  return [...groups.values()]
}

/**
 * The printed rents of one owned property, straight from ``deeds.ts``.
 *
 * It is reference data, never the rent now owed: the server decides that, and
 * the copy says so. A street goes through ``rentForLevel``; a railroad and a
 * utility print their own schedules.
 */
function rentSummary(space: Space): string {
  if (space.kind === 'street') {
    const deed = deedFor(space.index)
    const parts = [
      `base ${formatMoney(rentForLevel(deed, 0))}`,
      `grupo ${formatMoney(deed.setRent)}`,
      `1 casa ${formatMoney(rentForLevel(deed, 1))}`,
      `2 casas ${formatMoney(rentForLevel(deed, 2))}`,
      `3 casas ${formatMoney(rentForLevel(deed, 3))}`,
      `4 casas ${formatMoney(rentForLevel(deed, 4))}`,
      `hotel ${formatMoney(rentForLevel(deed, 5))}`,
    ]
    return `Rentas impresas: ${parts.join(' · ')}.`
  }
  if (space.kind === 'railroad') {
    return `Rentas impresas: ${RAILROAD_RENTS.map(formatMoney).join(' / ')} según ferrocarriles.`
  }
  return `Rentas impresas: ${UTILITY_DICE_MULTIPLIERS[0]}× los dados con uno, ${UTILITY_DICE_MULTIPLIERS[1]}× con los dos.`
}

/** The board index an option carries, or ``null`` when it is not one. */
function optionIndex(option: string): number | null {
  if (!/^\d+$/.test(option)) return null
  const index = Number(option)
  if (!Number.isInteger(index) || index < 0 || index >= BOARD_SIZE) return null
  return index
}

/**
 * The cash one more level costs a street, whatever its current level (S3/S5).
 *
 * A house and a hotel cost the same ``houseCost``, so the price of the next
 * level is the difference between the property's development value now and one
 * level up. It is deliberately not the property's *total* value, and it never
 * guesses house versus hotel: the server does not publish that per option and
 * the client does not recompute the rule.
 */
function buildPrice(deed: Deed, level: number): number {
  const current = Math.min(level, MAX_HOUSE_LEVEL)
  const next = Math.min(current + 1, HOTEL_LEVEL)
  return developmentCost(deed, next) - developmentCost(deed, current)
}

/**
 * The label of one build or sell option (S11).
 *
 * These two actions' options are board indexes, so they are resolved through
 * the panel's own copy of the board data (``spaceAt``, ``deedFor``) instead of
 * printed raw. The prompt stays the server's verb. An option that is not a
 * street index falls back to the generic ``prompt: option`` so a malformed
 * payload degrades to a button, not a crashed screen.
 */
function optionLabel(
  action: MonopolyAction,
  option: string,
  buildings: Record<string, number>,
): string {
  const index = optionIndex(option)
  if (index === null) return `${action.prompt}: ${option}`
  const space = spaceAt(index)
  if (!isPurchasable(space)) return `${action.prompt}: ${option}`
  if (action.name === 'mortgage') {
    return `${action.prompt} en ${space.name} · +${formatMoney(mortgageValue(index))}`
  }
  if (action.name === 'unmortgage') {
    return `${action.prompt} en ${space.name} · −${formatMoney(mortgageLiftCost(index))}`
  }
  if (space.kind !== 'street') return `${action.prompt}: ${option}`
  if (action.name === 'build') {
    const level: number = buildings[String(index)] ?? 0
    return `${action.prompt} en ${space.name} · ${formatMoney(buildPrice(deedFor(index), level))}`
  }
  if (action.name === 'sell') {
    return `${action.prompt} en ${space.name} · +${formatMoney(sellBack(deedFor(index)))}`
  }
  return `${action.prompt}: ${option}`
}

/** One option a property card can draw, ready to become a button (S14). */
type PropertyAction = {
  /** The action name the runtime grades the submission against. */
  name: string
  /** The option the server offered, submitted unchanged. */
  option: string
  /** The button's text: the server's verb and the money the option moves. */
  label: string
}

/**
 * Whether a property card claims this option (S14).
 *
 * A card claims an option only when a card for that space exists, which is the
 * one condition that matters: an option the client cannot place has to stay with
 * the strip instead of leaving the screen. ``cardIndexes`` is built from the very
 * groups the wallet renders, so "claimed" can never mean "no card exists".
 *
 * ``build`` and ``sell`` keep their own restriction: they are street-only rules,
 * so an option of theirs that does not name a street is not a price a card can
 * pay and is left to the strip.
 */
function claimedByCard(
  cardIndexes: Set<number>,
  action: MonopolyAction,
  option: string,
): boolean {
  if (!PROPERTY_ACTIONS.has(action.name)) return false
  const index = optionIndex(option)
  if (index === null || !cardIndexes.has(index)) return false
  if (action.name === 'build' || action.name === 'sell') return spaceAt(index).kind === 'street'
  return true
}

/**
 * The label of one option a card draws (S14).
 *
 * The card already names the property, so the label is the server's own verb
 * plus the money the option moves and never the space name a second time. Every
 * price comes from ``deeds.ts``, the same table the printed board is drawn from:
 * the client still decides no rule and still prices nothing the server did not
 * offer.
 */
function cardOptionLabel(action: MonopolyAction, index: number, level: number): string {
  if (action.name === 'build') {
    return `${action.prompt} · ${formatMoney(buildPrice(deedFor(index), level))}`
  }
  if (action.name === 'sell') {
    return `${action.prompt} · +${formatMoney(sellBack(deedFor(index)))}`
  }
  if (action.name === 'mortgage') return `${action.prompt} · +${formatMoney(mortgageValue(index))}`
  if (action.name === 'unmortgage') {
    return `${action.prompt} · −${formatMoney(mortgageLiftCost(index))}`
  }
  return `${action.prompt}`
}

/**
 * The options each property card draws, keyed by board index (S14).
 *
 * The order is fixed here -- build, sell, mortgage, unmortgage -- so a card's
 * buttons never move between frames because the server reordered its own list.
 */
function propertyActionsByIndex(
  actions: MonopolyAction[],
  cardIndexes: Set<number>,
  buildings: Record<string, number>,
): Map<number, PropertyAction[]> {
  const byIndex = new Map<number, PropertyAction[]>()
  for (const name of ['build', 'sell', 'mortgage', 'unmortgage']) {
    const action = actions.find((candidate) => candidate.name === name)
    if (!action) continue
    for (const option of action.options) {
      if (!claimedByCard(cardIndexes, action, option)) continue
      const index = Number(option)
      const level: number = buildings[String(index)] ?? 0
      const drawn = byIndex.get(index) ?? []
      drawn.push({ name: action.name, option, label: cardOptionLabel(action, index, level) })
      byIndex.set(index, drawn)
    }
  }
  return byIndex
}

/** The options of one action its card took, so the strip does not draw them twice (S14). */
function claimedOptions(action: MonopolyAction, cardIndexes: Set<number>): Set<string> {
  return new Set(action.options.filter((option) => claimedByCard(cardIndexes, action, option)))
}

/**
 * One button per action the server offered this seat.
 *
 * The prompt is taken verbatim and the client never decides which actions
 * exist: an action with an empty option list is submitted with a ``null`` value
 * and an action with options gets one button per option, because the runtime
 * rejects any value it did not offer. ``build`` and ``sell`` get the dedicated
 * presentation above; every other action keeps the plain ``prompt: option``.
 *
 * A ``freeform`` action is **skipped**: its value is composed by the
 * negotiation block, and a generic button would submit ``null`` to an action
 * that requires a composed value (S11).
 *
 * An option a property card claimed is **skipped** as well (S14): it is drawn on
 * its card, and drawing it here too would offer the same submission twice. What
 * is left still goes through the presentation above, so an option no card could
 * place keeps the label it always had.
 */
function actionButtons(
  action: MonopolyAction,
  busy: boolean,
  onAction: (name: string, value: string | null) => void,
  buildings: Record<string, number>,
  claimed: ReadonlySet<string>,
): ReactElement[] {
  if (action.freeform) return []
  if (action.options.length === 0) {
    return [
      <button
        className="monopoly-action"
        disabled={busy}
        key={action.name}
        onClick={() => onAction(action.name, null)}
        type="button"
      >
        {action.prompt}
      </button>,
    ]
  }
  return action.options
    .filter((option) => !claimed.has(option))
    .map((option) => (
      <button
        className="monopoly-action"
        disabled={busy}
        key={`${action.name}:${option}`}
        onClick={() => onAction(action.name, option)}
        type="button"
      >
        {optionLabel(action, option, buildings)}
      </button>
    ))
}

function ownSeatBlock(
  own: MonopolyPlayer,
  ownGroups: OwnGroup[],
  cardActions: Map<number, PropertyAction[]>,
  buildings: Record<string, number>,
  mortgaged: Record<string, true>,
  busy: boolean,
  onAction: (name: string, value: string | null) => void,
): ReactElement {
  return (
    <>
      <dl className="monopoly-own-facts">
        {/* The wallet shows the money alone: a printed label over every number
            is what made the panel read as a data sheet. The ``dt`` stays in the
            markup, clipped out of sight, because it is what keeps the ``dl``
            meaningful and what a screen reader announces before the amount. */}
        <div className="monopoly-own-fact">
          <dt className="monopoly-visually-hidden">Capital</dt>
          <dd className="monopoly-own-cash">{formatMoney(own.cash)}</dd>
        </div>
        {/* The own position is not repeated here: the seat reads it where it
            lives, on its piece standing on the board. */}
        {/* A fact is printed only while it says something, so a free seat has no
            jail restriction to report and a hand with no jail card is not an
            inventory worth a row. */}
        {own.in_jail && (
          <div className="monopoly-own-fact">
            <dt>Cárcel</dt>
            <dd className="monopoly-own-jail">
              {`En la cárcel (${own.jail_turns} ${own.jail_turns === 1 ? 'turno' : 'turnos'})`}
            </dd>
          </div>
        )}
        {own.jail_cards > 0 && (
          <div className="monopoly-own-fact">
            <dt>Cartas de «Salí de la cárcel gratis»</dt>
            <dd className="monopoly-own-jail-cards">{own.jail_cards}</dd>
          </div>
        )}
      </dl>

      <div className="monopoly-own-properties">
        <p className="monopoly-own-properties-title">Tus propiedades</p>
        {/* No disclaimer sentence here: every rent line below is prefixed
            "Rentas impresas" on its own, which is what says the printed table
            is a reference and not the rent in force. */}
        {ownGroups.length === 0 ? (
          <p className="monopoly-own-empty">Todavía no tenés propiedades.</p>
        ) : (
          ownGroups.map((group) => (
            <div
              className="monopoly-property-group"
              data-group={group.group ?? undefined}
              data-kind={group.kind ?? undefined}
              key={group.key}
            >
              {/* The group is told on screen by the colour band of its own
                  cards and by the block they share; the name stays in the
                  markup, clipped out of sight, so colour is never the only
                  channel (WCAG 1.4.1). */}
              <p className="monopoly-property-group-title monopoly-visually-hidden">
                {group.label}
              </p>
              <ul className="monopoly-property-list">
                {group.spaces.map((space) => {
                  const level: number | undefined = buildings[String(space.index)]
                  const isMortgaged = mortgaged[String(space.index)] === true
                  const actions = cardActions.get(space.index) ?? []
                  return (
                    <li className="monopoly-property" key={space.index}>
                      <span className="monopoly-property-name">{space.name}</span>
                      {level !== undefined && (
                        <span className="monopoly-property-level">{levelLabel(level)}</span>
                      )}
                      {isMortgaged && (
                        <span className="monopoly-property-mortgaged">Hipotecada</span>
                      )}
                      <span className="monopoly-property-price">
                        {`Precio ${formatMoney(purchasePrice(space.index))}`}
                      </span>
                      <span className="monopoly-property-rents">{rentSummary(space)}</span>
                      {actions.length > 0 && (
                        <div className="monopoly-property-actions">
                          {actions.map((action) => (
                            <button
                              className="monopoly-property-action"
                              disabled={busy}
                              key={`${action.name}:${action.option}`}
                              onClick={() => onAction(action.name, action.option)}
                              type="button"
                            >
                              {action.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          ))
        )}
      </div>
    </>
  )
}

/**
 * The open auction as the whole table sees it (S9).
 *
 * It reads only the public ``auction`` field: the space, the standing high bid
 * and its holder, and the roster names still to bid. It deliberately renders no
 * control: the eligible seats already receive their own ``bid`` and ``pass``
 * actions, and the actions block draws one button per option.
 */
function auctionBlock(auction: MonopolyAuction, match: MatchState<MonopolyView>): ReactElement {
  const noBids = auction.high_bid === 0 && auction.high_bidder === null
  const waiting = auction.waiting_for.map((seat) => seatName(match, seat))
  return (
    <div className="monopoly-players-block monopoly-auction">
      <h3 className="monopoly-block-title">Subasta</h3>
      <dl className="monopoly-own-facts">
        <div className="monopoly-own-fact">
          <dt>Casilla</dt>
          <dd className="monopoly-auction-space">{spaceAt(auction.space).name}</dd>
        </div>
        <div className="monopoly-own-fact">
          <dt>Puja más alta</dt>
          <dd className="monopoly-auction-bid">
            {noBids ? 'Todavía no hay pujas.' : formatMoney(auction.high_bid)}
          </dd>
        </div>
        {auction.high_bidder !== null && (
          <div className="monopoly-own-fact">
            <dt>Mayor postor</dt>
            <dd className="monopoly-auction-bidder">
              {`${seatName(match, auction.high_bidder)}${
                auction.high_bidder === match.view.you ? ' (tú)' : ''
              }`}
            </dd>
          </div>
        )}
      </dl>
      <p className="monopoly-auction-waiting">
        {waiting.length === 0
          ? 'No queda nadie por pujar.'
          : `Esperando la puja de ${waiting.join(', ')}.`}
      </p>
    </div>
  )
}

/**
 * The negotiation block: compose one ``propose`` value (S11).
 *
 * It is drawn only when the server offers ``propose``. The receiver is picked
 * among the other non-eliminated seats -- what the view shows, never a
 * solvency rule it computes -- and the two property groups are the own seat's
 * and the chosen receiver's own lists. The two amounts are bounded by the cash
 * the view carries. The block composes the S3 grammar and hands it to the
 * existing action channel; it never decides whether the trade is legal.
 */
function tradeFormBlock(
  view: MonopolyView,
  match: MatchState<MonopolyView>,
  busy: boolean,
  onAction: (name: string, value: string | null) => void,
  trade: MonopolyTradeDraft,
  onTradeChange: (next: MonopolyTradeDraft) => void,
  own: MonopolyPlayer,
): ReactElement {
  const candidates = view.players.filter(
    (player) => player.seat !== view.you && !player.eliminated,
  )
  const receiver =
    trade.receiver === null
      ? null
      : view.players.find((player) => player.seat === trade.receiver) ?? null
  const composed = composeTradeValue(trade)
  const ownProperties = [...own.properties].sort((left, right) => left - right)
  const receiverProperties = receiver === null ? [] : [...receiver.properties].sort((left, right) => left - right)
  return (
    <div className="monopoly-players-block monopoly-trade">
      <h3 className="monopoly-block-title">Comercio</h3>
      <label className="monopoly-trade-receiver-field">
        <span className="monopoly-trade-field-label">Receptor</span>
        <select
          className="monopoly-trade-receiver"
          disabled={busy}
          onChange={(event) =>
            onTradeChange({
              ...trade,
              receiver: event.target.value === '' ? null : event.target.value,
              want: [],
            })
          }
          value={trade.receiver ?? ''}
        >
          <option value="">Elegí un asiento</option>
          {candidates.map((candidate) => (
            <option key={candidate.seat} value={candidate.seat}>
              {seatName(match, candidate.seat)}
            </option>
          ))}
        </select>
      </label>

      <div className="monopoly-trade-side monopoly-trade-give">
        <p className="monopoly-trade-side-title">Entregás</p>
        {ownProperties.length === 0 ? (
          <p className="monopoly-trade-empty">No tenés propiedades para entregar.</p>
        ) : (
          <ul className="monopoly-trade-properties">
            {ownProperties.map((index) => (
              <li className="monopoly-trade-property-item" key={index}>
                <label>
                  <input
                    checked={trade.give.includes(index)}
                    className="monopoly-trade-property monopoly-trade-give-property"
                    disabled={busy}
                    onChange={() =>
                      onTradeChange({ ...trade, give: toggleIndex(trade.give, index) })
                    }
                    type="checkbox"
                    value={index}
                  />
                  {spaceAt(index).name}
                </label>
              </li>
            ))}
          </ul>
        )}
        <label className="monopoly-trade-cash-field">
          <span>Efectivo que entregás</span>
          <input
            className="monopoly-trade-cash monopoly-trade-give-cash"
            disabled={busy}
            max={Math.max(own.cash, 0)}
            min={0}
            onChange={(event) =>
              onTradeChange({ ...trade, giveCash: clampedCash(event.target.value, own.cash) })
            }
            type="number"
            value={trade.giveCash}
          />
        </label>
      </div>

      <div className="monopoly-trade-side monopoly-trade-want">
        <p className="monopoly-trade-side-title">Pedís</p>
        {receiver === null ? (
          <p className="monopoly-trade-empty">Elegí un receptor para ver sus propiedades.</p>
        ) : receiverProperties.length === 0 ? (
          <p className="monopoly-trade-empty">Ese asiento no tiene propiedades.</p>
        ) : (
          <ul className="monopoly-trade-properties">
            {receiverProperties.map((index) => (
              <li className="monopoly-trade-property-item" key={index}>
                <label>
                  <input
                    checked={trade.want.includes(index)}
                    className="monopoly-trade-property monopoly-trade-want-property"
                    disabled={busy}
                    onChange={() =>
                      onTradeChange({ ...trade, want: toggleIndex(trade.want, index) })
                    }
                    type="checkbox"
                    value={index}
                  />
                  {spaceAt(index).name}
                </label>
              </li>
            ))}
          </ul>
        )}
        <label className="monopoly-trade-cash-field">
          <span>Efectivo que pedís</span>
          <input
            className="monopoly-trade-cash monopoly-trade-want-cash"
            disabled={busy}
            max={receiver === null ? 0 : Math.max(receiver.cash, 0)}
            min={0}
            onChange={(event) =>
              onTradeChange({
                ...trade,
                wantCash: clampedCash(event.target.value, receiver === null ? 0 : receiver.cash),
              })
            }
            type="number"
            value={trade.wantCash}
          />
        </label>
      </div>

      <button
        className="monopoly-trade-send"
        disabled={busy || composed === null}
        onClick={() => {
          if (composed !== null) onAction('propose', composed)
        }}
        type="button"
      >
        Proponer el trato
      </button>
    </div>
  )
}

/**
 * The open offers, for the whole table (S10).
 *
 * Each offer reads its terms with printed names, the amounts and which side
 * belongs to whom, and a stale offer is marked as no longer acceptable. The
 * response buttons come from the server's own ``accept``/``reject``/``withdraw``
 * options, so the block never invents an action: accept is only drawn for an
 * offer the view marked valid and only for its receiver, reject for its
 * receiver, withdraw for its proposer. A spectator sees the terms and no
 * button.
 */
function offersBlock(
  view: MonopolyView,
  match: MatchState<MonopolyView>,
  busy: boolean,
  onAction: (name: string, value: string | null) => void,
): ReactElement | null {
  const offers = view.offers ?? []
  if (offers.length === 0) return null
  const accepts = offeredOptions(view.actions, 'accept')
  const rejects = offeredOptions(view.actions, 'reject')
  const withdraws = offeredOptions(view.actions, 'withdraw')
  return (
    <div className="monopoly-players-block monopoly-offers">
      <h3 className="monopoly-block-title">Ofertas abiertas</h3>
      <ul className="monopoly-offer-list">
        {offers.map((offer) => {
          const proposer = seatName(match, offer.proposer)
          const canAccept =
            offer.valid && offer.receiver === view.you && accepts.has(offer.id)
          const canReject = offer.receiver === view.you && rejects.has(offer.id)
          const canWithdraw = offer.proposer === view.you && withdraws.has(offer.id)
          return (
            <li
              className="monopoly-offer"
              data-valid={offer.valid ? 'true' : 'false'}
              key={offer.id}
            >
              <p className="monopoly-offer-line monopoly-offer-give">
                {`${proposer} entrega ${propertyNames(offer.give.properties)} y ${formatMoney(
                  offer.give.cash,
                )}.`}
              </p>
              <p className="monopoly-offer-line monopoly-offer-want">
                {`${proposer} pide ${propertyNames(offer.want.properties)} y ${formatMoney(
                  offer.want.cash,
                )}.`}
              </p>
              {!offer.valid && (
                <p className="monopoly-offer-invalid">Ya no es aceptable.</p>
              )}
              {(canAccept || canReject || canWithdraw) && (
                <div className="monopoly-offer-actions">
                  {canAccept && (
                    <button
                      className="monopoly-offer-response monopoly-offer-accept"
                      disabled={busy}
                      onClick={() => onAction('accept', offer.id)}
                      type="button"
                    >
                      Aceptar
                    </button>
                  )}
                  {canReject && (
                    <button
                      className="monopoly-offer-response monopoly-offer-reject"
                      disabled={busy}
                      onClick={() => onAction('reject', offer.id)}
                      type="button"
                    >
                      Rechazar
                    </button>
                  )}
                  {canWithdraw && (
                    <button
                      className="monopoly-offer-response monopoly-offer-withdraw"
                      disabled={busy}
                      onClick={() => onAction('withdraw', offer.id)}
                      type="button"
                    >
                      Retirar
                    </button>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

type MonopolyPanelLayoutProps = {
  match: MatchState<MonopolyView>
  busy: boolean
  onAction: (name: string, value: string | null) => void
  selected: number | null
  onSelect: (index: number) => void
  trade: MonopolyTradeDraft
  onTradeChange: (next: MonopolyTradeDraft) => void
  activeView: MonopolyPane
  onViewChange: (next: MonopolyPane) => void
  /**
   * The 3D table, when the match screen has one (S6, S7).
   *
   * The layout never imports the scene: a canvas cannot be mounted in the
   * project's DOM-less harness, so the wrapper builds the element and this pure
   * component only places it. Without it the tab shows the flat board, which is
   * what every existing test renders.
   */
  boardScene?: ReactNode
  /** How many quarters the table is turned, and the request to turn it (V3). */
  sceneTurns?: { turns: number; onRotate: (direction: 1 | -1) => void }
}

/**
 * The own-seat panel and its layout (S5).
 *
 * It owns the ``which space is open`` state, the view the player is looking at
 * (S2 of ``monopoly-view-switcher.md``) and hands both to the board and to the
 * layout, so those stay pure functions of their props. It renders the actions
 * the server already sent -- with their prompts verbatim -- and never computes
 * a rule, a legal action or a current rent.
 *
 * The inner layout is a separate component because it is a pure function of its
 * props: the project renders with ``react-dom/server`` and walks the element
 * tree to test a click, and a component that calls ``useState`` cannot be
 * invoked that way. Keeping the hook at this edge is what keeps the layout
 * testable in the existing harness.
 */
export function MonopolyPanel({ match, busy, onAction }: MatchRendererProps<MonopolyView>) {
  const [selected, setSelected] = useState<number | null>(null)
  const [trade, setTrade] = useState<MonopolyTradeDraft>(EMPTY_TRADE_DRAFT)
  const [pane, setPane] = useState<MonopolyPane>(OPENING_PANE)
  const [turns, setTurns] = useState(0)
  return (
    <MonopolyPanelLayout
      match={match}
      busy={busy}
      onAction={onAction}
      selected={selected}
      onSelect={setSelected}
      trade={trade}
      onTradeChange={setTrade}
      activeView={pane}
      onViewChange={setPane}
      boardScene={
        <MonopolyTable3D
          active={pane === 'tablero'}
          match={match}
          onSelect={setSelected}
          seat={match.seatIndex ?? 0}
          selected={selected}
          turns={turns}
        />
      }
      sceneTurns={{ turns, onRotate: (direction) => setTurns((count) => count + direction) }}
    />
  )
}

export function MonopolyPanelLayout({
  match,
  busy,
  onAction,
  selected,
  onSelect,
  trade,
  onTradeChange,
  activeView,
  onViewChange,
  boardScene,
  sceneTurns,
}: MonopolyPanelLayoutProps) {
  const { view } = match
  const own = view.you ? view.players.find((player) => player.seat === view.you) ?? null : null
  const ownGroups = own === null ? [] : ownPropertyGroups(own)
  const canPropose = view.actions.some((action) => action.name === 'propose')
  const genericActions = view.actions.filter((action) => !TRADE_RESPONSES.has(action.name))
  const openOffers = (view.offers ?? []).length
  const debt = view.phase === 'raising_cash' ? view.debt : null
  /**
   * The indexes the wallet draws a card for, and the actions those cards take
   * (S14).
   *
   * ``cardIndexes`` is built from the very groups the wallet renders, so
   * "claimed" can never mean "no card exists", and the strip below is left with
   * exactly the options no card could place.
   */
  const cardIndexes = new Set(ownGroups.flatMap((group) => group.spaces.map((space) => space.index)))
  const cardActions = propertyActionsByIndex(view.actions, cardIndexes, view.buildings)
  const cardActionCount = [...cardActions.values()].reduce(
    (total, actions) => total + actions.length,
    0,
  )
  const stripButtons = genericActions.flatMap((action) =>
    actionButtons(action, busy, onAction, view.buildings, claimedOptions(action, cardIndexes)),
  )

  /**
   * One view's panel.
   *
   * ``hidden`` is what takes an unopened view out of the tab order and out of
   * the accessibility tree, so a button of a view nobody opened can never be
   * focused. CSS alone would not do it: a ``display`` rule of ours would beat
   * the ``display: none`` a user agent gives ``[hidden]``. The panel stays in
   * the markup so every tab's ``aria-controls`` always resolves.
   */
  const pane = (key: MonopolyPane, children: ReactNode): ReactElement => (
    <div
      aria-labelledby={paneTabId(key)}
      className={`monopoly-pane monopoly-pane-${key}`}
      hidden={activeView !== key}
      id={panePanelId(key)}
      role="tabpanel"
    >
      {children}
    </div>
  )

  return (
    <section className="monopoly-panel" aria-label="Mesa de Monopoly">
      {view.finished && !view.ended_by_abandon && view.winner && (
        <p className="monopoly-winner" role="status">
          {winnerLine(view, match)}
        </p>
      )}

      <div
        aria-label="Vistas de la partida"
        className="monopoly-tabs"
        onKeyDown={(event) => {
          const next = paneForKey(activeView, event.key)
          if (next === null) return
          event.preventDefault()
          onViewChange(next)
        }}
        role="tablist"
      >
        {PANES.map(({ key, label }) => {
          const waiting = paneWaiting(key, openOffers, cardActionCount)
          return (
            <button
              aria-controls={panePanelId(key)}
              aria-label={
                waiting === null ? undefined : `${label} (${waiting.count} ${waiting.noun})`
              }
              aria-selected={key === activeView}
              className="monopoly-tab"
              data-pane={key}
              id={paneTabId(key)}
              key={key}
              onClick={() => onViewChange(key)}
              role="tab"
              tabIndex={key === activeView ? 0 : -1}
              type="button"
            >
              <span className="monopoly-tab-label">{label}</span>
              {waiting !== null && (
                <span aria-hidden="true" className="monopoly-tab-badge">
                  {waiting.count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/*
        The debt and the offered actions live outside every view (S5), so
        whichever view is open they are on screen: changing view can never hide
        an obligation the seat still has to answer.
      */}
      {(debt !== null || stripButtons.length > 0) && (
        <div className="monopoly-persistent">
          {debt !== null && (
            <div className="monopoly-players-block monopoly-debt">
              <h3 className="monopoly-block-title">Deuda</h3>
              <p className="monopoly-debt-line">
                {`Deuda: ${formatMoney(debt.amount)} ${
                  debt.creditor === null ? 'con el banco' : `con ${seatName(match, debt.creditor)}`
                }`}
              </p>
            </div>
          )}

          {stripButtons.length > 0 && (
            <div className="monopoly-actions-block">
              <h3 className="monopoly-block-title">Acciones</h3>
              <div className="monopoly-actions" role="group" aria-label="Acciones disponibles">
                {stripButtons}
              </div>
            </div>
          )}
        </div>
      )}

      {pane(
        'tablero',
        boardScene === undefined ? (
          <MonopolyBoard match={match} selected={selected} onSelect={onSelect} />
        ) : (
          <div className="monopoly-scene">
            {boardScene}
            {/*
              S9: the middle of the table, over the rendered board. The camera
              looks at the board's centre, so the card that carries the turn, the
              last throw and the tapped space sits in the middle of the frame.
            */}
            <div className="monopoly-scene-centre">
              <MonopolyTableCentre match={match} selected={selected} />
            </div>
            {sceneTurns !== undefined && (
              <div className="monopoly-scene-turns" role="group" aria-label="Giro del tablero">
                <button
                  aria-label="Girar el tablero a la izquierda"
                  className="monopoly-viewport-button"
                  onClick={() => sceneTurns.onRotate(-1)}
                  type="button"
                >
                  ↺
                </button>
                <button
                  aria-label="Girar el tablero a la derecha"
                  className="monopoly-viewport-button"
                  onClick={() => sceneTurns.onRotate(1)}
                  type="button"
                >
                  ↻
                </button>
              </div>
            )}
            {/*
              S6: the accessible board. A canvas is invisible to a screen reader
              and unreachable by the keyboard, so the forty buttons are still
              here -- clipped out of sight, never ``display: none``, because that
              would take away both the tab order and the announcement.
            */}
            <div className="monopoly-table-mirror">
              <MonopolyBoard
                centre="none"
                match={match}
                onFocus={onSelect}
                onSelect={onSelect}
                selected={selected}
              />
            </div>
          </div>
        ),
      )}

      {pane(
        'cartera',
        <div className="monopoly-own">
          <h3 className="monopoly-block-title">Tu situación</h3>
          {own === null ? (
            <p className="monopoly-spectator">Estás como espectador.</p>
          ) : (
            ownSeatBlock(
              own,
              ownGroups,
              cardActions,
              view.buildings,
              view.mortgaged,
              busy,
              onAction,
            )
          )}
        </div>,
      )}

      {pane(
        'mesa',
        <>
          <div className="monopoly-players-block">
            <h3 className="monopoly-block-title">Jugadores</h3>
            <ul className="monopoly-players">
              {view.players.map((player) => {
                const isYou = player.seat === view.you
                return (
                  <li
                    className={
                      player.eliminated
                        ? 'monopoly-player monopoly-player-out'
                        : 'monopoly-player'
                    }
                    key={player.seat}
                  >
                    <span className="monopoly-player-name">
                      {`${seatName(match, player.seat)}${isYou ? ' (tú)' : ''}`}
                    </span>
                    <span className="monopoly-player-cash">{formatMoney(player.cash)}</span>
                    <span className="monopoly-player-position">
                      {spaceAt(player.position).name}
                    </span>
                    {player.in_jail && <span className="monopoly-player-jail">En la cárcel</span>}
                    {player.eliminated && (
                      <span className="monopoly-player-out-label">Fuera de la partida</span>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>

          {own !== null && canPropose &&
            tradeFormBlock(view, match, busy, onAction, trade, onTradeChange, own)}

          {offersBlock(view, match, busy, onAction)}

          {view.decks !== null && (
            <div className="monopoly-players-block monopoly-decks">
              <h3 className="monopoly-block-title">Mazos</h3>
              <dl className="monopoly-own-facts">
                <div className="monopoly-own-fact">
                  <dt>{DECK_LABELS.chance}</dt>
                  <dd className="monopoly-deck-count">{view.decks.chance}</dd>
                </div>
                <div className="monopoly-own-fact">
                  <dt>{DECK_LABELS.community_chest}</dt>
                  <dd className="monopoly-deck-count">{view.decks.community_chest}</dd>
                </div>
              </dl>
            </div>
          )}

          {view.bank !== null && (
            <div className="monopoly-players-block monopoly-bank">
              <h3 className="monopoly-block-title">Banco</h3>
              <dl className="monopoly-own-facts">
                <div className="monopoly-own-fact">
                  <dt>Casas</dt>
                  <dd className="monopoly-bank-houses">{view.bank.houses}</dd>
                </div>
                <div className="monopoly-own-fact">
                  <dt>Hoteles</dt>
                  <dd className="monopoly-bank-hotels">{view.bank.hotels}</dd>
                </div>
              </dl>
            </div>
          )}

          {view.auction !== null && auctionBlock(view.auction, match)}
        </>,
      )}
    </section>
  )
}
