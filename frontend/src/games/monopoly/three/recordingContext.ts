/**
 * A recording stand-in for the 2D context (S7 of ``monopoly-printed-cells.md``).
 *
 * The harness is Node with no DOM, so the canvas painters used to be untested on
 * purpose. This double implements the slice of ``CanvasRenderingContext2D`` the
 * painters actually use, records every call together with the ink it was drawn
 * in, and answers ``measureText`` with a width derived from the current font
 * size (0.55 em per character) -- close enough to ``system-ui`` for the fitting
 * loop of the cell painter to take its real branches.
 *
 * It is test scaffolding: nothing in the app imports it, so it never reaches the
 * bundle. Its job is to let a suite say **what a painter was told to draw**; it
 * does not pretend to know what the result looks like. That last part is still
 * the headless capture and the person looking at the board.
 */

/**
 * The shadow a call was drawn with, when it carried one.
 *
 * A glow is a stroke plus a shadow of the same ink, so a suite that only read
 * the ink could not tell a lit frame from a flat one.
 */
export type RecordedShadow = { colour: string; blur: number }

/** One recorded call: the operation, the ink it used and its arguments. */
export type DrawCall = {
  op: string
  /** The fill or stroke colour in force, or an empty string for transforms. */
  ink: string
  args: readonly number[]
  /** The string argument of ``fillText``, when the operation has one. */
  text?: string
  /** The shadow in force when the call was made, or absent for an unlit shape. */
  shadow?: RecordedShadow
}

/** The approximation the double uses for the width of a character, in ems. */
const CHAR_WIDTH = 0.55

/** The font size of the current ``font`` string, in pixels. */
function fontSize(font: string): number {
  const match = /(\d+(?:\.\d+)?)px/.exec(font)
  return match === null ? 10 : Number(match[1])
}

/** The recording context the painters are handed in the suites. */
export class RecordingContext {
  readonly calls: DrawCall[] = []
  fillStyle = '#000000'
  strokeStyle = '#000000'
  lineWidth = 1
  lineCap = 'butt'
  lineJoin = 'miter'
  font = '10px sans-serif'
  textAlign = 'start'
  textBaseline = 'alphabetic'
  shadowColor = 'transparent'
  shadowBlur = 0

  /** The calls of one operation. */
  of(op: string): DrawCall[] {
    return this.calls.filter((call) => call.op === op)
  }

  /** Every ``fillText`` in order, as plain strings. */
  texts(): string[] {
    return this.of('fillText').map((call) => call.text ?? '')
  }

  private push(op: string, args: number[] = [], text?: string, ink?: string): void {
    const call: DrawCall = { op, args, text, ink: ink ?? '' }
    if (this.shadowBlur > 0) call.shadow = { colour: this.shadowColor, blur: this.shadowBlur }
    this.calls.push(call)
  }

  private pushFill(op: string, args: number[] = []): void {
    this.push(op, args, undefined, this.fillStyle)
  }

  private pushStroke(op: string, args: number[] = []): void {
    this.push(op, args, undefined, this.strokeStyle)
  }

  save(): void {
    this.push('save')
  }

  restore(): void {
    this.push('restore')
  }

  setTransform(a: number, b: number, c: number, d: number, e: number, f: number): void {
    this.push('setTransform', [a, b, c, d, e, f])
  }

  translate(x: number, y: number): void {
    this.push('translate', [x, y])
  }

  rotate(angle: number): void {
    this.push('rotate', [angle])
  }

  scale(x: number, y: number): void {
    this.push('scale', [x, y])
  }

  clearRect(x: number, y: number, width: number, height: number): void {
    this.push('clearRect', [x, y, width, height])
  }

  fillRect(x: number, y: number, width: number, height: number): void {
    this.pushFill('fillRect', [x, y, width, height])
  }

  strokeRect(x: number, y: number, width: number, height: number): void {
    this.pushStroke('strokeRect', [x, y, width, height])
  }

  beginPath(): void {
    this.push('beginPath')
  }

  rect(x: number, y: number, width: number, height: number): void {
    this.push('rect', [x, y, width, height])
  }

  clip(): void {
    this.push('clip')
  }

  moveTo(x: number, y: number): void {
    this.push('moveTo', [x, y])
  }

  lineTo(x: number, y: number): void {
    this.push('lineTo', [x, y])
  }

  closePath(): void {
    this.push('closePath')
  }

  arc(x: number, y: number, radius: number, from: number, to: number): void {
    this.push('arc', [x, y, radius, from, to])
  }

  fill(): void {
    this.pushFill('fill')
  }

  stroke(): void {
    this.pushStroke('stroke')
  }

  fillText(text: string, x: number, y: number, maxWidth?: number): void {
    this.push('fillText', maxWidth === undefined ? [x, y] : [x, y, maxWidth], text, this.fillStyle)
  }

  measureText(text: string): TextMetrics {
    return { width: text.length * fontSize(this.font) * CHAR_WIDTH } as TextMetrics
  }
}

/** The double typed as the context the painters expect. */
export function recordingContext(): CanvasRenderingContext2D {
  return new RecordingContext() as unknown as CanvasRenderingContext2D
}
