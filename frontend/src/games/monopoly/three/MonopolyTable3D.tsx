/**
 * The table, in 3D (S5 of ``monopoly-3d-table.md``).
 *
 * A board on a wooden table seen from one seat's corner: cells are planes lying
 * on a slab, lit by one warm directional light with soft shadows, and every
 * surface is painted at runtime from the game's own data -- no images, no fonts,
 * no network (S3).
 *
 * The geometry is not decided here. Where the camera stands comes from
 * ``camera.ts`` and what each cell says comes from ``textures.ts``; this file
 * only puts them in a scene. That is why the harness can pin the two of them
 * without a DOM and why this component is the one that has to be looked at.
 *
 * It mounts a canvas, so it must never be rendered by the project's test harness
 * (``react-dom/server``, no DOM): the panel receives it as a prop (S7).
 */

import { Canvas, useFrame, useThree } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { PerspectiveCamera } from '@react-three/drei'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import { Object3D } from 'three'
import type { Group } from 'three'
import { BOARD } from '../board'
import { GRID_SIZE, spaceSide } from '../grid'
import type { MatchState } from '../../registry'
import type { MonopolyDecks, MonopolyPlayer, MonopolyView } from '../view'
import {
  BOARD_CENTER,
  cameraFor,
  cellCenter,
  centrePrintRotation,
  dragTurnRadians,
  nearestTurn,
  turnToFace,
} from './camera'
import type { Point3 } from './camera'
import { toTexture } from './canvasTexture'
import { DICE_TOTAL_MS } from './dice'
import { Dice3D } from './Dice3D'
import { usePrefersReducedMotion } from './useReducedMotion'
import { walkPlan, walkPose } from './walk'
import type { WalkPlan } from './walk'
import { Figure3D } from './Figure3D'
import { ownedCells, ownerSignature } from './owners'
import { seatedTokens } from './tokens'
import {
  CELL_TEXTURE_SIZE,
  CENTRE_FACE,
  PILE_FACE,
  centreTexture,
  deckPilePrint,
  deckPileTexture,
  spaceTexture,
} from './textures'

/** How thick the board is, which is what makes it read as an object. */
const SLAB_THICKNESS = 0.12

/**
 * How far the cells float above the slab's top face.
 *
 * They used to sit exactly on it (``SLAB_THICKNESS / 2``), which made the cell
 * planes and the slab's top two coplanar surfaces: the depth test could not
 * decide between them, and the printed surface came out striped and shimmering
 * while the table turned. Two millimetres -- in a board where a cell is one
 * unit -- is invisible and far more than the depth buffer needs.
 */
const BOARD_LIFT = 0.002

/** The face the printed board is glued to: the slab's top, plus that gap. */
const BOARD_TOP = SLAB_THICKNESS / 2 + BOARD_LIFT

/** Side of one cell's plane: the gap shows the slab's ink, as in the 2D board. */
const CELL_PLANE = 0.97

/** How many table widths the wooden table covers. */
const TABLE_SIZE = GRID_SIZE * 40

/** The height of a house and of a hotel, in cells, so they read from a seat. */
const HOUSE_SIZE = { width: 0.17, height: 0.13, depth: 0.17 } as const
const HOTEL_SIZE = { width: 0.3, height: 0.17, depth: 0.22 } as const

/**
 * How fast the table settles into its new angle (W4).
 *
 * Ten is a little under half a second to visually settle: fast enough that the
 * board feels like it was pushed and stopped, slow enough that the eye can follow
 * *which way* it turned. It is an exponential approach, so it never overshoots and
 * never needs a timeline.
 */
const TURN_DAMPING = 10

/**
 * How tightly the board follows the hand while it is being dragged (X3).
 *
 * The same exponential approach with a shorter time constant, so the board still
 * weights the gesture instead of teleporting with each pointer event, but trails
 * the finger by a few dozen milliseconds at most. Releasing it hands the angle
 * back to ``TURN_DAMPING`` so it glides the last few pixels onto where the hand
 * stopped instead of freezing where the pointer events left it.
 */
const DRAG_DAMPING = 30

/**
 * How far a drag has to travel for one quarter of a turn (X3).
 *
 * Horizontal pixels. It no longer sets a step: every pixel moves the board, and
 * this only fixes the sensitivity, so a quarter still asks for the same swipe it
 * did when the gesture stepped. Eighty pixels is about a third of a phone's
 * width.
 */
export const DRAG_STEP_PX = 80

/** A drag shorter than this is a tap on a space, not a turn. */
const DRAG_SLOP_PX = 6

/**
 * The board, turning to the angle the hand left it at (W4, X3).
 *
 * While the hand is down the angle it has added lives in a ref and moves every
 * pointer event; the committed angle moves it by a quarter from the buttons and
 * by the exact radians of a drag. Both are the same target here: the committed
 * angle plus the live drag offset, which returns to zero when the gesture ends.
 *
 * The scene renders on demand, so an animation has to ask for its own frames:
 * ``invalidate`` schedules one, and this requests the next until the angle has
 * arrived. A drag keeps asking for frames for as long as it lasts, even after the
 * board has caught up, because the next pointer event will move the target even
 * though nothing in React changed. Mutating the group's rotation is what a ref is
 * for -- it is the renderer's own mutable object, not React state.
 */
/**
 * What the table faces on its own (X11).
 *
 * Two moments make the board turn: a turn starting, which brings the piece of the
 * player whose turn it is towards the camera, and a throw, after which the table
 * follows that piece while it walks. Both are written into refs and not state --
 * the camera is a frame-by-frame thing, and React has nothing to say about it.
 *
 * **The player always wins.** A drag or one of the two keyboard buttons takes the
 * table over: the automatic turn stops until the next turn or throw, because
 * otherwise the very next frame would undo the hand that just moved it. The
 * keyboard is the awkward case, because the buttons change the committed angle
 * without touching the screen: an angle that moves while the automatic turn is on
 * *is* the player asking for it, so the committed angle is rebased onto what is on
 * screen and the automatic turn stops.
 *
 * With the reduced-motion preference the board does not turn by itself at all.
 */
function FollowTurn({
  angle,
  autoRef,
  followPointRef,
  lastAngleRef,
  match,
  onTurnBy,
  reduced,
  syncingRef,
  visualAngleRef,
}: {
  angle: number
  autoRef: RefObject<boolean>
  followPointRef: RefObject<Point3 | null>
  lastAngleRef: RefObject<number>
  match: MatchState<MonopolyView>
  onTurnBy?: (radians: number) => void
  reduced: boolean
  syncingRef: RefObject<boolean>
  visualAngleRef: RefObject<number>
}) {
  const invalidate = useThree((state) => state.invalidate)
  const latest = useRef(match)
  useEffect(() => {
    latest.current = match
  }, [match])

  const turn = match.view.turn
  const roll = match.view.last_roll === null ? '' : match.view.last_roll.join(',')

  // A turn starting brings that player's piece towards the camera. Keyed on the
  // turn alone: a poll must not pull the aim away from a piece that is walking.
  useEffect(() => {
    if (turn === null) return
    const player = latest.current.view.players.find((candidate) => candidate.seat === turn)
    if (player === undefined) return
    followPointRef.current = cellCenter(player.position)
    autoRef.current = !reduced
    invalidate()
  }, [turn, reduced, invalidate, followPointRef, autoRef])

  // A throw makes the table follow the piece while it walks; the walk publishes
  // where the piece is (``Tokens``).
  useEffect(() => {
    autoRef.current = !reduced
    invalidate()
  }, [roll, reduced, invalidate, autoRef])

  // The committed angle moving is the player asking for a turn of their own.
  useEffect(() => {
    if (syncingRef.current) {
      syncingRef.current = false
      lastAngleRef.current = angle
      return
    }
    const delta = angle - lastAngleRef.current
    lastAngleRef.current = angle
    if (Math.abs(delta) < 1e-9 || !autoRef.current) return
    autoRef.current = false
    // Only ask for a rebase that really changes the number: a commit of zero is
    // swallowed by the panel's own ``setState``, so no render would arrive, the
    // sync flag would stay raised and every later settle would be ignored --
    // leaving the committed angle and the screen permanently out of step.
    const rebase = visualAngleRef.current + delta - angle
    if (Math.abs(rebase) > 1e-9) {
      syncingRef.current = true
      onTurnBy?.(rebase)
    }
  }, [angle, autoRef, lastAngleRef, onTurnBy, syncingRef, visualAngleRef])

  return null
}

/**
 * The board, turning to the angle the hand or the automatic turn asks for (W4,
 * X3, X11).
 *
 * While the hand is down the angle it has added lives in a ref and moves every
 * pointer event; the committed angle moves it by a quarter from the buttons and by
 * the exact radians of a drag; and while the automatic turn is on, the board faces
 * the piece it is following, recomputed every frame because the piece is walking.
 *
 * The scene renders on demand, so an animation has to ask for its own frames:
 * ``invalidate`` schedules one, and this requests the next until the angle has
 * arrived.
 */
function TurningBoard({
  angle,
  autoRef,
  dragBaseRef,
  dragOffset,
  dragging,
  followPointRef,
  onSettle,
  seat,
  visualAngleRef,
  children,
}: {
  angle: number
  autoRef: RefObject<boolean>
  dragBaseRef: RefObject<number | null>
  dragOffset: RefObject<number>
  dragging: boolean
  followPointRef: RefObject<Point3 | null>
  onSettle: (angle: number) => void
  seat: number
  visualAngleRef: RefObject<number>
  children: ReactNode
}) {
  const group = useRef<Group>(null)
  const invalidate = useThree((state) => state.invalidate)

  // A frame for the first step, or a click would change the number and no frame
  // would be drawn to move towards it. A gesture starting or ending has to ask
  // for one for the same reason: neither changes the committed angle.
  useEffect(() => {
    invalidate()
  }, [invalidate, angle, dragging])

  useFrame((_, delta) => {
    const node = group.current
    if (node === null) return
    let desired = angle
    if (dragging) {
      desired = (dragBaseRef.current ?? angle) + dragOffset.current
    } else if (autoRef.current && followPointRef.current !== null) {
      // The short way round, from where the eye already is.
      desired = nearestTurn(turnToFace(seat, followPointRef.current), node.rotation.y)
    }
    const remaining = desired - node.rotation.y
    if (!dragging && Math.abs(remaining) < 0.002) {
      node.rotation.y = desired
      visualAngleRef.current = desired
      // An automatic turn is not a committed angle: hand it to the panel once it
      // rests, so the buttons and the next drag start from what is on screen.
      if (Math.abs(desired - angle) > 0.002) onSettle(desired)
      return
    }
    const damping = dragging ? DRAG_DAMPING : TURN_DAMPING
    node.rotation.y += remaining * (1 - Math.exp(-damping * delta))
    visualAngleRef.current = node.rotation.y
    invalidate()
  })

  return (
    <group position={[BOARD_CENTER.x, 0, BOARD_CENTER.z]} ref={group}>
      <group position={[-BOARD_CENTER.x, 0, -BOARD_CENTER.z]}>{children}</group>
    </group>
  )
}

/**
 * Turn the table by dragging it (X2, X3, X7).
 *
 * Pointer events, so a mouse and a finger are the same gesture. The board follows
 * the hand: dragging right turns it right, and it does so for every pixel instead
 * of waiting for the finger to cross a step. Two details make it usable next to a
 * board made of buttons -- a drag past a few pixels marks the gesture so the
 * release does not also select a space, and the angle is left in a ref that the
 * scene reads each frame, so a moving finger never re-renders the panel.
 *
 * When the hand lets go, **the angle it stopped at is the angle the table keeps**
 * (X7): the offset is committed verbatim instead of being rounded to a quarter.
 * The board therefore does not move after the release beyond the few pixels it
 * was trailing the finger by, and turning it again continues from there.
 */
function useDragToTurn({
  angle,
  visualAngleRef,
  onTakeOver,
  onTurnBy,
}: {
  angle: number
  visualAngleRef: RefObject<number>
  onTakeOver: () => void
  onTurnBy: (radians: number) => void
}) {
  const drag = useRef<{ pointerId: number; x: number } | null>(null)
  const dragged = useRef(false)
  // How far the hand has turned the table since it went down, in radians. A ref
  // and not state: it changes on every pointer event, and React has nothing to
  // say about a frame's angle.
  const offset = useRef(0)
  // The angle the hand went down on. It is read off the screen rather than from
  // the committed angle: after an automatic turn (X11) the two differ, and
  // measuring from the committed one would snap the table back the moment a
  // finger touched it.
  const base = useRef<number | null>(null)
  const [dragging, setDragging] = useState(false)

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>): void => {
    if (event.pointerType === 'mouse' && event.button !== 0) return
    // One hand at a time (X7). A second finger landing while the first one drags
    // must not take the gesture over: the offset is measured from where its own
    // pointer went down, so restarting it mid-gesture would snap the board back to
    // the angle it had when the gesture began. The second pointer is simply not
    // this gesture's, and every event below is checked against the one that is.
    if (drag.current !== null) return
    onTakeOver()
    base.current = visualAngleRef.current
    drag.current = { pointerId: event.pointerId, x: event.clientX }
    dragged.current = false
    offset.current = 0
    setDragging(true)
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>): void => {
    const state = drag.current
    if (state === null || event.pointerId !== state.pointerId) return
    const travelled = event.clientX - state.x
    if (Math.abs(travelled) > DRAG_SLOP_PX) dragged.current = true
    // The offset since the finger went down, not since the last event: the angle
    // is absolute while the gesture lasts, so it cannot drift by accumulating
    // rounding on every move.
    offset.current = dragTurnRadians(travelled, DRAG_STEP_PX)
  }

  const end = (event: React.PointerEvent<HTMLDivElement>): void => {
    const state = drag.current
    if (state === null || event.pointerId !== state.pointerId) return
    drag.current = null
    // Commit the angle exactly as the hand left it, then zero the offset in the
    // same event: the parent's new angle and this reset are batched together, so
    // the target the next frame reads is that angle and not the old base plus a
    // zeroed offset. A gesture that only took the table over still has to commit
    // the base it took it from, or the next frame would pull it back.
    const turned = offset.current
    const from = base.current ?? angle
    offset.current = 0
    base.current = null
    setDragging(false)
    if (turned !== 0 || from !== angle) onTurnBy(from - angle + turned)
  }

  return {
    dragging,
    dragBaseRef: base,
    dragOffset: offset,
    dragged,
    handlers: {
      onPointerCancel: end,
      onPointerDown,
      onPointerMove,
      onPointerUp: end,
    },
  }
}

/**
 * The seat's camera, declared rather than moved.
 *
 * Everything it needs is arithmetic in ``camera.ts`` -- where it stands, how wide
 * it is and the two Euler angles that aim it at the middle -- so the scene only
 * passes numbers. Mutating ``three``'s camera from an effect would be the one
 * thing the project's React rules forbid, and an aim that lives in an effect
 * cannot be asserted; the aim is a test instead.
 *
 * The camera object is keyed by seat and zoom, so a zoom step builds a fresh one
 * and its projection matrix is right by construction instead of by remembering
 * to update it.
 */
function SeatCamera({ seat }: { seat: number }) {
  // The frame's own shape decides the field of view (W6): a square phone frame
  // needs a wider one or the seat's corner falls off the bottom.
  const size = useThree((state) => state.size)
  const aspect = size.height === 0 ? 4 / 3 : size.width / size.height
  const placed = cameraFor(seat, aspect)
  return (
    <PerspectiveCamera
      far={200}
      fov={placed.fov}
      key={`seat:${seat}:${Math.round(aspect * 100)}`}
      makeDefault
      near={0.1}
      position={[placed.position.x, placed.position.y, placed.position.z]}
      rotation={[placed.rotation.x, placed.rotation.y, 0, placed.rotation.order]}
    />
  )
}

/**
 * The light that casts the shadows, aimed at the middle of the board (X4).
 *
 * It used to keep three's default target at the world origin while standing at
 * the board's corner, so the shadow camera's axis ran through the origin and not
 * through the table. Measured in that camera's own plane, the board's near corner
 * reached about 9.5 units from the axis, past the ±9 orthographic box, so the
 * outer sliver of the player's own corner was left out of the shadow map -- and
 * which sliver was out moved as the table turned. Aiming the light at the board's
 * centre keeps the whole board inside the box at every angle. The direction is
 * the one it always had -- the light moved with its target -- so nothing about
 * the shading changes, only which shadows fit.
 */
function BoardLight() {
  const target = useMemo(() => {
    const aim = new Object3D()
    aim.position.set(BOARD_CENTER.x, 0, BOARD_CENTER.z)
    return aim
  }, [])

  return (
    <>
      {/* A light's target only updates its matrix as part of the scene graph. */}
      <primitive object={target} />
      <directionalLight
        castShadow
        intensity={1.25}
        position={[BOARD_CENTER.x + 12.5, 13, BOARD_CENTER.z + 11.5]}
        shadow-bias={-0.0004}
        shadow-mapSize={[1024, 1024]}
        target={target}
      >
        <orthographicCamera args={[-9, 9, 9, -9, 0.5, 60]} attach="shadow-camera" />
      </directionalLight>
    </>
  )
}

/**
 * The surface the board rests on: plain white, because that is what the owner of
 * the look asked for. It is a plane and not "no floor" on purpose -- the board's
 * contact shadow needs something to fall on, and that shadow is what makes the
 * board read as an object instead of a picture of one.
 */
function Table() {
  return (
    <mesh
      position={[BOARD_CENTER.x, -SLAB_THICKNESS, BOARD_CENTER.z]}
      receiveShadow
      rotation={[-Math.PI / 2, 0, 0]}
    >
      <planeGeometry args={[TABLE_SIZE, TABLE_SIZE]} />
      {/* Unlit and white, the same white as the background: a lit plane at a
          grazing angle turns grey towards its horizon, and that band is what the
          first attempt at a white surface actually drew. */}
      <meshBasicMaterial color="#ffffff" />
    </mesh>
  )
}

/**
 * The board itself: one slab whose top is the printed board's paper.
 *
 * The top is cream and not ink on purpose. With a dark slab the board reads as a
 * black frame with white cards scattered on it; the printed board is a pale sheet
 * whose cells are separated by hairlines and a white margin, which is what the
 * gaps between these planes are.
 */
function BoardSlab() {
  return (
    <mesh castShadow position={[BOARD_CENTER.x, 0, BOARD_CENTER.z]} receiveShadow>
      <boxGeometry args={[GRID_SIZE + 0.16, SLAB_THICKNESS, GRID_SIZE + 0.16]} />
      {/* The cells float ``BOARD_LIFT`` above this face (X4), and the polygon
          offset pushes the slab back by a depth-buffer step as well: a context
          whose depth buffer is only 16 bits -- WebGL's floor -- resolves 2 mm
          worse than that at this distance, and the cells must still win. */}
      <meshStandardMaterial
        color="#9cb49c"
        polygonOffset
        polygonOffsetFactor={1}
        polygonOffsetUnits={1}
        roughness={0.88}
      />
    </mesh>
  )
}

/**
 * The forty cells, each a plane with its own painted face.
 *
 * The plane lies flat with ``rotation.x = -Math.PI / 2``, which maps the top of
 * the texture to the far edge of the board and its bottom to the near one -- the
 * same orientation the painter assumes when it puts a cell's colour band on the
 * edge that faces the centre (S5 of ``textures.ts``). Changing either half
 * without the other puts every band on the outside.
 *
 * The face of a cell a seat owns is painted in that seat's ink: the frame
 * takes the tile's own border, so the board says "already bought" exactly where
 * a printed board says it. A purchase repaints the forty faces at once instead
 * of tracking forty textures: the painter is pure canvas work, a purchase is a
 * rare answer to a deliberate tap, and one set that is replaced as a whole
 * cannot leak the face of a cell that changed hands.
 */
function Cells({
  match,
  selected,
  onSelect,
}: {
  match: MatchState<MonopolyView>
  selected: number | null
  onSelect: (index: number) => void
}) {
  const owned = ownedCells(match)
  const signature = ownerSignature(owned)
  const faces = useMemo(() => {
    const inks = new Map(owned.map((cell) => [cell.index, cell.ink]))
    return new Map(
      BOARD.map((space) => [
        space.index,
        toTexture(spaceTexture(space.index, CELL_TEXTURE_SIZE, inks.get(space.index)), 8),
      ]),
    )
    // ``signature`` is the whole input of this memo: it changes exactly when a
    // cell is bought, sold or changes hands, and not on the fresh view object a
    // poll brings with the same board.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature])
  // The set that a repaint replaced leaves after this commit, never during the
  // render that replaced it: the frame on screen may still be sampling it.
  useEffect(
    () => () => {
      for (const texture of faces.values()) texture.dispose()
    },
    [faces],
  )

  return (
    <group>
      {BOARD.map((space) => {
        const centre = cellCenter(space.index)
        return (
          <mesh
            key={space.index}
            onClick={(event: ThreeEvent<MouseEvent>) => {
              event.stopPropagation()
              onSelect(space.index)
            }}
            position={[centre.x, BOARD_TOP, centre.z]}
            receiveShadow
            rotation={[-Math.PI / 2, 0, 0]}
          >
            <planeGeometry args={[CELL_PLANE, CELL_PLANE]} />
            <meshStandardMaterial
              map={faces.get(space.index)}
              roughness={0.86}
              // A tapped cell is the one the detail layer is showing, so it is
              // the one that may look pressed.
              emissive={space.index === selected ? '#3a2f14' : '#000000'}
            />
          </mesh>
        )
      })}
    </group>
  )
}

/** Four thin bars around the tapped cell, so the selection reads from afar. */
function SelectedFrame({ index }: { index: number }) {
  const centre = cellCenter(index)
  const bar = CELL_PLANE / 2 + 0.015
  const thickness = 0.045
  const height = BOARD_TOP + 0.004
  const bars: readonly [number, number, number, number][] = [
    [centre.x, centre.z - bar, CELL_PLANE + thickness * 2, thickness],
    [centre.x, centre.z + bar, CELL_PLANE + thickness * 2, thickness],
    [centre.x - bar, centre.z, thickness, CELL_PLANE],
    [centre.x + bar, centre.z, thickness, CELL_PLANE],
  ]
  return (
    <group>
      {bars.map(([x, z, width, depth]) => (
        <mesh key={`${x}:${z}:${width}`} position={[x, height, z]}>
          <boxGeometry args={[width, 0.02, depth]} />
          <meshStandardMaterial color="#c8102e" emissive="#c8102e" emissiveIntensity={0.35} />
        </mesh>
      ))}
    </group>
  )
}

/** One piece walking its throw, and when that walk may start (X10). */
type Walk = { plan: WalkPlan; start: number; startedAt: number }

/**
 * Where one piece stands: the middle of its cell, or beside the others on it (X5).
 *
 * One source for the render and for the two ends of a walk, so a piece that
 * arrives on a shared cell takes its offset back the moment the walk ends,
 * instead of waiting for a prop to change.
 */
function tokenSpot(
  players: readonly MonopolyPlayer[],
  seat: string,
): { x: number; z: number } | null {
  const counts = new Map<number, number>()
  for (const player of players) {
    if (player.eliminated) continue
    const share = counts.get(player.position) ?? 0
    counts.set(player.position, share + 1)
    if (player.seat !== seat) continue
    const centre = cellCenter(player.position)
    return {
      x: centre.x + ((share % 3) - 1) * 0.28,
      z: centre.z + Math.floor(share / 3) * 0.26,
    }
  }
  return null
}

/** Put one piece where the view says it stands. */
function placeToken(
  node: Group | null | undefined,
  players: readonly MonopolyPlayer[],
  seat: string,
): void {
  if (node === null || node === undefined) return
  const spot = tokenSpot(players, seat)
  if (spot !== null) node.position.set(spot.x, BOARD_TOP, spot.z)
}

/**
 * Every piece still in the match, spread over its cell when it is shared (X5),
 * and walking the throw that just moved it (X10).
 *
 * The piece is the marker the player chose in the room: ``figureFor`` maps the
 * roster's ``game_marker`` to a silhouette and ``Figure3D`` prints it as a flat
 * token -- a chip of paper with the black figure on it, always facing the screen
 * -- because the project carries no ``.glb`` (S12c) and the primitives it used to
 * build read as lumps from a seat (``monopoly-flat-figures.md``, S3). The chip
 * keeps the same paper for every piece, so what its shape says is which marker
 * you picked; its rim and bloom carry the seat's tone (``tokens.ts``), which is
 * what separates two seats that picked the same marker. It floats a little over
 * its cell with a soft shadow underneath, which is what tells the eye it is
 * hovering rather than printed.
 *
 * **The walk waits for the dice.** The server publishes the position a throw
 * *reached*, never the cells it crossed, so the path is the client's arithmetic
 * (``walk.ts``) and the walk starts ``DICE_TOTAL_MS`` after the throw arrives: the
 * piece stays where it was while the dice fall, then steps cell by cell. A move
 * that is not a throw -- jail, a card that sends the piece to a cell, a piece
 * pushed back -- makes a single jump to where it lands instead of walking through
 * cells it never stood on. With the reduced-motion preference nothing is animated
 * and the piece is placed where the server says.
 */
function Tokens({
  match,
  followPointRef,
}: {
  match: MatchState<MonopolyView>
  /** Where the table should be facing while a piece walks (X11). */
  followPointRef: RefObject<Point3 | null>
}) {
  const seated = seatedTokens(match)
  const reduced = usePrefersReducedMotion()
  const invalidate = useThree((state) => state.invalidate)
  const groups = useRef(new Map<string, Group>())
  const previous = useRef<Map<string, number> | null>(null)
  const walks = useRef(new Map<string, Walk>())
  /** The cell each walking piece is heading to, where an interrupted walk restarts. */
  const heading = useRef(new Map<string, number>())

  // Where every piece is in the view, so a change can be told from a poll that
  // changed nothing. The first render only records: rejoining a match must not
  // walk a piece across half the board. A layout effect and not an effect, so the
  // reposition below happens before the frame that carries the new position is
  // painted.
  useLayoutEffect(() => {
    const next = new Map(
      match.view.players
        .filter((player) => !player.eliminated)
        .map((player) => [player.seat, player.position] as const),
    )
    const before = previous.current
    previous.current = next
    if (before === null) return
    const startedAt = performance.now() + DICE_TOTAL_MS
    for (const [seat, position] of next) {
      const from = before.get(seat)
      if (from === undefined || from === position) continue
      // A walk still running was heading somewhere: restarting from that cell
      // keeps an interruption from teleporting the piece across the distance it
      // had left.
      const start = walks.current.has(seat) ? (heading.current.get(seat) ?? from) : from
      const plan = reduced ? null : walkPlan(start, position)
      const node = groups.current.get(seat)
      if (plan === null) {
        walks.current.delete(seat)
        heading.current.delete(seat)
        placeToken(node, match.view.players, seat)
        continue
      }
      walks.current.set(seat, { plan, start, startedAt })
      heading.current.set(seat, start)
      // Wait on the cell it came from, in the same commit that put it on the
      // destination: one frame at the destination would read as a jump.
      if (node !== undefined) {
        const centre = cellCenter(start)
        node.position.set(centre.x, BOARD_TOP, centre.z)
      }
    }
    if (walks.current.size > 0) invalidate()
  }, [match, reduced, invalidate])

  useFrame(() => {
    if (walks.current.size === 0) return
    const now = performance.now()
    for (const [seat, walk] of walks.current) {
      const pose = walkPose(walk.plan, walk.start, now - walk.startedAt)
      const node = groups.current.get(seat)
      if (node !== undefined) {
        const origin = cellCenter(pose.from)
        const target = cellCenter(pose.to)
        node.position.set(
          origin.x + (target.x - origin.x) * pose.t,
          BOARD_TOP + pose.lift,
          origin.z + (target.z - origin.z) * pose.t,
        )
        // The table follows the piece itself, not the cell it is heading to: the
        // aim moves with the walk instead of stepping at every cell.
        followPointRef.current = { x: node.position.x, y: 0, z: node.position.z }
      }
      heading.current.set(seat, pose.to)
      if (pose.done) {
        walks.current.delete(seat)
        heading.current.delete(seat)
        placeToken(node, match.view.players, seat)
        followPointRef.current = cellCenter(pose.to)
      }
    }
    if (walks.current.size > 0) invalidate()
  })

  return (
    <group>
      {seated.map(({ seat, figure, tone }) => {
        const spot = tokenSpot(match.view.players, seat)
        return (
          <group
            key={seat}
            position={[spot?.x ?? 0, BOARD_TOP, spot?.z ?? 0]}
            ref={(node: Group | null) => {
              if (node === null) groups.current.delete(seat)
              else groups.current.set(seat, node)
            }}
          >
            <Figure3D figure={figure} tone={tone} />
          </group>
        )
      })}
    </group>
  )
}

/**
 * Houses and hotels, as blocks with volume.
 *
 * The level comes only from ``view.buildings`` -- the server's fact -- and the
 * cell's own side decides which edge of the cell holds them, so a hotel never
 * floats over the board's centre.
 */
function Buildings({ view }: { view: MonopolyView }) {
  return (
    <group>
      {Object.entries(view.buildings).map(([key, level]) => {
        const index = Number(key)
        const centre = cellCenter(index)
        const side = spaceSide(index)
        const along = side === 'top' || side === 'bottom' ? 'x' : 'z'
        const inward = side === 'top' ? 0.34 : side === 'bottom' ? -0.34 : 0
        const inwardZ = side === 'left' ? 0.34 : side === 'right' ? -0.34 : 0
        const isHotel = level >= 5
        const count = isHotel ? 1 : level
        return Array.from({ length: count }, (_, position) => {
          const spread = count === 1 ? 0 : (position - (count - 1) / 2) * 0.2
          const x = centre.x + (along === 'x' ? spread : inward)
          const z = centre.z + (along === 'x' ? inwardZ : inward + spread)
          const size = isHotel ? HOTEL_SIZE : HOUSE_SIZE
          return (
            <mesh castShadow key={`${key}:${position}`} position={[x, BOARD_TOP + size.height / 2, z]}>
              <boxGeometry args={[size.width, size.height, size.depth]} />
              <meshStandardMaterial
                color={isHotel ? '#c8102e' : '#1f9d55'}
                roughness={0.55}
                metalness={0.05}
              />
            </mesh>
          )
        })
      })}
    </group>
  )
}

/** One pile of cards: a stack with a visible edge, as on the reference table. */
/** How far from the middle of the board each pile stands, in cells (X8). */
const PILE_OFFSET = 2.45

/**
 * One pile of cards, face up on the board (X8).
 *
 * A box with a printed wrapper on top: the deck's name and how many cards are
 * left, which is what the HTML card used to say from the middle of the frame.
 * The face is repainted only when that count changes, and the texture it replaces
 * is disposed with it -- a deck is drawn from a handful of times per match, and
 * leaking a texture each time would be the one way this pile costs anything.
 */
function DeckPile({
  deck,
  colour,
  count,
  offsetX,
}: {
  deck: string
  colour: string
  count: number | null
  offsetX: number
}) {
  const face = useMemo(
    () => toTexture(deckPileTexture(deckPilePrint(deck, count)), 8),
    [deck, count],
  )
  useEffect(() => () => face.dispose(), [face])
  return (
    <group position={[offsetX, 0, 0]}>
      <mesh castShadow position={[0, 0.035, 0]}>
        <boxGeometry args={[PILE_FACE.width + 0.04, 0.07, PILE_FACE.depth + 0.04]} />
        <meshStandardMaterial color={colour} roughness={0.8} />
      </mesh>
      <mesh position={[0, 0.071, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[PILE_FACE.width, PILE_FACE.depth]} />
        <meshStandardMaterial map={face} roughness={0.86} />
      </mesh>
    </group>
  )
}

/**
 * The printed middle of the board (X8): the game's name and the two piles.
 *
 * The group is turned towards the seat (``centrePrintRotation``), so the print is
 * upright when the table rests at its own angle; from there it turns with the
 * board, because it is printed on it. The piles stand left and right of the name
 * rather than one behind the other, which is what keeps the arrangement reading
 * the same after a quarter turn.
 */
function BoardCentre({
  seat,
  decks,
  turn,
  roll,
}: {
  seat: number
  decks: MonopolyDecks | null
  turn: string | null
  roll: readonly number[] | null
}) {
  const print = useMemo(() => toTexture(centreTexture(), 8), [])
  useEffect(() => () => print.dispose(), [print])
  return (
    <group
      position={[BOARD_CENTER.x, BOARD_TOP, BOARD_CENTER.z]}
      rotation={[0, centrePrintRotation(seat), 0]}
    >
      <mesh receiveShadow rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[CENTRE_FACE.width, CENTRE_FACE.depth]} />
        <meshStandardMaterial map={print} roughness={0.86} transparent />
      </mesh>
      <DeckPile colour="#e39a2a" count={decks?.chance ?? null} deck="chance" offsetX={-PILE_OFFSET} />
      <DeckPile
        colour="#3d7fb5"
        count={decks?.community_chest ?? null}
        deck="community_chest"
        offsetX={PILE_OFFSET}
      />
      {/* X9: the throw lands on the printed middle, in front of the name from
          the seat's own side, and turns with the board because it is on it. */}
      <Dice3D roll={roll} turn={turn} />
    </group>
  )
}

/**
 * The 3D table for one seat.
 *
 * ``seat`` decides the corner the camera stands at; ``selected`` and ``onSelect``
 * are the same selection the panel already owns, so tapping a cell here and
 * focusing one in the accessible mirror (S6) are one act.
 */
export function MonopolyTable3D({
  match,
  seat,
  selected,
  onSelect,
  angle = 0,
  onTurnBy,
  active = true,
}: {
  match: MatchState<MonopolyView>
  seat: number
  selected: number | null
  onSelect: (index: number) => void
  /**
   * How far the table has been turned, in radians, clockwise (V3, X7).
   *
   * Not a count of quarters any more: a drag leaves the table at whatever angle
   * the hand stopped, so the angle travels as a real number and the keyboard's
   * two buttons move it a quarter at a time. The camera stands at the seat's
   * corner and does not move: what turns is the board on the table, the way a
   * player turns a real board with their hands. The table, the overlays and the
   * accessible mirror are outside the turned group, so only the printed surface
   * and what stands on it move.
   */
  angle?: number
  /** Adds the radians a drag turned the table by, committed on release (X7). */
  onTurnBy?: (radians: number) => void
  /**
   * Whether the board tab is the one on screen (S11).
   *
   * The three views live in the DOM at once, so an inactive tab would otherwise
   * keep a renderer alive behind a ``hidden`` panel. ``never`` stops the loop
   * without tearing the scene down, so coming back does not rebuild forty
   * textures.
   */
  active?: boolean
}) {
  const reduced = usePrefersReducedMotion()
  // The automatic turn (X11): what the board faces on its own, whether it is still
  // following, and where the eye is right now. Refs and not state: they change per
  // frame, and React has nothing to say about a camera's angle.
  const followPointRef = useRef<Point3 | null>(null)
  const autoRef = useRef(true)
  const visualAngleRef = useRef(0)
  const syncingRef = useRef(false)
  const lastAngleRef = useRef(angle)
  const turning = useDragToTurn({
    angle,
    visualAngleRef,
    onTakeOver: () => {
      autoRef.current = false
    },
    onTurnBy: (radians) => onTurnBy?.(radians),
  })
  /** Hand an automatic turn to the panel once it rests, so the buttons start there. */
  const settle = (settled: number): void => {
    if (syncingRef.current) return
    syncingRef.current = true
    onTurnBy?.(settled - angle)
  }
  // A drag that turned the board must not also open the space it ended on.
  const select = (index: number): void => {
    if (turning.dragged.current) return
    onSelect(index)
  }

  return (
    <div className="monopoly-table3d" {...turning.handlers}>
      {/*
        S11 said the board does not animate, and the table used to render on
        demand: a click or a texture arriving invalidated a frame and nothing else
        did. That is no longer the whole picture -- the flat tokens breathe
        (``monopoly-flat-figures.md``, S4 and S6), so while the tab is open a
        token asks for the next frame and the scene renders continuously. What
        still holds is the pause: ``frameloop`` is ``never`` when the tab is not
        the active view, so a closed board costs nothing.
      */}
      <Canvas
        dpr={[1, 2]}
        frameloop={active ? 'demand' : 'never'}
        gl={{ antialias: true }}
        shadows
      >
        {/* The reference photograph is a board on a pale surface: the wood is
            gone, and the background is white so the board is the object. */}
        <color args={['#ffffff']} attach="background" />
        <SeatCamera seat={seat} />
        <FollowTurn
          angle={angle}
          autoRef={autoRef}
          followPointRef={followPointRef}
          lastAngleRef={lastAngleRef}
          match={match}
          onTurnBy={onTurnBy}
          reduced={reduced}
          syncingRef={syncingRef}
          visualAngleRef={visualAngleRef}
        />

        <ambientLight intensity={0.5} />
        <BoardLight />
        {/* A cool fill from the far side, so the shadowed halves are not black. */}
        <directionalLight intensity={0.28} position={[BOARD_CENTER.x - 8, 9, BOARD_CENTER.z - 7]} />

        <Table />
        {/* V3, X3: the printed surface and everything standing on it, turned
            around the board's own centre. The pivot is the two nested groups: a
            rotation in three.js turns around the group's origin, so the outer one
            sits at the centre and the inner one puts the board back where it
            belongs. Without the pivot the board swings off the table. */}
        <TurningBoard
          angle={angle}
          autoRef={autoRef}
          dragBaseRef={turning.dragBaseRef}
          dragOffset={turning.dragOffset}
          dragging={turning.dragging}
          followPointRef={followPointRef}
          onSettle={settle}
          seat={seat}
          visualAngleRef={visualAngleRef}
        >
          <BoardSlab />
            <Cells match={match} onSelect={select} selected={selected} />
          <Buildings view={match.view} />
          <Tokens followPointRef={followPointRef} match={match} />
          {selected !== null && <SelectedFrame index={selected} />}
          <BoardCentre
            decks={match.view.decks}
            roll={match.view.last_roll}
            seat={seat}
            turn={match.view.turn}
          />
        </TurningBoard>

      </Canvas>
    </div>
  )
}
