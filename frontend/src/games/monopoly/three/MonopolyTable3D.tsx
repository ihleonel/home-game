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

import { Canvas } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { ContactShadows, PerspectiveCamera } from '@react-three/drei'
import { useMemo } from 'react'
import { CanvasTexture, SRGBColorSpace } from 'three'
import { BOARD } from '../board'
import { GRID_SIZE, spaceSide } from '../grid'
import type { MatchState } from '../../registry'
import type { MonopolyView } from '../view'
import { BOARD_CENTER, DEFAULT_ZOOM, cameraFor, cellCenter, sceneRotationFor } from './camera'
import { spaceTexture, tableTexture } from './textures'

/** The top face of the slab the printed board is glued to. */
const BOARD_TOP = 0.06

/** How thick the board is, which is what makes it read as an object. */
const SLAB_THICKNESS = 0.12

/** Side of one cell's plane: the gap shows the slab's ink, as in the 2D board. */
const CELL_PLANE = 0.97

/** How many table widths the wooden table covers. */
const TABLE_SIZE = GRID_SIZE * 5

/**
 * The colour of each seat's piece, by seat index.
 *
 * Deliberately not the eight colour groups of the board: a piece must never be
 * confused with the band of the property it is standing on.
 */
const SEAT_COLOURS: readonly string[] = [
  '#c8102e',
  '#1868b3',
  '#1f9d55',
  '#f2a20c',
  '#7b4bc4',
  '#0a8f8f',
  '#c2185b',
  '#4a4a4a',
]

/** The height of a house and of a hotel, in cells, so they read from a seat. */
const HOUSE_SIZE = { width: 0.17, height: 0.13, depth: 0.17 } as const
const HOTEL_SIZE = { width: 0.3, height: 0.17, depth: 0.22 } as const

/** Canvas pixels into a texture the renderer can sample. */
function toTexture(canvas: HTMLCanvasElement, anisotropy: number): CanvasTexture {
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  texture.anisotropy = anisotropy
  return texture
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
function SeatCamera({ seat, zoom }: { seat: number; zoom: number }) {
  const placed = cameraFor(seat, zoom)
  return (
    <PerspectiveCamera
      far={200}
      fov={placed.fov}
      key={`${seat}:${zoom}`}
      makeDefault
      near={0.1}
      position={[placed.position.x, placed.position.y, placed.position.z]}
      rotation={[placed.rotation.x, placed.rotation.y, 0, placed.rotation.order]}
    />
  )
}

/** The wooden table the board rests on. */
function Table() {
  const map = useMemo(() => toTexture(tableTexture(), 4), [])
  return (
    <mesh
      position={[BOARD_CENTER.x, -SLAB_THICKNESS, BOARD_CENTER.z]}
      receiveShadow
      rotation={[-Math.PI / 2, 0, 0]}
    >
      <planeGeometry args={[TABLE_SIZE, TABLE_SIZE]} />
      <meshStandardMaterial map={map} metalness={0.05} roughness={0.82} />
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
      <meshStandardMaterial color="#fdfbf4" roughness={0.86} />
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
 */
function Cells({
  selected,
  onSelect,
}: {
  selected: number | null
  onSelect: (index: number) => void
}) {
  const faces = useMemo(
    () => new Map(BOARD.map((space) => [space.index, toTexture(spaceTexture(space.index), 8)])),
    [],
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

/**
 * One player's piece, standing on the cell it occupies.
 *
 * A piece is what the reference photograph shows: a small metal figure with a
 * shadow of its own. It is built from three primitives -- a round base, a tapered
 * body and a head -- because the project carries no `.glb` (S12c), and it casts a
 * shadow, which is what tells the eye it is standing rather than printed.
 */
function Token({ colour, at, offsetX, offsetZ }: {
  colour: string
  at: { x: number; z: number }
  offsetX: number
  offsetZ: number
}) {
  return (
    <group position={[at.x + offsetX, BOARD_TOP, at.z + offsetZ]}>
      <mesh castShadow position={[0, 0.012, 0]} receiveShadow>
        <cylinderGeometry args={[0.13, 0.15, 0.024, 20]} />
        <meshStandardMaterial color={colour} metalness={0.55} roughness={0.35} />
      </mesh>
      <mesh castShadow position={[0, 0.135, 0]}>
        <cylinderGeometry args={[0.055, 0.1, 0.22, 18]} />
        <meshStandardMaterial color={colour} metalness={0.55} roughness={0.35} />
      </mesh>
      <mesh castShadow position={[0, 0.29, 0]}>
        <sphereGeometry args={[0.078, 18, 14]} />
        <meshStandardMaterial color={colour} metalness={0.6} roughness={0.3} />
      </mesh>
    </group>
  )
}

/** Every piece still in the match, spread over its cell when it is shared. */
function Tokens({ match }: { match: MatchState<MonopolyView> }) {
  const seated = match.view.players.filter((player) => !player.eliminated)
  const perCell = new Map<number, number>()
  return (
    <group>
      {seated.map((player, order) => {
        const share = perCell.get(player.position) ?? 0
        perCell.set(player.position, share + 1)
        const centre = cellCenter(player.position)
        // Two pieces on one cell stand side by side instead of inside each other.
        const column = share % 3
        const row = Math.floor(share / 3)
        return (
          <Token
            at={centre}
            colour={SEAT_COLOURS[(match.roster.find((entry) => entry.seat_id === player.seat)?.index ?? order) % SEAT_COLOURS.length]}
            key={player.seat}
            offsetX={(column - 1) * 0.28}
            offsetZ={row * 0.26}
          />
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
function DeckPile({
  offsetX,
  colour,
}: {
  offsetX: number
  colour: string
}) {
  return (
    <group position={[BOARD_CENTER.x + offsetX, BOARD_TOP, BOARD_CENTER.z]}>
      <mesh castShadow position={[0, 0.035, 0]}>
        <boxGeometry args={[0.9, 0.07, 1.2]} />
        <meshStandardMaterial color={colour} roughness={0.8} />
      </mesh>
      <mesh position={[0, 0.072, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[0.86, 1.16]} />
        <meshStandardMaterial color="#fdfbf4" roughness={0.9} />
      </mesh>
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
  zoom = DEFAULT_ZOOM,
  turns = 0,
  active = true,
}: {
  match: MatchState<MonopolyView>
  seat: number
  selected: number | null
  onSelect: (index: number) => void
  zoom?: number
  /**
   * How many quarters the table has been turned, clockwise (V3).
   *
   * The camera stands at the seat's corner and does not move: what turns is the
   * board on the table, the way a player turns a real board with their hands. The
   * table, the overlays and the accessible mirror are outside the turned group, so
   * only the printed surface and what stands on it move.
   */
  turns?: number
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
  return (
    <div className="monopoly-table3d">
      {/*
        S11: the board does not animate, so the scene renders on demand instead of
        sixty times a second -- a click or a texture arriving invalidates a frame
        and nothing else does. It is also what lets a headless capture finish: a
        permanent render loop keeps the browser busy forever.
      */}
      <Canvas
        dpr={[1, 2]}
        frameloop={active ? 'demand' : 'never'}
        gl={{ antialias: true }}
        shadows
      >
        <color args={['#171419']} attach="background" />
        <SeatCamera seat={seat} zoom={zoom} />

        <ambientLight intensity={0.55} />
        <directionalLight
          castShadow
          intensity={1.55}
          position={[BOARD_CENTER.x + 7, 13, BOARD_CENTER.z + 6]}
          shadow-bias={-0.0004}
          shadow-mapSize={[1024, 1024]}
        >
          <orthographicCamera args={[-9, 9, 9, -9, 0.5, 60]} attach="shadow-camera" />
        </directionalLight>
        {/* A cool fill from the far side, so the shadowed halves are not black. */}
        <directionalLight intensity={0.38} position={[BOARD_CENTER.x - 8, 9, BOARD_CENTER.z - 7]} />

        <Table />
        {/* V3: the printed surface and everything standing on it, turned by
            quarters around the board's own centre. The pivot is the two nested
            groups: a rotation in three.js turns around the group's origin, so the
            outer one sits at the centre and the inner one puts the board back
            where it belongs. Without the pivot the board swings off the table. */}
        <group position={[BOARD_CENTER.x, 0, BOARD_CENTER.z]} rotation-y={sceneRotationFor(turns)}>
          <group position={[-BOARD_CENTER.x, 0, -BOARD_CENTER.z]}>
            <BoardSlab />
            <Cells onSelect={onSelect} selected={selected} />
            <Buildings view={match.view} />
            <Tokens match={match} />
            {selected !== null && <SelectedFrame index={selected} />}
            <DeckPile colour="#e39a2a" offsetX={-0.75} />
            <DeckPile colour="#3d7fb5" offsetX={0.75} />
          </group>
        </group>

        {/* The board's own shadow on the table, which is what glues it down. */}
        <ContactShadows
          blur={2.6}
          far={6}
          opacity={0.5}
          position={[BOARD_CENTER.x, -SLAB_THICKNESS + 0.002, BOARD_CENTER.z]}
          scale={GRID_SIZE * 2.4}
        />
      </Canvas>
    </div>
  )
}
