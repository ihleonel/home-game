import type { CSSProperties, ReactElement } from 'react'
import type { MatchState } from '../registry'
import { BOARD, isPurchasable } from './board'
import type { Space } from './board'
import { HOTEL_LEVEL, levelLabel, purchasePrice } from './deeds'
import {
  GROUP_INITIALS,
  GROUP_LABELS,
  KIND_LABELS,
  formatMoney,
  initialOf,
  seatIndexOf,
  seatName,
  seatTone,
} from './display'
import { MonopolyTableCentre } from './MonopolyTableCentre'
import { spaceArea, spaceSide } from './grid'
import type { MonopolyPlayer, MonopolyView } from './view'

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
function ownerOf(match: MatchState<MonopolyView>, index: number): string | null {
  const seat = match.view.owners[String(index)]
  return seat === undefined ? null : seatName(match, seat)
}

/**
 * The tone of the seat that owns ``index``, or ``null`` when there is none.
 *
 * Ownership and colour are read from two different places and neither is
derived from the other: the seat is the server's fact in ``view.owners``, the
 * tone is the roster entry's ``index``. A seat the roster cannot name keeps the
 * badge and loses only the colour.
 */
function ownerTone(match: MatchState<MonopolyView>, index: number): string | null {
  const seat = match.view.owners[String(index)]
  if (seat === undefined) return null
  return seatTone(seatIndexOf(match.roster, seat))
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
 *
 * The token also carries the tone of its seat (``--monopoly-seat-tone``), the
 * same one the owned spaces are framed in: two seats standing on one cell are
 * the hardest thing on the board to read, and the tone is what separates them
 * when their initials happen to match.
 */
function renderToken(player: MonopolyPlayer, match: MatchState<MonopolyView>): ReactElement {
  const name = seatName(match, player.seat)
  const isYou = player.seat === match.view.you
  const tone = seatTone(seatIndexOf(match.roster, player.seat))
  const label = `${name}${isYou ? ' (tú)' : ''}${player.in_jail ? ' · En la cárcel' : ''}`
  const classes = [
    'monopoly-token',
    isYou ? 'monopoly-token-you' : '',
    player.in_jail ? 'monopoly-token-jailed' : '',
  ]
    .filter(Boolean)
    .join(' ')
  // The custom property sits on the token, not on the initial, so a seat the
  // roster cannot name simply has no tone and the stylesheet falls back to ink.
  const style = tone === null ? undefined : ({ '--monopoly-seat-tone': tone } as CSSProperties)
  return (
    <span
      aria-label={label}
      className={classes}
      key={player.seat}
      role="img"
      style={style}
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
 * The owner is printed twice over, and both readings are presentation: the
 * seat's tone frames the cell (``data-owned`` plus
 * ``--monopoly-seat-tone`` for the stylesheet) and the badge carries the tone,
 * the seat's initial and its name. The tone never replaces the name.
 */
export function MonopolyBoard({
  match,
  selected,
  onSelect,
  centre = 'board',
  onFocus,
}: {
  match: MatchState<MonopolyView>
  selected: number | null
  onSelect: (index: number) => void
  /**
   * Whether the middle of the board holds the table's content (S9).
   *
   * The 3D scene draws that block itself, over the table, so the board it hides
   * for the accessible mirror is asked for the ring alone; a full copy would
   * announce the turn and the last throw twice.
   */
  centre?: 'board' | 'none' | 'print'
  /** Reports the space that takes keyboard focus, so a mirror can select it. */
  onFocus?: (index: number) => void
}) {
  const { view } = match

  return (
    <div className="monopoly-board" role="group" aria-label="Tablero de Monopoly">
      {BOARD.map((space) => {
        const area = spaceArea(space.index)
        const owner = ownerOf(match, space.index)
        const tone = ownerTone(match, space.index)
        const auctioned = view.auction !== null && view.auction.space === space.index
        const mortgaged = view.mortgaged[String(space.index)] === true
        const level = buildingLevel(view, space.index)
        const holders = view.players.filter(
          (player) => !player.eliminated && player.position === space.index,
        )
        // The tone travels as a custom property so the stylesheet owns the
        // shape of the cue: the cell's frame and the badge's initial both read
        // it, and a space with no tone simply falls back to neutral ink.
        const style = {
          gridRow: area.row,
          gridColumn: area.column,
          ...(tone === null ? {} : { '--monopoly-seat-tone': tone }),
        } as CSSProperties
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
            data-owned={owner === null ? undefined : 'true'}
            data-side={spaceSide(space.index)}
            key={space.index}
            onClick={() => onSelect(space.index)}
            onFocus={onFocus === undefined ? undefined : () => onFocus(space.index)}
            style={style}
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
            {owner && (
              <span className="monopoly-space-owner">
                <span className="monopoly-space-owner-initial" aria-hidden="true">
                  {initialOf(owner)}
                </span>
                <span className="monopoly-space-owner-name">{owner}</span>
              </span>
            )}
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
      ) : centre === 'print' ? (
        // X8: the mirror's copy of what the rendered board prints on its middle.
        // The canvas is invisible to a screen reader, so these facts live here.
        <MonopolyTableCentre match={match} placement="print" selected={selected} />
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
