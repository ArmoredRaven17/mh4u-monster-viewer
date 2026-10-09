r"""Bulk-convert every MH4U monster (models, textures, motion lists) with RevilToolset and check each
output against its own source header -- the MH3U Monster Viewer's convert_monsters.py, for 4U.

    python scripts/convert_monsters.py                 # stage + convert + validate
    python scripts/convert_monsters.py --only em001    # a subset (comma list)
    python scripts/convert_monsters.py --check         # validate the existing conversion only

Source: the cart's own archives, read in place (ARC v19, tools\arc4.py's reader):
  romfs/data/emNNN.arc          one monster per archive: enemy\emNNN\mod\* (.mod, .mrl, .tex),
                                enemy\emNNN\mot\emNNN_K (.lmt, LMT v67 -- one motion list each)
  romfs/snake/data/emNNN_.arc   the New 3DS ("SNAKE") copies of the monster's textures, at twice the
                                texel count, internal path snake\enemy\emNNN\mod\*. Staged beside the
                                standard ones as <name>.snake.tex; build_viewer.py picks which to ship.
Event and demo archives (d*.arc, e*.arc) carry a few monster models again (em110_event ...); they are
not staged.

Outputs: <EXTRACT>\conv\monster\emNNN\  *.mod/.mrl/.tex/.lmt as staged, *.glb (mod_to_gltf),
         *.tex.dds (mtf_tex_to_dds), anim\<list>_out.glb (lmt_to_gltf onto a copy of the model glb);
         conv\monster\report.json

LMT v67 is 3U's v66 layout (0x40-byte motion header, 0x24-byte tracks). The rotation types 11/12/13
are NOT 3U's: 4U stores the two fields unsigned (14 bits each) and scales them through the track's
bounds block, min + range * v / 16383 (the bounds are [range xyzw, min xyzw]); 3U's were signed
14-bit / 4096 with no bounds. lmt_to_gltf decodes the 4U form correctly -- checked on Rathian's list 0,
2,977 keys agree to 0.0015 -- so 4U needs none of the 3U viewer's lmt_fix.py patch. (lmt_to_gltf puts
the track's reference rotation at frame 0 and each key at the running total of the frame counts, so
its keys sit one frame after a reading that starts the first key at 0; the same convention for every
track type, so nothing is offset against anything else.)
"""
import argparse, glob, hashlib, json, math, os, re, shutil, struct, subprocess, sys

EXTRACT = r'C:\MH4U-Extract'
sys.path.insert(0, os.path.join(EXTRACT, 'tools'))
import arc4

CONV = os.path.join(EXTRACT, 'conv', 'monster')
TOOL = r'C:\MHGU-Extract\tools\reviltoolset\revil_toolset.exe'   # run read-only
EXT = {0x58a15856: 'mod', 0x2749c8a8: 'mrl', 0x241f5deb: 'tex', 0x76820d81: 'lmt'}
EM_ARC = re.compile(r'^(em\d{3})\.arc$')


def run(*args, timeout=None):
    try:
        r = subprocess.run([TOOL, *args], cwd=os.path.dirname(TOOL), capture_output=True,
                           text=True, errors='replace', timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 'TIMEOUT %s' % (args,)


def monsters():
    return sorted(m.group(1) for p in os.listdir(os.path.join(EXTRACT, 'romfs', 'data'))
                  for m in [EM_ARC.match(p)] if m)


def stage_arc(src, dst, em, suffix='', manifest=None):
    """every model, material, texture and motion list of the monster's own folder in one archive;
    `manifest` gets every model and motion list the archive packs, from any monster's folder"""
    n = 0
    with open(src, 'rb') as f:
        for name, th, cs, ds, fl, off in arc4.entries(src):
            parts = name.replace('/', '\\').lower().split('\\')
            if parts[0] == 'snake':
                parts = parts[1:]
            if th not in EXT or parts[0] != 'enemy':
                continue
            ext = EXT[th]
            if suffix and ext != 'tex':
                continue
            if manifest is not None and ext in ('mod', 'lmt'):
                data = arc4.read_entry(f, cs, ds, off)
                manifest['models' if ext == 'mod' else 'lists'].append(
                    [parts[1], parts[-1], hashlib.md5(data).hexdigest()])
            if parts[1] != em:
                continue
            out = os.path.join(dst, parts[-1] + suffix + '.' + ext)
            open(out, 'wb').write(arc4.read_entry(f, cs, ds, off))
            n += 1
    return n


def stage(em):
    r"""the monster's own files, and manifest.json: what its archive packs. The archive is what the game
    loads for the monster, so it says which model and lists it plays with: Pink Rathian's (em003) packs
    its own model and Rathian's lists (enemy\em001\mot), Apex Rajang's (em112) Rajang's model and
    lists, Apex Zinogre's (em114) Zinogre's model with three lists of its own."""
    dst = os.path.join(CONV, em)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.join(dst, 'anim'))
    manifest = {'models': [], 'lists': []}
    n = stage_arc(os.path.join(EXTRACT, 'romfs', 'data', em + '.arc'), dst, em, manifest=manifest)
    snake = os.path.join(EXTRACT, 'romfs', 'snake', 'data', em + '_.arc')
    if os.path.isfile(snake):
        n += stage_arc(snake, dst, em, '.snake')
    # A list from another folder that its home archive does not carry the same is this monster's own,
    # filed under the other name: Furious and Apex Rajang (em045, em112) both pack enemy\em019\mot\em019_4,
    # which Rajang's em019.arc does not have. Staged here (and converted onto this monster's model);
    # the manifest row gains a 4th field, True. Every other packed list is its home folder's byte for byte.
    src = os.path.join(EXTRACT, 'romfs', 'data', em + '.arc')
    for row in manifest['lists']:
        folder, stem, digest = row
        if folder != em and home_digest(folder, stem) != digest:
            with open(src, 'rb') as f:
                for name, th, cs, ds, fl, off in arc4.entries(src):
                    parts = name.replace('/', '\\').lower().split('\\')
                    if th == 0x76820d81 and parts[:2] == ['enemy', folder] and parts[-1] == stem:
                        open(os.path.join(dst, stem + '.lmt'), 'wb').write(arc4.read_entry(f, cs, ds, off))
                        n += 1
            row.append(True)
    json.dump(manifest, open(os.path.join(dst, 'manifest.json'), 'w'), indent=1)
    return n


_home = {}


def home_digest(folder, stem):
    r"""md5 of enemy\<folder>\mot\<stem> in <folder>.arc itself, or None"""
    if folder not in _home:
        _home[folder] = {}
        p = os.path.join(EXTRACT, 'romfs', 'data', folder + '.arc')
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                for name, th, cs, ds, fl, off in arc4.entries(p):
                    parts = name.replace('/', '\\').lower().split('\\')
                    if th == 0x76820d81 and parts[:2] == ['enemy', folder]:
                        _home[folder][parts[-1]] = hashlib.md5(arc4.read_entry(f, cs, ds, off)).hexdigest()
    return _home[folder].get(stem)


def main_model(em):
    """(folder, stem) of the body model the monster's archive packs: its own, else the one model
    named after its own folder"""
    m = json.load(open(os.path.join(CONV, em, 'manifest.json')))
    mains = [(f, s) for f, s, _ in m['models'] if s == f]
    own = [x for x in mains if x[0] == em]
    return own[0] if own else (mains[0] if len(mains) == 1 else None)


# ---- vertex formats mod_to_gltf does not know --------------------------------------------------------
# Mesh row (48 bytes, header +0x34; vertex buffer at header +0x38, size +0x18, index buffer +0x3C):
#   +2 u16 vertex count, +0xA u8 stride, +0xC u32 first vertex, +0x10 u32 byte offset of the block in
#   the vertex buffer, +0x14 u32 vertex format.
# Every 4U monster mesh but 24 uses 0xF606F017 (36 bytes: f32 position[3], s8 normal[4], f32 uv[2],
# u8 joint[2] + u8 weight[2] (summing to 255), s8 tangent[4], u32) or one of the smaller rigid formats.
# The 24 (Tigrex, Brute Tigrex, Akantor, Khezu, Red Khezu, Molten Tigrex, Savage Deviljho) stop
# mod_to_gltf with "Unregistered vertex format":
#   0x866B6018  44 bytes: the 36-byte layout exactly (joint weights sum to 255, tangent w = +-127),
#               then f32 uv2[2]. Repacked to 0xF606F017 by dropping uv2.
#   0xCE5A801C  36 bytes: the same, but bytes 28-31 are an RGBA colour, not a tangent (the 4th byte
#               varies; a tangent's is always +-127). Retagged 0xF606F017 as it stands: the colour is
#               read as a tangent, which the viewer never uses (it draws no normal maps).
# The original .mod stays beside the glb (the build reads its mesh table); the repacked copy is
# converted in conv\monster\emNNN\_repack and removed.
STD_FMT = 0xF606F017
REPACK = {0x866B6018: 44, 0xCE5A801C: 36}


def repack_mod(src):
    """bytes of a copy of the .mod with every REPACK mesh in the standard 36-byte format, or None"""
    d = open(src, 'rb').read()
    h = list(struct.unpack_from('<16I', d, 0))
    nmesh = struct.unpack_from('<H', d, 8)[0]
    mo, vb, vsize, ib = h[13], h[14], h[6], h[15]
    rows = [bytearray(d[mo + 48 * i:mo + 48 * (i + 1)]) for i in range(nmesh)]
    if not any(struct.unpack_from('<I', r, 0x14)[0] in REPACK for r in rows):
        return None
    # meshes sharing a block offset share its stride; rebuild block by block in buffer order
    blocks = sorted({struct.unpack_from('<I', r, 0x10)[0] for r in rows})
    out, new_off = bytearray(), {}
    for bi, boff in enumerate(blocks):
        end = blocks[bi + 1] if bi + 1 < len(blocks) else vsize
        members = [r for r in rows if struct.unpack_from('<I', r, 0x10)[0] == boff]
        fmts = {struct.unpack_from('<I', r, 0x14)[0] for r in members}
        stride = {r[0xA] for r in members}
        assert len(stride) == 1, (src, boff, stride)
        stride = stride.pop()
        new_off[boff] = len(out)
        raw = d[vb + boff:vb + end]
        if stride != 36:
            # a block of 44-byte vertices; a 36-byte retag (0xCE5A801C) can share a block with
            # standard meshes and needs no byte changed
            assert all(REPACK.get(f) == stride for f in fmts), (src, boff, fmts, stride)
            for i in range(len(raw) // stride):
                out += raw[i * stride:i * stride + 36]
        else:
            out += raw
    for r in rows:
        struct.pack_into('<I', r, 0x10, new_off[struct.unpack_from('<I', r, 0x10)[0]])
        if struct.unpack_from('<I', r, 0x14)[0] in REPACK:
            r[0xA] = 36
            struct.pack_into('<I', r, 0x14, STD_FMT)
    assert ib == vb + vsize, src             # the index buffer follows the vertex buffer directly
    h[6] = len(out)
    h[15] = vb + len(out)
    body = bytearray(d[:vb])
    struct.pack_into('<16I', body, 0, *h)
    for i, r in enumerate(rows):
        body[mo + 48 * i:mo + 48 * (i + 1)] = r
    return bytes(body + out + d[ib:])


def convert(em):
    d = os.path.join(CONV, em)
    log = []
    if glob.glob(os.path.join(d, '*.mod')):
        log.append(run('mod_to_gltf', d, timeout=600))
    for mp in glob.glob(os.path.join(d, '*.mod')):
        data = None if os.path.isfile(mp[:-4] + '.glb') else repack_mod(mp)
        if data:
            # converted alone, in a temporary folder, and its glb moved to the model's own name
            tmp = os.path.join(d, '_repack')
            os.makedirs(tmp, exist_ok=True)
            stem = os.path.splitext(os.path.basename(mp))[0]
            open(os.path.join(tmp, stem + '.mod'), 'wb').write(data)
            shutil.copy2(mp[:-4] + '.mrl', tmp)
            log.append('REPACKED ' + stem + '\n' + run('mod_to_gltf', os.path.join(tmp, stem + '.mod'), timeout=600))
            if os.path.isfile(os.path.join(tmp, stem + '.glb')):
                shutil.move(os.path.join(tmp, stem + '.glb'), mp[:-4] + '.glb')
            shutil.rmtree(tmp, ignore_errors=True)
    if glob.glob(os.path.join(d, '*.tex')):
        log.append(run('mtf_tex_to_dds', '--platform', 'N3DS', d, timeout=600))
    open(os.path.join(d, 'convert.log'), 'w', encoding='utf-8').write('\n'.join(log))


def convert_lists(em):
    """lmt_to_gltf merges each of the monster's own motion lists onto a copy of the model its archive
    packs (its own, or another monster's -- so this runs after every model is converted)"""
    d = os.path.join(CONV, em)
    lmts = sorted(glob.glob(os.path.join(d, '*.lmt')))
    mm = main_model(em)
    base = os.path.join(CONV, mm[0], mm[1] + '.glb') if mm else None
    if not lmts or not base or not os.path.isfile(base):
        return
    pairs = []
    for l in lmts:
        n = os.path.splitext(os.path.basename(l))[0]
        shutil.copy2(base, os.path.join(d, 'anim', n + '.glb'))
        shutil.copy2(l, os.path.join(d, 'anim', n + '.lmt'))
        pairs.append([n + '.glb', n + '.lmt'])
    bj = os.path.join(d, 'anim', 'batch.json')
    json.dump(pairs, open(bj, 'w'))
    log = run('lmt_to_gltf', bj, timeout=1800)
    for n, _ in pairs:                 # the merge inputs; only the _out files are read later
        for ext in ('.glb', '.lmt'):
            q = os.path.join(d, 'anim', n[:-4] + ext)
            if os.path.isfile(q):
                os.remove(q)
    open(os.path.join(d, 'convert.log'), 'a', encoding='utf-8').write('\n' + log)


# ---- validation ------------------------------------------------------------------------------------

def glb_json(p):
    b = open(p, 'rb').read()
    n = struct.unpack_from('<I', b, 12)[0]
    return json.loads(b[20:20 + n]), b


def accessor_floats(j, b, ai):
    a = j['accessors'][ai]
    bv = j['bufferViews'][a['bufferView']]
    off = 20 + struct.unpack_from('<I', b, 12)[0] + 8 + bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    comps = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
    fmt = {5126: 'f', 5122: 'h', 5123: 'H', 5120: 'b', 5121: 'B'}[a['componentType']]
    size = struct.calcsize(fmt)
    stride = bv.get('byteStride', comps * size)
    out = []
    for i in range(a['count']):
        out.extend(struct.unpack_from('<' + fmt * comps, b, off + i * stride))
    return out


def mod_header(p):
    h = open(p, 'rb').read(0x40)
    assert h[:4] == b'MOD\0' and struct.unpack_from('<H', h, 4)[0] == 0xE6, p
    bones, meshes, mats = struct.unpack_from('<HHH', h, 6)
    verts = struct.unpack_from('<I', h, 12)[0]
    return {'bones': bones, 'meshes': meshes, 'materials': mats, 'verts': verts}


def lmt_motions(p):
    """{motion index: set of bones its tracks drive}"""
    b = open(p, 'rb').read()
    ver, cnt = struct.unpack_from('<HH', b, 4)
    out = {}
    for i in range(cnt):
        mo = struct.unpack_from('<I', b, 8 + 4 * i)[0]
        if mo:
            to, n = struct.unpack_from('<II', b, mo)
            out[i] = {b[to + 0x24 * k + 3] for k in range(n)}
    return ver, out


def check_one(em):
    d = os.path.join(CONV, em)
    r = {'models': {}, 'textures': {}, 'lists': {}, 'problems': []}
    for mp in sorted(glob.glob(os.path.join(d, '*.mod'))):
        n = os.path.splitext(os.path.basename(mp))[0]
        h = mod_header(mp)
        gp = os.path.join(d, n + '.glb')
        m = r['models'][n] = {'mod': h}
        if not os.path.isfile(gp):
            r['problems'].append(f'{n}: no glb')
            continue
        j, b = glb_json(gp)
        verts = sum(j['accessors'][pr['attributes']['POSITION']]['count']
                    for me in j.get('meshes', []) for pr in me['primitives'])
        prims = sum(len(me['primitives']) for me in j.get('meshes', []))
        bone_nodes = [nd for nd in j['nodes'] if re.match(r'^\d+:\d+$', nd.get('name', ''))]
        m['glb'] = {'verts': verts, 'prims': prims, 'bone_nodes': len(bone_nodes),
                    'skins': [len(s['joints']) for s in j.get('skins', [])]}
        if verts != h['verts']:
            r['problems'].append(f'{n}: glb verts {verts} != mod {h["verts"]}')
        if prims != h['meshes']:
            r['problems'].append(f'{n}: glb prims {prims} != mod meshes {h["meshes"]}')
        if len(bone_nodes) != h['bones']:
            r['problems'].append(f'{n}: glb bone nodes {len(bone_nodes)} != mod bones {h["bones"]}')
        for nd in j['nodes']:
            for k in ('translation', 'rotation', 'scale'):
                if any(not math.isfinite(v) for v in nd.get(k, [])):
                    r['problems'].append(f'{n}: non-finite {k} on node {nd.get("name")}')
    for tp in sorted(glob.glob(os.path.join(d, '*.tex'))):
        n = os.path.basename(tp)
        dp = tp + '.dds'
        if not os.path.isfile(dp):
            r['problems'].append(f'{n}: no dds')
            continue
        try:
            from PIL import Image
            r['textures'][n] = list(Image.open(dp).size)
        except Exception as e:
            r['problems'].append(f'{n}: dds unreadable ({e})')
    for lp in sorted(glob.glob(os.path.join(d, '*.lmt'))):
        n = os.path.splitext(os.path.basename(lp))[0]
        ver, mots = lmt_motions(lp)
        authored = len(mots)
        op = os.path.join(d, 'anim', n + '_out.glb')
        L = r['lists'][n] = {'lmt_version': ver, 'authored': authored}
        if not os.path.isfile(op):
            r['problems'].append(f'{n}: no animation output')
            continue
        j, b = glb_json(op)
        anims = [a for a in j.get('animations', []) if a.get('channels')]
        base = {int(mm.group(1)) for a in anims for mm in [re.match(r'Motion\[(\d+)\]', a['name'])] if mm}
        bad, dur = 0, []
        for a in anims:
            mx = 0.0
            for s in a['samplers']:
                mx = max(mx, j['accessors'][s['input']].get('max', [0])[0])
                if any(not math.isfinite(v) for v in accessor_floats(j, b, s['output'])):
                    bad += 1
            dur.append(mx)
        L.update({'clips': len(anims), 'motions': len(base), 'nonfinite_samplers': bad,
                  'duration_s': [round(min(dur), 2), round(max(dur), 2)] if dur else None})
        # lmt_to_gltf leaves out a motion that drives only one or two bones (Rathian's 96/97/99: a
        # single jaw or eye track, a layer played over a body motion); those are listed, not problems
        lost = sorted(set(mots) - base)
        layers = [i for i in lost if len(mots[i]) <= 2]
        if layers:
            L['layersDropped'] = {i: sorted(mots[i]) for i in layers}
        if len(lost) > len(layers):
            r['problems'].append(f'{n}: motions not converted {[i for i in lost if i not in layers]}')
        if bad:
            r['problems'].append(f'{n}: {bad} samplers with NaN/Inf')
    return r


def check(ems):
    path = os.path.join(CONV, 'report.json')
    report = json.load(open(path)) if os.path.isfile(path) else {}
    for em in ems:
        if os.path.isdir(os.path.join(CONV, em)):
            report[em] = check_one(em)
    report = dict(sorted(report.items()))
    json.dump(report, open(path, 'w'), indent=1)
    models = sum(len(v['models']) for v in report.values())
    texs = sum(len(v['textures']) for v in report.values())
    lists = sum(len(v['lists']) for v in report.values())
    clips = sum(L.get('clips', 0) for v in report.values() for L in v['lists'].values())
    probs = [(em, p) for em, v in report.items() for p in v['problems']]
    print(f'{len(report)} monsters, {models} models, {texs} textures, {lists} motion lists, {clips} clips')
    print(f'{len(probs)} problems')
    for em, p in probs[:80]:
        print(' ', em, p)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--only')
    ap.add_argument('--check', action='store_true')
    opt = ap.parse_args()
    ems = monsters()
    if opt.only:
        want = set(opt.only.split(','))
        ems = [e for e in ems if e in want]
    if not opt.check:
        os.makedirs(CONV, exist_ok=True)
        for em in ems:
            n = stage(em)
            convert(em)
            print(em, 'staged', n, flush=True)
        for em in ems:
            convert_lists(em)
    check(ems)
