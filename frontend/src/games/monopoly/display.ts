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
import type { MatchSeatRosterEntry } from '../matchRoster'
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
 * The game's printed name, shown on the board's centre band (S6).
 *
 * The board is rendered from the match view alone and never receives the game
 * catalog label the page heading uses, so the name is **copied** here next to
 * the deck and group labels this module already owns.
 *
 * It is a copy and not the source: the backend's ``label`` is. Renaming the game
 * therefore costs two edits and nothing fails when only one is made. Passing
 * the label through the match view would remove the copy, and that is a change
 * to the shared view for a cosmetic reason; until somebody decides to make it,
 * this comment is the only warning.
 */
export const GAME_NAME = 'Monopoly'

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

/**
 * The initial the board prints inside the badge and the token of a seat.
 *
 * A name with no letters at all (an empty roster name) still gets a glyph, so a
 * badge is never blank: ``?`` says there is a name the client could not read.
 */
export function initialOf(name: string): string {
  const first = name.trim().charAt(0)
  return first === '' ? '?' : first.toUpperCase()
}

/**
 * The ink of each seat, indexed by the roster's ``index``.
 *
 * The board answers "who owns this space". A name alone does not answer it at a
 * glance: the badge is a handful of pixels wide, so two long names are clipped
 * to the same shape and only a careful reader can tell them apart. A tone per
 * seat is what a player actually scans, and it costs the protocol nothing: the
 * roster already publishes the seat's index, every client derives the same
 * tone, and the server never learns that a colour exists.
 *
 * Three rules keep it honest:
 *
 * 1. **One tone per seat the table can hold.** The palette is exactly eight
 *    entries -- the printed board's own ``MAX_SEATS`` -- and never repeats
 *    itself inside that range. An index beyond it wraps, which is a colour two
 *    seats would share, and that is why the caller always prints the seat's
 *    initial next to the tone: colour is never the only cue.
 * 2. **It never competes with a colour group.** The eight deed colours are the
 *    light or mid-tone hues of the printed board; these are deliberately dark
 *    and muted. They also sit on different surfaces -- the group paints the
 *    inner band, the owner paints the cell's frame and the badge's initial -- so
 *    a player who cannot tell violet from navy still reads both facts.
 * 3. **It is presentation, never state.** Nothing about ownership is derived
 *    here: the seat comes from ``view.owners`` and its name from the roster.
 *    A seat the roster does not name has no index, and therefore no tone.
 */
export const SEAT_TONES: readonly string[] = [
  '#5b2a86', // violeta
  '#0b7285', // petróleo
  '#1b3a8f', // azul marino
  '#4d5d1f', // oliva
  '#9c1d3f', // vino
  '#2f7d32', // verde bosque
  '#6b2d5c', // ciruela
  '#7a4a00', // ámbar oscuro
]

/**
 * The tone of one seat index, or ``null`` when the index cannot name a seat.
 *
 * ``null`` is not a fallback colour on purpose: an unnameable seat gets the
 * badge without the tone instead of a tone that would claim an identity.
 */
export function seatTone(index: number | null | undefined): string | null {
  if (index === null || index === undefined) return null
  if (!Number.isInteger(index) || index < 0) return null
  return SEAT_TONES[index % SEAT_TONES.length]
}

/**
 * The roster index of ``seatId``, or ``null`` when the roster does not name it.
 *
 * The index is read from the roster entry and never parsed out of the seat id:
 * the id is an opaque string the server mints, while ``index`` is the public
 * fact the tone is keyed on.
 */
export function seatIndexOf(
  roster: readonly MatchSeatRosterEntry[],
  seatId: string,
): number | null {
  const entry = roster.find((candidate) => candidate.seat_id === seatId)
  return entry === undefined ? null : entry.index
}
