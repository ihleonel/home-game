import { BoxGeometry } from 'three'
import { describe, expect, it } from 'vitest'
import {
  DICE_START_HEIGHT,
  DICE_TOTAL_MS,
  DIE_FACES,
  DIE_SIZE,
  diceFall,
  diceState,
  faceNormal,
  orientationFor,
} from './dice'

/** A point in the scene, in world units. */
type Vec = { x: number; y: number; z: number }

/**
 * Rotate a vector by the three angles the scene would set on the die.
 *
 * The oracle is built here, axis by axis, and never imports the module's own
 * arithmetic: each of the six orientations is a quarter turn about one axis, so
 * the composition is short enough to write out.
 */
function rotate(point: Vec, euler: { x: number; y: number; z: number }): Vec {
  // X
  const cosX = Math.cos(euler.x)
  const sinX = Math.sin(euler.x)
  let { x, y, z } = point
  ;[y, z] = [y * cosX - z * sinX, y * sinX + z * cosX]
  // Y
  const cosY = Math.cos(euler.y)
  const sinY = Math.sin(euler.y)
  ;[x, z] = [x * cosY + z * sinY, -x * sinY + z * cosY]
  // Z
  const cosZ = Math.cos(euler.z)
  const sinZ = Math.sin(euler.z)
  ;[x, y] = [x * cosZ - y * sinZ, x * sinZ + y * cosZ]
  return { x, y, z }
}

const VALUES = [1, 2, 3, 4, 5, 6] as const

describe('the faces of one die', () => {
  it('carries each value once, and opposite faces add up to seven', () => {
    // BoxGeometry's material order is +x, -x, +y, -y, +z, -z, so the pairs that
    // face each other are the neighbours in this list.
    expect([...DIE_FACES].sort()).toEqual([...VALUES])
    expect([
      DIE_FACES[0] + DIE_FACES[1],
      DIE_FACES[2] + DIE_FACES[3],
      DIE_FACES[4] + DIE_FACES[5],
    ]).toEqual([7, 7, 7])
  })

  it('gives each value the unit normal of the face that carries it', () => {
    const normals: Vec[] = [
      { x: 1, y: 0, z: 0 },
      { x: -1, y: 0, z: 0 },
      { x: 0, y: 1, z: 0 },
      { x: 0, y: -1, z: 0 },
      { x: 0, y: 0, z: 1 },
      { x: 0, y: 0, z: -1 },
    ]
    for (const value of VALUES) {
      const face = DIE_FACES.indexOf(value)
      expect([value, faceNormal(value)]).toEqual([value, normals[face]])
    }
  })

  it('agrees with the face order the box geometry really builds', () => {
    // The list above is a promise about three's own order, and a hand-written
    // promise is exactly the kind that drifts. Reading the normals out of a real
    // BoxGeometry turns the comment into a fact the test can fail on.
    const geometry = new BoxGeometry(1, 1, 1)
    const normals = geometry.getAttribute('normal')
    const index = geometry.getIndex()
    if (index === null) throw new Error('the box geometry is expected to be indexed')
    // A group is a range of the *index* buffer, so the vertex its normal lives at
    // is the index value, not the group's own start.
    const built = geometry.groups.map((group) => {
      const vertex = index.getX(group.start)
      return {
        x: Math.round(normals.getX(vertex)),
        y: Math.round(normals.getY(vertex)),
        z: Math.round(normals.getZ(vertex)),
      }
    })
    geometry.dispose()
    expect(built).toEqual(DIE_FACES.map(faceNormal))
  })

  it('turns the die so the value it rolled points at the ceiling', () => {
    // The point of the whole mapping: whatever the tumble does, the die has to
    // come to rest with the rolled number face up. A wrong orientation here is a
    // die that lies about the throw, which no capture of a spin would catch.
    for (const value of VALUES) {
      const up = rotate(faceNormal(value), orientationFor(value))
      expect([
        value,
        Math.abs(up.x) < 1e-9,
        Math.abs(up.y - 1) < 1e-9,
        Math.abs(up.z) < 1e-9,
      ]).toEqual([value, true, true, true])
    }
  })
})

describe('the fall of the dice', () => {
  it('starts above the board and ends resting on it', () => {
    expect(diceFall(0).lift).toBeCloseTo(DICE_START_HEIGHT)
    expect(diceFall(DICE_TOTAL_MS).lift).toBe(0)
    expect(diceFall(DICE_TOTAL_MS * 4).lift).toBe(0)
  })

  it('never sinks through the board and never spins backwards', () => {
    let previousSpin = 0
    for (let elapsed = 0; elapsed <= DICE_TOTAL_MS * 2; elapsed += 5) {
      const pose = diceFall(elapsed)
      expect(pose.lift).toBeGreaterThanOrEqual(0)
      expect(pose.spin).toBeGreaterThanOrEqual(previousSpin)
      previousSpin = pose.spin
    }
    expect(diceFall(0).spin).toBe(0)
    expect(diceFall(DICE_TOTAL_MS).spin).toBe(1)
  })

  it('lands before the animation is over, so the number is read for a moment', () => {
    // The last third of the animation is the die already at rest: without it the
    // throw would settle and vanish in the same instant.
    expect(diceFall(DICE_TOTAL_MS * 0.7).lift).toBeLessThan(DIE_SIZE)
  })
})

describe('when the dice are on the table', () => {
  const noRoll = { turn: 'seat-0', roll: null }
  const rolled = { turn: 'seat-0', roll: [3, 4] }

  it('shows them landed when a view arrives with a throw already made', () => {
    // Rejoining a match mid-turn must not replay a throw the player did not see.
    expect(diceState(null, rolled)).toBe('landed')
  })

  it('animates a throw that arrives while watching, in the same turn', () => {
    expect(diceState(noRoll, rolled)).toBe('animate')
    expect(diceState({ turn: 'seat-0', roll: [1, 1] }, rolled)).toBe('animate')
  })

  it('takes them away when the turn ends, so the next player starts clean', () => {
    expect(diceState(rolled, { turn: 'seat-1', roll: [3, 4] })).toBe('hidden')
    expect(diceState(rolled, { turn: 'seat-1', roll: null })).toBe('hidden')
  })

  it('leaves them alone while nothing about the throw changes', () => {
    expect(diceState(rolled, rolled)).toBe('keep')
    expect(diceState(noRoll, noRoll)).toBe('keep')
  })

  it('hides them when the throw is cleared without a new turn', () => {
    expect(diceState(rolled, noRoll)).toBe('hidden')
  })
})
