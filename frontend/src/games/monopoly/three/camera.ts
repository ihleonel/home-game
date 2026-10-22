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
 * Six, and the board is *not* meant to fit: the reference photograph fills its
 * frame with the near half of the board and lets the far corners run off the top,
 * which is exactly what makes the near cells big enough to read. The far edge is
 * not lost -- tapping a space puts it on the card over the table.
 */
export const OUTWARD_DISTANCE = 5

/**
 * How much of the way from the middle towards the seat's own corner the camera
 * aims at (W3).
 *
 * Aiming at the middle is what made a close view show the hollow: the near
 * corner fell below the frame and the empty centre filled it. The reference
 * photograph is framed on the *near corner* -- that is where the readable cells
 * are -- so the aim moves a third of the way towards it and the far edge runs off
 * the top, which is exactly the picture the owner of the look asked for.
 */
export const FRAME_TOWARDS_CORNER = 0.34

/**
 * Degrees above the table (X1).
 *
 * Twenty was too low: the near corner sat almost under the camera, so a square
 * phone frame lost it and the hollow of the ring filled the middle. Twenty-eight
 * tilts the view enough that the corner reads inside the frame at any aspect while
 * the board stays a board seen from a seat and not a plan view.
 */
export const ELEVATION_DEGREES = 28

/**
 * The single field of view a seat reads with (W3).
 *
 * There used to be a ladder of three steps and two buttons to walk it. The owner
 * of the look asked for one view like the reference photograph and the buttons
 * gone, and it is the right call: a close framing is a *decision*, not a control,
 * and the far edge it crops is read in the card over the table. What a seat can
 * still do is turn the board, which is the one interaction that changes what they
 * are looking at.
 */
export const SEAT_FOV = 32

/**
 * The narrowest and widest vertically-framed view the scene will accept (W6).
 *
 * A phone in portrait is a square frame; the same camera that fills a 4:3 screen
 * cuts the seat's own corner off the bottom of it. So the field of view is not a
 * constant any more: it is derived from the aspect so the near corner always
 * lands inside the frame with a margin, and the clamp keeps a degenerate aspect
 * from producing a fisheye.
 */
export const MIN_FOV = 24
export const MAX_FOV = 68

/** How much room the near corner keeps from the frame's edge. */
export const CORNER_MARGIN = 1.14

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

/**
 * How far the printed middle of the board has to be turned for a seat (X8).
 *
 * The middle used to carry its information in an HTML card, floating over the
 * frame; a card is not the board's middle once the table rests at an arbitrary
 * angle (X7), so the name and the piles are printed on the surface. A plane
 * lying flat maps the top of its texture to world ``-z``, and a seat calls "up"
 * the direction from its own corner towards the middle, so that is where the
 * texture's top is turned to. It is a print, not a billboard: it turns with the
 * board from there, exactly like the cells' own lettering.
 */
export function centrePrintRotation(seatIndex: number): number {
  const corner = seatCorner(seatIndex)
  const awayX = corner.x - BOARD_CENTER.x
  const awayZ = corner.z - BOARD_CENTER.z
  const length = Math.hypot(awayX, awayZ) || 1
  // ``atan2(d.x, d.z)`` is the yaw that takes ``(0, 0, -1)`` to ``-d``, and the
  // test proves that with the rotated axis rather than with this line's sign.
  return Math.atan2(awayX / length, awayZ / length)
}

/**
 * The direction from the middle of the board towards a seat's camera, in radians.
 *
 * The camera stands outside the seat's own corner, so this is also the direction
 * of that corner. It is what an automatic turn aims a piece at (X11).
 */
export function seatAzimuth(seatIndex: number): number {
  const camera = cameraFor(seatIndex).position
  return Math.atan2(camera.z - BOARD_CENTER.z, camera.x - BOARD_CENTER.x)
}

/**
 * How far the board has to turn to bring ``point`` towards the seat's camera
 * (X11).
 *
 * Rotating the board by ``θ`` moves a point at azimuth ``α`` to ``α - θ`` --
 * three's ``Y`` rotation turns the other way in the ``atan2(z, x)`` sense -- so
 * facing the camera asks for ``α - φ``. The result is not wrapped: the caller
 * picks the copy nearest the angle the eye already has (``nearestTurn``), which
 * is what keeps the table from sweeping the long way round.
 */
export function turnToFace(seatIndex: number, point: Point3): number {
  const azimuth = Math.atan2(point.z - BOARD_CENTER.z, point.x - BOARD_CENTER.x)
  return azimuth - seatAzimuth(seatIndex)
}

/**
 * The copy of ``target`` closest to ``current`` (X11).
 *
 * The board's angle accumulates across turns, so two angles a full turn apart are
 * the same view. Aiming at the raw target would sometimes spin the table all the
 * way round to reach a face the player is already looking at from the other side.
 */
export function nearestTurn(target: number, current: number): number {
  const turn = Math.PI * 2
  return target + turn * Math.round((current - target) / turn)
}

/** A quarter turn, in radians: the unit the table settles on. */
export const QUARTER_TURN = Math.PI / 2

/**
 * How far the hand has turned the table, in radians, for a horizontal drag (X3).
 *
 * Linear in the pixels, with no rounding, which is the whole point: the board
 * follows the finger instead of waiting for it to cross a step. A drag of one
 * ``stepPx`` turns a quarter, so the gesture keeps the reach it had when it
 * stepped in quarters.
 *
 * **Positive for a drag to the right, and that sign is the whole gesture.** The
 * board turns about the world's up axis, and rotating it by a positive angle
 * moves its near corner towards the frame's right for a camera standing on any
 * of the four corners: that is what ``camera.test.ts`` proves by projecting the
 * seat's own corner before and after the drag, instead of reading the sign back
 * from this function. The first implementation had it negative "because the
 * quarter step reported it that way", which turned the board against the hand.
 */
export function dragTurnRadians(pixels: number, stepPx: number): number {
  if (stepPx <= 0) return 0
  return (pixels / stepPx) * QUARTER_TURN
}

/**
 * The camera of a seat, at a zoom step (S4, S10).
 *
 * The camera stands outside the seat's own corner along the diagonal from the
 * centre, at a fixed elevation, and always looks at the middle of the board. The
 * height is derived from the horizontal distance rather than fixed, so the
 * elevation is the same twenty degrees for every corner of the square.
 */
/**
 * The vertical field of view that keeps ``corner`` inside a frame of ``aspect``
 * (W6).
 *
 * Worked in the camera's own basis rather than by trial: the corner's offset from
 * the view axis gives the two tangents the frustum has to satisfy -- vertical
 * ``|y| / z`` and horizontal ``|x| / z``, the second divided by the aspect because
 * the horizontal half-angle is ``atan(tan(fov / 2) · aspect)``. The binding one
 * wins, the margin is multiplied in, and the result is clamped.
 */
export function fovForAspect(
  position: Point3,
  target: Point3,
  corner: Point3,
  aspect: number,
): number {
  const forward = {
    x: target.x - position.x,
    y: target.y - position.y,
    z: target.z - position.z,
  }
  const forwardLength = Math.hypot(forward.x, forward.y, forward.z)
  const f = { x: forward.x / forwardLength, y: forward.y / forwardLength, z: forward.z / forwardLength }
  // Right comes from the world's up; up from the right and the forward axis.
  const rightRaw = { x: f.z, y: 0, z: -f.x }
  const rightLength = Math.hypot(rightRaw.x, rightRaw.z) || 1
  const r = { x: rightRaw.x / rightLength, y: 0, z: rightRaw.z / rightLength }
  const u = {
    x: r.y * f.z - r.z * f.y,
    y: r.z * f.x - r.x * f.z,
    z: r.x * f.y - r.y * f.x,
  }
  const toCorner = {
    x: corner.x - position.x,
    y: corner.y - position.y,
    z: corner.z - position.z,
  }
  const depth = Math.abs(toCorner.x * f.x + toCorner.y * f.y + toCorner.z * f.z)
  if (depth < 1e-6) return SEAT_FOV
  const across = Math.abs(toCorner.x * r.x + toCorner.y * r.y + toCorner.z * r.z) / depth
  const vertical = Math.abs(toCorner.x * u.x + toCorner.y * u.y + toCorner.z * u.z) / depth
  const safeAspect = Math.max(aspect, 0.2)
  const needed = Math.max(vertical, across / safeAspect) * CORNER_MARGIN
  const fov = (2 * Math.atan(needed) * 180) / Math.PI
  return Math.min(Math.max(fov, MIN_FOV), MAX_FOV)
}

export function cameraFor(seatIndex: number, aspect: number = 4 / 3): SeatCamera {
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
  const target = {
    x: BOARD_CENTER.x + awayX * FRAME_TOWARDS_CORNER,
    y: BOARD_CENTER.y,
    z: BOARD_CENTER.z + awayZ * FRAME_TOWARDS_CORNER,
  }
  // The height is set by the camera's distance to the *middle* of the board, so
  // twenty degrees means twenty degrees over the table for every seat; where it
  // aims is a separate decision (``FRAME_TOWARDS_CORNER``) and must not change it.
  const horizontal = Math.hypot(standing.x - BOARD_CENTER.x, standing.z - BOARD_CENTER.z)
  const height = horizontal * Math.tan((ELEVATION_DEGREES * Math.PI) / 180)
  const position = { x: standing.x, y: height, z: standing.z }
  return {
    position,
    target,
    rotation: rotationLookingAt(position, target),
    fov: fovForAspect(position, target, corner, aspect),
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
