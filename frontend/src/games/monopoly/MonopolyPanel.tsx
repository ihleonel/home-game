import { useState } from 'react'
import type { ReactElement } from 'react'
import type { MatchRendererProps, MatchState } from '../registry'
import { BOARD_SIZE, isPurchasable, spaceAt } from './board'
import type { Space } from './board'
import {
  HOTEL_LEVEL,
  MAX_HOUSE_LEVEL,
  RAILROAD_RENTS,
  UTILITY_DICE_MULTIPLIERS,
  deedFor,
  developmentCost,
  levelLabel,
  purchasePrice,
  rentForLevel,
  sellBack,
} from './deeds'
import type { Deed } from './deeds'
import { GROUP_LABELS, DECK_LABELS, formatMoney, seatName } from './display'
import { MonopolyBoard } from './MonopolyBoard'
import './monopoly.css'
import type { MonopolyAction, MonopolyAuction, MonopolyPlayer, MonopolyView } from './view'

function winnerLine(view: MonopolyView, match: MatchState<MonopolyView>): string {
  if (!view.winner) return 'La partida ha terminado.'
  if (view.winner === view.you) return 'Has ganado la partida.'
  return `Ha ganado ${seatName(match, view.winner)}.`
}

type OwnGroup = { key: string; label: string; spaces: Space[] }

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
    const existing = groups.get(key)
    if (existing) existing.spaces.push(space)
    else groups.set(key, { key, label: groupLabel(space), spaces: [space] })
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

/**
 * One button per action the server offered this seat.
 *
 * The prompt is taken verbatim and the client never decides which actions
 * exist: an action with an empty option list is submitted with a ``null`` value
 * and an action with options gets one button per option, because the runtime
 * rejects any value it did not offer. ``build`` and ``sell`` get the dedicated
 * presentation above; every other action keeps the plain ``prompt: option``.
 */
function actionButtons(
  action: MonopolyAction,
  busy: boolean,
  onAction: (name: string, value: string | null) => void,
  buildings: Record<string, number>,
): ReactElement[] {
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
  return action.options.map((option) => (
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
  buildings: Record<string, number>,
): ReactElement {
  return (
    <>
      <dl className="monopoly-own-facts">
        <div className="monopoly-own-fact">
          <dt>Capital</dt>
          <dd className="monopoly-own-cash">{formatMoney(own.cash)}</dd>
        </div>
        <div className="monopoly-own-fact">
          <dt>Posición</dt>
          <dd className="monopoly-own-position">{spaceAt(own.position).name}</dd>
        </div>
        <div className="monopoly-own-fact">
          <dt>Cárcel</dt>
          <dd className="monopoly-own-jail">
            {own.in_jail
              ? `En la cárcel (${own.jail_turns} ${own.jail_turns === 1 ? 'turno' : 'turnos'})`
              : 'Sin restricciones'}
          </dd>
        </div>
        <div className="monopoly-own-fact">
          <dt>Cartas de «Salí de la cárcel gratis»</dt>
          <dd className="monopoly-own-jail-cards">{own.jail_cards}</dd>
        </div>
      </dl>

      <div className="monopoly-own-properties">
        <p className="monopoly-own-properties-title">Tus propiedades</p>
        <p className="monopoly-reference-note">
          Datos impresos de la escritura: referencia, no la renta vigente.
        </p>
        {ownGroups.length === 0 ? (
          <p className="monopoly-own-empty">Todavía no tenés propiedades.</p>
        ) : (
          ownGroups.map((group) => (
            <div className="monopoly-property-group" key={group.key}>
              <p className="monopoly-property-group-title">{group.label}</p>
              <ul className="monopoly-property-list">
                {group.spaces.map((space) => {
                  const level: number | undefined = buildings[String(space.index)]
                  return (
                    <li className="monopoly-property" key={space.index}>
                      <span className="monopoly-property-name">{space.name}</span>
                      {level !== undefined && (
                        <span className="monopoly-property-level">{levelLabel(level)}</span>
                      )}
                      <span className="monopoly-property-price">
                        {`Precio ${formatMoney(purchasePrice(space.index))}`}
                      </span>
                      <span className="monopoly-property-rents">{rentSummary(space)}</span>
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

type MonopolyPanelLayoutProps = {
  match: MatchState<MonopolyView>
  busy: boolean
  onAction: (name: string, value: string | null) => void
  selected: number | null
  onSelect: (index: number) => void
}

/**
 * The own-seat panel and its layout (S5).
 *
 * It owns the ``which space is open`` state and hands it to the board, so the
 * board stays a pure function of its props. It renders the actions the server
 * already sent -- with their prompts verbatim -- and never computes a rule, a
 * legal action or a current rent.
 *
 * The inner layout is a separate component because it is a pure function of its
 * props: the project renders with ``react-dom/server`` and walks the element
 * tree to test a click, and a component that calls ``useState`` cannot be
 * invoked that way. Keeping the hook at this edge is what keeps the layout
 * testable in the existing harness.
 */
export function MonopolyPanel({ match, busy, onAction }: MatchRendererProps<MonopolyView>) {
  const [selected, setSelected] = useState<number | null>(null)
  return (
    <MonopolyPanelLayout
      match={match}
      busy={busy}
      onAction={onAction}
      selected={selected}
      onSelect={setSelected}
    />
  )
}

export function MonopolyPanelLayout({
  match,
  busy,
  onAction,
  selected,
  onSelect,
}: MonopolyPanelLayoutProps) {
  const { view } = match
  const own = view.you ? view.players.find((player) => player.seat === view.you) ?? null : null
  const ownGroups = own === null ? [] : ownPropertyGroups(own)

  return (
    <section className="monopoly-panel" aria-label="Mesa de Monopoly">
      <div className="monopoly-layout">
        <div className="monopoly-board-column">
          <MonopolyBoard match={match} selected={selected} onSelect={onSelect} />
        </div>

        <div className="monopoly-side">
          {view.finished && !view.ended_by_abandon && view.winner && (
            <p className="monopoly-winner" role="status">
              {winnerLine(view, match)}
            </p>
          )}

          <div className="monopoly-own">
            <h3 className="monopoly-block-title">Tu situación</h3>
            {own === null ? (
              <p className="monopoly-spectator">Estás como espectador.</p>
            ) : (
              ownSeatBlock(own, ownGroups, view.buildings)
            )}
          </div>

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

          {view.actions.length > 0 && (
            <div className="monopoly-actions-block">
              <h3 className="monopoly-block-title">Acciones</h3>
              <div className="monopoly-actions" role="group" aria-label="Acciones disponibles">
                {view.actions.map((action) =>
                  actionButtons(action, busy, onAction, view.buildings),
                )}
              </div>
            </div>
          )}

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
        </div>
      </div>
    </section>
  )
}
