/**
 * How a monopoly payload is shown to a person.
 *
 * One place for the labels and the two small formatters both match-screen
 * components need, so the money the board prints and the money the panel prints
 * cannot drift apart, and a colour group is spelled the same way in the cell,
 * in the centre detail and in the own-properties list.
 *
 * Nothing here computes a rule. A figure is either the printed deed data
 * (reference) or a field of the server view (state); which rent is *owed* is
 * the server's decision and never a function of this module.
 */

import type { MatchState } from '../registry'
import type { ColorGroup, SpaceKind } from './board'
import type { MonopolyView } from './view'

/**
 * Spanish names for every space kind, so the detail panel and the accessible
 * name never show the backend's machine identifiers to a person.
 */
export const KIND_LABELS: Record<SpaceKind, string> = {
  go: 'Salida',
  street: 'Calle',
  railroad: 'Ferrocarril',
  utility: 'Servicio',
  chance: 'Suerte',
  community_chest: 'Caja de comunidad',
  income_tax: 'Impuesto sobre los ingresos',
  luxury_tax: 'Impuesto de lujo',
  jail: 'Cárcel',
  free_parking: 'Parada libre',
  go_to_jail: 'Ir a la cárcel',
}

/** The colour groups in Spanish, as the printed board spells them. */
export const GROUP_LABELS: Record<ColorGroup, string> = {
  brown: 'Marrón',
  light_blue: 'Celeste',
  pink: 'Rosa',
  orange: 'Naranja',
  red: 'Rojo',
  yellow: 'Amarillo',
  green: 'Verde',
  dark_blue: 'Azul oscuro',
}

/**
 * Two-letter group initials shown under the colour band.
 *
 * Colour is never the only cue (S3): the space name and these initials say the
 * same thing the band paints, so the band is decoration for sighted players
 * rather than the information itself. Two letters because the Spanish group
 * names collide on their first letter (Rojo and Rosa, Marrón and, on a small
 * cell, Amarillo).
 */
export const GROUP_INITIALS: Record<ColorGroup, string> = {
  brown: 'MA',
  light_blue: 'CE',
  pink: 'RS',
  orange: 'NA',
  red: 'RO',
  yellow: 'AM',
  green: 'VE',
  dark_blue: 'AZ',
}

/**
 * The printed names of the two card decks (S12).
 *
 * The server sends the machine deck id; both the board and the panel turn it
 * into the words printed on the card piles through here, so a deck cannot be
 * spelled two different ways in the same screen.
 */
export const DECK_LABELS: Record<string, string> = {
  chance: 'Suerte',
  community_chest: 'Caja de comunidad',
}

/** A deck's printed name, falling back to the id for a deck we do not know. */
export function deckLabel(deck: string): string {
  return DECK_LABELS[deck] ?? deck
}

/**
 * Group an integer amount of dollars with dots, the way the board prints it.
 *
 * ``Intl`` is deliberately avoided: the tests run in Node and the markup has
 * to be identical no matter which ICU data the container happens to ship.
 */
export function formatMoney(value: number): string {
  const grouped = Math.trunc(Math.abs(value))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return value < 0 ? `-$${grouped}` : `$${grouped}`
}

/**
 * The display name the roster gives a seat.
 *
 * A seat the roster does not name reads ``Jugador``, never a seat number: the
 * client renders identity, it does not derive it.
 */
export function seatName(match: MatchState<MonopolyView>, seatId: string): string {
  const entry = match.roster.find((candidate) => candidate.seat_id === seatId)
  return entry ? entry.display_name : 'Jugador'
}
