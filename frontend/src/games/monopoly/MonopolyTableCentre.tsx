/**
 * The middle of the table: the game's name, the two deck piles, the match state
 * (turn, last throw, last card, open auction) and the detail of the tapped space.
 *
 * Two placements, one source (S9 of ``monopoly-3d-table.md``):
 *
 * 1. The spectator sees the flat board, so the block sits inside its 9x9 hole.
 * 2. The seat sees the 3D table, where the block is drawn over the scene as a
 *    card, because a rendered board has no DOM hole to put it in.
 *
 * Copying the markup into the two placements would let them drift, so the board
 * renders this component instead of its own copy.
 */

import type { ReactElement } from 'react'
import type { MatchState } from '../registry'
import { isPurchasable, spaceAt } from './board'
import type { Space } from './board'
import { deedFor, levelLabel, mortgageLiftCost, mortgageValue, purchasePrice, rentForLevel } from './deeds'
import {
  DECK_LABELS,
  GAME_NAME,
  GROUP_LABELS,
  KIND_LABELS,
  deckLabel,
  formatMoney,
  seatName,
} from './display'
import type { MonopolyView } from './view'

const RENT_ROW_LABELS = [
  'Renta base',
  'Con grupo completo',
  '1 casa',
  '2 casas',
  '3 casas',
  '4 casas',
  'Hotel',
]

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

/** The open space's card: kind, group, price, printed rents, buildings and mortgage. */
function spaceDetail(match: MatchState<MonopolyView>, chosen: Space): ReactElement {
  // The same two facts the cells of the ring read: the development level lives
  // only in ``view.buildings`` (keyed by string, because the state is ``jsonb``)
  // and the owner only in ``view.owners``. Neither is derived from the other,
  // and the badge on the cell and this line have to agree.
  const { view } = match
  const level: number | undefined = view.buildings[String(chosen.index)]
  const ownerSeat: string | undefined = view.owners[String(chosen.index)]
  const owner = ownerSeat === undefined ? null : seatName(match, ownerSeat)
  const mortgaged = view.mortgaged[String(chosen.index)] === true
  return (
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
      {level !== undefined && (
        <p className="monopoly-detail-buildings">
          {`Edificios: ${levelLabel(level)}`}
        </p>
      )}
      {mortgaged && isPurchasable(chosen) && (
        <p className="monopoly-detail-mortgaged">
          {`Hipotecada · Valor ${formatMoney(mortgageValue(chosen.index))} · Levantar ${formatMoney(mortgageLiftCost(chosen.index))}`}
        </p>
      )}
      {isPurchasable(chosen) && (
        <p className="monopoly-detail-owner">
          {`Dueño: ${owner ?? 'Sin dueño'}`}
        </p>
      )}
    </div>
  )
}

/**
 * Render the middle of the table for either placement (S10).
 *
 * It is a pure function of the match and the open space, like the board: it
 * owns no state and receives the selection instead of deciding it. The grid
 * placement is for the placement inside the ring; a strip under the window is
 * not a grid, and CSS ignores the two properties there.
 */
export function MonopolyTableCentre({
  match,
  selected,
}: {
  match: MatchState<MonopolyView>
  selected: number | null
}) {
  const { view } = match
  const chosen = selected === null ? null : spaceAt(selected)

  return (
    <div className="monopoly-centre" style={{ gridRow: '2 / 11', gridColumn: '2 / 11' }}>
      <div className="monopoly-centre-band">
        <p className="monopoly-brand-name">{GAME_NAME}</p>
        {view.decks !== null && (
          <div className="monopoly-piles">
            <div className="monopoly-pile monopoly-pile-chance">
              <span className="monopoly-pile-name">{DECK_LABELS.chance}</span>
              <span className="monopoly-pile-count">{view.decks.chance}</span>
            </div>
            <div className="monopoly-pile monopoly-pile-community">
              <span className="monopoly-pile-name">{DECK_LABELS.community_chest}</span>
              <span className="monopoly-pile-count">{view.decks.community_chest}</span>
            </div>
          </div>
        )}
      </div>
      <div className="monopoly-status">
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
      </div>
      {chosen !== null && spaceDetail(match, chosen)}
    </div>
  )
}
