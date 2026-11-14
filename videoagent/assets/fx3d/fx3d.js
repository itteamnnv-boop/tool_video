// Hiệu ứng 3D (three.js) cho khối ✨ Edit Pro — app/pipeline/fx3d.py mở trang này bằng Chromium headless, gọi
// __fx.setup(spec) rồi __fx.seek(giây) từng khung và chụp nền trong suốt để ghép đè lên video.
// Mọi chuyển động tính từ thời gian t (không dùng đồng hồ thật) → kết quả giống nhau mỗi lần, không phụ thuộc tốc độ máy.
import * as THREE from './three.module.min.js';

const W = innerWidth, H = innerHeight;
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(W, H);
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const VIEW_H = 10;                       // khung hình cao 10 đơn vị tại z = 0
const VIEW_W = VIEW_H * W / H;
const camera = new THREE.PerspectiveCamera(40, W / H, 0.1, 100);
camera.position.z = VIEW_H / 2 / Math.tan(THREE.MathUtils.degToRad(20));
const POS = { top: 2.7, center: 0, bottom: -2.6, low: -3.1 };

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const easeOut = x => 1 - Math.pow(1 - clamp(x), 3);
const easeIn = x => Math.pow(clamp(x), 3);
const easeBack = x => { x = clamp(x); const c = 1.70158; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
// vào (0 → 1) trong a giây đầu, ra (1 → 0) trong b giây cuối
const envelope = (t, dur, a = 0.6, b = 0.5) => ({ i: easeOut(t / a), o: 1 - easeIn((t - (dur - b)) / b) });
function rng(seed) {  // mulberry32 — ngẫu nhiên cố định theo seed
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let r = Math.imul(seed ^ seed >>> 15, 1 | seed);
    r = r + Math.imul(r ^ r >>> 7, 61 | r) ^ r; return ((r ^ r >>> 14) >>> 0) / 4294967296; };
}

function loadTex(url) {
  return new Promise((res, rej) => new THREE.TextureLoader().load(url, tex => {
    tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8; res(tex);
  }, undefined, () => rej(new Error('Không tải được ảnh ' + url))));
}

function cover(tex, aspect = 1) {  // ảnh phủ kín mặt vuông/chữ nhật (cắt bớt mép, không méo)
  const ia = tex.image.width / tex.image.height / aspect;
  if (ia > 1) { tex.repeat.set(1 / ia, 1); tex.offset.set((1 - 1 / ia) / 2, 0); }
  else { tex.repeat.set(1, ia); tex.offset.set(0, (1 - ia) / 2); }
  return tex;
}

function wrap(ctx, text, maxW) {
  const lines = []; let line = '';
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const test = line ? line + ' ' + word : word;
    if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = word; } else line = test;
  }
  if (line) lines.push(line);
  return lines.slice(0, 3);
}

// tấm chữ: nền lụa tối theo theme, viền + chữ màu nhấn (tiếng Việt vẽ bằng font hệ thống → đủ dấu).
// srgb = dùng cho vật liệu có sẵn của three (MeshBasic…); ShaderMaterial tự vẽ thì để thô (đúng màu canvas).
function textPlate(text, c, srgb = false) {
  const cv = document.createElement('canvas'), ctx = cv.getContext('2d');
  const font = '800 84px "Segoe UI", "Be Vietnam Pro", Arial, sans-serif', pad = 64, lh = 104, w = 1000;
  ctx.font = font;
  const lines = wrap(ctx, text, w - pad * 2);
  cv.width = w; cv.height = lines.length * lh + pad * 2;
  const g = ctx.createLinearGradient(0, 0, w, cv.height);
  g.addColorStop(0, c.light); g.addColorStop(1, c.base);
  ctx.fillStyle = g; ctx.beginPath(); ctx.roundRect(6, 6, w - 12, cv.height - 12, 44); ctx.fill();
  ctx.lineWidth = 8; ctx.strokeStyle = c.accent; ctx.stroke();
  ctx.font = font; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.shadowColor = c.accent; ctx.shadowBlur = 22; ctx.fillStyle = c.accent;
  lines.forEach((l, k) => ctx.fillText(l, w / 2, pad + lh * (k + 0.5)));
  const tex = new THREE.CanvasTexture(cv);
  tex.anisotropy = 8;
  if (srgb) tex.colorSpace = THREE.SRGBColorSpace;
  return { tex, aspect: cv.height / cv.width };
}

function dotTexture() {
  const cv = document.createElement('canvas'); cv.width = cv.height = 64;
  const ctx = cv.getContext('2d'), g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.35, 'rgba(255,255,255,0.75)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(cv);
}

function fade(obj, a) {  // mờ dần cả nhóm (giữ độ trong gốc của từng vật liệu)
  obj.traverse(o => [].concat(o.material || []).forEach(m => {
    if (m.userData.base === undefined) m.userData.base = m.opacity;
    m.transparent = true; m.opacity = m.userData.base * a;
    if (m.uniforms && m.uniforms.opacity) m.uniforms.opacity.value = a;
  }));
}

function metal(c) { return new THREE.MeshStandardMaterial({ color: c.accent, metalness: 0.85, roughness: 0.28 }); }

function sweepMaterial(tex) {  // mặt trước có vệt sáng quét chéo
  return new THREE.ShaderMaterial({
    transparent: true,
    uniforms: { map: { value: tex }, sweep: { value: -1 }, opacity: { value: 1 } },
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: `uniform sampler2D map; uniform float sweep; uniform float opacity; varying vec2 vUv;
      void main(){ vec4 c = texture2D(map, vUv);
        float band = exp(-pow((vUv.x + vUv.y * 0.35 - sweep) * 7.0, 2.0)) * 0.5 * c.a;
        gl_FragColor = vec4(min(c.rgb + band, 1.0), c.a * opacity); }`,
  });
}

const FX = {
  // chữ trên thẻ 3D xoay vào + vệt sáng quét
  async title_3d(spec, root, c) {
    const { tex, aspect } = textPlate(spec.text || '', c);
    const w = VIEW_W * 0.86, h = w * aspect, side = metal(c);
    const front = sweepMaterial(tex);
    const back = new THREE.MeshBasicMaterial({ color: c.base });
    const box = new THREE.Mesh(new THREE.BoxGeometry(w, h, 0.18), [side, side, side, side, front, back]);
    root.add(box);
    return t => {
      const e = envelope(t, spec.dur);
      box.rotation.y = (1 - easeBack(t / 0.9)) * -Math.PI / 2 + Math.sin(t * 0.9) * 0.06 * e.i;
      box.rotation.x = Math.sin(t * 1.3) * 0.05;
      box.scale.setScalar((0.7 + 0.3 * e.i) * (0.85 + 0.15 * e.o));
      box.position.y = (1 - e.o) * 0.6;
      front.uniforms.sweep.value = -0.5 + clamp((t - 0.6) / 1.2) * 2.3;
      fade(root, Math.min(e.i, e.o));
    };
  },

  // ảnh lật 3D rồi lắc nhẹ
  async card_flip(spec, root, c) {
    const tex = await loadTex(spec.images[0]);
    let w = VIEW_W * 0.72, h = w * tex.image.height / tex.image.width;
    if (h > VIEW_H * 0.55) { w *= VIEW_H * 0.55 / h; h = VIEW_H * 0.55; }
    const side = metal(c), back = new THREE.MeshStandardMaterial({ color: c.base, metalness: 0.4, roughness: 0.5 });
    const card = new THREE.Group();
    card.add(new THREE.Mesh(new THREE.BoxGeometry(w + 0.16, h + 0.16, 0.06), side));
    const face = new THREE.Mesh(new THREE.BoxGeometry(w, h, 0.1),
      [side, side, side, side, new THREE.MeshBasicMaterial({ map: tex }), back]);
    card.add(face);
    root.add(card);
    if (spec.text) {
      const p = textPlate(spec.text, c, true), pw = VIEW_W * 0.7;
      const cap = new THREE.Mesh(new THREE.PlaneGeometry(pw, pw * p.aspect), new THREE.MeshBasicMaterial({ map: p.tex, transparent: true }));
      cap.position.set(0, -h / 2 - pw * p.aspect / 2 - 0.25, 0.1);
      card.add(cap);
    }
    return t => {
      const e = envelope(t, spec.dur);
      card.rotation.y = Math.PI * (1 - easeBack(t / 1.0)) + Math.sin(t * 1.1) * 0.08 * e.i;
      card.rotation.x = Math.sin(t * 0.8) * 0.05 - (1 - e.i) * 0.3;
      card.scale.setScalar(0.8 + 0.2 * e.i);
      fade(root, Math.min(e.i, e.o));
    };
  },

  // khối lập phương xoay, mỗi mặt 1 ảnh
  async cube(spec, root, c) {
    const texs = await Promise.all(spec.images.map(loadTex));
    const s = VIEW_W * 0.5;
    const mats = [0, 1, 2, 3, 4, 5].map(k => new THREE.MeshBasicMaterial({ map: cover(texs[k % texs.length].clone()) }));
    mats.forEach(m => { m.map.needsUpdate = true; });
    const cube = new THREE.Mesh(new THREE.BoxGeometry(s, s, s), mats);
    cube.add(new THREE.LineSegments(new THREE.EdgesGeometry(cube.geometry), new THREE.LineBasicMaterial({ color: c.accent })));
    root.add(cube);
    return t => {
      const e = envelope(t, spec.dur);
      cube.scale.setScalar(0.3 + 0.7 * easeBack(t / 0.8));
      cube.rotation.y = -0.6 + t * 1.5;
      cube.rotation.x = 0.35 + Math.sin(t * 0.9) * 0.15;
      fade(root, Math.min(e.i, e.o));
    };
  },

  // sản phẩm xoay nghiêng trên vòng sáng, có bóng phản chiếu
  async product_spin(spec, root, c) {
    const tex = await loadTex(spec.images[0]);
    let w = VIEW_W * 0.62, h = w * tex.image.height / tex.image.width;
    if (h > VIEW_H * 0.45) { w *= VIEW_H * 0.45 / h; h = VIEW_H * 0.45; }
    const geo = new THREE.PlaneGeometry(w, h);
    const item = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide }));
    const gcv = document.createElement('canvas'); gcv.width = 4; gcv.height = 128;
    const gctx = gcv.getContext('2d'), gg = gctx.createLinearGradient(0, 0, 0, 128);
    gg.addColorStop(0, '#000'); gg.addColorStop(1, '#fff');
    gctx.fillStyle = gg; gctx.fillRect(0, 0, 4, 128);
    const mirror = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, alphaMap: new THREE.CanvasTexture(gcv),
      transparent: true, opacity: 0.3, side: THREE.DoubleSide }));
    mirror.scale.y = -1; mirror.position.y = -h - 0.04;
    const ring = new THREE.Mesh(new THREE.RingGeometry(w * 0.42, w * 0.5, 96),
      new THREE.MeshBasicMaterial({ color: c.accent, transparent: true, opacity: 0.75, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2.3; ring.position.y = -h / 2;
    const spin = new THREE.Group(); spin.add(item, mirror);
    root.add(ring, spin);
    return t => {
      const e = envelope(t, spec.dur, 0.8);
      spin.rotation.y = Math.sin(t * 1.2) * 0.45 * e.i + (1 - e.i) * 1.2;
      spin.position.y = (1 - easeBack(t / 0.9)) * -2 + Math.sin(t * 1.6) * 0.06;
      ring.scale.setScalar(0.5 + 0.5 * e.i + Math.sin(t * 2) * 0.03);
      ring.rotation.z = t * 0.8;
      fade(root, Math.min(e.i, e.o));
    };
  },

  // hạt sáng bung ra từ tâm rồi rơi nhẹ
  async particles(spec, root, c) {
    const n = 700, rand = rng(7), pos = new Float32Array(n * 3), vel = [], col = new Float32Array(n * 3), phase = [];
    const tint = [new THREE.Color(c.accent), new THREE.Color('#ffffff'), new THREE.Color(c.accent).lerp(new THREE.Color('#ffffff'), 0.5)];
    for (let k = 0; k < n; k++) {
      const th = rand() * Math.PI * 2, ph = Math.acos(2 * rand() - 1), sp = 3 + rand() * 6;
      vel.push(new THREE.Vector3(Math.sin(ph) * Math.cos(th), Math.sin(ph) * Math.sin(th) * 1.3, Math.cos(ph) * 0.5).multiplyScalar(sp));
      tint[k % 3].toArray(col, k * 3); phase.push(rand() * 6.28);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const mat = new THREE.PointsMaterial({ size: 0.16, map: dotTexture(), vertexColors: true, transparent: true, depthWrite: false });
    root.add(new THREE.Points(geo, mat));
    return t => {
      const e = envelope(t, spec.dur, 0.15, 0.9), k = 1.6, d = (1 - Math.exp(-k * t)) / k;
      for (let i = 0; i < n; i++) {
        const v = vel[i];
        pos[i * 3] = v.x * d + Math.sin(t * 2 + phase[i]) * 0.05;
        pos[i * 3 + 1] = v.y * d - 0.9 * t * t;
        pos[i * 3 + 2] = v.z * d;
      }
      geo.attributes.position.needsUpdate = true;
      mat.size = 0.16 * (0.8 + 0.4 * Math.abs(Math.sin(t * 6)));
      fade(root, Math.min(e.i, e.o));
    };
  },

  // vòng sáng 3D xoay quanh (có chữ ở giữa nếu có)
  async rings(spec, root, c) {
    const rs = [1.7, 2.05, 2.4].map((r, k) => {
      const m = new THREE.Mesh(new THREE.TorusGeometry(r, 0.04, 16, 160),
        new THREE.MeshStandardMaterial({ color: c.accent, emissive: c.accent, emissiveIntensity: 0.6, metalness: 0.6, roughness: 0.3 }));
      m.rotation.x = 1.1 + k * 0.35; root.add(m); return m;
    });
    let plate = null;
    if (spec.text) {
      const p = textPlate(spec.text, c, true), pw = VIEW_W * 0.62;
      plate = new THREE.Mesh(new THREE.PlaneGeometry(pw, pw * p.aspect),
        new THREE.MeshBasicMaterial({ map: p.tex, transparent: true, depthTest: false }));
      plate.renderOrder = 10;  // chữ luôn nằm trên các vòng sáng
      root.add(plate);
    }
    return t => {
      const e = envelope(t, spec.dur);
      rs.forEach((m, k) => {
        m.rotation.y = t * (0.9 + k * 0.4) * (k % 2 ? -1 : 1);
        m.rotation.z = t * 0.3 * (k + 1);
        m.scale.setScalar(0.2 + 0.8 * easeBack((t - k * 0.12) / 0.8));
      });
      if (plate) plate.scale.setScalar(0.6 + 0.4 * easeBack((t - 0.2) / 0.7));
      fade(root, Math.min(e.i, e.o));
    };
  },
};

let scene = null, update = () => {};

window.__fx = {
  types: Object.keys(FX),
  async setup(spec) {
    scene = new THREE.Scene();
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(3, 4, 6); scene.add(sun);
    const glow = new THREE.PointLight(spec.colors.accent, 30, 30); glow.position.set(-3, -2, 5); scene.add(glow);
    const root = new THREE.Group();
    root.position.y = POS[spec.pos] ?? 0;
    scene.add(root);
    update = await FX[spec.type](spec, root, spec.colors);
    return true;
  },
  seek(t) { update(t); renderer.render(scene, camera); },
};
window.__fxReady = true;
