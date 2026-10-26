"""glb helpers of the MH3U Monster Viewer's build_viewer.py, unchanged: read/write, skin merge, the
v flip, compaction, bone names, the .mod mesh table, and the motion-list strip."""
import collections, json, re, struct

MASK_DRAWN = 0x0001     # mesh-table +0 word, bit 0: drawn in the main colour pass (as in MHGU and 3U)
MASK_KEPT = 0x8000      # bit 15: exported by mod_to_gltf


# ---- glb io --------------------------------------------------------------------------------

def glb_read(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'glTF', path
    off, js, bin_ = 12, None, b''
    while off < len(d):
        ln, ty = struct.unpack_from('<II', d, off)
        chunk = d[off + 8:off + 8 + ln]
        if ty == 0x4E4F534A:
            js = json.loads(chunk)
        elif ty == 0x004E4942:
            bin_ = chunk
        off += 8 + ln
    return js, bytearray(bin_)


def glb_write(path, js, bin_):
    js['buffers'] = [{'byteLength': len(bin_)}]
    jb = json.dumps(js, separators=(',', ':')).encode('utf-8')
    jb += b' ' * (-len(jb) % 4)
    bb = bytes(bin_) + b'\0' * (-len(bin_) % 4)
    with open(path, 'wb') as f:
        f.write(b'glTF' + struct.pack('<II', 2, 12 + 8 + len(jb) + 8 + len(bb)))
        f.write(struct.pack('<II', len(jb), 0x4E4F534A) + jb)
        f.write(struct.pack('<II', len(bb), 0x004E4942) + bb)


FMT = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def acc_read(js, bin_, ai):
    a = js['accessors'][ai]
    bv = js['bufferViews'][a['bufferView']]
    n, f = NCOMP[a['type']], FMT[a['componentType']]
    size = struct.calcsize(f)
    stride = bv.get('byteStride', size * n)
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    return [struct.unpack_from('<' + f * n, bin_, base + i * stride) for i in range(a['count'])]


def acc_append(js, bin_, rows, ctype, atype, extra=None):
    """Append rows as a new tightly packed accessor + bufferView; returns the accessor index."""
    while len(bin_) % 4:
        bin_.append(0)
    f = FMT[ctype]
    start = len(bin_)
    for r in rows:
        bin_ += struct.pack('<' + f * len(r), *r)
    js['bufferViews'].append({'buffer': 0, 'byteOffset': start, 'byteLength': len(bin_) - start})
    acc = {'bufferView': len(js['bufferViews']) - 1, 'componentType': ctype, 'count': len(rows), 'type': atype}
    if extra:
        acc.update(extra)
    js['accessors'].append(acc)
    return len(js['accessors']) - 1


# ---- skins -----------------------------------------------------------------------------------

def merge_skins(js, bin_):
    """Fold every skin into skins[0]. The joints keep skin 0's order and gain the others' in
    first-seen order; each primitive's JOINTS_n is rewritten from its own skin's palette index to
    the merged one. The merge is only legal if a joint's inverse bind matrix is the same in every
    skin that lists it -- checked, and the build fails on a disagreement, because a different IBM
    would mean the palettes are not the same bind pose."""
    skins = js.get('skins') or []
    if len(skins) <= 1:
        return {'skins': len(skins), 'merged': False}
    union, ibm = [], {}
    worst = 0.0
    for s in skins:
        mats = acc_read(js, bin_, s['inverseBindMatrices'])
        for jn, m in zip(s['joints'], mats):
            if jn not in ibm:
                ibm[jn] = m
                union.append(jn)
            else:
                worst = max(worst, max(abs(a - b) for a, b in zip(ibm[jn], m)))
    if worst > 1e-4:
        raise ValueError('inverse bind matrices disagree between skins (%.6f)' % worst)
    at = {jn: i for i, jn in enumerate(union)}
    new_ibm = acc_append(js, bin_, [ibm[jn] for jn in union], 5126, 'MAT4')
    mesh_skin = {}
    for nd in js['nodes']:
        if 'mesh' in nd and 'skin' in nd:
            prev = mesh_skin.setdefault(nd['mesh'], nd['skin'])
            if prev != nd['skin']:
                raise ValueError('mesh %d is drawn with two different skins' % nd['mesh'])
    for mi, si in mesh_skin.items():
        remap = [at[jn] for jn in skins[si]['joints']]
        for pr in js['meshes'][mi]['primitives']:
            for key in [k for k in pr['attributes'] if k.startswith('JOINTS_')]:
                rows = [tuple(remap[x] for x in r) for r in acc_read(js, bin_, pr['attributes'][key])]
                ct = 5121 if len(union) < 256 else 5123
                pr['attributes'][key] = acc_append(js, bin_, rows, ct, 'VEC4')
    for nd in js['nodes']:
        if 'skin' in nd:
            nd['skin'] = 0
    merged = {'inverseBindMatrices': new_ibm, 'joints': union}
    if 'skeleton' in skins[0]:
        merged['skeleton'] = skins[0]['skeleton']
    js['skins'] = [merged]
    return {'skins': len(skins), 'merged': True, 'joints': len(union), 'ibmMaxDiff': worst}


def flip_v(js, bin_):
    """v -> 1 - v on every TEXCOORD_n. The 3DS samples texture-memory row H - 1 - v*H for a UV v
    (the PICA rasteriser flips t before the lookup; Citra's texture sampling), and the textures are
    decoded in memory order -- pica_tex.py reproduces RevilToolset's DDS exactly in that orientation.
    mod_to_gltf copies the .mod's float v unchanged (bytes 16/20 of the 36-byte vertex, measured), so
    every texture landed mirrored top to bottom. Proof on Rathian: its eye material's patch is the
    eye only after this flip. Shared accessors are rewritten once."""
    done = {}
    for me in js['meshes']:
        for pr in me['primitives']:
            for key in [k for k in pr['attributes'] if k.startswith('TEXCOORD_')]:
                ai = pr['attributes'][key]
                if ai not in done:
                    a = js['accessors'][ai]
                    assert a['componentType'] == 5126 and not a.get('normalized'), 'quantised UVs: flip needs a transform'
                    rows = [(u, 1.0 - v) for u, v in acc_read(js, bin_, ai)]
                    vs = [r[1] for r in rows]
                    done[ai] = acc_append(js, bin_, rows, 5126, 'VEC2',
                                          {'min': [min(r[0] for r in rows), min(vs)],
                                           'max': [max(r[0] for r in rows), max(vs)]})
                pr['attributes'][key] = done[ai]
    return len(done)


def compact(js, bin_):
    """Drop accessors and buffer views nothing references any more. merge_skins and flip_v append
    replacements and leave the originals behind; without this each model ships them as dead bytes."""
    used = set()
    for me in js.get('meshes', []):
        for pr in me['primitives']:
            used.update(pr['attributes'].values())
            if 'indices' in pr:
                used.add(pr['indices'])
            for t in pr.get('targets', []):
                used.update(t.values())
    for s in js.get('skins', []):
        if 'inverseBindMatrices' in s:
            used.add(s['inverseBindMatrices'])
    for a in js.get('animations', []):
        for s in a['samplers']:
            used.update((s['input'], s['output']))
    amap = {old: new for new, old in enumerate(sorted(used))}
    accs = [dict(js['accessors'][old]) for old in sorted(used)]
    vmap, views, out = {}, [], bytearray()
    for acc in accs:
        bvi = acc.get('bufferView')
        if bvi is None:
            continue
        if bvi not in vmap:
            bv = js['bufferViews'][bvi]
            while len(out) % 4:
                out.append(0)
            nb = {k: v for k, v in bv.items() if k not in ('byteOffset', 'buffer')}
            nb.update({'buffer': 0, 'byteOffset': len(out)})
            out += bin_[bv.get('byteOffset', 0):bv.get('byteOffset', 0) + bv['byteLength']]
            vmap[bvi] = len(views)
            views.append(nb)
        acc['bufferView'] = vmap[bvi]
    for me in js.get('meshes', []):
        for pr in me['primitives']:
            pr['attributes'] = {k: amap[v] for k, v in pr['attributes'].items()}
            if 'indices' in pr:
                pr['indices'] = amap[pr['indices']]
            if 'targets' in pr:
                pr['targets'] = [{k: amap[v] for k, v in t.items()} for t in pr['targets']]
    for s in js.get('skins', []):
        if 'inverseBindMatrices' in s:
            s['inverseBindMatrices'] = amap[s['inverseBindMatrices']]
    for a in js.get('animations', []):
        for s in a['samplers']:
            s['input'], s['output'] = amap[s['input']], amap[s['output']]
    js['accessors'], js['bufferViews'] = accs, views
    bin_[:] = out
    return len(amap)


def joints_of(js):
    out = []
    for idx in (js.get('skins') or [{}])[0].get('joints', []):
        m = re.match(r'^\d+:(\d+)(_s)?$', js['nodes'][idx].get('name', ''))
        out.append({'gid': int(m.group(1)) if m else None, 'leaf': bool(m and m.group(2))})
    return out


def bone_nodes(js, notes=None, who=''):
    """EVERY bone node of a model as [three.js name, gid, leaf], not only the skinned ones. A
    severed piece is skinned to joints the body may not skin at all (Rathalos' body binds nothing to
    tail gid 145, its piece binds its tip there), so attaching a piece needs the body's whole
    skeleton addressable by global id. three.js drops '[', ']', '.', ':' and '/' from a node name, so
    "31:145" arrives as "31145"; a collision would make a name ambiguous and is reported."""
    out, seen = [], {}
    for nd in js['nodes']:
        name = nd.get('name', '')
        m = re.match(r'^\d+:(\d+)(_s)?$', name)
        if not m:
            continue
        tname = re.sub(r'[\[\].:/]', '', name)
        if tname in seen and notes is not None:
            notes.append('%s: bone names %s and %s both arrive as %s' % (who, seen[tname], name, tname))
        seen[tname] = name
        out.append([tname, int(m.group(1)), bool(m.group(2))])
    return out


# ---- the .mod mesh table -----------------------------------------------------------------------

def mod_info(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'MOD\0' and struct.unpack_from('<H', d, 4)[0] == 0xE6, path
    bones, meshes, mats = struct.unpack_from('<HHH', d, 6)
    verts = struct.unpack_from('<I', d, 12)[0]
    off = struct.unpack_from('<I', d, 0x34)[0]          # 3U v0xE6; MHGU's v0xD4 keeps it at +0x30
    table = []
    for i in range(meshes):
        mask, nv, lvl = struct.unpack_from('<HHH', d, off + 48 * i)
        table.append({'mask': mask, 'verts': nv, 'part': lvl & 0xFFF, 'lvl': lvl >> 12})
    return {'bones': bones, 'meshes': meshes, 'materials': mats, 'verts': verts, 'table': table}


def prim_rows(js, table):
    """(part, verts) of every primitive in the viewer's walk order, and the ordinals whose mesh
    row lacks the draw bit. Matched as a multiset per (part, verts), consuming rows in table order
    among equals -- MHGU's rule, because the converter groups primitives by part."""
    prims = []
    for nd in js['nodes']:
        if 'mesh' not in nd:
            continue
        mm = re.match(r'^Group\[(\d+)\]', nd.get('name', ''))
        part = int(mm.group(1)) if mm else 0
        for pr in js['meshes'][nd['mesh']]['primitives']:
            prims.append((part, js['accessors'][pr['attributes']['POSITION']]['count']))
    pool = collections.defaultdict(list)
    for e in table:
        if e['mask'] & MASK_KEPT:
            pool[(e['part'], e['verts'])].append(e['mask'])
    hide, unmatched, ambiguous = [], [], []
    for i, key in enumerate(prims):
        row = pool.get(key)
        if not row:
            unmatched.append(list(key))
            continue
        # only a disagreement on the DRAW bit can change what is hidden; the mask's other bits
        # vary among drawn rows (0xedd7 / 0xecd3) and are not read here
        if len({m & MASK_DRAWN for m in row}) > 1:
            ambiguous.append(list(key))
        if not (row.pop(0) & MASK_DRAWN):
            hide.append(i)
    return prims, hide, unmatched, ambiguous


# ---- motion lists --------------------------------------------------------------------------------

def strip_to_animation(src, dst, model_node_names):
    """Keep the node tree and the animations of a lmt_to_gltf result; drop mesh, skin, materials
    and the buffer ranges only they used (MHGU harvest-monsters.py's pass)."""
    js, bin_ = glb_read(src)
    names = [n.get('name', '') for n in js['nodes']]
    keep, amap, anims, dropped = [], {}, [], collections.Counter()
    for a in js.get('animations', []):
        chans, used = [], set()
        for c in a['channels']:
            nm = names[c['target']['node']]
            if nm not in model_node_names:
                dropped[nm] += 1
                continue
            chans.append(c)
            used.add(c['sampler'])
        smap, samplers = {}, []
        for si, s in enumerate(a['samplers']):
            if si not in used:
                continue
            for k in ('input', 'output'):
                if s[k] not in amap:
                    amap[s[k]] = len(keep)
                    keep.append(s[k])
            smap[si] = len(samplers)
            samplers.append(dict(s, input=amap[s['input']], output=amap[s['output']]))
        for c in chans:
            c['sampler'] = smap[c['sampler']]
        anims.append({'name': a.get('name'), 'channels': chans, 'samplers': samplers})
    new_acc, new_bv, bvmap, out = [], [], {}, bytearray()
    for ai in keep:
        acc = dict(js['accessors'][ai])
        bvi = acc.get('bufferView')
        if bvi is not None:
            if bvi not in bvmap:
                bv = js['bufferViews'][bvi]
                start, ln = bv.get('byteOffset', 0), bv['byteLength']
                while len(out) % 4:
                    out.append(0)
                nb = {'buffer': 0, 'byteOffset': len(out), 'byteLength': ln}
                if 'byteStride' in bv:
                    nb['byteStride'] = bv['byteStride']
                out += bin_[start:start + ln]
                bvmap[bvi] = len(new_bv)
                new_bv.append(nb)
            acc['bufferView'] = bvmap[bvi]
        new_acc.append(acc)
    nodes = [{k: v for k, v in n.items() if k not in ('mesh', 'skin', 'weights')} for n in js['nodes']]
    js2 = {'asset': {'version': '2.0', 'generator': 'build_viewer.py (nodes + animations)'},
           'scene': js.get('scene', 0), 'scenes': js['scenes'], 'nodes': nodes,
           'animations': anims, 'accessors': new_acc, 'bufferViews': new_bv}
    glb_write(dst, js2, out)
    return dropped


def clip_list(path):
    js, _ = glb_read(path)
    out = []
    for a in js.get('animations', []):
        d = 0.0
        for s in a['samplers']:
            mx = js['accessors'][s['input']].get('max')
            if mx:
                d = max(d, mx[0])
        out.append({'clip': a.get('name', ''), 'dur': round(d, 3)})
    return out




# ---- the second UV (4U) --------------------------------------------------------------------------

UV2_FMT = {0x866B6018: 44}      # the 36-byte layout, then f32 uv2[2] at +36 (convert_monsters.py REPACK)


def add_uv2(js, bin_, mod_path):
    """TEXCOORD_1 on every primitive cut from a 44-byte .mod mesh (0x866B6018), from the .mod's own uv2.
    convert_monsters.py repacks those meshes to 36 bytes so mod_to_gltf can read them, which drops uv2;
    the shaders take it as UV_Extend (LtShaderPackage.lfx, IABGBase: TexCoord #1 -> UV_Extend), the UV the
    second albedo map (tExtendMap) samples. A primitive is matched to its mesh by vertex count and the
    exact f32 positions (the glb groups primitives by part, not in table order). Call before flip_v, which
    flips every TEXCOORD_n alike. Returns the number of primitives given a TEXCOORD_1."""
    d = open(mod_path, 'rb').read()
    h = struct.unpack_from('<16I', d, 0)
    nmesh = struct.unpack_from('<H', d, 8)[0]
    mo, vb = h[13], h[14]
    meshes = []
    for i in range(nmesh):
        r = d[mo + 48 * i:mo + 48 * (i + 1)]
        nv, stride = struct.unpack_from('<H', r, 2)[0], r[0xA]
        first, boff, fmt = struct.unpack_from('<III', r, 0xC)
        if fmt not in UV2_FMT:
            continue
        base = vb + boff + first * stride
        pos = [struct.unpack_from('<3f', d, base + k * stride) for k in range(nv)]
        uv2 = [struct.unpack_from('<2f', d, base + k * stride + 36) for k in range(nv)]
        meshes.append((nv, pos, uv2))
    if not meshes:
        return 0
    n = 0
    used = set()
    for me in js['meshes']:
        for pr in me['primitives']:
            pa = pr['attributes'].get('POSITION')
            if pa is None or 'TEXCOORD_1' in pr['attributes']:
                continue
            cnt = js['accessors'][pa]['count']
            cands = [i for i, m in enumerate(meshes) if m[0] == cnt and i not in used]
            if not cands:
                continue
            pos = acc_read(js, bin_, pa)
            for i in cands:
                if all(abs(a - b) < 1e-4 for p, q in zip(pos, meshes[i][1]) for a, b in zip(p, q)):
                    rows = meshes[i][2]
                    pr['attributes']['TEXCOORD_1'] = acc_append(js, bin_, rows, 5126, 'VEC2',
                        {'min': [min(r[0] for r in rows), min(r[1] for r in rows)],
                         'max': [max(r[0] for r in rows), max(r[1] for r in rows)]})
                    used.add(i)
                    n += 1
                    break
    return n
