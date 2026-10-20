import { describe, expect, it } from 'vitest'
import { BOARD_SIZE } from '../board'
import { GRID_SIZE } from '../grid'
import {
  BOARD_CENTER,
  FOV_STEPS,
  cameraFor,
  cellCenter,
  clampZoom,
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
  it('looks at the centre of the board from every seat', () => {
    for (let seat = 0; seat < 8; seat += 1) {
      expect([seat, cameraFor(seat).target]).toEqual([seat, BOARD_CENTER])
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
      const { position, target } = cameraFor(seat)
      const elevation = (Math.atan2(position.y, horizontalDistance(position, target)) * 180) / Math.PI
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

  it('keeps the board in frame at every corner', () => {
    // Every corner and the centre must fall inside the field of view, or a seat
    // would open on a board it cannot see whole.
    for (let seat = 0; seat < 8; seat += 1) {
      const { position, target, fov } = cameraFor(seat)
      const halfAngle = (fov * Math.PI) / 360
      for (const { point } of [...CORNERS.map((corner) => ({ point: corner.point })), { point: BOARD_CENTER }]) {
        const toPoint = { x: point.x - position.x, y: point.y - position.y, z: point.z - position.z }
        const toTarget = { x: target.x - position.x, y: target.y - position.y, z: target.z - position.z }
        const dot = toPoint.x * toTarget.x + toPoint.y * toTarget.y + toPoint.z * toTarget.z
        const cosine = dot / (Math.hypot(toPoint.x, toPoint.y, toPoint.z) * Math.hypot(toTarget.x, toTarget.y, toTarget.z))
        const angle = Math.acos(Math.min(1, Math.max(-1, cosine)))
        expect([seat, angle <= halfAngle]).toEqual([seat, true])
      }
    }
  })
})

describe('zooming in', () => {
  it('narrows the field of view one step at a time', () => {
    expect(FOV_STEPS).toEqual([50, 42, 34])
    expect(FOV_STEPS.every((fov, step) => step === 0 || fov < FOV_STEPS[step - 1])).toBe(true)
  })

  it('clamps a step outside the ladder instead of inventing a camera', () => {
    expect([clampZoom(-3), clampZoom(0), clampZoom(2), clampZoom(9)]).toEqual([0, 0, 2, 2])
  })

  it('zooms the same for every seat and never moves the target', () => {
    for (let seat = 0; seat < 8; seat += 1) {
      for (let step = 0; step < FOV_STEPS.length; step += 1) {
        const camera = cameraFor(seat, step)
        expect([seat, step, camera.fov]).toEqual([seat, step, FOV_STEPS[step]])
        expect(camera.target).toEqual(BOARD_CENTER)
      }
    }
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
