/**
 * Where the camera sits and what it looks at, per seat (S4 and S10 of
 * ``monopoly-3d-table.md``).
 *
 * The reference image is a real board on a table, photographed from one player's
 * corner: a low camera -- about twenty degrees above the table -- with the near
 * corner close and large and the far edge compressed. That is a *geometry*, so it
 * is decided here, in plain numbers, and not inside the scene.
 *
 * Nothing in this module imports ``three``: the scene converts these numbers into
 * a camera, and keeping that conversion out of here is what lets the view be
 * tested in the project's DOM-less harness.
 *
 * World units are cells: the board spans ``0..11`` on ``x`` and ``z``, ``y`` is
 * up, and ``z`` grows towards the viewer, so row 1 of the grid is the far row.
 */

import { BOARD_SIZE } from '../board'
import { GRID_SIZE, spaceArea } from '../grid'

/** One cell is one unit, which is what makes the numbers below readable. */
export const CELL_SIZE = 1

/** A point in the scene, in world units. */
export type Point3 = { x: number; y: number; z: number }

/**
 * Where the camera looks, as the two Euler angles a camera needs.
 *
 * ``order`` is ``YXZ``, which is what makes a yaw followed by a pitch enough to
 * aim a camera whose forward axis is ``-Z``; the roll stays zero because a table
 * seen from a seat is never tilted.
 */
export type CameraRotation = { x: number; y: number; order: 'YXZ' }

/** What a seat's camera is: where it stands, what it looks at and how wide. */
export type SeatCamera = {
  position: Point3
  target: Point3
  rotation: CameraRotation
  fov: number
}

/** The middle of the board, which is what every seat looks at. */
export const BOARD_CENTER: Point3 = {
  x: (GRID_SIZE * CELL_SIZE) / 2,
  y: 0,
  z: (GRID_SIZE * CELL_SIZE) / 2,
}

/**
 * How far outside its own corner a seat's camera stands, in cells.
 *
 * Eight is where the whole board fits inside the **vertical** field of view at
 * the lowest zoom, which is the number that matters: the two corners at ninety
 * degrees are the widest thing in the picture, and fitting them to the vertical
 * axis is what keeps a board whole on a narrow screen instead of only on a wide
 * one. Nearer than this and a player opens on a board with two corners cut off;
 * further away and the foreshortening the reference image lives on fades.
 */
export const OUTWARD_DISTANCE = 8

/** Degrees above the table. A high camera would flatten the board again. */
export const ELEVATION_DEGREES = 20

/** The zoom ladder, widest first (S10). Index 0 shows the whole board. */
export const FOV_STEPS: readonly number[] = [50, 42, 34]

/** The step a match opens on: the whole board, so nothing is cut off. */
export const DEFAULT_ZOOM = 0

/** Corners are ten spaces apart, like the ring's own shift. */
const CORNER_INDEX_STEP = BOARD_SIZE / 4

/** The four corners in circuit order, as far as the seat index is concerned. */
function cornerIndex(seatIndex: number): number {
  return ((seatIndex % 4) + 4) % 4
}

/**
 * The centre of the cell a space occupies, on the table's surface.
 *
 * The grid gives the row and the column; the scene wants the middle of that cell,
 * which is the half-cell offset, and ``z`` growing towards the viewer.
 */
export function cellCenter(index: number): Point3 {
  const { row, column } = spaceArea(index)
  return {
    x: (column - 0.5) * CELL_SIZE,
    y: 0,
    z: (row - 0.5) * CELL_SIZE,
  }
}

/**
 * The corner the seat sits at (S4).
 *
 * Seat order, not position: every seat starts on GO after the opening throw, so
 * where a player stands cannot choose a view. With more than four seats two
 * players share a corner, exactly as two people share a side of a real table.
 */
export function seatCorner(seatIndex: number): Point3 {
  return cellCenter(cornerIndex(seatIndex) * CORNER_INDEX_STEP)
}

/** A zoom step kept inside the ladder instead of inventing a camera. */
export function clampZoom(step: number): number {
  if (!Number.isFinite(step)) return DEFAULT_ZOOM
  return Math.min(Math.max(Math.round(step), 0), FOV_STEPS.length - 1)
}

/**
 * The camera of a seat, at a zoom step (S4, S10).
 *
 * The camera stands outside the seat's own corner along the diagonal from the
 * centre, at a fixed elevation, and always looks at the middle of the board. The
 * height is derived from the horizontal distance rather than fixed, so the
 * elevation is the same twenty degrees for every corner of the square.
 */
export function cameraFor(seatIndex: number, zoom: number = DEFAULT_ZOOM): SeatCamera {
  const corner = seatCorner(seatIndex)
  const awayX = corner.x - BOARD_CENTER.x
  const awayZ = corner.z - BOARD_CENTER.z
  const awayLength = Math.hypot(awayX, awayZ)
  const outwardX = awayX / awayLength
  const outwardZ = awayZ / awayLength
  const standing = {
    x: corner.x + outwardX * OUTWARD_DISTANCE,
    z: corner.z + outwardZ * OUTWARD_DISTANCE,
  }
  const horizontal = Math.hypot(standing.x - BOARD_CENTER.x, standing.z - BOARD_CENTER.z)
  const height = horizontal * Math.tan((ELEVATION_DEGREES * Math.PI) / 180)
  const position = { x: standing.x, y: height, z: standing.z }
  return {
    position,
    target: BOARD_CENTER,
    rotation: rotationLookingAt(position, BOARD_CENTER),
    fov: FOV_STEPS[clampZoom(zoom)],
  }
}

/**
 * The angles that aim a ``-Z`` forward camera from ``position`` at ``target``.
 *
 * The alternative -- moving the camera imperatively inside the scene -- is the
 * one thing the project's React rules forbid, mutating what a hook returned, and
 * rightly: an aim that lives in an effect cannot be asserted. So the aim is
 * arithmetic here: with ``YXZ`` the pitch is ``asin`` of the vertical component
 * and the yaw comes from the horizontal pair, and ``camera.test.ts`` proves the
 * result by rotating the forward axis and comparing it with the direction the
 * camera is supposed to look in.
 */
export function rotationLookingAt(position: Point3, target: Point3): CameraRotation {
  const dx = target.x - position.x
  const dy = target.y - position.y
  const dz = target.z - position.z
  const length = Math.hypot(dx, dy, dz)
  const pitch = Math.asin(dy / length)
  const yaw = Math.atan2(-dx, -dz)
  return { x: pitch, y: yaw, order: 'YXZ' }
}
