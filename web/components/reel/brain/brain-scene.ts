// The 3D brain's scene, outside React (plain three.js; loaded only with brain-canvas.tsx).
//
// One camera; each side in its own pivot, placed side by side (the mesh centres each side near
// x = 0, so the viewer sets them apart). Outside shows the lateral faces, Inside the medial
// faces. Dragging turns both sides mirrored (pitch held within 60 degrees; on touch only sideways,
// so a vertical swipe still scrolls the page: touch-action pan-y on the canvas). Reset and the
// presets tween in 250 ms (at once under reduced motion).
//
// It draws only when something changed (the second, the blend while playing, a turn, a hover, the
// size, the theme), never in a loop. A new second copies one stored row (20,484 levels) into the
// frame attribute. Hovering picks at most once a frame; a tap picks on touch (moved < 6px); the
// picked point is the hit triangle's corner nearest the hit (its largest weight) and its area
// comes from the atlas lookup. No text is drawn. dispose() frees everything and releases the
// context.
//
// The test hooks live on the canvas element: data-ready, data-frame, data-angle, data-yaw,
// data-hover-area (+ data-hover-side), data-mix (data-scale-abs is set by the React wrapper).

import { BufferAttribute, BufferGeometry, Group, Matrix4, Mesh, PerspectiveCamera, Quaternion, Raycaster, Scene, Vector2, Vector3, WebGLRenderer, type DataTexture } from "three";

import { BRAIN, frameRow, type BrainAtlas, type BrainFrames, type BrainMesh } from "@/lib/brain/format";

import { focusId, getFocus, setFocus, setPointer, type BrainFocus, type Side } from "./brain-focus";
import { brainMaterial, lutTexture } from "./brain-shader";
import { buildLut, sulcGreyParams, type BrainPalette } from "./lut";
import type { BrainView } from "./view";

export type Angle = "outside" | "inside" | "free";

const LINE_INDEX = { seeing: 1, hearing: 2, language: 3, attention: 4 } as const;
const PITCH_MAX = (60 * Math.PI) / 180;
const TURN_PER_PX = 0.01;
const TWEEN_MS = 250;
const BLEND_MS = 1000;
const TAP_PX = 6;

type SideGL = {
  pivot: Group;
  mesh: Mesh<BufferGeometry, ReturnType<typeof brainMaterial>>;
  v0: BufferAttribute;
  v1: BufferAttribute;
};

export type SceneOptions = {
  view: BrainView;
  data: { mesh: BrainMesh; atlas: BrainAtlas; frames: BrainFrames };
  palette: BrainPalette;
  touch: boolean;
  reduced: () => boolean;
  onReady: () => void;
  onLost: () => void;
  onAngle: (angle: Angle) => void;
};

const angleOf = (yaw: number, pitch: number): Angle => {
  const y = ((((yaw * 180) / Math.PI) % 360) + 360) % 360;
  if (Math.abs(pitch) > 0.01) return "free";
  if (y < 0.5 || y > 359.5) return "outside";
  if (Math.abs(y - 180) < 0.5) return "inside";
  return "free";
};

const yawDegrees = (yaw: number) => {
  const d = Math.round((((((yaw * 180) / Math.PI) % 360) + 540) % 360) - 180);
  return d === -180 ? 180 : d;
};

const ease = (x: number) => 1 - Math.pow(1 - x, 3);

/** One side's geometry: centred, with the per-point attributes the shader reads. */
function sideGeometry(view: BrainView, mesh: BrainMesh, atlas: BrainAtlas, side: Side) {
  const n = BRAIN.perSide;
  const off = side === "left" ? 0 : n;
  const src = mesh.coords[side];
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) {
    for (let d = 0; d < 3; d++) {
      const v = src[3 * i + d];
      if (v < min[d]) min[d] = v;
      if (v > max[d]) max[d] = v;
    }
  }
  const mid = [0, 1, 2].map((d) => (min[d] + max[d]) / 2);
  const pos = new Float32Array(src.length);
  for (let i = 0; i < n; i++) for (let d = 0; d < 3; d++) pos[3 * i + d] = src[3 * i + d] - mid[d];

  const area = new Float32Array(n);
  const net = new Float32Array(n);
  const line = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const k = atlas.hcp[off + i];
    area[i] = k;
    if (k > 0) {
      net[i] = view.atlas.network[k - 1] ?? 0;
      const l = view.atlas.line[k - 1];
      line[i] = l ? LINE_INDEX[l] : 0;
    }
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(pos, 3));
  g.setIndex(new BufferAttribute(new Uint16Array(mesh.faces[side]), 1));
  g.computeVertexNormals();
  g.setAttribute("aSulc", new BufferAttribute(new Float32Array(mesh.sulc[side]), 1));
  g.setAttribute("aArea", new BufferAttribute(area, 1));
  g.setAttribute("aNet", new BufferAttribute(net, 1));
  g.setAttribute("aLine", new BufferAttribute(line, 1));
  const v0 = new BufferAttribute(new Int8Array(n), 1, true);
  const v1 = new BufferAttribute(new Int8Array(n), 1, true);
  g.setAttribute("aV0", v0);
  g.setAttribute("aV1", v1);
  g.computeBoundingSphere();
  return { g, v0, v1, half: [(max[0] - min[0]) / 2, (max[1] - min[1]) / 2, (max[2] - min[2]) / 2] };
}

/** Mesh axes (x right, y front, z up) to the view: each side's lateral face to the camera, the
 *  top up, the front outwards (left side: front on the left; right side: front on the right). */
function baseTurn(side: Side): Quaternion {
  const m = new Matrix4();
  if (side === "left") m.makeBasis(new Vector3(0, 0, -1), new Vector3(-1, 0, 0), new Vector3(0, 1, 0));
  else m.makeBasis(new Vector3(0, 0, 1), new Vector3(1, 0, 0), new Vector3(0, 1, 0));
  return new Quaternion().setFromRotationMatrix(m);
}

export class BrainScene {
  private readonly canvas: HTMLCanvasElement;
  private readonly wrap: HTMLElement;
  private readonly opts: SceneOptions;
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  private readonly camera = new PerspectiveCamera(22, 2, 10, 5000);
  private readonly sides: [SideGL, SideGL];
  private readonly lut: DataTexture;
  private readonly fit: { halfW: number; halfH: number; depth: number };
  private readonly ray = new Raycaster();
  private readonly ro: ResizeObserver;
  private readonly cleanups: Array<() => void> = [];
  private yaw = 0;
  private pitch = 0;
  private frame = -1;
  private blend: { to: number; start: number } | null = null;
  private tween: { yaw0: number; pitch0: number; yaw1: number; pitch1: number; start: number } | null = null;
  private raf = 0;
  private ready = false;
  private hoverAt: { x: number; y: number } | null = null;
  private drag: { id: number; x: number; y: number; x0: number; y0: number; type: string; moved: boolean } | null = null;
  private disposed = false;

  /** Throws when WebGL cannot start (the wrapper shows the fallback). */
  constructor(canvas: HTMLCanvasElement, wrap: HTMLElement, opts: SceneOptions) {
    this.canvas = canvas;
    this.wrap = wrap;
    this.opts = opts;
    const lost = (e: Event) => {
      e.preventDefault();
      if (!this.disposed) opts.onLost();
    };
    canvas.addEventListener("webglcontextlost", lost);
    this.cleanups.push(() => canvas.removeEventListener("webglcontextlost", lost));
    this.renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: "low-power" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, opts.touch ? 1.75 : 2));
    this.renderer.setClearColor(0x000000, 0);

    const { view, data } = opts;
    this.lut = lutTexture(buildLut(opts.palette, view.fullAt));
    const built = (["left", "right"] as const).map((side) => {
      const { g, v0, v1, half } = sideGeometry(view, data.mesh, data.atlas, side);
      const mesh = new Mesh(g, brainMaterial(this.lut, view));
      const base = new Group();
      base.quaternion.copy(baseTurn(side));
      base.add(mesh);
      const pivot = new Group();
      pivot.add(base);
      this.scene.add(pivot);
      return { pivot, mesh, v0, v1, half };
    });
    // In the view each side's front-back length runs along x and its height along y.
    const halfLen = Math.max(built[0].half[1], built[1].half[1]);
    const offset = halfLen * 1.08;
    built[0].pivot.position.x = -offset;
    built[1].pivot.position.x = offset;
    this.fit = { halfW: offset + halfLen, halfH: Math.max(built[0].half[2], built[1].half[2]), depth: Math.max(built[0].half[0], built[1].half[0]) };
    this.sides = [built[0], built[1]];

    const ds = canvas.dataset;
    ds.ready = "false";
    ds.angle = "outside";
    ds.yaw = "0";
    ds.mix = "0";
    ds.hoverArea = "";

    this.setPalette(opts.palette);
    this.applyFocus(getFocus());
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(wrap);
    this.resize();
    this.listen();
  }

  // ---------------------------------------------------------------- public

  /** Show second `t` (clamped to the read's rows); while playing, blend from the second shown. */
  setSecond(t: number, playing: boolean) {
    const rows = this.opts.data.frames.rows;
    const row = Math.min(Math.max(0, Math.floor(t)), rows - 1);
    if (row === this.frame) return;
    const prev = this.frame;
    this.frame = row;
    this.canvas.dataset.frame = String(row);
    if (playing && !this.opts.reduced() && prev >= 0 && row === prev + 1) {
      this.copyRow(prev, "v0");
      this.copyRow(row, "v1");
      this.blend = { to: row, start: performance.now() };
      this.setMix(0);
    } else {
      this.blend = null;
      this.copyRow(row, "v0");
      this.setMix(0);
    }
    this.request();
  }

  setPalette(pal: BrainPalette) {
    (this.lut.image.data as Uint8Array).set(buildLut(pal, this.opts.view.fullAt));
    this.lut.needsUpdate = true;
    const grey = sulcGreyParams(pal);
    for (const s of this.sides) {
      const u = s.mesh.material.uniforms;
      u.uGreyBase.value = grey.base;
      u.uGreyDepth.value = grey.depth;
      u.uInk.value.set(pal.ink[0], pal.ink[1], pal.ink[2]);
    }
    this.request();
  }

  /** Outline the focused area, network or line, and grey the rest a little. */
  applyFocus(f: BrainFocus | null) {
    const kind = !f ? 0 : f.kind === "area" ? 1 : f.kind === "net" ? 2 : 3;
    const val = !f ? 0 : f.kind === "area" ? f.k + 1 : f.kind === "net" ? f.n : LINE_INDEX[f.line];
    (["left", "right"] as const).forEach((side, i) => {
      const u = this.sides[i].mesh.material.uniforms;
      u.uFocusKind.value = kind;
      u.uFocusVal.value = val;
      u.uFocusOn.value = kind ? 1 : 0;
      u.uSideOn.value = f && (f.kind !== "area" || f.side === null || f.side === side) ? 1 : 0;
    });
    this.canvas.dataset.hoverArea = focusId(f);
    if (f?.kind === "area" && f.side) this.canvas.dataset.hoverSide = f.side;
    else delete this.canvas.dataset.hoverSide;
    this.request();
  }

  /** Turn to a preset the short way round (250 ms; at once under reduced motion). */
  turnTo(angle: "outside" | "inside") {
    const target = angle === "inside" ? Math.PI : 0;
    const turns = Math.round((this.yaw - target) / (2 * Math.PI));
    this.tween = { yaw0: this.yaw, pitch0: this.pitch, yaw1: target + turns * 2 * Math.PI, pitch1: 0, start: performance.now() };
    this.request();
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    for (const c of this.cleanups) c();
    for (const s of this.sides) {
      s.mesh.geometry.dispose();
      s.mesh.material.dispose();
    }
    this.lut.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    if (getFocus()?.from === "brain") setFocus(null);
    setPointer(null);
  }

  // ---------------------------------------------------------------- drawing

  private request() {
    if (this.disposed || this.raf) return;
    this.raf = requestAnimationFrame((now) => this.draw(now));
  }

  private resize() {
    const w = Math.max(1, this.wrap.clientWidth);
    const h = Math.max(1, this.wrap.clientHeight);
    this.renderer.setSize(w, h, false);
    const cam = this.camera;
    cam.aspect = w / h;
    const tanV = Math.tan((cam.fov * Math.PI) / 360);
    const dist = Math.max(this.fit.halfW / (tanV * cam.aspect), this.fit.halfH / tanV) * 1.06 + this.fit.depth;
    cam.position.set(0, 0, dist);
    cam.lookAt(0, 0, 0);
    cam.updateProjectionMatrix();
    this.request();
  }

  private setPose(yaw: number, pitch: number) {
    this.yaw = yaw;
    this.pitch = Math.max(-PITCH_MAX, Math.min(PITCH_MAX, pitch));
    this.sides[0].pivot.rotation.set(this.pitch, this.yaw, 0, "XYZ");
    this.sides[1].pivot.rotation.set(this.pitch, -this.yaw, 0, "XYZ");
    const angle = angleOf(this.yaw, this.pitch);
    this.canvas.dataset.yaw = String(yawDegrees(this.yaw));
    if (this.canvas.dataset.angle !== angle) {
      this.canvas.dataset.angle = angle;
      this.opts.onAngle(angle);
    }
  }

  /** Copy one stored second into the frame attribute (v0 = shown, v1 = blending to). */
  private copyRow(row: number, which: "v0" | "v1") {
    const q = frameRow(this.opts.data.frames, row);
    const n = BRAIN.perSide;
    this.sides.forEach((s, i) => {
      (s[which].array as Int8Array).set(q.subarray(i * n, (i + 1) * n));
      s[which].needsUpdate = true;
    });
  }

  private setMix(mix: number) {
    for (const s of this.sides) s.mesh.material.uniforms.uMix.value = mix;
    this.canvas.dataset.mix = mix === 0 ? "0" : mix.toFixed(2);
  }

  private draw(now: number) {
    this.raf = 0;
    if (this.disposed) return;
    let again = false;
    const reduced = this.opts.reduced();
    if (this.tween) {
      const tw = this.tween;
      const k = reduced ? 1 : Math.min(1, (now - tw.start) / TWEEN_MS);
      const e = ease(k);
      this.setPose(tw.yaw0 + (tw.yaw1 - tw.yaw0) * e, tw.pitch0 + (tw.pitch1 - tw.pitch0) * e);
      if (k >= 1) this.tween = null;
      else again = true;
    }
    if (this.blend) {
      const k = reduced ? 1 : Math.min(1, (now - this.blend.start) / BLEND_MS);
      if (k >= 1) {
        // Land on the new second: one plain frame, no blend left over.
        this.copyRow(this.blend.to, "v0");
        this.setMix(0);
        this.blend = null;
      } else {
        this.setMix(k);
        again = true;
      }
    }
    if (this.hoverAt) {
      this.pick(this.hoverAt, "hover");
      this.hoverAt = null;
    }
    this.renderer.render(this.scene, this.camera);
    if (!this.ready) {
      this.ready = true;
      this.canvas.dataset.ready = "true";
      this.opts.onReady();
    }
    if (again) this.request();
  }

  // ---------------------------------------------------------------- pointer: turn, hover, tap

  private pick(at: { x: number; y: number }, how: "hover" | "tap") {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    this.ray.setFromCamera(new Vector2((at.x / w) * 2 - 1, -(at.y / h) * 2 + 1), this.camera);
    const hit = this.ray.intersectObjects([this.sides[0].mesh, this.sides[1].mesh], false)[0];
    let found: { k: number; side: Side } | null = null;
    if (hit?.face) {
      const sideIndex = hit.object === this.sides[0].mesh ? 0 : 1;
      const mesh = this.sides[sideIndex].mesh;
      const local = mesh.worldToLocal(hit.point.clone());
      const pos = mesh.geometry.getAttribute("position");
      let best = hit.face.a;
      let bestD = Infinity;
      for (const v of [hit.face.a, hit.face.b, hit.face.c]) {
        const d = (pos.getX(v) - local.x) ** 2 + (pos.getY(v) - local.y) ** 2 + (pos.getZ(v) - local.z) ** 2;
        if (d < bestD) [best, bestD] = [v, d];
      }
      const k = this.opts.data.atlas.hcp[sideIndex * BRAIN.perSide + best];
      if (k > 0) found = { k: k - 1, side: sideIndex === 0 ? "left" : "right" };
    }
    const cur = getFocus();
    if (found) {
      setFocus({ kind: "area", k: found.k, side: found.side, from: "brain", pinned: how === "tap" });
      setPointer(how === "hover" ? at : null);
    } else {
      if (cur?.from === "brain") setFocus(null);
      setPointer(null);
    }
  }

  private listen() {
    const canvas = this.canvas;
    const local = (e: PointerEvent) => {
      const box = canvas.getBoundingClientRect();
      return { x: e.clientX - box.left, y: e.clientY - box.top };
    };
    const down = (e: PointerEvent) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      const p = local(e);
      this.drag = { id: e.pointerId, x: p.x, y: p.y, x0: p.x, y0: p.y, type: e.pointerType, moved: false };
      canvas.setPointerCapture(e.pointerId);
      this.tween = null;
    };
    const move = (e: PointerEvent) => {
      const p = local(e);
      const d = this.drag;
      if (d && d.id === e.pointerId) {
        const [dx, dy] = [p.x - d.x, p.y - d.y];
        d.x = p.x;
        d.y = p.y;
        if (!d.moved && Math.hypot(p.x - d.x0, p.y - d.y0) >= TAP_PX) d.moved = true;
        if (d.moved) {
          this.setPose(this.yaw + dx * TURN_PER_PX, d.type === "mouse" ? this.pitch + dy * TURN_PER_PX : this.pitch);
          this.request();
        }
        return;
      }
      if (e.pointerType === "mouse") {
        this.hoverAt = p;
        this.request();
      }
    };
    const up = (e: PointerEvent) => {
      const d = this.drag;
      if (!d || d.id !== e.pointerId) return;
      this.drag = null;
      if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
      if (!d.moved && e.pointerType !== "mouse") this.pick(local(e), "tap");
      this.request();
    };
    const cancel = (e: PointerEvent) => {
      if (this.drag?.id === e.pointerId) this.drag = null;
    };
    const leave = (e: PointerEvent) => {
      if (e.pointerType !== "mouse" || this.drag) return;
      this.hoverAt = null;
      const cur = getFocus();
      if (cur?.from === "brain" && !cur.pinned) setFocus(null);
      setPointer(null);
    };
    const on: Array<[string, (e: PointerEvent) => void]> = [
      ["pointerdown", down],
      ["pointermove", move],
      ["pointerup", up],
      ["pointercancel", cancel],
      ["pointerleave", leave],
    ];
    for (const [name, fn] of on) canvas.addEventListener(name, fn as EventListener);
    this.cleanups.push(() => {
      for (const [name, fn] of on) canvas.removeEventListener(name, fn as EventListener);
    });
  }
}
