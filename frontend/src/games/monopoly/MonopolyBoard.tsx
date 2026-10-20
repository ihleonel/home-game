import type { ReactElement } from 'react'
import type { MatchState } from '../registry'
import { BOARD, isPurchasable } from './board'
import type { Space } from './board'
import { HOTEL_LEVEL, levelLabel, purchasePrice } from './deeds'
import {
  GROUP_INITIALS,
  GROUP_LABELS,
  KIND_LABELS,
  formatMoney,
  seatName,
} from './display'
import { MonopolyTableCentre } from './MonopolyTableCentre'
import { cellFor, sideFor } from './viewport'
import type { QuarterTurns } from './viewport'
import type { MonopolyPlayer, MonopolyView } from './view'

function initialOf(name: string): string {
  const first = name.trim().charAt(0)
  return first === '' ? '?' : first.toUpperCase()
}

/**
 * The development level of a space, or ``null`` when it is unbuilt (S10).
 *
 * The level comes **only** from ``view.buildings``, keyed by ``String(index)``
 * because the state is ``jsonb``. It is never derived from the owner map or
 * from the colour group: the server is the one that decides a build happened.
 */
function buildingLevel(view: MonopolyView, index: number): number | null {
  const level: number | undefined = view.buildings[String(index)]
  return level === undefined ? null : level
}

/**
 * The houses (1-4) or the single hotel (5) of a built street (S10).
 *
 * CSS shapes only, no asset. The marker is decorative: the same level is in
 * the space's accessible name and in the centre detail, so a screen reader
 * never depends on this element.
 */
function renderBuildings(level: number): ReactElement {
  return (
    <span className="monopoly-space-buildings" aria-hidden="true">
      {level === HOTEL_LEVEL ? (
        <span className="monopoly-space-hotel" />
      ) : (
        Array.from({ length: level }, (_, house) => (
          <span className="monopoly-space-house" key={house} />
        ))
      )}
    </span>
  )
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
function spaceAriaLabel(
  space: Space,
  owner: string | null,
  auctioned: boolean,
  mortgaged: boolean,
  level: number | null,
): string {
  const parts = [space.name, KIND_LABELS[space.kind]]
  if (space.group) parts.push(GROUP_LABELS[space.group])
  if (isPurchasable(space)) parts.push(`Precio ${formatMoney(purchasePrice(space.index))}`)
  if (owner) parts.push(`Dueño ${owner}`)
  if (auctioned) parts.push('En subasta')
  if (mortgaged) parts.push('Hipotecada')
  if (level !== null) parts.push(levelLabel(level))
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
 *
 * The three seat-view props are optional and the board of today is what they
 * default to (S13):
 *
 * - ``turns`` re-indexes the ring with ``cellFor``/``sideFor`` (S4). It is never
 *   a ``transform``: a turn moves a space to another cell, so its name, price
 *   and tokens stay upright and the band still faces the centre.
 * - ``centre`` decides whether the 9x9 middle holds the table's content or
 *   stays an empty surface. A seven-cell window can never hold a nine-cell
 *   centre, so the seat's placement leaves it empty and the same block is drawn
 *   in a strip under the window (S10).
 * - ``onFocus`` reports the space that takes keyboard focus, so the panel can
 *   recentre the window on a space it cut off (S11). It is never called on a
 *   click: the board does not decide anything, it only reports.
 */
export function MonopolyBoard({
  match,
  selected,
  onSelect,
  turns = 0,
  centre = 'board',
  onFocus,
}: {
  match: MatchState<MonopolyView>
  selected: number | null
  onSelect: (index: number) => void
  turns?: QuarterTurns
  centre?: 'board' | 'none'
  onFocus?: (index: number) => void
}) {
  const { view } = match

  return (
    <div className="monopoly-board" role="group" aria-label="Tablero de Monopoly">
      {BOARD.map((space) => {
        const area = cellFor(space.index, turns)
        const owner = ownerName(match, space.index)
        const auctioned = view.auction !== null && view.auction.space === space.index
        const mortgaged = view.mortgaged[String(space.index)] === true
        const level = buildingLevel(view, space.index)
        const holders = view.players.filter(
          (player) => !player.eliminated && player.position === space.index,
        )
        return (
          <button
            aria-label={spaceAriaLabel(space, owner, auctioned, mortgaged, level)}
            aria-pressed={selected === space.index}
            className={[
              'monopoly-space',
              auctioned ? 'monopoly-space-auction' : '',
              mortgaged ? 'monopoly-space-mortgaged' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            data-auction={auctioned ? 'true' : undefined}
            data-group={space.group ?? undefined}
            data-kind={space.kind}
            data-mortgaged={mortgaged ? 'true' : undefined}
            data-side={sideFor(space.index, turns)}
            key={space.index}
            onClick={() => onSelect(space.index)}
            onFocus={onFocus === undefined ? undefined : () => onFocus(space.index)}
            style={{ gridRow: area.row, gridColumn: area.column }}
            type="button"
          >
            {space.group && <span className="monopoly-space-band" aria-hidden="true" />}
            {level !== null && renderBuildings(level)}
            <span className="monopoly-space-name">{space.name}</span>
            {isPurchasable(space) && (
              <span className="monopoly-space-price">
                {formatMoney(purchasePrice(space.index))}
              </span>
            )}
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

      {centre === 'board' ? (
        <MonopolyTableCentre match={match} selected={selected} />
      ) : (
        <div
          aria-hidden="true"
          className="monopoly-centre monopoly-centre-empty"
          style={{ gridRow: '2 / 11', gridColumn: '2 / 11' }}
        />
      )}
    </div>
  )
}
