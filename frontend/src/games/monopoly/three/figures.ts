/**
 * Which classic piece stands for each marker (X5 of ``monopoly-3d-table.md``).
 *
 * The marker is the player's choice in the room and it travels in the roster
 * (``game_marker``); the board never invents it and never maps it to a label --
 * the label comes from the server too. What this module owns is the one thing
 * the server cannot send: **which silhouette** the scene prints for that id.
 *
 * It is deliberately pure and free of ``three`` so the catalogue can be pinned
 * by the DOM-less harness. ``figureInk.ts`` turns a ``PieceFigure`` into path
 * data and the scene paints it on a token, and new markers on the server fall
 * back to the neutral counter instead of breaking the table.
 *
 * Seam to remember: the ids are the ``seat_options`` of the monopoly definition
 * (``backend/modules/games/monopoly/game.py``), which offers **more markers than
 * the table seats players** -- ``MAX_SEATS`` is 8 and the catalogue is 10, because
 * a marker reserves nothing. A marker added there is invisible here until this
 * list and the figure map learn it, which is the same kind of copy
 * ``GROUP_COLOURS`` already makes from the stylesheet.
 */

/** Every silhouette the scene can build, the neutral fallback included. */
export const PIECE_FIGURES = [
  'sombrero',
  'automovil',
  'perro',
  'barco',
  'gato',
  'plancha',
  'botin',
  'dedal',
  'pinguino',
  'pato',
  'ficha',
] as const

/** One silhouette the scene knows how to build from primitives. */
export type PieceFigure = (typeof PIECE_FIGURES)[number]

/**
 * The figure for each marker id the room offers.
 *
 * A ``Map`` and not an object literal: an object also answers to ``toString``,
 * ``constructor`` and the rest of ``Object.prototype``, so
 * ``FIGURE_BY_MARKER['toString']`` would hand back a function and the scene
 * would ask for a figure that does not exist. The map knows these ids and
 * nothing else; any other string is ``undefined`` and becomes the counter.
 */
const FIGURE_BY_MARKER: ReadonlyMap<string, PieceFigure> = new Map([
  ['sombrero', 'sombrero'],
  ['automovil', 'automovil'],
  ['perro', 'perro'],
  ['barco', 'barco'],
  ['gato', 'gato'],
  ['plancha', 'plancha'],
  ['botin', 'botin'],
  ['dedal', 'dedal'],
  ['pinguino', 'pinguino'],
  ['pato', 'pato'],
])

/**
 * The silhouette of a marker id.
 *
 * The id travels verbatim, so it is matched verbatim: an empty marker (a roster
 * with no entry for the seat) and an id from another game both get ``ficha``.
 * Falling back is the honest behaviour -- the alternative is a figure that lies
 * about what the player chose.
 */
export function figureFor(marker: string): PieceFigure {
  return FIGURE_BY_MARKER.get(marker) ?? 'ficha'
}
