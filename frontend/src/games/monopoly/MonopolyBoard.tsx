import type { ReactElement } from 'react'
import type { MatchState } from '../registry'
import { BOARD, isPurchasable, spaceAt } from './board'
import type { Space } from './board'
import { deedFor, purchasePrice, rentForLevel } from './deeds'
import { GROUP_INITIALS, GROUP_LABELS, KIND_LABELS, deckLabel, formatMoney, seatName } from './display'
import { spaceArea } from './grid'
import type { MonopolyPlayer, MonopolyView } from './view'

const RENT_ROW_LABELS = [
  'Renta base',
  'Con grupo completo',
  '1 casa',
  '2 casas',
  '3 casas',
  '4 casas',
  'Hotel',
]

function initialOf(name: string): string {
  const first = name.trim().charAt(0)
  return first === '' ? '?' : first.toUpperCase()
}

/** The display name of the seat that owns ``index``, or ``null``. */
function ownerName(match: MatchState<MonopolyView>, index: number): string | null {
  const seat = match.view.owners[String(index)]
  if (seat === undefined) return null
  return seatName(match, seat)
}

/**
 * The accessible name of one space.
 *
 * It carries the four things S3 asks a space to announce -- name, kind, the
 * printed price when the bank can sell it and the owner's display name when it
 * has one -- so a screen reader reaches the same facts the badge and the band
 * show a sighted player.
 */
function spaceAriaLabel(space: Space, owner: string | null, auctioned: boolean): string {
  const parts = [space.name, KIND_LABELS[space.kind]]
  if (space.group) parts.push(GROUP_LABELS[space.group])
  if (isPurchasable(space)) parts.push(`Precio ${formatMoney(purchasePrice(space.index))}`)
  if (owner) parts.push(`Dueño ${owner}`)
  if (auctioned) parts.push('En subasta')
  return parts.join('. ')
}

/**
 * One ficha, drawn inside the cell of its seat's position.
 *
 * Every seat still in the match gets one, so a shared cell can hold up to eight
 * and the stylesheet wraps and shrinks them instead of letting them overlap.
 * The visible glyph is the player's initial; the title and the accessible name
 * carry the whole sentence, including the own-seat ``(tú)`` suffix and the jail
 * mark, so the token is not a bare shape.
 *
 * A jailed seat is marked with an outline instead of words: a token is about a
 * tenth of the board across, so a sentence inside it would be clipped to
 * nothing by the cell's own overflow. The words stay in the title, in the
 * accessible name and in the players list, where they can be read.
 */
function renderToken(player: MonopolyPlayer, match: MatchState<MonopolyView>): ReactElement {
  const name = seatName(match, player.seat)
  const isYou = player.seat === match.view.you
  const label = `${name}${isYou ? ' (tú)' : ''}${player.in_jail ? ' · En la cárcel' : ''}`
  const classes = [
    'monopoly-token',
    isYou ? 'monopoly-token-you' : '',
    player.in_jail ? 'monopoly-token-jailed' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <span
      aria-label={label}
      className={classes}
      key={player.seat}
      role="img"
      title={label}
    >
      <span className="monopoly-token-initial" aria-hidden="true">{initialOf(name)}</span>
    </span>
  )
}

/**
 * The printed rent schedule of a street deed.
 *
 * It is reference data: the rent actually owed is the server's decision and
 * never computed here. Every level goes through ``rentForLevel`` so the panel
 * and the deed table cannot drift apart.
 */
function rentSchedule(index: number): ReactElement {
  const deed = deedFor(index)
  const values = [
    rentForLevel(deed, 0),
    deed.setRent,
    rentForLevel(deed, 1),
    rentForLevel(deed, 2),
    rentForLevel(deed, 3),
    rentForLevel(deed, 4),
    rentForLevel(deed, 5),
  ]
  return (
    <ul className="monopoly-rents">
      {values.map((value, level) => (
        <li className="monopoly-rent" key={RENT_ROW_LABELS[level]}>
          <span className="monopoly-rent-label">{RENT_ROW_LABELS[level]}</span>
          <span className="monopoly-rent-value">{formatMoney(value)}</span>
        </li>
      ))}
    </ul>
  )
}

/**
 * Render the shared, read-only Monopoly board (S3/S4) for players and
 * spectators alike.
 *
 * The board is a pure function of its props: it owns no state, it never calls
 * ``onAction`` and it never decides which space is open. Tapping a space only
 * reports the index to the panel that owns the selection, which is what lets
 * this component be rendered from a static snapshot in the tests.
 *
 * Every fact it prints -- owner, positions, cash, last throw, turn -- is a
 * field of the server view; nothing about the game is recomputed here.
 */
export function MonopolyBoard({
  match,
  selected,
  onSelect,
}: {
  match: MatchState<MonopolyView>
  selected: number | null
  onSelect: (index: number) => void
}) {
  const { view } = match
  const chosen = selected === null ? null : spaceAt(selected)

  return (
    <div className="monopoly-board" role="group" aria-label="Tablero de Monopoly">
      {BOARD.map((space) => {
        const area = spaceArea(space.index)
        const owner = ownerName(match, space.index)
        const auctioned = view.auction !== null && view.auction.space === space.index
        const holders = view.players.filter(
          (player) => !player.eliminated && player.position === space.index,
        )
        return (
          <button
            aria-label={spaceAriaLabel(space, owner, auctioned)}
            aria-pressed={selected === space.index}
            className={auctioned ? 'monopoly-space monopoly-space-auction' : 'monopoly-space'}
            data-auction={auctioned ? 'true' : undefined}
            data-group={space.group ?? undefined}
            data-kind={space.kind}
            key={space.index}
            onClick={() => onSelect(space.index)}
            style={{ gridRow: area.row, gridColumn: area.column }}
            type="button"
          >
            {space.group && <span className="monopoly-space-band" aria-hidden="true" />}
            <span className="monopoly-space-name">{space.name}</span>
            {space.group && (
              <span className="monopoly-space-group" aria-hidden="true">
                {GROUP_INITIALS[space.group]}
              </span>
            )}
            {owner && <span className="monopoly-space-owner">{owner}</span>}
            {holders.length > 0 && (
              <span className="monopoly-space-tokens">
                {holders.map((player) => renderToken(player, match))}
              </span>
            )}
          </button>
        )
      })}

      <div className="monopoly-centre" style={{ gridRow: '2 / 11', gridColumn: '2 / 11' }}>
        <p className="monopoly-turn" role="status">
          {view.turn === null ? 'Sin turno' : `Turno de ${seatName(match, view.turn)}`}
        </p>
        {view.last_roll !== null && (
          <p className="monopoly-roll" role="status">
            {`Última tirada: ${view.last_roll[0]} y ${view.last_roll[1]}`}
          </p>
        )}
        {view.last_card !== null && (
          <p className="monopoly-roll monopoly-card" role="status">
            {`${deckLabel(view.last_card.deck)}: ${view.last_card.title}`}
          </p>
        )}
        {view.auction !== null && (
          <p className="monopoly-roll monopoly-auction-line" role="status">
            {`Subasta de ${spaceAt(view.auction.space).name}`}
          </p>
        )}
        {chosen !== null && (
          <div className="monopoly-detail" role="status">
            <p className="monopoly-detail-name">{chosen.name}</p>
            <p className="monopoly-detail-kind">{KIND_LABELS[chosen.kind]}</p>
            {chosen.group && (
              <p className="monopoly-detail-group">{GROUP_LABELS[chosen.group]}</p>
            )}
            {isPurchasable(chosen) && (
              <p className="monopoly-detail-price">
                {`Precio: ${formatMoney(purchasePrice(chosen.index))}`}
              </p>
            )}
            {chosen.kind === 'street' && rentSchedule(chosen.index)}
            {isPurchasable(chosen) && (
              <p className="monopoly-detail-owner">
                {`Dueño: ${ownerName(match, chosen.index) ?? 'Sin dueño'}`}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
