// The brain view's colours, from one source: the 3D map's look-up table (a 256 x 1 texture), the
// legend's CSS gradient and the tests all call these functions. A PuOr_r-like diverging scale
// around the model's zero, built in OKLCH from the palette tokens in app/globals.css (cool blue
// "lower", warm orange "higher", checked with the dataviz palette validator): each arm keeps its
// hue and steps its lightness one way only, and 0 is the neutral grey. It mirrors peak.png
// (scoring/score.py _hemi_polys): below grey_below x vmax only the grey sulcal shading shows, the
// colour comes in linearly and is full from full_at x vmax. A colour depends on the value alone,
// on ONE scale for the whole reel, never on the second, the area or the frame.
//
// Values here are u = value / vmax in [-1, 1] (the stored level q / 127). Colours are sRGB 0..1.
// Pure functions: no DOM, no three.js, safe anywhere (tests/brain.spec.ts runs them in Node).

export type RGB = [number, number, number];

export type BrainPalette = {
  cool: RGB;
  warm: RGB;
  /** The "near 0" grey (legend swatch, and the base of the sulcal greys). */
  near: RGB;
  /** Ink, for the outline of a hovered area. */
  ink: RGB;
  dark: boolean;
};

/** peak.png's thresholds (scoring/score.py BRAIN_GREY_BELOW / BRAIN_FULL_AT); the page's
 *  scale block carries the same numbers and wins when given. */
export const GREY_BELOW = 0.15;
export const FULL_AT = 0.5;
export const LUT_SIZE = 256;

export function hexToRgb(hex: string): RGB | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

const hex = (h: string): RGB => hexToRgb(h) as RGB;

/** The tokens of app/globals.css, for the server render and before the page's CSS is read. */
export const DEFAULT_PALETTE: { light: BrainPalette; dark: BrainPalette } = {
  light: { cool: hex("#2a78d6"), warm: hex("#eb6834"), near: hex("#c4c4cc"), ink: hex("#18181b"), dark: false },
  dark: { cool: hex("#3987e5"), warm: hex("#d95926"), near: hex("#4a4a52"), ink: hex("#ededed"), dark: true },
};

// ---------------------------------------------------------------- OKLab / OKLCH

const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
const toGamma = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

export type LCH = [number, number, number];

export function rgbToOklch([r, g, b]: RGB): LCH {
  const [lr, lg, lb] = [toLinear(r), toLinear(g), toLinear(b)];
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return [L, Math.hypot(A, B), Math.atan2(B, A)];
}

export function oklchToRgb([L, C, h]: LCH): RGB {
  const A = C * Math.cos(h);
  const B = C * Math.sin(h);
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const b = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  return [clamp01(toGamma(r)), clamp01(toGamma(g)), clamp01(toGamma(b))];
}

// ---------------------------------------------------------------- the scale

/** How much colour shows over the grey at u: 0 below the grey threshold, 1 from full_at up.
 *  Symmetric: alphaAt(u) === alphaAt(-u). */
export function alphaAt(u: number, greyBelow = GREY_BELOW, fullAt = FULL_AT): number {
  return clamp01((Math.abs(u) - greyBelow) / Math.max(1e-6, fullAt - greyBelow));
}

/** One arm's three OKLCH stops: a pale tint at 0, the token at full_at, a deeper step at 1
 *  (lighter on a dark surface), hue held, lightness moving one way only. */
function arm(pole: RGB, dark: boolean): [LCH, LCH, LCH] {
  const [L, C, h] = rgbToOklch(pole);
  const tint: LCH = dark ? [Math.max(0.3, L - 0.2), C * 0.4, h] : [Math.min(0.93, L + 0.25), C * 0.35, h];
  const deep: LCH = dark ? [Math.min(0.86, L + 0.12), C * 0.95, h] : [Math.max(0.25, L - 0.13), C * 1.05, h];
  return [tint, [L, C, h], deep];
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** The pole colour at u (no grey mixed in): the cool arm below 0, the warm arm above. */
export function poleColor(u: number, pal: BrainPalette, fullAt = FULL_AT): RGB {
  const a = Math.min(1, Math.abs(u));
  const [tint, mid, deep] = arm(u < 0 ? pal.cool : pal.warm, pal.dark);
  const [p, q, t] = a <= fullAt ? [tint, mid, a / fullAt] : [mid, deep, (a - fullAt) / (1 - fullAt)];
  return oklchToRgb([lerp(p[0], q[0], t), lerp(p[1], q[1], t), p[2]]);
}

/** What the map shows at u over a grey: the pole colour mixed in by alphaAt. */
export function colorFor(u: number, grey: RGB, pal: BrainPalette, greyBelow = GREY_BELOW, fullAt = FULL_AT): RGB {
  const a = alphaAt(u, greyBelow, fullAt);
  const c = poleColor(u, pal, fullAt);
  return [lerp(grey[0], c[0], a), lerp(grey[1], c[1], a), lerp(grey[2], c[2], a)];
}

/** The u of LUT entry i: entry i and entry size-1-i are u and -u. */
export const lutU = (i: number, size = LUT_SIZE) => (i / (size - 1)) * 2 - 1;

/** The 256 x 1 RGBA table the shader reads (pole colours; the shader mixes in its own grey). */
export function buildLut(pal: BrainPalette, fullAt = FULL_AT, size = LUT_SIZE): Uint8Array {
  const out = new Uint8Array(size * 4);
  for (let i = 0; i < size; i++) {
    const [r, g, b] = poleColor(lutU(i, size), pal, fullAt);
    out.set([Math.round(r * 255), Math.round(g * 255), Math.round(b * 255), 255], i * 4);
  }
  return out;
}

/** The sulcal greys under the colour: deeper folds (sulc > 0) darker, as in peak.png. */
export function sulcGreyParams(pal: BrainPalette): { base: number; depth: number } {
  const near = (pal.near[0] + pal.near[1] + pal.near[2]) / 3;
  return pal.dark ? { base: near + 0.04, depth: 0.08 } : { base: Math.min(0.8, near - 0.03), depth: 0.12 };
}

const css = ([r, g, b]: RGB) => `rgb(${Math.round(r * 255)} ${Math.round(g * 255)} ${Math.round(b * 255)})`;

/** The legend: the map's colours from -1 to 1 over the flat "near 0" grey, as a CSS gradient. */
export function legendGradient(pal: BrainPalette, greyBelow = GREY_BELOW, fullAt = FULL_AT, steps = 24): string {
  const stops: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const u = (i / steps) * 2 - 1;
    stops.push(`${css(colorFor(u, pal.near, pal, greyBelow, fullAt))} ${((i / steps) * 100).toFixed(1)}%`);
  }
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

export const rgbCss = css;
