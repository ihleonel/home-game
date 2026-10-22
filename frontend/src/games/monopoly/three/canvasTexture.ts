/**
 * A painted canvas as a texture the renderer can sample.
 *
 * Split out so the scene and the dice can both use it without importing each
 * other: the dice are built by their own component and the board imports that
 * component, so a helper living in the board would be a cycle.
 */

import { CanvasTexture, SRGBColorSpace } from 'three'

/** ``canvas`` as a texture, with the colour space and anisotropy it needs. */
export function toTexture(canvas: HTMLCanvasElement, anisotropy: number): CanvasTexture {
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  texture.anisotropy = anisotropy
  return texture
}
