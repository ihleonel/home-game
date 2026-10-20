import { describe, expect, it } from 'vitest'
import { BOARD_SIZE } from '../board'
import { GRID_SIZE } from '../grid'
import {
  BOARD_CENTER,
  MAX_FOV,
  MIN_FOV,
  fovForAspect,
  SEAT_FOV,
  cameraFor,
  cellCenter,
  sceneRotationFor,
  seatCorner,
} from './camera'
import type { Point3 } from './camera'

/** The four corners of the printed board in world units, in circuit order. */
const CORNERS: readonly { seat: number; point: Point3 }[] = [
  { seat: 0, point: { x: 10.5, y: 0, z: 10.5 } },
  { seat: 1, point: { x: 0.5, y: 0, z: 10.5 } },
  { seat: 2, point: { x: 0.5, y: 0, z: 0.5 } },
  { seat: 3, point: { x: 10.5, y: 0, z: 0.5 } },
]

function distance(left: Point3, right: Point3): number {
  return Math.hypot(left.x - right.x, left.y - right.y, left.z - right.z)
}

function horizontalDistance(left: Point3, right: Point3): number {
  return Math.hypot(left.x - right.x, left.z - right.z)
}

describe('where each seat sits', () => {
  it('gives the four printed corners to the first four seats, in circuit order', () => {
    for (const { seat, point } of CORNERS) {
      expect([seat, seatCorner(seat)]).toEqual([seat, point])
    }
  })

  it('makes seats share a corner once there are more than four, the way people sit', () => {
    // Eight seats share four corners: two people on the same side of a real
    // table look from the same place.
    expect(seatCorner(4)).toEqual(seatCorner(0))
    expect(seatCorner(7)).toEqual(seatCorner(3))
    for (let seat = 0; seat < 8; seat += 1) {
      expect([seat, seatCorner(seat)]).toEqual([seat, seatCorner(seat % 4)])
    }
  })
})

describe('the camera of a seat', () => {
  it('aims between the middle of the board and the seat own corner', () => {
    // Not the centre: the near corner is where the readable cells are, so the aim
    // moves towards it and the far edge runs off the top, as in the reference.
    for (let seat = 0; seat < 8; seat += 1) {
      const { target } = cameraFor(seat)
      const corner = seatCorner(seat)
      const onTheLine =
        Math.abs(
          (target.x - BOARD_CENTER.x) * (corner.z - BOARD_CENTER.z) -
            (target.z - BOARD_CENTER.z) * (corner.x - BOARD_CENTER.x),
        ) < 1e-9
      const between = Math.hypot(target.x - BOARD_CENTER.x, target.z - BOARD_CENTER.z)
      expect([seat, onTheLine, between > 0, between < Math.hypot(corner.x - BOARD_CENTER.x, corner.z - BOARD_CENTER.z)]).toEqual(
        [seat, true, true, true],
      )
    }
  })

  it('stands outside the board, above the table', () => {
    for (let seat = 0; seat < 8; seat += 1) {
      const { position } = cameraFor(seat)
      // The board is eleven cells across (``GRID_SIZE``); forty is how many
      // spaces it holds, which is a different number and a trap worth naming.
      const outside =
        position.x < 0 || position.x > GRID_SIZE || position.z < 0 || position.z > GRID_SIZE
      expect([seat, outside, position.y > 0]).toEqual([seat, true, true])
    }
  })

  it('is low, which is what gives the reference image its foreshortening', () => {
    // About twenty degrees above the table: the near corner is close and huge,
    // the far edge is compressed. A high camera would flatten the board again.
    for (let seat = 0; seat < 8; seat += 1) {
      const { position } = cameraFor(seat)
      // Measured to the middle of the board: the aim sits closer to the corner,
      // and that is a framing decision, not the elevation of the camera.
      const elevation = (Math.atan2(position.y, horizontalDistance(position, BOARD_CENTER)) * 180) / Math.PI
      expect([seat, Math.round(elevation * 10) / 10]).toEqual([seat, 20])
    }
  })

  it("has the seat's own corner as the nearest one", () => {
    // The defining property of a seat's view: your corner is the one under your
    // nose, so what you must read first is the biggest thing on screen.
    for (let seat = 0; seat < 8; seat += 1) {
      const { position } = cameraFor(seat)
      const own = distance(position, seatCorner(seat))
      for (const { point } of CORNERS) {
        expect([seat, own <= distance(position, point)]).toEqual([seat, true])
      }
    }
  })

  it('never puts two different corners in the same place', () => {
    const places = CORNERS.map(({ seat }) => JSON.stringify(cameraFor(seat).position))
    expect(new Set(places).size).toBe(4)
  })

})

describe('where a space sits in the scene', () => {
  it('places the circuit on the plane, GO near the viewer on the right', () => {
    expect(cellCenter(0)).toEqual({ x: 10.5, y: 0, z: 10.5 })
    expect(cellCenter(1)).toEqual({ x: 9.5, y: 0, z: 10.5 })
    expect(cellCenter(10)).toEqual({ x: 0.5, y: 0, z: 10.5 })
    expect(cellCenter(20)).toEqual({ x: 0.5, y: 0, z: 0.5 })
    expect(cellCenter(30)).toEqual({ x: 10.5, y: 0, z: 0.5 })
  })

  it('keeps the 40 spaces apart and inside the board', () => {
    const places = new Set<string>()
    for (let index = 0; index < BOARD_SIZE; index += 1) {
      const { x, z } = cellCenter(index)
      places.add(`${x}:${z}`)
      const inside = x >= 0 && x <= GRID_SIZE && z >= 0 && z <= GRID_SIZE
      expect([index, inside]).toEqual([index, true])
    }
    expect(places.size).toBe(BOARD_SIZE)
  })
})

describe('aiming the camera', () => {
  /** Apply a YXZ Euler to the camera's forward axis, in plain arithmetic. */
  function forwardOf(rotation: { x: number; y: number }): Point3 {
    // The camera looks down -Z. A pitch about X, then a yaw about Y, in the
    // order the component declares.
    const afterPitch = { x: 0, y: Math.sin(rotation.x), z: -Math.cos(rotation.x) }
    return {
      x: afterPitch.x * Math.cos(rotation.y) + afterPitch.z * Math.sin(rotation.y),
      y: afterPitch.y,
      z: -afterPitch.x * Math.sin(rotation.y) + afterPitch.z * Math.cos(rotation.y),
    }
  }

  it('aims every seat exactly at the middle of the board', () => {
    // The proof the scene cannot get wrong: the declared rotation, applied to
    // the camera's own forward axis, is the direction to the target.
    for (let seat = 0; seat < 8; seat += 1) {
      const { position, target, rotation } = cameraFor(seat)
      const forward = forwardOf(rotation)
      const length = Math.hypot(target.x - position.x, target.y - position.y, target.z - position.z)
      const expected = {
        x: (target.x - position.x) / length,
        y: (target.y - position.y) / length,
        z: (target.z - position.z) / length,
      }
      expect([seat, rotation.order]).toEqual([seat, 'YXZ'])
      for (const axis of ['x', 'y', 'z'] as const) {
        // A tolerance rather than a rounded equality: the residue of the trig is
        // around 1e-16 and rounding it can land on a signed zero.
        expect([seat, axis, Math.abs(forward[axis] - expected[axis]) < 1e-9]).toEqual([
          seat,
          axis,
          true,
        ])
      }
    }
  })

  it('looks down at the table, never up', () => {
    for (let seat = 0; seat < 8; seat += 1) {
      // A camera above the table aims below the horizon: its pitch is negative.
      expect([seat, cameraFor(seat).rotation.x < 0]).toEqual([seat, true])
    }
  })
})

describe('the table can be turned', () => {
  it('turns a quarter at a time, and keeps counting past a full turn', () => {
    expect([0, 1, 2, 3].map(sceneRotationFor)).toEqual([
      0,
      Math.PI / 2,
      Math.PI,
      (3 * Math.PI) / 2,
    ])
    // Four quarters and none are the same angle, but not the same number: an
    // animation must slide a quarter forward rather than three quarters back.
    expect(sceneRotationFor(4)).toBe(Math.PI * 2)
    expect(sceneRotationFor(4) - sceneRotationFor(3)).toBeCloseTo(Math.PI / 2)
    expect(sceneRotationFor(-1)).toBeCloseTo(-Math.PI / 2)
  })

  it('is linear in the count, which is what makes a slide possible', () => {
    for (const turns of [-9, -1, 0, 1, 7, 13]) {
      expect([turns, sceneRotationFor(turns)]).toEqual([turns, (turns * Math.PI) / 2])
    }
  })
})

describe('the shape of the frame decides the view', () => {
  /**
   * Whether a point lands inside the frustum, computed from scratch.
   *
   * Deliberately not `fovForAspect`: this is the oracle, so it rebuilds the
   * camera's basis and the two tangents by its own arithmetic.
   */
  function insideFrame(seat: number, aspect: number, point: Point3): boolean {
    const { position, target, fov } = cameraFor(seat, aspect)
    const forward = {
      x: target.x - position.x,
      y: target.y - position.y,
      z: target.z - position.z,
    }
    const length = Math.hypot(forward.x, forward.y, forward.z)
    const f = { x: forward.x / length, y: forward.y / length, z: forward.z / length }
    const rightLength = Math.hypot(f.z, f.x) || 1
    const r = { x: f.z / rightLength, y: 0, z: -f.x / rightLength }
    const u = {
      x: r.y * f.z - r.z * f.y,
      y: r.z * f.x - r.x * f.z,
      z: r.x * f.y - r.y * f.x,
    }
    const d = { x: point.x - position.x, y: point.y - position.y, z: point.z - position.z }
    const depth = Math.abs(d.x * f.x + d.y * f.y + d.z * f.z)
    const across = Math.abs(d.x * r.x + d.y * r.y + d.z * r.z)
    const vertical = Math.abs(d.x * u.x + d.y * u.y + d.z * u.z)
    const half = (fov * Math.PI) / 360
    return vertical <= Math.tan(half) * depth && across <= Math.tan(half) * aspect * depth
  }

  it("keeps the seat's own corner inside the frame at every aspect", () => {
    // The defect this fixes: a fixed 32 degrees framed a 4:3 screen and cut the
    // near corner off a square phone. The corner is the thing the player must
    // see, so it is what the field of view is solved for.
    for (const aspect of [0.45, 0.62, 0.8, 1, 1.33, 1.78, 2.4]) {
      for (let seat = 0; seat < 4; seat += 1) {
        expect([aspect, seat, insideFrame(seat, aspect, seatCorner(seat))]).toEqual([
          aspect,
          seat,
          true,
        ])
      }
    }
  })

  it('never narrows as the frame gets narrower, and never leaves its clamp', () => {
    // What binds for the seat's own corner is its *vertical* offset -- it sits
    // almost under the camera -- so the field of view is flat across ordinary
    // frames. Narrower never needs less, which is the property that matters.
    const square = cameraFor(0, 1).fov
    expect(cameraFor(0, 0.6).fov).toBeGreaterThanOrEqual(square)
    expect(cameraFor(0, 2.4).fov).toBeLessThanOrEqual(square)
    for (const aspect of [0, 0.02, 1, 12, 400]) {
      const fov = cameraFor(0, aspect).fov
      expect([aspect, fov >= MIN_FOV, fov <= MAX_FOV]).toEqual([aspect, true, true])
    }
  })

  it('divides the horizontal half-angle by the aspect, which is what the term is for', () => {
    // Proved directly, with a point to the side of the axis: a frame twice as wide
    // needs half the horizontal tangent, so it needs a narrower view for it.
    const position = { x: 0, y: 10, z: 20 }
    const target = { x: 0, y: 0, z: 0 }
    const beside = { x: 6, y: 0, z: 0 }
    const square = fovForAspect(position, target, beside, 1)
    const wide = fovForAspect(position, target, beside, 2)
    expect(square).toBeGreaterThan(wide)
    expect(fovForAspect(position, target, beside, 0.5)).toBeGreaterThan(square)
  })

  it('still opens on a close view at a desktop aspect', () => {
    // The framing the owner of the look asked for: close, not a wide establishing
    // shot. The derived field of view has to stay in that neighbourhood.
    expect(cameraFor(0, 4 / 3).fov).toBeGreaterThan(SEAT_FOV - 6)
    expect(cameraFor(0, 4 / 3).fov).toBeLessThan(SEAT_FOV + 14)
  })
})
