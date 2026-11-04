// Lyceum 学园 · 三渲二舞台
// MeshToonMaterial（3 阶 gradientMap，NearestFilter）+ 后处理墨线（法线/深度边缘检测）
// + 滚动转场：平涂 → 半调网点 → 铜版排线。
import * as THREE from 'three';
import { mergeGeometries } from '/vendor/BufferGeometryUtils.js';

const PAPER = new THREE.Color('#f5f3ee');
const hexV = (h) => new THREE.Vector3(parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255);
const PAPER_S = hexV('#f5f3ee');
const INK_S = hexV('#1b2142');

/* ---------------- 材质 ---------------- */
function makeGradient(steps) {
  const data = new Uint8Array(steps.length * 4);
  steps.forEach((v, i) => { data.set([v, v, v, 255], i * 4); });
  const tex = new THREE.DataTexture(data, steps.length, 1, THREE.RGBAFormat);
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.needsUpdate = true;
  return tex;
}
const GRAD3 = makeGradient([40, 150, 255]);
const GRAD2 = makeGradient([60, 255]);
const toon = (hex, grad = GRAD3) => new THREE.MeshToonMaterial({ color: hex, gradientMap: grad });

const M = {
  stone: toon('#fbfaf6', GRAD2),
  stone2: toon('#efede7', GRAD2),
  door: toon('#c9d1ee', GRAD2),
  owl: toon('#2b50e4'),
  owlDark: toon('#1f3cc0'),
  owlFace: toon('#7d95f2'),
  cream: toon('#f7f1e1'),
  white: toon('#ffffff', GRAD2),
  pupil: new THREE.MeshBasicMaterial({ color: '#1b2142' }),
  beak: toon('#f7d348', GRAD2),
  bookA: toon('#2b50e4'),
  bookB: toon('#f7f1e1'),
  bookC: toon('#e9e4d6'),
  laurel: toon('#5f8a5a', GRAD2),
};

/* ---------------- 几何：柱式 ---------------- */
// 带凹槽与收分的柱身（解析法线，接缝无断线）
function shaftGeometry({ h, rb, rt, flutes, depth }) {
  const rs = flutes * 8, hs = 16;
  const pos = [], nor = [], uv = [], idx = [];
  const P = (a, t) => {
    const R = rb + (rt - rb) * t + 0.018 * Math.sin(Math.PI * Math.min(1, t * 1.25));
    const f = (a / (Math.PI * 2)) * flutes;
    const fr = f - Math.floor(f);
    const r = R - depth * Math.sin(Math.PI * fr);
    return new THREE.Vector3(Math.cos(a) * r, t * h, Math.sin(a) * r);
  };
  for (let j = 0; j <= hs; j++) {
    const t = j / hs;
    for (let i = 0; i <= rs; i++) {
      const a = (i / rs) * Math.PI * 2;
      const p = P(a, t);
      // 每个凹槽内部用中心差分，棱线处取槽内侧，保证锐利棱线
      const e = (Math.PI * 2) / rs * 0.25;
      const fpos = ((a / (Math.PI * 2)) * flutes) % 1;
      const a1 = fpos < 1e-6 ? a : a - e;
      const a2 = fpos > 1 - 1e-6 ? a : a + e;
      const da = new THREE.Vector3().subVectors(P(a2 === a ? a + e * 0.001 : a2, t), P(a1, t));
      const dt = new THREE.Vector3().subVectors(P(a, Math.min(1, t + 0.01)), P(a, Math.max(0, t - 0.01)));
      const n = new THREE.Vector3().crossVectors(da, dt).normalize().multiplyScalar(-1);
      if (n.dot(new THREE.Vector3(p.x, 0, p.z)) < 0) n.negate();
      pos.push(p.x, p.y, p.z); nor.push(n.x, n.y, n.z); uv.push(i / rs, t);
    }
  }
  for (let j = 0; j < hs; j++) for (let i = 0; i < rs; i++) {
    const a = j * (rs + 1) + i, b = a + rs + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}
const lathe = (pts, seg = 40) => new THREE.LatheGeometry(pts.map(([x, y]) => new THREE.Vector2(x, y)), seg);
const at = (g, x, y, z, rx = 0, ry = 0, rz = 0, s = null) => {
  g = g.toNonIndexed ? g : g;
  const m = new THREE.Matrix4().compose(
    new THREE.Vector3(x, y, z),
    new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, rz)),
    s ? new THREE.Vector3(...s) : new THREE.Vector3(1, 1, 1));
  g.applyMatrix4(m);
  return g;
};
const clean = (g) => { // 统一属性，便于合并
  if (!g.index) g = mergeGeometries([g]);
  for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv'].includes(k)) g.deleteAttribute(k);
  return g;
};

export const COLUMN_H = 6.0;
function buildColumn(order) {
  const parts = [];
  let base = 0, cap = 0, rb, rt, flutes;
  if (order === 'doric') { rb = 0.44; rt = 0.35; flutes = 16; cap = 0.42; }
  else if (order === 'ionic') { rb = 0.37; rt = 0.31; flutes = 18; cap = 0.5; base = 0.34; }
  else { rb = 0.35; rt = 0.29; flutes = 18; cap = 0.92; base = 0.34; }
  const sh = COLUMN_H - base - cap;
  if (base) {
    parts.push(at(new THREE.BoxGeometry(1.0, 0.12, 1.0), 0, 0.06, 0));
    parts.push(lathe([[0, 0.12], [rb + 0.14, 0.12], [rb + 0.17, 0.17], [rb + 0.14, 0.22], [rb + 0.05, 0.25], [rb + 0.09, 0.29], [rb + 0.03, 0.34], [0, 0.34]]));
  }
  parts.push(at(shaftGeometry({ h: sh, rb, rt, flutes, depth: order === 'doric' ? 0.022 : 0.016 }), 0, base, 0));
  const y0 = base + sh;
  if (order === 'doric') {
    parts.push(lathe([[0, y0], [rt + 0.02, y0], [rt + 0.02, y0 + 0.05], [rt + 0.06, y0 + 0.1], [rt + 0.2, y0 + 0.2], [rt + 0.22, y0 + 0.24], [0, y0 + 0.24]]));
    parts.push(at(new THREE.BoxGeometry(1.12, 0.18, 1.12), 0, y0 + 0.33, 0));
  } else if (order === 'ionic') {
    parts.push(lathe([[0, y0], [rt + 0.04, y0], [rt + 0.1, y0 + 0.1], [rt + 0.06, y0 + 0.16], [0, y0 + 0.16]]));
    parts.push(at(new THREE.BoxGeometry(1.0, 0.2, 0.62), 0, y0 + 0.24, 0)); // 涡卷枕
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      parts.push(at(new THREE.TorusGeometry(0.15, 0.045, 10, 28), sx * 0.47, y0 + 0.18, sz * 0.31));
      parts.push(at(new THREE.SphereGeometry(0.06, 14, 10), sx * 0.47, y0 + 0.18, sz * 0.31));
    }
    parts.push(at(new THREE.BoxGeometry(0.96, 0.08, 0.96), 0, y0 + 0.42, 0));
  } else {
    parts.push(lathe([[0, y0], [rt + 0.02, y0], [rt + 0.08, y0 + 0.4], [rt + 0.2, y0 + 0.72], [rt + 0.22, y0 + 0.78], [0, y0 + 0.78]]));
    for (let row = 0; row < 2; row++) {
      const n = 8, ry = y0 + 0.2 + row * 0.26, rr = rt + 0.03 + row * 0.07;
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + row * (Math.PI / n);
        const leaf = new THREE.SphereGeometry(1, 12, 8);
        leaf.scale(0.11, 0.24, 0.05);
        leaf.translate(0, 0.12, 0);
        leaf.rotateX(0.42);
        leaf.rotateY(-a + Math.PI / 2);
        leaf.translate(Math.cos(a) * rr, ry, Math.sin(a) * rr);
        parts.push(leaf);
      }
    }
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      parts.push(at(new THREE.TorusGeometry(0.07, 0.025, 8, 18), sx * 0.42, y0 + 0.74, sz * 0.42, 0, Math.PI / 4 * sx * sz));
    }
    parts.push(at(new THREE.BoxGeometry(1.02, 0.14, 1.02), 0, y0 + 0.85, 0));
  }
  return mergeGeometries(parts.map(clean));
}

/* ---------------- 神庙 ---------------- */
const COLS_X = [-5.5, -3.3, -1.1, 1.1, 3.3, 5.5];
const COLS_Z = [1.25, -1.25];
function buildTemple(order) {
  const g = new THREE.Group();
  // 台基三级
  const steps = [[15.2, 6.6], [14.4, 5.8], [13.6, 5.0]];
  steps.forEach(([w, d], i) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, 0.32, d), M.stone);
    m.position.y = 0.16 + i * 0.32; m.castShadow = m.receiveShadow = true; g.add(m);
  });
  const floor = 0.96;
  // 内殿墙
  const cella = new THREE.Mesh(new THREE.BoxGeometry(11.4, COLUMN_H, 1.4), M.stone2);
  cella.position.set(0, floor + COLUMN_H / 2, -1.25); cella.receiveShadow = true; g.add(cella);
  const door = new THREE.Mesh(new THREE.BoxGeometry(1.7, 3.4, 0.4), M.door);
  door.position.set(0, floor + 1.7, -0.5); door.receiveShadow = true; g.add(door);
  // 柱
  const colGeo = buildColumn(order);
  const inst = new THREE.InstancedMesh(colGeo, M.stone, COLS_X.length * COLS_Z.length);
  let k = 0; const m4 = new THREE.Matrix4();
  for (const z of COLS_Z) for (const x of COLS_X) { m4.makeTranslation(x, floor, z); inst.setMatrixAt(k++, m4); }
  inst.castShadow = inst.receiveShadow = true; g.add(inst);
  // 檐部
  const top = floor + COLUMN_H;
  const arch = new THREE.Mesh(new THREE.BoxGeometry(13.2, 0.55, 3.8), M.stone);
  arch.position.set(0, top + 0.275, 0); arch.castShadow = arch.receiveShadow = true; g.add(arch);
  const frieze = new THREE.Mesh(new THREE.BoxGeometry(12.9, 0.6, 3.5), M.stone2);
  frieze.position.set(0, top + 0.85, 0); frieze.receiveShadow = true; g.add(frieze);
  if (order === 'doric') { // 三陇板
    const tg = new THREE.BoxGeometry(0.42, 0.6, 0.08);
    const n = 13; const tri = new THREE.InstancedMesh(tg, M.stone, n);
    for (let i = 0; i < n; i++) { m4.makeTranslation(-6.3 + i * 1.05, top + 0.85, 1.78); tri.setMatrixAt(i, m4); }
    tri.castShadow = true; g.add(tri);
  } else { // 连续浮雕带：小齿饰
    const tg = new THREE.BoxGeometry(0.16, 0.16, 0.12);
    const n = 44; const den = new THREE.InstancedMesh(tg, M.stone, n);
    for (let i = 0; i < n; i++) { m4.makeTranslation(-6.3 + i * 0.3, top + 1.06, 1.78); den.setMatrixAt(i, m4); }
    g.add(den);
  }
  const cornice = new THREE.Mesh(new THREE.BoxGeometry(13.9, 0.24, 4.3), M.stone);
  cornice.position.set(0, top + 1.27, 0); cornice.castShadow = cornice.receiveShadow = true; g.add(cornice);
  // 山花
  const tri = (w, h, d) => {
    const s = new THREE.Shape(); s.moveTo(-w / 2, 0); s.lineTo(w / 2, 0); s.lineTo(0, h); s.closePath();
    const e = new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false }); e.translate(0, 0, -d / 2); return e;
  };
  const ped = new THREE.Mesh(tri(13.4, 1.68, 3.5), M.stone2);
  ped.position.y = top + 1.39; ped.castShadow = true; ped.receiveShadow = true; g.add(ped);
  // 斜檐（raking cornice）
  const slope = Math.atan2(1.82, 6.95), len = Math.hypot(6.95, 1.82) + 0.25;
  for (const sx of [-1, 1]) {
    const rk = new THREE.Mesh(new THREE.BoxGeometry(len, 0.26, 4.3), M.stone);
    rk.position.set(sx * 3.42, top + 1.39 + 0.91 + 0.05, 0); rk.rotation.z = -sx * slope;
    rk.castShadow = true; g.add(rk);
  }
  // 山花顶饰（akroterion）
  const akro = new THREE.Mesh(new THREE.SphereGeometry(0.28, 20, 14), M.stone);
  akro.scale.set(1, 1.25, 0.4); akro.position.set(0, top + 3.42, 1.95); g.add(akro);
  return g;
}

/* ---------------- 猫头鹰 · 小雅 ---------------- */
function buildOwl() {
  const owl = new THREE.Group();
  const add = (parent, geo, mat, p, s, r) => {
    const m = new THREE.Mesh(geo, mat); if (p) m.position.set(...p); if (s) m.scale.set(...s); if (r) m.rotation.set(...r);
    m.castShadow = true; parent.add(m); return m;
  };
  const S = (d = 40) => new THREE.SphereGeometry(1, d, Math.round(d * 0.75));
  // 书（底座）
  const books = new THREE.Group(); owl.add(books);
  add(books, new THREE.BoxGeometry(2.3, 0.34, 1.6), M.bookA, [0, 0.17, 0], null, [0, 0.08, 0]);
  add(books, new THREE.BoxGeometry(2.16, 0.26, 1.46), M.bookC, [0.03, 0.17, 0.08], null, [0, 0.08, 0]);
  add(books, new THREE.BoxGeometry(2.0, 0.3, 1.4), M.bookB, [-0.05, 0.49, 0], null, [0, -0.12, 0]);
  add(books, new THREE.BoxGeometry(2.04, 0.08, 1.44), M.bookA, [-0.05, 0.66, 0], null, [0, -0.12, 0]);
  const body = new THREE.Group(); body.position.y = 0.7; owl.add(body);
  add(body, S(), M.owl, [0, 1.0, 0], [0.86, 1.02, 0.78]);
  add(body, S(), M.cream, [0, 0.82, 0.36], [0.6, 0.66, 0.46]);
  const wings = [];
  for (const sx of [-1, 1]) {
    const pivot = new THREE.Group(); pivot.position.set(sx * 0.74, 1.35, -0.02); body.add(pivot);
    add(pivot, S(32), M.owlDark, [sx * 0.06, -0.42, 0], [0.24, 0.62, 0.52], [0, 0, sx * 0.12]);
    wings.push(pivot);
  }
  for (const sx of [-1, 1]) for (let i = -1; i <= 1; i++) {
    add(body, new THREE.SphereGeometry(0.075, 12, 8), M.beak, [sx * 0.32 + i * 0.1, 0.06, 0.5], [1, 0.7, 1.4]);
  }
  // 头（可转动）
  const head = new THREE.Group(); head.position.set(0, 1.32, 0.05); body.add(head);
  add(head, S(), M.owl, [0, 0.42, -0.05], [0.84, 0.72, 0.74]);
  add(head, S(), M.owlFace, [0, 0.36, 0.3], [0.68, 0.5, 0.36]);
  for (const sx of [-1, 1]) {
    add(head, new THREE.ConeGeometry(0.16, 0.42, 24), M.owl, [sx * 0.5, 1.02, -0.06], [1, 1, 0.7], [0, 0, -sx * 0.45]);
  }
  const eyes = [];
  for (const sx of [-1, 1]) {
    const eye = new THREE.Group(); eye.position.set(sx * 0.3, 0.42, 0.58); head.add(eye);
    add(eye, S(32), M.white, [0, 0, 0], [0.3, 0.3, 0.12]);
    const pupil = new THREE.Group(); eye.add(pupil);
    add(pupil, S(24), M.pupil, [0, 0, 0.09], [0.16, 0.16, 0.06]);
    add(pupil, S(12), new THREE.MeshBasicMaterial({ color: '#ffffff' }), [0.06, 0.06, 0.15], [0.05, 0.05, 0.02]);
    eyes.push({ eye, pupil });
  }
  add(head, new THREE.ConeGeometry(0.1, 0.24, 20), M.beak, [0, 0.2, 0.66], null, [Math.PI / 2 + 0.5, 0, 0]);
  const laurel = new THREE.Group(); head.add(laurel);
  // 反向外壳描边（只进颜色层，不进法线层）：让腹部、脸盘、眼白、翅膀在身体上也有墨线
  const hullMat = HULL;
  const T = 0.05;
  owl.traverse((m) => {
    if (!m.isMesh || !m.geometry.type.startsWith('Sphere') || m.material === M.pupil || m.scale.x < 0.1) return;
    const h = new THREE.Mesh(m.geometry, hullMat);
    h.position.copy(m.position); h.rotation.copy(m.rotation);
    h.scale.set(m.scale.x + T, m.scale.y + T, m.scale.z + T);
    h.layers.set(1); m.parent.add(h);
  });
  owl.userData = { body, head, eyes, wings, laurel };
  return owl;
}

const HULL = new THREE.MeshBasicMaterial({ color: '#1b2142', side: THREE.BackSide });

/* 深色主题 = 月夜：石材压成墨蓝灰、墨线换成纸色、太阳盘变月亮；小雅保持钴蓝。 */
const THEME = {
  light: { stone: '#fbfaf6', stone2: '#efede7', door: '#c9d1ee', cream: '#f7f1e1', white: '#ffffff', bookB: '#f7f1e1', bookC: '#e9e4d6',
    ink: '#1b2142', paper: '#f5f3ee', disc: '#dfe6fb', sky: '#b3c1f3', gnd: '#e2e5f3', amb: 2.05, sun: 1.8, shadow: '#3a4aa0', shadowA: 0.14 },
  dark: { stone: '#4a5288', stone2: '#3d4579', door: '#262d5c', cream: '#cfc8b4', white: '#dcd8cd', bookB: '#cfc8b4', bookC: '#a9a392',
    ink: '#ece8de', paper: '#161b36', disc: '#e9e4d2', sky: '#8796d8', gnd: '#2a3160', amb: 1.7, sun: 1.25, shadow: '#05081c', shadowA: 0.35 },
};

/* ---------------- 合成着色器：墨线 + 半调 + 铜版 ---------------- */
const CompositeShader = {
  uniforms: {
    tColor: { value: null }, tNormal: { value: null }, tDepth: { value: null },
    uRes: { value: new THREE.Vector2(1, 1) }, uPx: { value: 1.5 }, uCell: { value: 7 },
    uInk: { value: INK_S }, uPaper: { value: PAPER_S },
    uHalf: { value: 0 }, uEtch: { value: 0 }, uNear: { value: 1 }, uFar: { value: 100 },
    uRefZ: { value: 20 }, uFadeA: { value: 30 }, uFadeB: { value: 46 }, uLapA: { value: 0.035 }, uLapB: { value: 0.07 },
  },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
  fragmentShader: `
    precision highp float;
    uniform sampler2D tColor, tNormal, tDepth;
    uniform vec2 uRes; uniform float uPx, uCell, uHalf, uEtch, uNear, uFar, uRefZ, uFadeA, uFadeB, uLapA, uLapB;
    uniform vec3 uInk, uPaper;
    varying vec2 vUv;
    vec3 toSRGB(vec3 c){ c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0/2.4)) - 0.055, step(0.0031308, c)); }
    float lin(float d){ float z = d * 2.0 - 1.0; return (2.0 * uNear * uFar) / (uFar + uNear - z * (uFar - uNear)); }
    vec3 nrm(vec2 uv){ return texture2D(tNormal, uv).rgb * 2.0 - 1.0; }
    void main(){
      vec4 c4 = texture2D(tColor, vUv);
      vec3 c = toSRGB(c4.rgb);
      float d0 = texture2D(tDepth, vUv).r;
      float z0 = d0 > 0.9999 ? uFar : lin(d0);
      // 距离衰减：越远采样半径越小（线越细），远处细节的法线边淡出，避免齿饰闪虚线
      float far = smoothstep(uFadeA, uFadeB, z0);
      vec2 px = uPx / uRes * clamp(uRefZ / max(z0, 0.001), 0.55, 1.0);
      vec3 n0 = nrm(vUv);
      float ne = 0.0, de = 0.0;
      vec2 off[8]; float zs[8];
      off[0]=vec2(1,0); off[1]=vec2(-1,0); off[2]=vec2(0,1); off[3]=vec2(0,-1);
      off[4]=vec2(.7,.7); off[5]=vec2(-.7,.7); off[6]=vec2(.7,-.7); off[7]=vec2(-.7,-.7);
      for (int i = 0; i < 8; i++) {
        vec2 uv = vUv + off[i] * px;
        float di = texture2D(tDepth, uv).r;
        float zi = di > 0.9999 ? uFar : lin(di); zs[i] = zi;
        vec3 ni = nrm(uv);
        bool bg0 = d0 > 0.9999, bgi = di > 0.9999;
        if (bg0 != bgi) { de = 1.0; }
        else if (!bg0) {
          de = max(de, abs(zi - z0) / max(z0, 0.001));
          ne = max(ne, 1.0 - dot(n0, ni));
        }
      }
      // 深度二阶差（平面上≈0，与倾角无关）：抓住齿饰/门框这类浅台阶（相对深度差 < 0.7% 时原深度边抓不到，只剩时有时无的法线边 → 虚线）
      float lap = 0.0;
      if (!(d0 > 0.9999)) {
        lap = max(max(abs(zs[0] + zs[1] - 2.0 * z0), abs(zs[2] + zs[3] - 2.0 * z0)),
                  max(abs(zs[4] + zs[7] - 2.0 * z0), abs(zs[5] + zs[6] - 2.0 * z0)));
        lap = lap * uRefZ / max(z0, 0.001);
      }
      float lE = smoothstep(uLapA, uLapB, lap) * (1.0 - far);
      float edge = max(max(smoothstep(0.32, 0.6, ne) * (1.0 - far), lE), smoothstep(0.007 + 0.02 * far, 0.018 + 0.03 * far, de));
      bool bg = d0 > 0.9999;
      if (bg) c = uPaper;
      // 半调网点
      vec2 fc = gl_FragCoord.xy;
      float lum = dot(c, vec3(0.299, 0.587, 0.114));
      float sat = max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b));
      vec3 dotCol = mix(uInk, c * 0.82, smoothstep(0.18, 0.4, sat));
      vec2 rp = mat2(0.7071, -0.7071, 0.7071, 0.7071) * fc;
      vec2 cell = mod(rp, uCell) - 0.5 * uCell;
      float rad = 0.5 * uCell * 1.18 * sqrt(clamp((0.97 - lum) / 0.97, 0.0, 1.0)) + 0.35;
      float dm = 1.0 - smoothstep(rad - 0.7, rad + 0.7, length(cell));
      vec3 halftone = bg ? uPaper : mix(uPaper, dotCol, dm);
      // 铜版排线
      vec2 hp = mat2(0.866, -0.5, 0.5, 0.866) * fc;
      float sp = uCell * 0.62;
      float l1 = abs(fract(hp.y / sp) - 0.5) * sp;
      float dark = clamp((0.98 - lum) * 1.25, 0.0, 1.0);
      float h1 = 1.0 - smoothstep(dark * sp * 0.42 - 0.5, dark * sp * 0.42 + 0.5, l1);
      vec2 hp2 = mat2(0.866, 0.5, -0.5, 0.866) * fc;
      float l2 = abs(fract(hp2.y / sp) - 0.5) * sp;
      float dark2 = clamp((0.62 - lum) * 1.6, 0.0, 1.0);
      float h2 = 1.0 - smoothstep(dark2 * sp * 0.4 - 0.5, dark2 * sp * 0.4 + 0.5, l2);
      float hatch = max(h1 * step(0.02, dark), h2 * step(0.02, dark2));
      vec3 etch = bg ? uPaper : mix(uPaper, dotCol, hatch);
      vec3 col = mix(c, halftone, uHalf);
      col = mix(col, etch, uEtch);
      col = mix(col, uInk, edge);
      if (bg) {
        // 背景透明，透出页面纸纹；只保留地面投影（随阶段变成网点/排线）和描边
        float sa = c4.a;
        vec3 sc = toSRGB(c4.rgb / max(sa, 1e-4));
        vec3 cs = mix(uPaper, sc, sa);
        float gate = smoothstep(0.012, 0.04, sa);
        float ls = dot(cs, vec3(0.299, 0.587, 0.114));
        float rs = 0.5 * uCell * 1.18 * sqrt(clamp((0.97 - ls) / 0.97, 0.0, 1.0)) + 0.35;
        float ds = (1.0 - smoothstep(rs - 0.7, rs + 0.7, length(cell))) * gate;
        float dks = clamp((0.98 - ls) * 1.25, 0.0, 1.0);
        float hs = (1.0 - smoothstep(dks * sp * 0.42 - 0.5, dks * sp * 0.42 + 0.5, l1)) * step(0.02, dks) * gate;
        vec3 inkS = mix(uInk, sc * 0.82, 0.5);
        vec4 o = vec4(sc * sa, sa);
        o = mix(o, vec4(inkS * ds, ds) * 0.85, uHalf);
        o = mix(o, vec4(inkS * hs, hs) * 0.85, uEtch);
        gl_FragColor = mix(o, vec4(uInk, 1.0), edge);
      } else {
        gl_FragColor = vec4(col, 1.0);
      }
    }`,
};

/* ---------------- 舞台 ---------------- */
export class Stage {
  constructor() {
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'stage-canvas';
    this.canvas.setAttribute('aria-label', '三渲二希腊神庙与猫头鹰小雅');
    this.ok = true;
    try {
      this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: false, alpha: true, premultipliedAlpha: true, powerPreference: 'low-power' });
    } catch (e) { this.ok = false; return; }
    const r = this.renderer;
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFShadowMap;
    r.setClearColor(0x000000, 0);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(28, 1, 1, 120);
    this.camera.layers.enable(1);
    // 光
    const amb = this.amb = new THREE.HemisphereLight('#b3c1f3', '#e2e5f3', 2.05);
    this.scene.add(amb);
    const sun = this.sun = new THREE.DirectionalLight('#fffdf8', 1.8);
    sun.position.set(-9, 14, 11);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const sc = sun.shadow.camera; sc.left = -11; sc.right = 11; sc.top = 11; sc.bottom = -6; sc.near = 1; sc.far = 50;
    sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.06;
    this.scene.add(sun);
    // 地面（只接收阴影，不参与描边）
    const ground = this.ground = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.ShadowMaterial({ color: '#3a4aa0', opacity: 0.14 }));
    ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; ground.layers.set(1);
    this.scene.add(ground);
    // 远处的太阳盘
    const disc = new THREE.Mesh(new THREE.CircleGeometry(5.2, 96), new THREE.MeshBasicMaterial({ color: '#dfe6fb' }));
    disc.position.set(1.2, 8.6, -12); this.scene.add(disc); this.disc = disc;

    this.order = 'doric';
    this.temple = buildTemple(this.order); this.scene.add(this.temple);
    this.owl = buildOwl();
    this.owl.position.set(-2.6, 0.96, 3.15); this.owl.rotation.y = 0.28; this.owl.scale.setScalar(0.92);
    this.scene.add(this.owl);

    // 后处理目标
    this.rtColor = new THREE.WebGLRenderTarget(2, 2, { samples: 4, type: THREE.HalfFloatType });
    this.rtNormal = new THREE.WebGLRenderTarget(2, 2);
    this.rtNormal.depthTexture = new THREE.DepthTexture(2, 2);
    this.normalMat = new THREE.MeshNormalMaterial();
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial(CompositeShader));
    this.setTheme(document.documentElement.dataset.theme === 'dark', false);
    new MutationObserver(() => this.setTheme(document.documentElement.dataset.theme === 'dark'))
      .observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    this.quad.frustumCulled = false;
    this.postScene = new THREE.Scene(); this.postScene.add(this.quad);
    this.postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const u = this.quad.material.uniforms;
    u.tColor.value = this.rtColor.texture; u.tNormal.value = this.rtNormal.texture; u.tDepth.value = this.rtNormal.depthTexture;

    // 状态
    this.mode = 'hero';
    this.view = { pos: new THREE.Vector3(), look: new THREE.Vector3(), shift: 0 };
    this.presets = {
      hero: { pos: [13, 6.4, 31], look: [0.4, 3.9, 0], shift: -0.19, fov: 27 },
      heroNarrow: { pos: [9, 6.5, 44], look: [-0.6, 3.6, 0], shift: 0, fov: 30 },
      owl: { pos: [1.6, 5.2, 19.5], look: [-3.6, 2.5, 3.1], shift: 0, fov: 26 },
    };
    this.target = 'hero';
    this.applyPreset(this.presets.hero, 1);
    this.mouse = new THREE.Vector2(0, 0); this.mouseS = new THREE.Vector2(0, 0);
    this.scroll = 0; this.state = 'idle'; this.t = 0; this.nextBlink = 2; this.blink = 0;
    this.hop = 0; this.visible = true;
    this.mood = 'wait'; this.moodT = 0; this.pose = { wing: 0, squint: 0, bob: 0 };
    addEventListener('pointermove', (e) => { this.mouse.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight * 2 - 1)); });
    this.clock = new THREE.Clock();
    this.ro = new ResizeObserver(() => this.resize());
    const io = new IntersectionObserver((es) => { this.visible = es[0].isIntersecting; if (this.visible) this.kick(); });
    io.observe(this.canvas);
    document.addEventListener('visibilitychange', () => this.kick());
    this.running = false;
  }
  applyPreset(p, k) {
    const v = this.view;
    v.pos.lerp(new THREE.Vector3(...p.pos), k); v.look.lerp(new THREE.Vector3(...p.look), k);
    v.shift += (p.shift - v.shift) * k; this.camera.fov += (p.fov - this.camera.fov) * k;
  }
  mount(el, mode) {
    if (!this.ok) return;
    this.mode = mode; el.appendChild(this.canvas); this.ro.disconnect(); this.ro.observe(el); this.resize();
    this.target = mode === 'owl' ? 'owl' : (el.clientWidth < 860 ? 'heroNarrow' : 'hero');
    if (this.reduced) this.applyPreset(this.presets[this.target], 1);
    this.kick();
  }
  resize() {
    const el = this.canvas.parentElement; if (!el) return;
    const w = Math.max(2, el.clientWidth), h = Math.max(2, el.clientHeight);
    const dpr = Math.min(devicePixelRatio || 1, 1.75);
    this.renderer.setPixelRatio(dpr); this.renderer.setSize(w, h, false);
    this.canvas.style.width = w + 'px'; this.canvas.style.height = h + 'px';
    const W = Math.floor(w * dpr), H = Math.floor(h * dpr);
    this.rtColor.setSize(W, H); this.rtNormal.setSize(W, H);
    const u = this.quad.material.uniforms;
    u.uRes.value.set(W, H); u.uPx.value = Math.max(1.2, 1.15 * dpr); u.uCell.value = 6.5 * dpr;
    this.camera.aspect = w / h;
    if (this.mode !== 'owl') this.target = w < 860 ? 'heroNarrow' : 'hero';
    this.w = w; this.h = h; this.kick();
  }
  setTheme(dark, redraw = true) {
    const t = THEME[dark ? 'dark' : 'light'];
    for (const k of ['stone', 'stone2', 'door', 'cream', 'white', 'bookB', 'bookC']) M[k].color.set(t[k]);
    HULL.color.set(t.ink);
    this.amb.color.set(t.sky); this.amb.groundColor.set(t.gnd); this.amb.intensity = t.amb;
    this.sun.intensity = t.sun;
    this.ground.material.color.set(t.shadow); this.ground.material.opacity = t.shadowA;
    this.disc.material.color.set(t.disc);
    if (this.quad) {
      const u = this.quad.material.uniforms;
      u.uInk.value = hexV(t.ink); u.uPaper.value = hexV(t.paper);
    }
    if (redraw) this.kick();
  }

  setOrder(order) {
    if (!this.ok || order === this.order) return;
    this.order = order;
    const old = this.temple; const neu = buildTemple(order);
    this.scene.add(neu); this.temple = neu;
    const t0 = performance.now(), dur = this.reduced ? 1 : 520;
    neu.position.y = -0.6; neu.scale.y = 0.96;
    const step = () => {
      const k = Math.min(1, (performance.now() - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      neu.position.y = -0.6 * (1 - e); neu.scale.y = 0.96 + 0.04 * e;
      old.visible = k < 0.5;
      if (k < 1) requestAnimationFrame(step); else { this.scene.remove(old); old.traverse(o => o.geometry && o.geometry.dispose()); }
      this.kick();
    };
    step();
    this.setMood('hint');   // 换柱式：小雅点一下头（不再跳，跳留给「解出」）
    clearTimeout(this._moodBack); this._moodBack = setTimeout(() => this.mood === 'hint' && this.setMood('wait'), 1200);
  }
  setState(s) { this.setMood(s === 'think' ? 'think' : 'wait'); }
  /* 情绪状态机（只动骨骼：头的转向 / 点头 / 歪头、眼睛眯起与眨眼、翅膀、身体起伏；不碰材质与描边）
     wait 等待 · listen 倾听 · think 思考 · hint 提示 · encourage 鼓励 · celebrate 庆祝 */
  setMood(m) {
    if (!m || m === this.mood) return;
    this.mood = m; this.moodT = 0; this.state = m === 'think' ? 'think' : 'idle';
    if (m === 'celebrate') this.hop = 1;
    if (m === 'listen' || m === 'hint') this.blink = 1;   // 换神情时眨一下眼
    this.kick();
  }
  cheer() { this.hop = 1; this.kick(); }
  setScroll(p) { this.scroll = p; this.kick(); }
  kick() { if (!this.running && this.ok) { this.running = true; this.clock.getDelta(); requestAnimationFrame(() => this.loop()); } }
  loop() {
    if (!this.visible || document.hidden) { this.running = false; return; }
    const dt = Math.min(0.05, this.clock.getDelta());
    this.update(dt); this.render();
    const idle = this.reduced && this.hop <= 0 && this.moodT > 0.1 && Math.abs(this.mouseS.x - this.mouse.x) < 0.002;
    if (idle) { this.running = false; return; }
    requestAnimationFrame(() => this.loop());
  }
  update(dt) {
    this.t += dt; const t = this.t; const rm = this.reduced;
    this.applyPreset(this.presets[this.target], rm ? 1 : 1 - Math.pow(0.02, dt));
    this.mouseS.lerp(this.mouse, rm ? 1 : 1 - Math.pow(0.004, dt));
    const { head, eyes, wings, body, laurel } = this.owl.userData;
    this.moodT += dt; const md = this.mood, mt = this.moodT;
    const think = md === 'think';
    const wave = rm ? 0 : 1;                           // 降级：去掉一切周期摆动，只留静止姿态
    // 默认（等待 / 庆祝）：头跟着鼠标
    let tx = this.mouseS.x * 0.55, ty = -this.mouseS.y * 0.3, tz = 0;
    let px = this.mouseS.x * 0.06, py = this.mouseS.y * 0.05, wing = 0, squint = 0, bob = 0;
    if (md === 'listen') {            // 倾听：转向左边的对话区，微微歪头，眼睛看过去
      tx = -0.42; ty = 0.1; tz = 0.1; px = -0.05; py = -0.01;
    } else if (think) {               // 思考：左右慢慢歪头，眼珠往上找
      tx = Math.sin(t * 1.6) * 0.35 * wave; ty = 0.25; tz = Math.sin(t * 1.6) * 0.18 * wave;
      px = Math.sin(t * 2.4) * 0.05 * wave; py = 0.07; wing = Math.sin(t * 3) * 0.06 * wave;
    } else if (md === 'hint') {       // 提示：面向学生，一下一下点头；开头抬一下翅膀像在指
      const nod = Math.pow(Math.max(0, Math.sin(mt * 4.4)), 3) * 0.28 * wave;
      tx = -0.2; ty = 0.06 + nod / 0.6; px = -0.03; py = 0;
      wing = 0.32 * Math.min(1, mt / 0.22) * Math.max(0, 1 - Math.max(0, mt - 0.5) / 0.6);
    } else if (md === 'encourage') {  // 鼓励：歪头、眯眼笑、轻轻颠两下
      tx = -0.15; ty = -0.08; tz = 0.16; squint = mt < 1.4 ? 1 : 0;
      bob = mt < 1.2 ? Math.abs(Math.sin(mt * 5.2)) * 0.05 * wave : 0;
    } else if (md === 'celebrate') {  // 庆祝：跳 + 拍翅（hop），眯眼
      squint = this.hop > 0 ? 1 : 0;
    }
    const k = rm ? 1 : 1 - Math.pow(0.0005, dt);       // 帧率无关的跟随
    head.rotation.y += (tx - head.rotation.y) * k;
    head.rotation.x += (Math.max(-0.35, Math.min(0.25, ty)) * 0.6 - head.rotation.x) * k;
    head.rotation.z += (tz - head.rotation.z) * (rm ? 1 : 1 - Math.pow(0.002, dt));
    for (const { pupil } of eyes) {
      pupil.position.x += (px - pupil.position.x) * k; pupil.position.y += (py - pupil.position.y) * k;
    }
    const P = this.pose; const kp = rm ? 1 : 1 - Math.pow(0.001, dt);
    P.wing += (wing - P.wing) * kp; P.squint += (squint - P.squint) * kp; P.bob += (bob - P.bob) * (rm ? 1 : 0.5);
    // 眨眼
    if (!rm) {
      if (t > this.nextBlink) { this.blink = 1; this.nextBlink = t + 2.2 + Math.random() * 3.2; }
      this.blink = Math.max(0, this.blink - dt * 7);
    }
    const bs = 1 - Math.sin(this.blink * Math.PI) * 0.92;
    for (const { eye } of eyes) eye.scale.y = bs * (1 - P.squint * 0.42);
    // 呼吸、跳跃、拍翅
    const breath = rm ? 0 : Math.sin(t * 2.1) * 0.012;
    body.scale.set(1 - breath * 0.5, 1 + breath, 1 - breath * 0.5);
    if (this.hop > 0) this.hop = Math.max(0, this.hop - dt * 1.6);
    const hopY = Math.sin((1 - this.hop) * Math.PI) * (this.hop > 0 ? 0.42 : 0);
    body.position.y = 0.7 + hopY + P.bob;
    const flap = this.hop > 0 ? Math.sin(t * 26) * 0.5 : 0;
    wings[0].rotation.z = -Math.abs(flap) - (think ? Math.abs(P.wing) : 0); wings[1].rotation.z = Math.abs(flap) + Math.abs(P.wing);
    laurel.rotation.z = Math.sin(t * 1.3) * (rm ? 0 : 0.03);
    // 相机：鼠标视差 + 滚动推近
    const s = this.mode === 'hero' ? this.scroll : 0;
    const v = this.view;
    const pos = v.pos.clone();
    pos.x += this.mouseS.x * 0.8 - s * 3.0; pos.y += this.mouseS.y * 0.4 + s * 1.0; pos.z -= s * 4.0;
    this.camera.position.copy(pos); this.camera.lookAt(v.look.x - s * 0.4, v.look.y - s * 0.2, v.look.z);
    this.camera.setViewOffset(this.w, this.h, v.shift * this.w * (1 - s * 0.3), 0, this.w, this.h);
    this.camera.updateProjectionMatrix();
    const u = this.quad.material.uniforms;
    const ss = (a, b, x) => { const k = Math.min(1, Math.max(0, (x - a) / (b - a))); return k * k * (3 - 2 * k); };
    u.uHalf.value = ss(0.12, 0.45, s); u.uEtch.value = ss(0.55, 0.9, s);
  }
  render() {
    const r = this.renderer, u = this.quad.material.uniforms;
    u.uNear.value = this.camera.near; u.uFar.value = this.camera.far;
    { const oz = this.camera.position.distanceTo(this.owl.position); u.uRefZ.value = oz * 1.05; u.uFadeA.value = oz * 1.35; u.uFadeB.value = oz * 2.1; }
    r.setRenderTarget(this.rtColor); r.setClearColor(0x000000, 0); r.clear(); r.render(this.scene, this.camera);
    this.camera.layers.disable(1);
    this.scene.overrideMaterial = this.normalMat;
    r.setRenderTarget(this.rtNormal); r.setClearColor(0x000000, 0); r.clear(); r.render(this.scene, this.camera);
    this.scene.overrideMaterial = null; this.camera.layers.enable(1);
    r.setRenderTarget(null); r.setClearColor(0x000000, 0); r.clear(); r.render(this.postScene, this.postCam);
  }
  // 猫头鹰在屏幕上的包围盒（给「选中对象」手柄用）
  owlRect() {
    if (!this.ok || !this.w) return null;
    const box = new THREE.Box3().setFromObject(this.owl.userData.body);
    const pts = [];
    for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) pts.push(new THREE.Vector3(x, y, z).project(this.camera));
    const xs = pts.map(p => (p.x + 1) / 2 * this.w), ys = pts.map(p => (1 - p.y) / 2 * this.h);
    return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  }
}
