// MOTION EFFECTS (4U): replays what 4U's own effect code drew, recorded offline under the MH4U-Extract harness
// (tools\fx\record_effects.py) -- GU's method, run the game's code and record it. Two files per monster:
//   effects/<em>.json       scripts/build_effects.py: the .mef records (key -> efl, joint, placement, condition) and
//                           each clip's effect page (page 2), bit spans per motion
//   effects/<em>.play.json  per .efl, per frame, the 0x40-byte GPU record the Billboard draw (0x42fdfc) wrote for each
//                           particle: [gen, pass, x, y, z, rgba, u, v, cellW/8, cellH/8, size*256, rot 1/4096 turn,
//                           aspect*16, flags, tex]
//
// READ (4U code, C:\MH4U-Extract\notes\effects.md):
//   - firing: the driver cMhMotionEffect ORs the page's runs over the frames (last, now] (0x95fda8) and fires the
//     bits that were not on last frame (0x39329c); a motion change clears last frame's bits; a loop wrap keeps them
//     and restarts the range at the loop frame; an enemy walks bits 0..16 (0x3915bc); key 1100 is a marker;
//   - a key with no record in the monster's .mef spawns nothing; a record's byte 0 is a condition bit the class sets
//     per frame (0x3918c8), not read -- conditions(on) shows those records whenever their motion fires them
//     (Include Class-State Effects), else they are counted and held back;
//   - the effect follows the record's joint by number (effect+0x34, vt+0x48 0xaffdf8) = the viewer's gid (FIT).
// APPROXIMATED (flagged; the GPU half is not read):
//   - the quad: the sprite shader (LtShaderPackage.lfx program 55, IAPrimitiveSpriteGs: SprScale +0x18, SprRot
//     +0x1a, SprWidth / SprHeight +0x1c / +0x1d, SprRatio +0x1e, SprRotMode +0x1f) READ in part: its geometry stage
//     takes a world width and height, halves them, turns them by the rotation plus the view's roll (fPrimViewRot)
//     and lays them in the camera plane (fViewI). Which fields feed that width and height is the attribute packing,
//     not read. FIT: one texel is a centimetre at scale 1 -- width = SprScale * cell width, height = SprScale *
//     cell height * SprRatio / 16; SprRotMode (flips) is not applied;
//   - colour bytes taken as R, G, B, A from the low byte up; blending normal alpha, additive for a texture with no
//     transparent texel (INFERRED, batch(): the selector is not read -- not the draw layer, not the technique id
//     0x39dde0 returns, not gen+0x44, all checked); u / v in texels from the
//     image's top left (getTexture loads with flipY off);
//   - placement is READ by running each record's effect under a joint the harness turns and moves
//     (place_probe.classify -> eff.place: rot / follow / local); what is approximated is the frame a world-space
//     particle was made in -- the spawn's stands in for all of them;
//   - Model / Polyline / Polygon / Filter generators run in the recording but their draws are not captured yet.
import * as THREE from 'three';
import { loadJson, getTexture } from './assets.js';
import { gidBonesOf } from './skeleton.js';

const FPS = 60;
const MT = 0.01;                       // MT centimetres -> viewer metres, as the hit-zone capsules place them
const LAST_ENEMY_BIT = 16;             // 0x3915bc: owner type 2 stops after bit 16
const MARKER = 1100;                   // 0x3916e0

const VS = `
attribute vec3 iPos; attribute vec3 iSizeRot; attribute vec4 iUv; attribute vec4 iColor;
varying vec2 vUv; varying vec4 vColor;
void main(){
  vec4 mv = viewMatrix * vec4(iPos, 1.0);
  float c = cos(iSizeRot.z), s = sin(iSizeRot.z);
  vec2 p = position.xy * iSizeRot.xy;
  mv.xy += vec2(c * p.x - s * p.y, s * p.x + c * p.y);
  gl_Position = projectionMatrix * mv;
  vUv = iUv.xy + vec2(position.x * 0.5 + 0.5, 0.5 - position.y * 0.5) * iUv.zw;
  vColor = iColor;
}`;
const FS = `
uniform sampler2D uMap; uniform float uHasMap;
varying vec2 vUv; varying vec4 vColor;
void main(){
  vec4 t = uHasMap > 0.5 ? texture2D(uMap, vUv) : vec4(1.0);
  vec4 c = t * vColor;
  if (c.a < 0.004) discard;
  gl_FragColor = c;
}`;

export function createEffects(scene){
  const group = new THREE.Group();
  group.name = 'motion-effects';
  scene.add(group);
  const quad = new THREE.PlaneGeometry(2, 2);
  const batches = new Map();           // texture path -> { mesh, attrs, cap }
  let data = null, play = null, texOf = null, root = null, bones = null;
  let on = false, loadSeq = 0;
  let condOn = false;                  // records with a class condition (byte 0, not read): the Animation panel's toggle
  let last = null;                     // { key, frame, bits }
  let idle = null;                     // { key, frame }: the clip on screen when it has no effect page
  let live = [];                       // { eff, start (frames on the effect clock), matrix }
  let clock = 0;                       // frames the effects have run
  const stats = { fired: 0, skippedCond: 0, noRecord: 0, drawn: 0, undrawn: {} };

  function batch(path){
    let b = batches.get(path);
    if (b) return b;
    const mat = new THREE.ShaderMaterial({
      vertexShader: VS, fragmentShader: FS, transparent: true, depthWrite: false,
      uniforms: { uMap: { value: null }, uHasMap: { value: 0 } } });
    const rel = path && texOf[path];
    if (rel) getTexture(rel).then(t => {
      mat.uniforms.uMap.value = t; mat.uniforms.uHasMap.value = 1;
      // BLEND, INFERRED (the game's blend selector is not read yet): a sprite with no transparent texel at all can
      // only look as it does in the game when it is ADDED -- drawn over alpha, its black ground shows as a square
      // (Rathian's ground fire, em001_001_BM). So an opaque texture is drawn additively; any other keeps alpha.
      // Colour added (src alpha, one); the framebuffer's alpha left as it is (zero, one) -- three's AdditiveBlending
      // writes alpha too, and over a clear canvas the black ground then shows as grey squares (GU's material.js trap).
      if (opaqueImage(t.image)){
        mat.blending = THREE.CustomBlending;
        mat.blendEquation = THREE.AddEquation; mat.blendSrc = THREE.SrcAlphaFactor; mat.blendDst = THREE.OneFactor;
        mat.blendEquationAlpha = THREE.AddEquation; mat.blendSrcAlpha = THREE.ZeroFactor; mat.blendDstAlpha = THREE.OneFactor;
        mat.needsUpdate = true;
      }
    }).catch(() => {});
    const geo = new THREE.InstancedBufferGeometry();
    geo.index = quad.index;
    geo.attributes.position = quad.attributes.position;
    const mesh = new THREE.Mesh(geo, mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = 8000;
    group.add(mesh);
    b = { mesh, geo, cap: 0, n: 0, mat };
    grow(b, 64);
    batches.set(path, b);
    return b;
  }
  // every texel's alpha at 250 or more (sampled on a 64 x 64 copy)
  function opaqueImage(img){
    try {
      if (!img || !img.width) return false;
      const c = document.createElement('canvas'); c.width = 64; c.height = 64;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0, 64, 64);
      const px = g.getImageData(0, 0, 64, 64).data;
      for (let i = 3; i < px.length; i += 4) if (px[i] < 250) return false;
      return true;
    } catch (e){ return false; }
  }
  function grow(b, cap){
    b.cap = cap;
    for (const [name, size] of [['iPos', 3], ['iSizeRot', 3], ['iUv', 4], ['iColor', 4]])
      b.geo.setAttribute(name, new THREE.InstancedBufferAttribute(new Float32Array(cap * size), size));
  }

  // id: the monster (an Apex's own id when the Apex state is on); a monster with no recording loads nothing
  async function load(id, mountedRoot){
    const mine = ++loadSeq;
    monsterId = id;
    clear();
    disposeBatches();
    data = play = shellData = null;
    root = mountedRoot || null;
    bones = null;
    if (!id) return;
    const get = url => loadJson(url).catch(() => null);
    const [d, p, s] = await Promise.all([get('effects/' + id + '.json'), get('effects/' + id + '.play.json'),
                                         get('effects/' + id + '.shells.json')]);
    if (mine !== loadSeq) return;
    data = d || null; play = p || null; shellData = s || null;
    texOf = {};
    if (data) for (const [path, r] of Object.entries(data.resources || {})) if (r.tex) texOf[path] = r.tex;
  }

  // the effects on screen stop; the texture batches stay for the monster's next ones
  function clear(){
    live = [];
    last = null;
    shells = []; sLast = null; shellAcc = 0;
    for (const b of batches.values()){ b.n = 0; b.geo.instanceCount = 0; b.mesh.visible = false; }
  }
  function disposeBatches(){
    for (const b of batches.values()){ group.remove(b.mesh); b.geo.dispose(); b.mat.dispose(); }
    batches.clear();
  }

  // GU's draw meter (live.js METER): the effects alone over grey, against the same pass without them, counted by
  // pixel -- draws, not starts
  // With no camera given it aims its own at the live particles from 3 m out (GU's meterAimed), so a draw off
  // screen still counts as a draw and a miss means nothing was drawn.
  let meterRT = null;
  function meter(renderer, camera, w = 256, h = 256){
    if (!meterRT) meterRT = new THREE.WebGLRenderTarget(w, h);
    if (!camera){
      const box = new THREE.Box3();
      for (const b of batches.values()) for (let i = 0; i < b.n; i++)
        box.expandByPoint(_v.fromBufferAttribute(b.geo.attributes.iPos, i));
      if (box.isEmpty()) return { pixels: 0, of: w * h, aimed: null };
      const c = box.getCenter(new THREE.Vector3()), r = Math.max(0.5, box.getSize(new THREE.Vector3()).length() / 2);
      camera = new THREE.PerspectiveCamera(40, w / h, 0.01, 1000);
      camera.position.copy(c).add(new THREE.Vector3(0, 0.3, 1).normalize().multiplyScalar(r * 3));
      camera.lookAt(c);
      camera.updateMatrixWorld();
    }
    const prevTarget = renderer.getRenderTarget(), prevColor = new THREE.Color(), prevAlpha = renderer.getClearAlpha();
    renderer.getClearColor(prevColor);
    const sc = new THREE.Scene(), parent = group.parent, vis = group.visible;
    sc.add(group);
    const pass = show => {
      group.visible = show;
      renderer.setRenderTarget(meterRT);
      renderer.setClearColor(0x808080, 1);
      renderer.clear();
      renderer.render(sc, camera);
      const px = new Uint8Array(w * h * 4);
      renderer.readRenderTargetPixels(meterRT, 0, 0, w, h, px);
      return px;
    };
    const base = pass(false), px = pass(true);
    group.visible = vis;
    renderer.setRenderTarget(prevTarget);
    renderer.setClearColor(prevColor, prevAlpha);
    if (parent) parent.add(group);
    let n = 0;
    for (let i = 0; i < px.length; i += 4)
      if (Math.abs(px[i] - base[i]) > 2 || Math.abs(px[i + 1] - base[i + 1]) > 2 || Math.abs(px[i + 2] - base[i + 2]) > 2) n++;
    return { pixels: n, of: w * h };
  }

  function boneMatrix(joint){
    if (!root) return null;
    if (!bones){
      bones = new Map();
      for (const b of gidBonesOf(root)) bones.set(b.gid, b.leaf || b.node);
    }
    const n = joint >= 0 ? bones.get(joint) : null;
    return (n || root).matrixWorld;
  }

  const _m = new THREE.Matrix4(), _o = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler();
  const _p = new THREE.Vector3(), _s = new THREE.Vector3();
  // persist: a state's effect (the shared pass below), which the game runs over any clip -- a clip change keeps it
  function spawn(key, persist){
    const rec = data.records[String(key)];
    if (!rec){ stats.noRecord++; return; }
    if (rec.cond && !condOn){ stats.skippedCond++; return; }
    const rel = play.records[String(key)];
    const eff = rel && play.effects[rel];
    if (!eff) return;
    stats.fired++;
    const jm = boneMatrix(rec.joint);
    if (!jm || !root) return;
    if (eff.place){
      // READ by running the effect (MH4U-Extract tools\fx\place_probe.py): the recording already holds the record's own
      // offset, rotation and scale; only the joint is applied, as eff.place says (see placement())
      live.push({ eff, start: clock, joint: rec.joint, jSpawn: jm.clone(), hist: [jm.clone()], persist: !!persist });
      for (const [c, n] of Object.entries(eff.undrawn || {})) stats.undrawn[c] = (stats.undrawn[c] || 0) + n;
      return;
    }
    // (an older recording, made with no parent: the joint's position and the monster's facing, a FIT)
    _p.fromArray(rec.pos).multiplyScalar(MT).applyMatrix4(jm);
    root.matrixWorld.decompose(_v, _q, _s);
    _o.compose(_p, _q.multiply(new THREE.Quaternion().setFromEuler(_e.set(rec.rot[0], rec.rot[1], rec.rot[2]))),
               _s.multiply(new THREE.Vector3().fromArray(rec.scale)));
    const matrix = _o.clone();
    live.push({ eff, start: clock, matrix, persist: !!persist });
    for (const [c, n] of Object.entries(eff.undrawn || {})) stats.undrawn[c] = (stats.undrawn[c] || 0) + n;
  }

  // the bits on anywhere in frames [a, b] (0x95fda8: a run counts when it ends past a and starts by b)
  function bitsOver(motion, a, b){
    let bits = 0;
    for (const x of motion.bits) if (x.bit <= LAST_ENEMY_BIT && x.key !== MARKER)
      for (const [f0, f1] of x.on) if (f1 >= a && f0 <= b){ bits |= 1 << x.bit; break; }
    return bits >>> 0;
  }

  // info: { list, clip, time, playing } for the clip on screen, or null
  function update(info){
    group.visible = on;
    if (!on || !data || !play) return;
    // the pose driver sets the bones' local transforms; their world matrices are otherwise only brought up to date
    // by the render, a frame after the effects would read them
    if (root) root.updateMatrixWorld(true);
    const clock0 = clock;
    let motion = null, offset = 0, end = 0, key = '';
    if (info && info.clip){
      const m = /^(Motion\[\d+\])(?:_(start|loop))?$/.exec(info.clip);
      motion = m && data.clips[info.list] && data.clips[info.list][m[1]];
      if (motion){
        offset = m[2] === 'loop' ? motion.loop : 0;
        end = m[2] === 'start' ? motion.loop : motion.frames;
        key = info.list + '/' + info.clip;
      }
    }
    if (motion){
      const now = offset + info.time * FPS;
      if (!last || last.key !== key){
        // a motion change: last frame's bits are cleared; the range starts at the motion's first frame. The
        // effects of the clip before stop with it (Raven, 2026-10-25: "They also persist when animations are
        // changed") -- which of them the game would keep running is not read.
        if (last) live = live.filter(L => L.persist);
        last = { key, frame: now, bits: 0 };
        fire(motion, Math.floor(now) - 1, Math.floor(now));
      } else if (now < last.frame){
        if (info.wrapped){
          // a loop wrap keeps last frame's bits and starts the range again at the loop frame (0x39329c)
          clock += (end - last.frame) + (now - offset);
          fire(motion, Math.floor(offset) - 1, Math.floor(now));
        } else {
          live = live.filter(L => L.persist); last.bits = 0;   // a seek back: start over, as a fresh motion
          fire(motion, Math.floor(now) - 1, Math.floor(now));
        }
        last.frame = now;
      } else if (now > last.frame){
        clock += now - last.frame;
        fire(motion, Math.floor(last.frame), Math.floor(now));
        last.frame = now;
      }
    } else {
      if (last) live = live.filter(L => L.persist);
      last = null;
      // a clip with no effect page still runs the clock -- the shared pass's states play over any clip
      if (info && info.clip){
        const now = info.time * FPS, k = info.list + '/' + info.clip;
        if (idle && idle.key === k){
          if (now > idle.frame) clock += now - idle.frame;
          else if (info.wrapped) clock += now;
        }
        idle = { key: k, frame: now };
      } else idle = null;
    }
    if (motion) idle = null;
    const cs = clipState(info);
    showMode(cs && cs.rage ? 'rage' : userMode);
    sharedPass(clock - clock0);
    clipEvery(cs, info, clock - clock0);
    shellTick(info);
    draw();
  }

  function fire(motion, a, b){
    const bits = bitsOver(motion, a, b);
    const pending = (bits & ~last.bits) >>> 0;
    last.bits = bits;
    if (!pending) return;
    for (const x of motion.bits) if (pending >>> x.bit & 1 && x.key !== MARKER) spawn(x.key);
  }

  // ---- SHELLS --------------------------------------------------------------------------------------------
  // effects/<em>.shells.json (MH4U-Extract tools\shells\build_shells.py): the projectiles and ground fires a monster's
  // actions make. READ by running each case of the class's action dispatcher under the harness with the shells it
  // makes run for real (the factory 0x6607f4 -> move line 18; uShell001, the generic monster projectile, init 0xc4be8c,
  // update 0xc4d280; notes C:\MH4U-Extract\notes\shells.md):
  //   spawns   per clip and clip frame (the action's frame test 0x9416ec), per action (dispatcher case; one is picked
  //            per clip, `pick`): the kind (type / sub id), the joint and the
  //            offset in its space (Rathian's descriptor 0x6eb0ac: the spawn is joint matrix x offset), pitch and yaw
  //            (u16, 65536 a turn); an `aimed` pitch is the AI's aim block [e+0x8d88]+0x18 added to it;
  //   motion   uShell001: the velocity table 0x10ba5e4[sub] turned by yaw and pitch, v = Ry(yaw) Rx(pitch) v0 (+x for
  //            a positive yaw, down for a positive pitch -- checked against the harness), added to the position every
  //            frame from the one it is made in (line 18 runs after the enemy); acceleration +0x5d0[sub] (turned by the
  //            yaw only); life 0x101b024[sub] frames. Other kinds the runs saw stand still;
  //   contact  the line test 0x2b9594 from last frame's position to this one's: a floor contact ends the shell, places
  //            its landing effects there and makes its landing shells there, on world axes (their angle words are 0
  //            whatever the shell's yaw) -- Rathian's fireball: em001_006, and three uShell003: the ground fire
  //            em001_008 (202 frames) and two that draw nothing;
  //   effects  a shell's own effects are bound to it (setParent joint -1: they follow the shell's matrix, turned by
  //            its angles) and end with it -- the ground fire's is stopped by its shell (effect vt+0x70) when the shell
  //            ends; that the fireball's ends with its shell too is taken, not read.
  // NOT READ (the viewer has none of it): which action the AI took on a clip several share; the AI's target -- an
  // aimed shot aims at a floor point AIM_AHEAD in front of where it starts; the hunter; the quest level (the puffs read it: the low-rank ids are used); the stage -- a floor at
  // y = FLOOR_Y; the turn side (an action that turns picks its other clip then: only the one side is in the table);
  // the order of the acceleration and position adds (no kind built so far accelerates).
  let AIM_AHEAD = 10;                  // m in front of an aimed shot's start, on the floor (an input: Shot Target)
  const FLOOR_Y = 0;
  const TURN = Math.PI * 2 / 65536;
  let shellData = null, shells = [], sLast = null, shellAcc = 0;
  const _sq = new THREE.Quaternion(), _ss = new THREE.Vector3(), _sp = new THREE.Vector3(), _se = new THREE.Euler();

  function shellTick(info){
    if (!shellData || !root) return;
    let rows = null, now = 0, key = '', end = 0, offset = 0;
    const m = info && info.clip ? /^(Motion\[\d+\])(?:_(start|loop))?$/.exec(info.clip) : null;
    if (m){
      const mo = data && data.clips[info.list] && data.clips[info.list][m[1]];
      offset = m[2] === 'loop' && mo ? mo.loop : 0;
      end = mo ? mo.frames : 0;
      now = offset + info.time * FPS;
      key = info.list + '/' + m[1];                    // a split clip's _start and _loop are one motion
      const c = shellData.spawns[info.list] && shellData.spawns[info.list][m[1]];
      // several actions can play one clip (Rathian's L2 M18: the fireball, case 10, and a hit volume, case 11); the
      // build picks one -- the first whose shells draw -- since which the AI chose is not the viewer's to know
      rows = c ? c.rows.filter(r => r.cases.includes(c.pick)) : null;
    }
    let dt = 0;
    const due = (a, b) => { if (rows) for (const r of rows) if (r.frame > a && r.frame <= b) makeFromRow(r); };
    if (!sLast || sLast.key !== key){
      endAll();                                        // a clip change: its shells stop with it, as its effects do
      if (key) due(now - 1, now);
    } else if (now < sLast.frame){
      if (info.wrapped){
        due(sLast.frame, Infinity);
        due(offset - 1, now);
        dt = Math.max(0, (end || sLast.frame) - sLast.frame) + (now - offset);
      } else {
        endAll();                                      // a seek back: start over
        due(now - 1, now);
      }
    } else {
      due(sLast.frame, now);
      dt = now - sLast.frame;
    }
    sLast = key ? { key, frame: now } : null;
    shellAcc += dt;
    while (shellAcc >= 1){
      shellAcc -= 1;
      for (const s of shells.slice()) if (!s.dead && !s.fresh) move(s);
      for (const s of shells) s.fresh = false;
      shells = shells.filter(s => !s.dead);
    }
  }
  function endAll(){
    for (const s of shells) end(s);
    shells = [];
    shellAcc = 0;
  }

  // the matrix a shell's effects follow: its position, its angles, the monster's size
  function anchorOf(s){
    return () => _m.compose(s.pos, s.quat, s.scale).clone();
  }
  function makeFromRow(r){
    const k = shellData.kinds[r.kind];
    if (!k) return;
    const jm = boneMatrix(r.joint);
    root.matrixWorld.decompose(_sp, _sq, _ss);
    const rootQ = _sq.clone(), scale = _ss.clone();
    const pos = new THREE.Vector3().fromArray(r.offset).multiplyScalar(MT).applyMatrix4(jm);
    let pitch = r.pitch * TURN;
    if (r.aimed){
      // the AI's aim (NOT READ): a floor point AIM_AHEAD in front of where the shot starts, along the monster's
      // facing (the root does not travel with the clip's root motion, so the head can be metres ahead of it)
      pitch += Math.atan2(pos.y - FLOOR_Y, AIM_AHEAD);
    }
    const yaw = r.yaw * TURN;
    const quat = rootQ.clone().multiply(new THREE.Quaternion().setFromEuler(_se.set(pitch, yaw, 0, 'YXZ')));
    make(k, pos, quat, scale, rootQ.clone().multiply(new THREE.Quaternion().setFromEuler(_se.set(0, yaw, 0))));
  }
  function make(k, pos, quat, scale, yawQ){
    if (k.floor) pos.y = FLOOR_Y;
    const s = { k, pos, quat, scale, age: 0, fx: [], dead: false, fresh: true, origin: pos.clone(),
                pathQ: (yawQ || quat).clone(),
                vel: new THREE.Vector3().fromArray(k.v || [0, 0, 0]).multiplyScalar(MT).applyQuaternion(quat),
                acc: new THREE.Vector3().fromArray(k.a || [0, 0, 0]).multiplyScalar(MT).applyQuaternion(yawQ || quat) };
    for (const b of k.body || []) startFx(b, anchorOf(s), s);
    shells.push(s);
    move(s);                                           // it moves in the frame it is made
  }
  function move(s){
    const k = s.k;
    if (k.path){
      // a shell that moves by its own code (not uShell001's tables): the path the harness recorded from its spawn,
      // per frame, with the monster facing +z -- turned by the monster's facing here; `floor`: it runs on the floor
      const p = k.path[Math.min(s.age, k.path.length - 1)];
      s.pos.copy(s.origin).add(_sp.set(p[0], p[1], p[2]).multiplyScalar(MT).applyQuaternion(s.pathQ));
      if (k.floor) s.pos.y = FLOOR_Y;
      if (++s.age >= (k.life || k.path.length)) end(s);
      return;
    }
    if (!k.still){
      const prev = s.pos.clone();
      s.pos.add(s.vel);
      s.vel.add(s.acc);
      if (k.land && prev.y > FLOOR_Y && s.pos.y <= FLOOR_Y){
        const t = (prev.y - FLOOR_Y) / (prev.y - s.pos.y);
        const at = prev.lerp(s.pos, t).setY(FLOOR_Y);
        s.pos.copy(at);
        land(s, at);
        end(s);
        return;
      }
    }
    if (++s.age >= (k.life || 0)) end(s);
  }
  function land(s, at){
    const ident = new THREE.Quaternion();
    for (const e of s.k.land.effects || []){
      const p = at.clone().add(new THREE.Vector3().fromArray(e.offset || [0, 0, 0]).multiplyScalar(MT));
      const M = new THREE.Matrix4().compose(p, ident, s.scale);
      startFx(e, () => M, null);
    }
    for (const c of s.k.land.shells || []){
      const k = shellData.kinds[c.kind];
      if (!k) continue;
      const p = at.clone().add(new THREE.Vector3().fromArray(c.offset || [0, 0, 0]).multiplyScalar(MT));
      make(k, p, ident.clone(), s.scale.clone());
    }
  }
  function end(s){
    if (s.dead) return;
    s.dead = true;
    for (const L of s.fx) L.until = clock;
  }
  function startFx(b, anchor, s){
    const eff = shellData.effects[b.efl + '#' + b.flags];
    if (!eff || !eff.recs || !eff.recs.length) return;
    const m0 = anchor();
    const L = { eff, start: clock, joint: -1, anchor, jSpawn: m0.clone(), hist: [m0.clone()], persist: false, until: null };
    live.push(L);
    if (s) s.fx.push(L);
    stats.fired++;
    for (const [c, n] of Object.entries(eff.undrawn || {})) stats.undrawn[c] = (stats.undrawn[c] || 0) + n;
  }

  // ---- THE SHARED PASS -----------------------------------------------------------------------------------
  // 4U's shared enemy code, 0x919868 (once per enemy update), READ in part (C:\MH4U-Extract\notes\effects-gu-review.md):
  // countdowns at e28+0x792c / +0x7930 ticked by 0xb069d4, each requesting a .mef key when it runs out. GU's
  // SHARED_STATES / RAGE_PUFF / TIRED_DROOL are the same mechanism, and its findings agree:
  //   enraged (e28+0x530 == 1, 0x954778): every 30 frames (50 in action 0x59, not modelled) the class pick vt+0x130
  //     chooses 1020 or 1021, then 1022, 1023, 1024 and 1025 are requested -- each family's .mef holds its own of them
  //     (the Rath line 1020 / 1021, the Tigrex line 1022, the Khezu / Basarios / Gravios lines 1023);
  //   exhausted (e28+0x51c in {2, 3}, 0x92e2c8): 1009 every 48 frames -- GU's drool cadence;
  //   the combat byte (e28+0x34c, 0x91aa88): 0 -> 2 requests 1000, 2 -> 0 requests 1001.
  // A countdown at 0 when its state comes on fires at once (0xb069d4 returns true at 0), as GU's does.
  const RAGE_PERIOD = 30, TIRED_PERIOD = 48;
  const PUFF_KEYS = [1022, 1023, 1024, 1025];
  let mode = 'normal', combat = false;
  const timer = { rage: 0, tired: 0 };
  // THE PUFF PICK, vt+0x130 per class (READ): the base 0x934474 returns 0 (1021). The overrides take the puff joint's
  // third rotation row (0x915bbc: the joint e28+0x7a1c, its matrix built from the joint quaternion by 0xb04c24) into
  // e28+0x7a20, and 0x568b3c turns atan2(-vy, sqrt(vx^2 + vz^2)) into a 16-bit angle u (uxth); then
  //   'rath'  (Rath line 0x6e984c, Seregios 0x8b1624, Diablos 0x8d3ec8, Monoblos 0x8defb0): u - 0x8000 >= 0x6e39 (unsigned)
  //   'ge'    (Akantor 0x7e4ffc): u >= 0xe39;   'gt' (Ukanlos 0x908e90): u > 0xe39
  // -- GU's rathianPuffPick and fatalisPuffPick formulas. The joint each class writes into e28+0x7a1c: 4 (Rath line
  // 0x6de018, Seregios 0x8aa3ec, Diablos 0x8d92e8, Monoblos 0x8e4d6c), 3 (Akantor 0x7e09f0, Ukanlos 0x904d10).
  const CLASS_OF = { em001: 'uEm001', em002: 'uEm001', em003: 'uEm001', em004: 'uEm001', em005: 'uEm001', em006: 'uEm001',
                     em011: 'uEm011', em012: 'uEm011', em080: 'uEm011', em121: 'uEm011', em033: 'uEm033',
                     em036: 'uEm036', em037: 'uEm036', em038: 'uEm038', em039: 'uEm038', em040: 'uEm038', em041: 'uEm038',
                     em115: 'uEm038', em088: 'uEm088', em122: 'uEm088', em099: 'uEm099', em100: 'uEm099', em119: 'uEm099',
                     em101: 'uEm101', em102: 'uEm101', em116: 'uEm116' };
  const PUFF_PICK = { uEm001: { joint: 4, rule: 'rath' }, uEm088: { joint: 4, rule: 'rath' }, uEm099: { joint: 4, rule: 'rath' },
                      uEm101: { joint: 4, rule: 'rath' }, uEm033: { joint: 3, rule: 'ge' }, uEm116: { joint: 3, rule: 'gt' } };
  let monsterId = null;
  function puffKey(){
    const pk = PUFF_PICK[CLASS_OF[monsterId]];
    if (!pk || !root) return 1021;
    let node = null;
    for (const b of gidBonesOf(root)) if (b.gid === pk.joint){ node = b.node; break; }
    if (!node) return 1021;
    const f = Math.fround, q = node.quaternion;
    const x = f(q.x), y = f(q.y), z = f(q.z), w = f(q.w);
    const z2 = f(z + z), y2 = f(y + y), x2 = f(x + x);
    const vx = f(f(x * z2) + f(y2 * w)), vy = f(f(y * z2) - f(x2 * w)), vz = f(1 - f(f(x * x2) + f(y * y2)));
    let a = Math.atan2(-vy, Math.sqrt(vx * vx + vz * vz));
    if (a < 0) a += Math.PI * 2;
    const u = Math.trunc(a * 65536 / (Math.PI * 2)) & 0xffff;
    const yes = pk.rule === 'rath' ? ((u - 0x8000) >>> 0) >= 0x6e39 : pk.rule === 'ge' ? u >= 0xe39 : u > 0xe39;
    return yes ? 1020 : 1021;
  }
  function sharedPass(dt){
    if (!(dt > 0)) return;
    if (mode === 'rage'){
      timer.rage -= dt;
      while (timer.rage <= 0){
        spawn(puffKey(), true);
        for (const k of PUFF_KEYS) if (data.records[String(k)]) spawn(k, true);
        timer.rage += RAGE_PERIOD;
      }
    } else if (mode === 'tired'){
      timer.tired -= dt;
      while (timer.tired <= 0){ spawn(1009, true); timer.tired += TIRED_PERIOD; }
    }
  }
  // THE RAGE ENTRY (GU's MOTION_STATES `rage: true` rows; effects/<em>.shells.json `states`, MH4U-Extract
  // tools\shells\build_shells.py): 0x91f258 issues the AI's command group 6 (0x91489c(e, 6, 0)) and sets rage
  // (0x9332cc(e, 1)); the clips of the actions that group can issue (the command table walked by tools\shells\emc.py,
  // each action run for its first motion) show rage from their frame 0 while they play -- Rathian's ground roar L0
  // Motion[4] (action (1, 9)) and air roar L1 Motion[3] ((4, 11)), GU's own finding for her. As GU's rows do, this
  // changes what is shown, not the user's State: when the clip is over the user's choice is shown again.
  let userMode = 'normal';
  function setMode(m){
    userMode = m === 'rage' || m === 'tired' ? m : 'normal';
    showMode(userMode);
  }
  function showMode(m){
    if (m !== mode){ timer.rage = 0; timer.tired = 0; }
    mode = m;
  }
  // A CLIP'S STATUS (states `every`, MH4U-Extract tools\shells\state_census.py): an action that sets the status byte
  // e28+0x790d to 2 / 3 / 7 / 8 makes the shared pass (0x919868) request 1018 on its timer +0x7938, reloaded from the
  // record's own +0x14 (the request returns it, 0x391550) -- Rathian's L0 Motion[20] (action (1, 0x20)), every 40.
  // While such a clip plays its key fires from the frame the action set the status, the first at once (a countdown at
  // 0 fires, 0xb069d4); a clip change ends it. What each status means is not read (GU's sleep / wake rows are the
  // same clips).
  let everyKey = '', everyT = [];
  function clipEvery(cs, info, dt){
    const key = cs && cs.every && info ? info.list + '/' + info.clip : '';
    if (key !== everyKey){ everyKey = key; everyT = key ? cs.every.map(() => 0) : []; }
    if (!key || !(dt > 0)) return;
    const now = info.time * FPS;
    cs.every.forEach((r, i) => {
      if (now < r.from) return;
      everyT[i] -= dt;
      while (everyT[i] <= 0){ spawn(r.key); everyT[i] += r.period > 0 ? r.period : 1e9; }
    });
  }
  function clipState(info){
    const m = info && info.clip ? /^(Motion\[\d+\])/.exec(info.clip) : null;
    const st = m && shellData && shellData.states && shellData.states[info.list];
    return st && st[m[1]] || null;
  }
  // silent: take the value without the flip's request (a reload restoring the saved switch)
  function setCombat(v, silent){
    v = !!v;
    if (v !== combat && data && play && !silent) spawn(v ? 1000 : 1001, true);
    combat = v;
  }

  // The matrix a particle is carried by, from how the game's own code used the joint (place_probe.classify: a
  // joint turned and a joint moving): rot -- the joint's rotation too, else world axes at the joint's position;
  // follow -- the joint moves the effect after it fired; local false -- its particles stay where they were made,
  // so each takes the joint of its own birth frame (recorded: the Billboard spawn 0x42f570). L.hist holds the
  // joint matrix for each frame of the effect.
  const _pq = new THREE.Quaternion(), _pp = new THREE.Vector3(), _ps = new THREE.Vector3();
  function placement(L, k, out){
    const pl = L.eff.place;
    const j = pl.follow ? L.hist[Math.max(0, Math.min(k, L.hist.length - 1))] : L.hist[0];
    if (pl.rot) return out.copy(j);
    _pp.setFromMatrixPosition(j);
    root.matrixWorld.decompose(_ps, _pq, _v);          // the monster's size; the axes stay the world's
    return out.compose(_pp, _pq.identity(), _v);
  }
  const _mcache = new Map();

  const _v = new THREE.Vector3();
  function draw(){
    for (const b of batches.values()) b.n = 0;
    const keep = [];
    let drawn = 0;
    for (const L of live){
      const f = Math.floor(clock - L.start);
      const recs = L.eff.recs;
      // An effect ends where its recording does. A capped one (still running when the recording stopped) ends
      // there too: held on its last frame it stayed on screen for good and piled up (Raven, 2026-10-24: the
      // background turned light grey).
      if (f >= recs.length) continue;
      if (L.until != null && clock >= L.until) continue;   // a shell's effect ends with its shell (see SHELLS)
      keep.push(L);
      const frame = recs[f] || [];
      if (L.hist){
        const jm = L.anchor ? L.anchor() : boneMatrix(L.joint);
        while (L.hist.length <= f) L.hist.push((jm || L.jSpawn).clone());
      }
      _mcache.clear();
      for (const r of frame){
        // the matrix for this particle: its birth frame's joint when it was made in world space, this frame's when
        // it rides with the effect (an older recording: the one matrix it was placed with)
        let M = L.matrix;
        if (L.eff.place){
          const k = L.eff.place.follow && L.eff.place.local === false && r.length > 15 ? r[15] : f;
          M = _mcache.get(k);
          if (!M){ M = placement(L, k, new THREE.Matrix4()); _mcache.set(k, M); }
        }
        const scale = _s.setFromMatrixColumn(M, 0).length();
        const gen = L.eff.generators[r[0]] || {};
        // no texture resolved (the draw bound none, or a stand-in): not drawn, rather than drawn as a white square
        const tex = (gen.textures || [])[0] || '';
        if (!texOf[tex]) continue;
        const b = batch(tex);
        if (b.n >= b.cap){ const old = b; const keepN = old.n; growCopy(old, old.cap * 2); old.n = keepN; }
        const i = b.n++;
        _v.set(r[2] * MT, r[3] * MT, r[4] * MT).applyMatrix4(M);
        b.geo.attributes.iPos.setXYZ(i, _v.x, _v.y, _v.z);
        // half extents (the quad is -1..1): SprScale (8.8) * cell texels, a texel a centimetre (FIT, see the header)
        const k = r[10] / 256 * MT * scale * 0.5 * 8;
        b.geo.attributes.iSizeRot.setXYZ(i, k * r[8], k * r[9] * (r[12] || 16) / 16, r[11] / 4096 * Math.PI * 2);
        const img = b.mat.uniforms.uMap.value && b.mat.uniforms.uMap.value.image;
        const W = img ? img.width : 256, H = img ? img.height : 256;
        b.geo.attributes.iUv.setXYZW(i, r[6] / W, r[7] / H, r[8] * 8 / W, r[9] * 8 / H);
        const c = r[5] >>> 0;
        b.geo.attributes.iColor.setXYZW(i, (c & 255) / 255, (c >>> 8 & 255) / 255, (c >>> 16 & 255) / 255, (c >>> 24) / 255);
        drawn++;
      }
    }
    live = keep;
    for (const b of batches.values()){
      b.geo.instanceCount = b.n;
      for (const k of ['iPos', 'iSizeRot', 'iUv', 'iColor']) b.geo.attributes[k].needsUpdate = true;
      b.mesh.visible = b.n > 0;
    }
    stats.drawn = drawn;
  }
  function growCopy(b, cap){
    const old = {};
    for (const k of ['iPos', 'iSizeRot', 'iUv', 'iColor']) old[k] = b.geo.attributes[k].array;
    grow(b, cap);
    for (const k of Object.keys(old)) b.geo.attributes[k].array.set(old[k]);
  }

  return {
    group, load, update, clear, meter,
    get on(){ return on; },
    set(v){ on = !!v; group.visible = on; if (!on){ clear(); disposeBatches(); } },
    stats: () => Object.assign({ live: live.length, loaded: !!(data && play), shells: shells.length }, stats),
    aim: m => { if (m > 0) AIM_AHEAD = m; },
    hasAimed: () => !!(shellData && Object.values(shellData.spawns || {}).some(l => Object.values(l).some(c =>
      c.rows.some(r => r.aimed && r.cases.includes(c.pick))))),
    shellList: () => shells.map(s => ({ kind: s.k.type + '/' + s.k.sub, age: s.age, pos: s.pos.toArray().map(v => +v.toFixed(3)) })),
    conditions: v => { condOn = !!v; },
    state: m => setMode(m), combat: (v, silent) => setCombat(v, silent), mode: () => mode,
    // whether the loaded monster holds any record the State drives (the rage puffs, the drool)
    hasStates: () => !!(data && [1009, 1020, 1021, ...PUFF_KEYS].some(k => data.records[String(k)])),
  };
}
