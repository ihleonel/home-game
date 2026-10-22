/**
 * The classic pieces, built from primitives (X5 of ``monopoly-3d-table.md``).
 *
 * S3 forbids binary assets: no ``.glb``, no downloaded model. So each piece is
 * a small assembly of three's own geometry, chosen for its **silhouette** -- the
 * brim of the top hat, the ears of the cat, the handle of the iron -- because at
 * a seat's distance that is what the eye recognises. They are not sculpted
 * models and do not pretend to be; the alternative was the pawn the owner of the
 * look rejected.
 *
 * The colour is paper and ink (X12). The pieces were silver, and the silver had
 * no contrast against the coloured cells: on a yellow or a light-blue space a
 * grey token disappeared. So the body is white and every part is drawn a second
 * time, inflated along its own normals and turned inside out, in black -- the
 * black hull is only visible around the silhouette, and that edge is what makes
 * the shape readable on any cell, in the family of the dice. The colour still
 * says nothing about the seat: the figure alone says which marker you chose, two
 * pieces on one cell are told apart by where they stand (``Tokens`` spreads
 * them), and the accessible mirror prints each player's initial. Every piece
 * stands on the same pedestal, which gives it a clean contact shadow on the
 * board.
 *
 * ``figures.ts`` owns the marker-to-figure decision and is the tested half; this
 * file only turns a figure id into meshes, which the headless capture checks.
 */

import { createContext, useContext, useEffect, useMemo, type ComponentType } from 'react'
import { BackSide, MeshBasicMaterial, MeshStandardMaterial } from 'three'
import type { Material } from 'three'
import type { PieceFigure } from './figures'

/** Paper: the pieces' body, a shade warmer than the board's own white. */
const PAPER = '#fbf9f3'
const BODY_METALNESS = 0.02
const BODY_ROUGHNESS = 0.62

/** Ink: the outline's colour, and how far it stands off the silhouette, in cells. */
const INK = '#0d0b10'
const OUTLINE = 0.022

/**
 * The material every part is drawn with.
 *
 * The pieces are rendered twice from the same component tree -- once with the
 * ink, once with the paper -- and this context is what makes that possible
 * without repeating the meshes or threading a material through nine components.
 */
const PieceLook = createContext<Material | null>(null)

/** One part's material: whatever the current pass is painting with. */
function Paint() {
  const material = useContext(PieceLook)
  if (material === null) throw new Error('a piece part was drawn outside its look')
  return <primitive attach="material" object={material} />
}

/**
 * The ink pass: the same geometry, inflated along its normals and turned inside
 * out, so only the rim around the white body is visible.
 *
 * The inflation is per vertex along its own normal, which is what keeps the
 * outline the same thickness on a part far from the piece's origin as on one in
 * the middle. ``onBeforeCompile`` runs once, when the renderer compiles the
 * material, so the cost is one add per vertex; no binary asset, no extra pass of
 * the whole scene.
 */
function useInkMaterial(): MeshBasicMaterial {
  return useMemo(() => {
    const material = new MeshBasicMaterial({ color: INK, side: BackSide })
    material.onBeforeCompile = (shader) => {
      shader.vertexShader = shader.vertexShader.replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>\n  transformed += normal * ${OUTLINE.toFixed(4)};`,
      )
    }
    return material
  }, [])
}

/** The paper pass: the piece itself, lit like everything else on the board. */
function usePaperMaterial(): MeshStandardMaterial {
  return useMemo(
    () =>
      new MeshStandardMaterial({
        color: PAPER,
        metalness: BODY_METALNESS,
        roughness: BODY_ROUGHNESS,
      }),
    [],
  )
}

/** The disc every piece stands on, so it casts one clean shadow. */
function Pedestal() {
  return (
    <mesh castShadow position={[0, 0.008, 0]} receiveShadow>
      <cylinderGeometry args={[0.115, 0.125, 0.016, 20]} />
      <Paint />
    </mesh>
  )
}

/** Top hat: a wide brim under a tall crown. */
function Sombrero() {
  return (
    <group>
      <Pedestal />
      <mesh castShadow position={[0, 0.03, 0]}>
        <cylinderGeometry args={[0.155, 0.16, 0.014, 24]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.125, 0]}>
        <cylinderGeometry args={[0.085, 0.09, 0.175, 20]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.218, 0]}>
        <cylinderGeometry args={[0.092, 0.09, 0.012, 20]} />
        <Paint />
      </mesh>
    </group>
  )
}

/** Car: a low narrow body, a small cabin set back, and wheels that stick out. */
function Automovil() {
  const wheels: readonly (readonly [number, number])[] = [
    [-0.105, 0.072],
    [0.105, 0.072],
    [-0.105, -0.072],
    [0.105, -0.072],
  ]
  return (
    <group>
      <Pedestal />
      {wheels.map(([x, z]) => (
        <mesh castShadow key={`${x}:${z}`} position={[x, 0.052, z]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.052, 0.052, 0.036, 16]} />
          <Paint />
        </mesh>
      ))}
      <mesh castShadow position={[0, 0.082, 0]}>
        <boxGeometry args={[0.32, 0.045, 0.11]} />
        <Paint />
      </mesh>
      {/* A long hood and a narrow cabin are what make the side read as a car;
          the wheels sit outside the body so the top view shows four corners. */}
      <mesh castShadow position={[0.105, 0.112, 0]} rotation={[0, 0, -0.08]}>
        <boxGeometry args={[0.09, 0.025, 0.1]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.045, 0.12, 0]}>
        <boxGeometry args={[0.095, 0.05, 0.095]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.15, 0.125, 0]}>
        <boxGeometry args={[0.022, 0.035, 0.11]} />
        <Paint />
      </mesh>
    </group>
  )
}

/** Dog: body on four legs, head with a snout, pointed ears and a tail. */
function Perro() {
  const legs: readonly (readonly [number, number])[] = [
    [-0.07, 0.04],
    [0.07, 0.04],
    [-0.07, -0.04],
    [0.07, -0.04],
  ]
  return (
    <group>
      <Pedestal />
      {legs.map(([x, z]) => (
        <mesh castShadow key={`${x}:${z}`} position={[x, 0.055, z]}>
          <cylinderGeometry args={[0.016, 0.018, 0.075, 10]} />
          <Paint />
        </mesh>
      ))}
      <mesh castShadow position={[0, 0.14, 0]} scale={[1.45, 1, 0.8]}>
        <sphereGeometry args={[0.082, 18, 12]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0.115, 0.21, 0]}>
        <sphereGeometry args={[0.058, 16, 12]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0.165, 0.2, 0]}>
        <boxGeometry args={[0.055, 0.04, 0.042]} />
        <Paint />
      </mesh>
      {[1, -1].map((side) => (
        <mesh
          castShadow
          key={`ear:${side}`}
          position={[0.1, 0.26, 0.036 * side]}
          rotation={[0.35 * side, 0, -0.2]}
        >
          <coneGeometry args={[0.026, 0.06, 10]} />
          <Paint />
        </mesh>
      ))}
      <mesh castShadow position={[-0.09, 0.19, 0]} rotation={[0, 0, 0.9]}>
        <cylinderGeometry args={[0.009, 0.013, 0.1, 8]} />
        <Paint />
      </mesh>
    </group>
  )
}

/** Ship: hull with a pointed bow, a bridge, two funnels and a mast. */
function Barco() {
  return (
    <group>
      <Pedestal />
      <mesh castShadow position={[0, 0.05, 0]}>
        <boxGeometry args={[0.26, 0.05, 0.1]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0.155, 0.05, 0]} rotation={[0, 0, -Math.PI / 2]} scale={[0.45, 1, 0.45]}>
        <coneGeometry args={[0.055, 0.09, 4]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.085, 0]}>
        <boxGeometry args={[0.2, 0.02, 0.085]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.035, 0.12, 0]}>
        <boxGeometry args={[0.075, 0.06, 0.07]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.05, 0.16, 0]}>
        <cylinderGeometry args={[0.018, 0.022, 0.05, 12]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.005, 0.16, 0]}>
        <cylinderGeometry args={[0.014, 0.018, 0.05, 12]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0.08, 0.155, 0]}>
        <cylinderGeometry args={[0.006, 0.008, 0.13, 6]} />
        <Paint />
      </mesh>
    </group>
  )
}

/** Cat: a low, wide body with a round head, big ears and an upturned tail. */
function Gato() {
  return (
    <group>
      <Pedestal />
      <mesh castShadow position={[0, 0.105, 0]} scale={[1.1, 0.95, 0.95]}>
        <sphereGeometry args={[0.085, 18, 12]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.21, 0.01]}>
        <sphereGeometry args={[0.062, 16, 12]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.196, 0.066]} scale={[0.7, 0.55, 0.6]}>
        <sphereGeometry args={[0.04, 12, 8]} />
        <Paint />
      </mesh>
      {/* Ears are the whole silhouette: two tall triangles, tilted outward. */}
      {[1, -1].map((side) => (
        <mesh
          castShadow
          key={`ear:${side}`}
          position={[0.043 * side, 0.262, 0.005]}
          rotation={[0, 0, -0.35 * side]}
        >
          <coneGeometry args={[0.031, 0.072, 10]} />
          <Paint />
        </mesh>
      ))}
      <mesh castShadow position={[-0.105, 0.13, -0.02]} rotation={[0.25, 0, 1.2]}>
        <cylinderGeometry args={[0.008, 0.015, 0.17, 8]} />
        <Paint />
      </mesh>
    </group>
  )
}

/** Iron: a wide pointed sole under a low dome, with an arched handle. */
function Plancha() {
  return (
    <group>
      <Pedestal />
      <mesh castShadow position={[0, 0.036, 0]}>
        <boxGeometry args={[0.27, 0.026, 0.15]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0.172, 0.036, 0]} rotation={[0, 0, -Math.PI / 2]} scale={[0.55, 1, 0.66]}>
        <coneGeometry args={[0.06, 0.09, 4]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.005, 0.055, 0]} scale={[1.55, 0.42, 0.9]}>
        <sphereGeometry args={[0.08, 18, 12]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.098, 0]}>
        <torusGeometry args={[0.055, 0.011, 8, 20, Math.PI]} />
        <Paint />
      </mesh>
    </group>
  )
}

/** Boot: a long foot with a pointed toe and a shaft with a cuff. */
function Botin() {
  return (
    <group>
      <Pedestal />
      <mesh castShadow position={[0.045, 0.045, 0]}>
        <boxGeometry args={[0.22, 0.045, 0.1]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0.17, 0.045, 0]} rotation={[0, 0, -Math.PI / 2]} scale={[0.5, 1, 0.55]}>
        <coneGeometry args={[0.05, 0.07, 4]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.04, 0.135, 0]}>
        <cylinderGeometry args={[0.052, 0.06, 0.17, 16]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[-0.04, 0.225, 0]}>
        <cylinderGeometry args={[0.064, 0.058, 0.022, 16]} />
        <Paint />
      </mesh>
    </group>
  )
}

/** Thimble: a truncated cone closed by a dome, with a rim at the hem. */
function Dedal() {
  return (
    <group>
      <Pedestal />
      <mesh castShadow position={[0, 0.105, 0]}>
        <cylinderGeometry args={[0.072, 0.105, 0.17, 20]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.19, 0]}>
        <sphereGeometry args={[0.072, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <Paint />
      </mesh>
      <mesh castShadow position={[0, 0.024, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.103, 0.008, 8, 24]} />
        <Paint />
      </mesh>
    </group>
  )
}

/**
 * The neutral counter.
 *
 * What an unknown marker gets. The alternative -- a pawn or a guessed piece --
 * would tell the player they chose something they did not choose. A plain disc
 * is honest and still readable on the board.
 */
function Ficha() {
  return (
    <group>
      <Pedestal />
      <mesh castShadow position={[0, 0.05, 0]} receiveShadow>
        <cylinderGeometry args={[0.1, 0.11, 0.05, 20]} />
        <Paint />
      </mesh>
    </group>
  )
}

/**
 * The catalogue the figure id indexes.
 *
 * Typed as a complete ``Record`` so adding a ``PieceFigure`` without building
 * its meshes fails to compile instead of rendering nothing.
 */
const FIGURES: Record<PieceFigure, ComponentType> = {
  sombrero: Sombrero,
  automovil: Automovil,
  perro: Perro,
  barco: Barco,
  gato: Gato,
  plancha: Plancha,
  botin: Botin,
  dedal: Dedal,
  ficha: Ficha,
}

/**
 * One player's piece, standing on its pedestal.
 *
 * Drawn twice from the same tree: the ink hull first, then the white body on top
 * of it. Both passes share the piece's own geometry, so the outline cannot
 * disagree with the shape it is outlining.
 */
export function Figure3D({ figure }: { figure: PieceFigure }) {
  const Piece = FIGURES[figure]
  const ink = useInkMaterial()
  const paper = usePaperMaterial()
  useEffect(
    () => () => {
      ink.dispose()
      paper.dispose()
    },
    [ink, paper],
  )
  return (
    <group>
      <PieceLook.Provider value={ink}>
        <Piece />
      </PieceLook.Provider>
      <PieceLook.Provider value={paper}>
        <Piece />
      </PieceLook.Provider>
    </group>
  )
}
