// The 3D brain's material (plain three.js ShaderMaterial; loaded only with brain-canvas.tsx).
//
// Per point: its sulcal depth, its HCP area (0 = medial wall), that area's Yeo network and line,
// and two stored levels (aV0 = this second, aV1 = the next; int8 read as -1..1 = value / vmax).
// uMix blends the two while Play steps (0 under reduced motion). The colour mirrors peak.png:
// below grey_below only the grey sulcal shading, then the reel's ONE colour scale (uLut, 256 x 1,
// from lut.ts) mixed in, full from full_at. The scale never changes per frame. A focused area,
// network or line gets an ink outline (the 0.5 iso-line of a per-point 0/1 flag) and the rest of
// the map is greyed 30%. Colours are sRGB numbers in and out (no colour-space conversion), like
// the legend's CSS gradient. No text is ever drawn.

import { DataTexture, LinearFilter, RGBAFormat, ShaderMaterial, Vector3, type IUniform } from "three";

import { FULL_AT, GREY_BELOW, LUT_SIZE } from "./lut";

const vertexShader = /* glsl */ `
attribute float aSulc;
attribute float aArea;
attribute float aNet;
attribute float aLine;
attribute float aV0;
attribute float aV1;
uniform float uMix;
uniform float uFocusKind;
uniform float uFocusVal;
uniform float uSideOn;
varying float vU;
varying float vSulc;
varying float vWall;
varying float vFocus;
varying vec3 vNormal;
void main() {
  vU = mix(aV0, aV1, uMix);
  vSulc = aSulc;
  vWall = aArea < 0.5 ? 1.0 : 0.0;
  float key = uFocusKind < 1.5 ? aArea : (uFocusKind < 2.5 ? aNet : aLine);
  vFocus = (uFocusKind > 0.5 && uSideOn > 0.5 && abs(key - uFocusVal) < 0.5) ? 1.0 : 0.0;
  vNormal = normalize(normalMatrix * normal);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const fragmentShader = /* glsl */ `
uniform sampler2D uLut;
uniform float uLutSize;
uniform float uGreyBelow;
uniform float uFullAt;
uniform float uGreyBase;
uniform float uGreyDepth;
uniform float uFocusOn;
uniform vec3 uInk;
varying float vU;
varying float vSulc;
varying float vWall;
varying float vFocus;
varying vec3 vNormal;
void main() {
  float u = clamp(vU, -1.0, 1.0);
  float a = clamp((abs(u) - uGreyBelow) / max(1e-4, uFullAt - uGreyBelow), 0.0, 1.0) * (1.0 - vWall);
  float x = (u + 1.0) * 0.5;
  vec3 pole = texture2D(uLut, vec2((x * (uLutSize - 1.0) + 0.5) / uLutSize, 0.5)).rgb;
  float grey = uGreyBase - uGreyDepth * tanh(2.0 * vSulc);
  vec3 col = mix(vec3(grey), pole, a);
  vec3 n = normalize(vNormal);
  float shade = 0.62 + 0.38 * clamp(dot(n, normalize(vec3(0.35, 0.45, 1.0))), 0.0, 1.0);
  col *= shade;
  if (uFocusOn > 0.5) {
    float l = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(col, vec3(l), 0.3 * (1.0 - vFocus));
    float w = fwidth(vFocus);
    float edge = (1.0 - smoothstep(0.0, max(w * 1.5, 1e-4), abs(vFocus - 0.5))) * step(1e-4, w);
    col = mix(col, uInk, edge);
  }
  gl_FragColor = vec4(col, 1.0);
}
`;

export type BrainUniforms = {
  uLut: IUniform<DataTexture>;
  uLutSize: IUniform<number>;
  uMix: IUniform<number>;
  uGreyBelow: IUniform<number>;
  uFullAt: IUniform<number>;
  uGreyBase: IUniform<number>;
  uGreyDepth: IUniform<number>;
  uFocusKind: IUniform<number>;
  uFocusVal: IUniform<number>;
  uSideOn: IUniform<number>;
  uFocusOn: IUniform<number>;
  uInk: IUniform<Vector3>;
};

/** The shared 256 x 1 colour table (filled from lut.ts buildLut). */
export function lutTexture(data: Uint8Array): DataTexture {
  const tex = new DataTexture(data, LUT_SIZE, 1, RGBAFormat);
  tex.minFilter = LinearFilter;
  tex.magFilter = LinearFilter;
  tex.generateMipmaps = false;
  tex.needsUpdate = true;
  return tex;
}

/** One side's material (each side has its own, so a hovered area outlines on its side only). */
export function brainMaterial(lut: DataTexture, scale: { greyBelow?: number; fullAt?: number }): ShaderMaterial & { uniforms: BrainUniforms } {
  const uniforms: BrainUniforms = {
    uLut: { value: lut },
    uLutSize: { value: LUT_SIZE },
    uMix: { value: 0 },
    uGreyBelow: { value: scale.greyBelow ?? GREY_BELOW },
    uFullAt: { value: scale.fullAt ?? FULL_AT },
    uGreyBase: { value: 0.74 },
    uGreyDepth: { value: 0.12 },
    uFocusKind: { value: 0 },
    uFocusVal: { value: 0 },
    uSideOn: { value: 0 },
    uFocusOn: { value: 0 },
    uInk: { value: new Vector3(0.1, 0.1, 0.11) },
  };
  return new ShaderMaterial({ uniforms, vertexShader, fragmentShader }) as ShaderMaterial & { uniforms: BrainUniforms };
}
