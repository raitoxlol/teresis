import * as T from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';

// A clothbound ledger in book space: the spine runs along y at x = 0, pages
// lie in +x (right) or -x (left), and +z is up off the table. The book group
// is laid flat in a y-up world and framed by a camera above the reader.

const BASE = import.meta.env.BASE_URL;
export const LAST = 8;
const W = 1.4;
const H = 2;
const BW = W + .07;
const BH = H + .1;
const BOARD = .045;
const LEAVES = 7;
const BLOCK = .2;
const SHEET = BLOCK / LEAVES;
const LIFT = .0035;
const COLS = 48;
const ROWS = 10;
const PROFILE = COLS;
const FOV = 24;

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const smooth = (t: number) => t * t * (3 - 2 * t);
const ease = (a: number, b: number, v: number) => smooth(clamp01((v - a) / (b - a)));
const sine = (t: number) => .5 - .5 * Math.cos(Math.PI * clamp01(t));
const mix = T.MathUtils.lerp;
const deg = T.MathUtils.degToRad;

export type PageSurface = {title: string; endpaper?: boolean; print?: string; variants?: string[]};
export type ViewState = {p: number; focus: number};
export type Picked = {page: number; u: number; v: number};

// Height of the top of a stack `depth` thick at distance x from the spine.
// `open` shapes the gutter: 0 is a closed block, 1 an open book whose pages
// rise out of the binding and bow before they settle.
function surface(x: number, depth: number, open: number) {
  const rise = 1 - (1 - clamp01(x / (.16 * W))) ** 3;
  const a = .1 * W;
  const bow = .034 * Math.min(1, depth / (2 * SHEET)) * (x / a) * Math.exp(1 - x / a);
  return depth * mix(1, rise, open) + bow * open;
}

function canvasTexture(width: number, height: number, draw: (ctx: CanvasRenderingContext2D) => void) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  draw(canvas.getContext('2d')!);
  return new T.CanvasTexture(canvas);
}

// Head, tail and fore edge of a page stack; the top is drawn by its sheet.
function stackGeometry() {
  const count = 2 * 2 * (PROFILE + 1) + 4;
  const geometry = new T.BufferGeometry();
  geometry.setAttribute('position', new T.BufferAttribute(new Float32Array(count * 3), 3).setUsage(T.DynamicDrawUsage));
  geometry.setAttribute('normal', new T.BufferAttribute(new Float32Array(count * 3), 3));
  geometry.setAttribute('uv', new T.BufferAttribute(new Float32Array(count * 2), 2).setUsage(T.DynamicDrawUsage));
  const index: number[] = [];
  for (let cap = 0; cap < 2; cap++) {
    const base = cap * 2 * (PROFILE + 1);
    for (let i = 0; i < PROFILE; i++) {
      const b0 = base + 2 * i;
      index.push(b0, b0 + 2, b0 + 1, b0 + 1, b0 + 2, b0 + 3);
    }
  }
  const fore = 4 * (PROFILE + 1);
  index.push(fore, fore + 1, fore + 2, fore + 2, fore + 1, fore + 3);
  geometry.setIndex(index);
  return geometry;
}

function shapeStack(geometry: T.BufferGeometry, side: number, depth: number, open: number) {
  const position = geometry.getAttribute('position') as T.BufferAttribute;
  const normal = geometry.getAttribute('normal') as T.BufferAttribute;
  const uv = geometry.getAttribute('uv') as T.BufferAttribute;
  let n = 0;
  for (const y of [H / 2, -H / 2]) {
    for (let i = 0; i <= PROFILE; i++) {
      const x = i / PROFILE * W;
      const top = surface(x, depth, open);
      for (const z of [0, top]) {
        position.setXYZ(n, side * x, y, z);
        normal.setXYZ(n, 0, Math.sign(y), 0);
        uv.setXY(n, x / W, z / BLOCK);
        n++;
      }
    }
  }
  const foreTop = surface(W, depth, open);
  for (const y of [H / 2, -H / 2]) {
    for (const z of [0, foreTop]) {
      position.setXYZ(n, side * W, y, z);
      normal.setXYZ(n, side, 0, 0);
      uv.setXY(n, (y + H / 2) / H * 2.2, z / BLOCK);
      n++;
    }
  }
  position.needsUpdate = normal.needsUpdate = uv.needsUpdate = true;
  geometry.computeBoundingSphere();
}

// A page lying on top of a stack.
function shapeSheet(geometry: T.BufferGeometry, side: number, depth: number, open: number) {
  const position = geometry.getAttribute('position') as T.BufferAttribute;
  for (let i = 0; i < position.count; i++) {
    const column = i % (PROFILE + 1);
    const u = column / PROFILE;
    const x = side > 0 ? u * W : -W + u * W;
    position.setX(i, x);
    position.setZ(i, surface(Math.abs(x), depth, open) + LIFT);
  }
  position.needsUpdate = true;
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
}

export function createScene(canvas: HTMLCanvasElement, context: WebGL2RenderingContext, pages: PageSurface[], invalidate: () => void) {
  const renderer = new T.WebGLRenderer({canvas, context, alpha: true, antialias: true});
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = T.PCFShadowMap;
  let shaderFailed = false;
  renderer.debug.onShaderError = () => { shaderFailed = true; };

  const scene = new T.Scene();
  const camera = new T.PerspectiveCamera(FOV, 1, .1, 60);
  const holder = new T.Group();
  const book = new T.Group();
  book.rotation.x = -Math.PI / 2;
  holder.add(book);
  scene.add(holder);

  scene.add(new T.HemisphereLight(0xfff6e8, 0x29473a, 1.75));
  const key = new T.DirectionalLight(0xfff0da, 2.15);
  key.position.set(-2.4, 5.2, 2.2);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, {left: -2.8, right: 2.8, top: 2.8, bottom: -2.8, near: .5, far: 14});
  key.shadow.bias = -.0005;
  key.shadow.normalBias = .02;
  key.shadow.radius = 5;
  scene.add(key);

  const geometries: T.BufferGeometry[] = [];
  const materials: T.Material[] = [];
  const textures = new Set<T.Texture>();
  const requests = new AbortController();
  let disposed = false;

  function mesh<G extends T.BufferGeometry, M extends T.Material | T.Material[]>(geometry: G, material: M, parent: T.Object3D, shadows = true) {
    geometries.push(geometry);
    const result = new T.Mesh(geometry, material);
    result.castShadow = result.receiveShadow = shadows;
    parent.add(result);
    return result;
  }
  function keep<M extends T.Material>(material: M) {
    materials.push(material);
    return material;
  }
  function texture<X extends T.Texture>(tex: X, color = true) {
    tex.colorSpace = color ? T.SRGBColorSpace : T.NoColorSpace;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    textures.add(tex);
    return tex;
  }
  function release(tex?: T.Texture) {
    if (!tex) return;
    textures.delete(tex);
    tex.dispose();
  }

  // The table: only the shadows show over the page's own forest ground.
  const ground = mesh(new T.PlaneGeometry(40, 40), keep(new T.ShadowMaterial({color: 0x020d08, opacity: .38})), scene, false);
  ground.receiveShadow = true;
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -BOARD - .002;
  const blobMap = texture(canvasTexture(256, 256, (ctx) => {
    const gradient = ctx.createRadialGradient(128, 128, 30, 128, 128, 127);
    gradient.addColorStop(0, 'rgba(2, 12, 8, .75)');
    gradient.addColorStop(.55, 'rgba(2, 12, 8, .32)');
    gradient.addColorStop(1, 'rgba(2, 12, 8, 0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 256, 256);
  }));
  const blob = mesh(new T.PlaneGeometry(1, 1), keep(new T.MeshBasicMaterial({map: blobMap, transparent: true, depthWrite: false})), book, false);
  blob.position.z = -BOARD - .001;
  blob.renderOrder = -1;

  // Materials
  const cloth = keep(new T.MeshStandardMaterial({color: 0x1b3e31, roughness: .9, side: T.DoubleSide}));
  const edge = keep(new T.MeshStandardMaterial({color: 0xc9a466, roughness: .48, metalness: .38, side: T.DoubleSide}));
  const foil = keep(new T.MeshStandardMaterial({
    color: 0xffffff, roughness: .4, metalness: .62, transparent: true, alphaTest: .2,
    emissive: 0x6d5226, emissiveIntensity: .55, bumpScale: .013,
  }));
  const pageMaterial = () => keep(new T.MeshStandardMaterial({color: 0xffffff, roughness: .94}));

  // Boards and spine
  const cover = new T.Group();
  book.add(cover);
  const frontBoard = mesh(new RoundedBoxGeometry(BW, BH, BOARD, 3, .011), cloth, cover);
  frontBoard.position.set(BW / 2 - .004, 0, BOARD / 2);
  const stamp = mesh(new T.PlaneGeometry(BW, BH), foil, cover, false);
  stamp.position.set(BW / 2 - .004, 0, BOARD + .0012);
  stamp.visible = false;
  const coverInside = mesh(new T.PlaneGeometry(W, H), pageMaterial(), cover);
  coverInside.rotation.y = Math.PI;
  coverInside.position.set(W / 2 + .006, 0, -.0012);
  const backBoard = mesh(new RoundedBoxGeometry(BW, BH, BOARD, 3, .011), cloth, book);
  backBoard.position.set(BW / 2 - .004, 0, -BOARD / 2);
  const backInside = mesh(new T.PlaneGeometry(W, H), pageMaterial(), book);
  backInside.position.set(W / 2 + .006, 0, .0012);
  const spineRadius = (BLOCK + LIFT + 2 * BOARD) / 2;
  const spine = mesh(new T.CylinderGeometry(spineRadius, spineRadius, BH - .004, 28, 1, true, Math.PI, Math.PI), cloth, book);

  // Raised sewing supports follow the round back as the binding opens.
  for (const y of [-.76, -.52, .52, .76]) {
    const band = mesh(new T.CylinderGeometry(spineRadius + .014, spineRadius + .014, .042, 28, 1, false, Math.PI, Math.PI), cloth, spine);
    band.position.y = y;
  }

  // Page stacks and the pages lying on them
  const leftStack = mesh(stackGeometry(), edge, book);
  const rightStack = mesh(stackGeometry(), edge, book);
  const leftSheet = mesh(new T.PlaneGeometry(W, H, PROFILE, 1), pageMaterial(), book);
  const rightSheet = mesh(new T.PlaneGeometry(W, H, PROFILE, 1), pageMaterial(), book);
  const leaf = mesh(new T.PlaneGeometry(W, H, COLS, ROWS), pageMaterial(), book);
  const leafBack = mesh(new T.PlaneGeometry(W, H, COLS, ROWS), keep(new T.MeshStandardMaterial({color: 0xffffff, roughness: .94, side: T.BackSide})), book);
  for (const part of [leaf, leafBack]) {
    (part.geometry.getAttribute('position') as T.BufferAttribute).setUsage(T.DynamicDrawUsage);
    part.frustumCulled = false;
  }
  leafBack.geometry.setAttribute('position', leaf.geometry.getAttribute('position'));
  leafBack.geometry.setAttribute('normal', leaf.geometry.getAttribute('normal'));
  const backUv = leafBack.geometry.getAttribute('uv');
  for (let i = 0; i < backUv.count; i++) backUv.setX(i, 1 - backUv.getX(i));

  // Surfaces: cloth, gilt edges and paper come from the generated textures.
  let clothImage: HTMLImageElement | undefined;
  async function loadImage(src: string) {
    const response = await fetch(src, {signal: requests.signal});
    if (!response.ok) throw new Error(src);
    const url = URL.createObjectURL(await response.blob());
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
    } finally {
      URL.revokeObjectURL(url);
    }
    return image;
  }

  void loadImage(`${BASE}book/cloth.webp`).then((image) => {
    if (disposed) return;
    clothImage = image;
    const size = image.width;
    const worn = texture(canvasTexture(size, size, (ctx) => {
      ctx.drawImage(image, 0, 0, size, size);
      const pixels = ctx.getImageData(0, 0, size, size);
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          const dx = Math.min(x, size - 1 - x) / size;
          const dy = Math.min(y, size - 1 - y) / size;
          const i = (y * size + x) * 4;
          const grain = (Math.imul(i, 2971215073) >>> 16) / 65535;
          const thread = pixels.data[i + 1] - 56;
          const patch = .48 + .22 * Math.sin(x * .045 + y * .025) + .18 * Math.sin(x * .09 - y * .061);
          const corner = Math.max(dx, dy) < .09;
          const wear = Math.max(0, 1 - Math.min(dx, dy) / .03) ** 2 * grain * patch * (corner ? 1.9 : .8);
          pixels.data[i] = mix(27 + thread * .72, 182, wear);
          pixels.data[i + 1] = mix(50 + thread * .86, 146, wear);
          pixels.data[i + 2] = mix(40 + thread * .64, 80, wear);
        }
      }
      ctx.putImageData(pixels, 0, 0);
    }));
    const bump = texture(new T.Texture(image), false);
    bump.needsUpdate = true;
    cloth.color.set(0xffffff);
    cloth.map = worn;
    cloth.bumpMap = bump;
    cloth.bumpScale = .012;
    cloth.needsUpdate = true;
    for (const [index, source] of endpaperSources) setSnapshot(index, source);
    for (const index of [0, pages.length - 1]) if (pages[index]?.endpaper && !snapshots.has(index)) dropFallback(index);
    invalidate();
  }).catch(() => { /* The boards keep their cloth colour. */ });

  void loadImage(`${BASE}book/edge.webp`).then((image) => {
    if (disposed) return;
    const map = texture(new T.Texture(image));
    map.wrapS = T.RepeatWrapping;
    map.needsUpdate = true;
    edge.color.set(0xf4e2c0);
    edge.map = map;
    edge.needsUpdate = true;
    invalidate();
  }).catch(() => { /* Plain gilt edges. */ });

  let paperImage: HTMLImageElement | undefined;
  void loadImage(`${BASE}book/paper.webp`).then((image) => {
    if (disposed) return;
    paperImage = image;
    for (const index of [...fallbacks.keys()]) dropFallback(index);
    invalidate();
  }).catch(() => { /* Flat paper colour. */ });

  // The front board's gilt: a rim, the real lotus and the title.
  void (async () => {
    try {
      const mark = new Image();
      mark.src = `${BASE}logos/teresis-mark.svg`;
      await Promise.all([mark.decode(), document.fonts?.ready]);
      if (disposed) return;
      const w = 1024;
      const h = Math.round(w * BH / BW);
      const map = texture(canvasTexture(w, h, (ctx) => {
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 7;
        ctx.strokeRect(34, 34, w - 68, h - 68);
        ctx.lineWidth = 2.5;
        ctx.strokeRect(52, 52, w - 104, h - 104);
        // Compass-work quarter rosettes, struck into the four corners.
        for (const x of [54, w - 54]) for (const y of [54, h - 54]) {
          ctx.save();
          ctx.translate(x, y);
          ctx.scale(x > w / 2 ? -1 : 1, y > h / 2 ? -1 : 1);
          for (const radius of [80, 88, 101]) {
            ctx.beginPath();
            ctx.arc(0, 0, radius, 0, Math.PI / 2);
            ctx.stroke();
          }
          for (let i = 1; i < 8; i++) {
            ctx.save();
            ctx.rotate(i * Math.PI / 16);
            ctx.beginPath();
            ctx.ellipse(44, 0, 27, 6, 0, 0, 2 * Math.PI);
            ctx.stroke();
            ctx.restore();
          }
          ctx.restore();
        }
        const mw = 332;
        const mh = mw * 160.06 / 180.96;
        ctx.lineWidth = 2;
        for (const inset of [0, 9]) {
          ctx.beginPath();
          ctx.ellipse(w / 2, h * .2 + mh / 2, mw * .63 + inset, mh * .7 + inset, 0, 0, 2 * Math.PI);
          ctx.stroke();
        }
        ctx.drawImage(mark, (w - mw) / 2, h * .2, mw, mh);
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.font = '600 104px Cormorant, Georgia, serif';
        ctx.fillText('Tell your agents', w / 2, h * .2 + mh + 175);
        ctx.fillText('once', w / 2, h * .2 + mh + 290);
        ctx.font = '500 40px Allo, system-ui, sans-serif';
        ctx.letterSpacing = '14px';
        ctx.fillText('TERESIS', w / 2 + 7, h - 150);
        const pixels = ctx.getImageData(0, 0, w, h);
        for (let y = 0; y < h; y++) {
          for (let x = 0; x < w; x++) {
            const i = (y * w + x) * 4;
            if (!pixels.data[i + 3]) continue;
            const grain = (Math.imul(i, 2971215073) >>> 16) / 65535;
            const mottle = Math.sin(x * .04 + Math.cos(y * .027) * 2) * Math.sin(y * .033 + x * .015);
            const gold = 150 + 55 * grain + 30 * mottle;
            pixels.data[i] = gold;
            pixels.data[i + 1] = gold * .8;
            pixels.data[i + 2] = gold * .5;
            if (grain < .06 && mottle < -.2) pixels.data[i + 3] *= .35;
          }
        }
        ctx.putImageData(pixels, 0, 0);
      }));
      foil.map = map;
      foil.bumpMap = map;
      foil.needsUpdate = true;
      stamp.visible = true;
      invalidate();
    } catch {
      // The board stays plain cloth if the mark cannot load.
    }
  })();

  // Page faces: snapshots of the DOM pages, or paper with the page title.
  const snapshots = new Map<number, T.Texture>();
  const prints = new Map<string, T.Texture>();
  const activePrint = new Map<number, string>();
  const endpaperSources = new Map<number, HTMLCanvasElement | HTMLImageElement>();
  const fallbacks = new Map<number, T.Texture>();
  function backing(ctx: CanvasRenderingContext2D, index: number, width: number, height: number) {
    if (pages[index]?.endpaper) {
      ctx.fillStyle = '#173d2c';
      ctx.fillRect(0, 0, width, height);
      if (clothImage) {
        ctx.globalAlpha = .8;
        ctx.fillStyle = ctx.createPattern(clothImage, 'repeat')!;
        ctx.fillRect(0, 0, width, height);
        ctx.globalAlpha = 1;
      }
      return;
    }
    ctx.fillStyle = '#efe6cf';
    ctx.fillRect(0, 0, width, height);
    if (paperImage) ctx.drawImage(paperImage, 0, 0, width, height);
  }
  function dropFallback(index: number) {
    release(fallbacks.get(index));
    fallbacks.delete(index);
    for (const material of materials) {
      if ('map' in material && fallbackOwners.get(material) === index) {
        (material as T.MeshStandardMaterial).map = null;
        fallbackOwners.delete(material);
      }
    }
  }
  const fallbackOwners = new Map<T.Material, number>();
  function pageMap(index: number) {
    const ready = snapshots.get(index) ?? fallbacks.get(index);
    if (ready) return ready;
    const map = texture(canvasTexture(560, 800, (ctx) => {
      backing(ctx, index, 560, 800);
      if (pages[index]?.endpaper) return;
      ctx.fillStyle = '#123a2a';
      ctx.font = '54px Cormorant, Georgia, serif';
      ctx.fillText(pages[index]?.title ?? '', 40, 120, 480);
    }));
    fallbacks.set(index, map);
    return map;
  }
  function showPage(target: T.Mesh, index: number) {
    const material = target.material as T.MeshStandardMaterial;
    const map = pageMap(index);
    target.userData.page = index;
    if (!snapshots.has(index)) fallbackOwners.set(material, index);
    else fallbackOwners.delete(material);
    if (material.map === map) return;
    material.map = map;
    material.needsUpdate = true;
  }

  function setSnapshot(index: number, source: HTMLCanvasElement | HTMLImageElement) {
    let face = source;
    if (pages[index]?.endpaper) {
      endpaperSources.set(index, source);
      face = document.createElement('canvas');
      face.width = source.width;
      face.height = source.height;
      const ctx = face.getContext('2d')!;
      backing(ctx, index, face.width, face.height);
      ctx.drawImage(source, 0, 0);
    }
    const map = texture(new T.Texture(face));
    map.needsUpdate = true;
    renderer.initTexture(map);
    if (!activePrint.delete(index)) release(snapshots.get(index));
    snapshots.set(index, map);
    dropFallback(index);
  }

  // The turning leaf: each column is a short segment whose angle moves from
  // the right page's rest shape to the left page's, while the free edge
  // lags behind the root so the leaf rolls over in a C.
  const restRight = new Float32Array(COLS);
  const restLeft = new Float32Array(COLS);
  const rightLength = new Float32Array(COLS);
  const leftLength = new Float32Array(COLS);
  function bendLeaf(t: number, fromDepth: number, toDepth: number, open: number) {
    const step = W / COLS;
    for (let i = 0; i < COLS; i++) {
      const x0 = i * step;
      const x1 = x0 + step;
      const dr = surface(x1, fromDepth, open) - surface(x0, fromDepth, open);
      const dl = surface(x1, toDepth, open) - surface(x0, toDepth, open);
      restRight[i] = Math.atan2(dr, step);
      restLeft[i] = Math.PI - Math.atan2(dl, step);
      rightLength[i] = Math.hypot(step, dr);
      leftLength[i] = Math.hypot(step, dl);
    }
    const root = sine(t);
    const lag = .78 * Math.sin(Math.PI * clamp01(t)) ** .9;
    const front = leaf.geometry.getAttribute('position') as T.BufferAttribute;
    for (let row = 0; row <= ROWS; row++) {
      const v = row / ROWS;
      const y = H / 2 - v * H;
      // The lower corner leads, as if the page were lifted from there.
      const corner = 1 + .42 * (.5 - v);
      let x = 0;
      let z = LIFT;
      for (let column = 0; column <= COLS; column++) {
        const index = row * (COLS + 1) + column;
        front.setXYZ(index, x, y, z);
        if (column === COLS) break;
        const u = (column + .5) / COLS;
        let angle = mix(restRight[column], restLeft[column], root) - lag * corner * u ** 1.45;
        angle = Math.max(angle, restRight[column]);
        // Match the receiving stack exactly when the moving leaf becomes its top sheet.
        const length = mix(rightLength[column], leftLength[column], root);
        x += Math.cos(angle) * length;
        z += Math.sin(angle) * length;
      }
    }
    front.needsUpdate = true;
    leaf.geometry.computeVertexNormals();
  }

  // Camera framing
  let width = 1;
  let height = 1;
  let dpr = 0;
  function resize(w: number, h: number) {
    const nextDpr = Math.min(window.devicePixelRatio, 2);
    if (width === w && height === h && dpr === nextDpr) return;
    width = w;
    height = h;
    if (dpr !== nextDpr) {
      dpr = nextDpr;
      renderer.setPixelRatio(dpr);
    }
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  const corners = Array.from({length: 8}, () => new T.Vector3());
  const projected = new T.Vector3();
  const target = new T.Vector3();
  const right = new T.Vector3();
  const up = new T.Vector3();
  function frame(xMin: number, xMax: number, zMax: number, elevation: number) {
    holder.updateMatrixWorld(true);
    let n = 0;
    for (const x of [xMin, xMax]) for (const y of [-BH / 2, BH / 2]) for (const z of [-BOARD, zMax]) {
      corners[n++].set(x, y, z).applyMatrix4(book.matrixWorld);
    }
    target.set(0, 0, 0);
    for (const corner of corners) target.add(corner);
    target.multiplyScalar(1 / 8);
    const marginX = Math.max(8, width * .022) / width;
    const marginY = Math.max(12, height * .035) / height;
    const fitX = 1 - 2 * marginX;
    const fitY = 1 - 2 * marginY;
    const direction = new T.Vector3(0, Math.sin(elevation), Math.cos(elevation));
    let distance = 7;
    for (let pass = 0; pass < 7; pass++) {
      camera.position.copy(target).addScaledVector(direction, distance);
      camera.lookAt(target);
      camera.updateMatrixWorld();
      let minX = Infinity;
      let maxX = -Infinity;
      let minY = Infinity;
      let maxY = -Infinity;
      for (const corner of corners) {
        projected.copy(corner).project(camera);
        minX = Math.min(minX, projected.x);
        maxX = Math.max(maxX, projected.x);
        minY = Math.min(minY, projected.y);
        maxY = Math.max(maxY, projected.y);
      }
      const halfHeight = distance * Math.tan(deg(FOV / 2));
      right.setFromMatrixColumn(camera.matrixWorld, 0);
      up.setFromMatrixColumn(camera.matrixWorld, 1);
      target.addScaledVector(right, (maxX + minX) / 2 * halfHeight * camera.aspect);
      target.addScaledVector(up, (maxY + minY) / 2 * halfHeight);
      distance *= Math.max((maxX - minX) / 2 / fitX, (maxY - minY) / 2 / fitY);
    }
    camera.position.copy(target).addScaledVector(direction, distance);
    camera.lookAt(target);
    camera.updateMatrixWorld();
  }

  let stackKey = '';
  function render({p, focus}: ViewState) {
    p = Math.min(LAST, Math.max(0, p));
    const c = clamp01(p);
    const open = ease(.2, 1, c);
    const settle = ease(0, .9, c);
    const k = Math.min(LAST, Math.floor(p));
    const t = p - k;
    const turning = k >= 1 && k < LAST && t > 1e-4;
    const turned = p < 1 ? 0 : k - 1;
    const gone = p < 1 ? 0 : turning ? k : k - 1;
    const leftDepth = turned * SHEET;
    const rightDepth = (LEAVES - gone) * SHEET;

    // Closed, the book lies turned three-quarters toward the reader; opening
    // squares it up and centres the spine.
    holder.rotation.y = mix(.42, 0, settle);
    book.position.x = mix(-BW / 2, 0, settle);

    const swing = sine(c);
    cover.rotation.y = -Math.PI * swing;
    cover.position.z = (BLOCK + 2 * LIFT) * (1 - ease(.5, 1, swing));
    spine.visible = c < .999;
    spine.position.set(0, 0, mix(BLOCK / 2, -BOARD / 2, open));
    spine.scale.set(mix(.42, .1, open), 1, mix(1, .12, open));

    const key = `${leftDepth}|${rightDepth}|${open}`;
    if (key !== stackKey) {
      stackKey = key;
      leftStack.visible = leftDepth > 0;
      rightStack.visible = rightDepth > 0;
      if (leftStack.visible) shapeStack(leftStack.geometry, -1, leftDepth, open);
      if (rightStack.visible) shapeStack(rightStack.geometry, 1, rightDepth, open);
      leftSheet.visible = turned >= 1;
      rightSheet.visible = gone < LEAVES;
      if (leftSheet.visible) shapeSheet(leftSheet.geometry, -1, leftDepth, open);
      if (rightSheet.visible) shapeSheet(rightSheet.geometry, 1, rightDepth, open);
    }
    coverInside.visible = turned === 0;
    backInside.visible = gone === LEAVES;
    if (coverInside.visible) showPage(coverInside, 0);
    if (backInside.visible) showPage(backInside, pages.length - 1);
    if (leftSheet.visible) showPage(leftSheet, 2 * turned);
    if (rightSheet.visible) showPage(rightSheet, 2 * gone + 1);

    leaf.visible = leafBack.visible = turning;
    if (turning) {
      showPage(leaf, 2 * k - 1);
      showPage(leafBack, 2 * k);
      bendLeaf(t, (LEAVES - k + 1) * SHEET, k * SHEET, open);
    }

    blob.position.set(mix(BW / 2, 0, open), 0, -BOARD - .001);
    blob.scale.set(mix(BW * 1.35, BW * 2.5, open), BH * 1.25, 1);

    const lean = Math.max(0, focus);
    const reach = Math.max(0, -focus);
    const xMin = mix(0, mix(-BW, -.04, lean), settle);
    const xMax = mix(BW, mix(BW, .04, reach), settle);
    // Pull back while the board or a leaf stands up off the book.
    const rise = Math.max(Math.sin(Math.PI * swing) * BW * .62, turning ? Math.sin(Math.PI * t) ** 1.4 * W * .42 : 0);
    const zMax = Math.max(mix(BLOCK + BOARD + LIFT, .08, settle), rise);
    frame(xMin, xMax, zMax, deg(mix(39, 77, settle)));
    renderer.render(scene, camera);
    return !shaderFailed;
  }

  const raycaster = new T.Raycaster();
  const pointer = new T.Vector2();
  function pick(x: number, y: number): Picked | null {
    pointer.set(x / width * 2 - 1, 1 - y / height * 2);
    raycaster.setFromCamera(pointer, camera);
    const candidates = [leftSheet, rightSheet, coverInside, backInside, leaf, leafBack].filter((part) => {
      for (let node: T.Object3D | null = part; node; node = node.parent) if (!node.visible) return false;
      return true;
    });
    const hit = raycaster.intersectObjects(candidates, false)[0];
    if (!hit?.uv || typeof hit.object.userData.page !== 'number') return null;
    if (hit.object === leaf || hit.object === leafBack) return null;
    return {page: hit.object.userData.page, u: hit.uv.x, v: 1 - hit.uv.y};
  }

  function dispose() {
    disposed = true;
    requests.abort();
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    for (const map of textures) map.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  }

  // The first visible frame of the results spread already contains its tables.
  // Live snapshots replace these prints as the reader changes tabs or metrics.
  function showPrint(index: number, name: string) {
    const map = prints.get(name);
    if (!map) return false;
    if (activePrint.get(index) === name) return true;
    if (!activePrint.has(index)) release(snapshots.get(index));
    activePrint.set(index, name);
    snapshots.set(index, map);
    dropFallback(index);
    invalidate();
    return true;
  }

  const printed = Promise.all(pages.flatMap((page, index) => {
    if (!page.print) return [];
    return [page.print, ...(page.variants ?? [])].map(async (name) => {
      try {
        const image = await loadImage(`${BASE}book/${name}`);
        if (disposed) return;
        const map = texture(new T.Texture(image));
        map.needsUpdate = true;
        prints.set(name, map);
        if (name === page.print) showPrint(index, name);
      } catch {
        // Live capture supplies the same results when a print is unavailable.
      }
    });
  }));
  return {resize, render, pick, setSnapshot, dispose, printed, showPrint};
}
