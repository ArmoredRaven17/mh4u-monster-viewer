r"""Build docs/hitzones.json and docs/hitzones/<id>.bin -- the Hit Zones panel's data -- from 4U's own files.

    python scripts/build_hitzones.py          # every monster in docs/monsters.json
    python scripts/build_hitzones.py --dry    # report only

The values, capsules, part records and state changes are scripts/hitzones4u.py's, read from 4U's code (its header
has every field and the address it was read at). The FILE CONTRACT and the BAKE are the MHGU Monster Viewer's
(C:\MHGU-Extract\build-hitzones.py), so the page's Hit Zones panel -- GU's -- reads it unchanged:

  bin        u32 primCount, primCount x u32 vertexCount, then two equal blocks of one byte per vertex in primitive
             order: the hit-zone slot, then the part record. Primitives are the glb's in file order, the proxy
             layer (monsters.json hideIdx) left out, as the page counts them.
  the bake   GU's viewer rule, not the game's: a drawn vertex takes the smallest capsule containing it that hangs off
             the bone it is most weighted to, else the smallest capsule containing it, else the nearest surface.
             Capsule = boneWorld @ (point / 100), radius / 100, in the bind pose.
  capsules   [slot, part, shape, boneA, boneB, radius, ax, ay, az, bx, by, bz], every record, in game units.
  capsuleFlags   capsule +0xa. 4U's weapon hit test (0xbedd3c, read 2026-10-17) is GU's 0x16bc54 bit for bit
             on the bits the page uses: attack types 37-47 count a capsule only with 0x4, type 8 with 0x3, type 9
             with 0x18, every other type skips one with any of 0x0152; 0x8000 counts only while work+0x7e64 > 0
             and the attack carries 0x4 (Congalala, Kushala Daora, Teostra). So the page's zoneNeverCounted /
             zoneSpecialOnly hold for 4U as written.
  candidates for the bake: no bit of 0x0152, no 0x8000 (GU leaves conditional shapes out, Raven's call there), shape
             0-2, bone A placeable, and not a row that is 100 in all ten columns (a placeholder, GU's rule).

4U's own additions, which the page reads where present:
  tables / tableNames / tableNotes   table 0 is the default rows; each further table is ONE state of STATES
             applied to it (its slots swapped to the alternate rows, or GLOBAL_ROWS for Gogmazios' hot tar).
             tableNotes carries the condition as the code reads it, and the address.
  parts      per part record: stagger = record +0, the damage pool whose running out is counted (0x93698c);
             break = the count at which the emd break list (+0x80, rows {part, count, ...}) fires, written
             'after N staggers'; sever = the sever pool (record +6) where the record is a sever (type 1 or
             Dah'ren's 126/127). Shown in the Parts pane.
  The Apex forms get their own records under their own ids (their tune data is their own); the page reads them
  while the Apex switch is on.
"""
import collections, json, os, re, struct, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hitzones4u as hz

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DOCS = os.path.join(ROOT, 'docs')
OUTDIR = os.path.join(DOCS, 'hitzones')
OUTJSON = os.path.join(DOCS, 'hitzones.json')
DRY = '--dry' in sys.argv
TYPES = hz.COLUMNS
CT = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2), 5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
NEVER_COMMON = 0x0152


# ---- glb helpers (the GU builder's) -------------------------------------------------------------------------------
def glb_split(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'glTF', path
    off, js, bin_ = 12, None, b''
    while off < len(d):
        ln, ty = struct.unpack_from('<II', d, off)
        chunk = d[off + 8: off + 8 + ln]
        if ty == 0x4E4F534A: js = json.loads(chunk.decode('utf-8'))
        elif ty == 0x004E4942: bin_ = chunk
        off += 8 + ln
    return js, bin_


def acc_raw(js, bin_, i):
    a = js['accessors'][i]
    bv = js['bufferViews'][a['bufferView']]
    fmt, sz = CT[a['componentType']]
    n = NC[a['type']]
    stride = bv.get('byteStride') or sz * n
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    if stride == sz * n:
        return np.frombuffer(bin_, dtype=np.dtype('<' + fmt), count=a['count'] * n, offset=base).reshape(-1, n)
    out = np.empty((a['count'], n), dtype=np.dtype('<' + fmt))
    for k in range(a['count']):
        out[k] = struct.unpack_from('<%d%s' % (n, fmt), bin_, base + k * stride)
    return out


def node_world_all(js):
    par = {}
    for i, nd in enumerate(js['nodes']):
        for c in nd.get('children', []): par[c] = i

    def local(i):
        nd = js['nodes'][i]
        if 'matrix' in nd:
            return np.array(nd['matrix'], float).reshape(4, 4).T
        M = np.eye(4)
        x, y, z, w = nd.get('rotation', [0, 0, 0, 1])
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)
        M[:3, :3] = R @ np.diag(nd.get('scale', [1, 1, 1]))
        M[:3, 3] = nd.get('translation', [0, 0, 0])
        return M

    out = {}
    for i in range(len(js['nodes'])):
        M, k, chain = np.eye(4), i, []
        while k is not None:
            chain.append(k); k = par.get(k)
        for k in reversed(chain): M = M @ local(k)
        out[i] = M
    return out


def bind_matrix(js, bin_, world):
    sk = js['skins'][0]
    raw = acc_raw(js, bin_, sk['inverseBindMatrices']).astype(np.float64)
    ibm = raw.reshape(-1, 4, 4).transpose(0, 2, 1)
    Ms = np.array([world[n] @ ibm[k] for k, n in enumerate(sk['joints'])])
    return Ms.mean(0), float(np.abs(Ms - Ms[0]).max())


def bone_world(js, world):
    out = {}
    for i, nd in enumerate(js['nodes']):
        m = re.match(r'^(\d+):(\d+)', nd.get('name', '') or '')
        if m: out[int(m.group(2))] = world[i]
    return out


def game_units(x):
    v = round(float(x), 3)
    return int(v) if v == int(v) else v


def capsule_world(c, bw):
    s = 0.01
    a, b = c['bones']
    if c['shape'] not in (0, 1, 2) or a not in bw: return None
    pa = (bw[a] @ np.append(np.array(c['pa']) * s, 1.0))[:3]
    if c['shape'] == 0:
        pb = pa
    elif c['shape'] == 1:
        pb = (bw[a] @ np.append(np.array(c['pb']) * s, 1.0))[:3]
    else:
        if b not in bw: return None
        pb = (bw[b] @ np.append(np.array(c['pb']) * s, 1.0))[:3]
    return pa, pb, c['radius'] * s


def nearest_slot(P, caps, dom):
    """GU's rule (its build-hitzones.py nearest_slot): same-bone smallest containing, else smallest containing,
    else nearest surface."""
    best = np.full(len(P), np.inf)
    slot = np.zeros(len(P), dtype=np.uint8); part = np.zeros(len(P), dtype=np.uint8)
    in_r = np.full(len(P), np.inf)
    in_slot = np.zeros(len(P), dtype=np.uint8); in_part = np.zeros(len(P), dtype=np.uint8)
    same_r = np.full(len(P), np.inf)
    same_slot = np.zeros(len(P), dtype=np.uint8); same_part = np.zeros(len(P), dtype=np.uint8)
    for pa, pb, r, sl, pt, ba, bb in caps:
        ab = pb - pa
        L2 = float(ab @ ab)
        if L2 < 1e-12:
            d = np.linalg.norm(P - pa, axis=1) - r
        else:
            t = np.clip(((P - pa) @ ab) / L2, 0.0, 1.0)[:, None]
            d = np.linalg.norm(P - (pa + t * ab), axis=1) - r
        hit = d < best
        best[hit] = d[hit]; slot[hit] = sl; part[hit] = pt
        inside = (d < 0) & (r < in_r)
        in_r[inside] = r; in_slot[inside] = sl; in_part[inside] = pt
        if dom is not None:
            own = (d < 0) & ((dom == ba) | (dom == bb)) & (r < same_r)
            same_r[own] = r; same_slot[own] = sl; same_part[own] = pt
    held = np.isfinite(in_r)
    slot[held] = in_slot[held]; part[held] = in_part[held]
    own = np.isfinite(same_r)
    slot[own] = same_slot[own]; part[own] = same_part[own]
    return slot, part, best


# ---- the 4U record ------------------------------------------------------------------------------------------------
def break_list(emd):
    """emd +0x80: 32-byte rows {u8 part, u8 count, ...} to a 0xff part (read by 0x942a50 / 0x9447b0)."""
    o, out = hz.u32(emd, 0x80), []
    while o and o + 32 <= len(emd) and emd[o] != 0xff:
        out.append((emd[o], emd[o + 1]))
        o += 32
        assert len(out) < 64
    return out


COUNT_RE = re.compile(r'^part (\d+) (?:sever )?count >= (\d+)')


def state_label(s, breaks):
    """The page's short name for a state. A part-count rule is 'Part N broken' when the break list fires at that
    count, else 'Part N staggered k x'; the rest carry their own `label`, else the condition up to its first aside."""
    if s.get('label'):
        return s['label']
    m = COUNT_RE.match(s['on'])
    if m and ' sever ' not in s['on']:
        p, c = int(m.group(1)), int(m.group(2))
        return 'Part %d broken' % p if (p, c) in breaks else 'Part %d staggered %dx' % (p, c)
    m = re.match(r'^parts (\d+) and (\d+) both count >= (\d+)', s['on'])
    if m:
        a, b, c = map(int, m.groups())
        if (a, c) in breaks and (b, c) in breaks:
            return 'Parts %d and %d broken' % (a, b)
        return 'Parts %d and %d staggered %dx' % (a, b, c)
    lab = re.split(r' \(|: |, | -- ', s['on'])[0]
    return lab[0].upper() + lab[1:]


def part_rows(d, breaks):
    out = []
    for i, (pool, limit, typ, b5, sever, b8) in enumerate(d['parts']):
        at = sorted(c for p, c in breaks if p == i)
        out.append({'stagger': pool or None,
                    'break': ('after %s stagger%s' % (' / '.join(map(str, at)), '' if at == [1] else 's')) if at else None,
                    'sever': sever if limit and sever != 0xffff else None})
    return out


def as_row(r):
    return {t: v for t, v in zip(TYPES, r)}


def tables_of(d, states, glob, breaks):
    base = [as_row(r) for r in d['zones']]
    tables, names, notes = [base], ['Default'], ['']
    for s in states:
        t = [dict(r) for r in base]
        for slot, row in s['slots'].items():
            if row is None:
                continue
            if isinstance(row, str):
                t[slot] = as_row(glob[int(row[1:])])
            else:
                t[slot] = as_row(d['alt'][row])
        tables.append(t)
        names.append(state_label(s, breaks))
        notes.append('%s (%s)' % (s['on'], s['src']))
    return tables, names, notes


def bake(e, d, emd, glob, stats):
    glb = os.path.join(DOCS, e['glb'])
    js, bin_ = glb_split(glb)
    if 'skins' not in js:
        stats['unskinned'] += 1
        return None, None
    world = node_world_all(js)
    M, spread = bind_matrix(js, bin_, world)
    if spread > 1e-4:
        stats['not in bind pose'] += 1
        return None, None
    bw = bone_world(js, world)
    dead = {sl for sl, r in enumerate(d['zones']) if all(v == 100 for v in r)}
    caps = []
    for c in d['capsules']:
        if c['slot'] in dead: stats['capsule on a placeholder row'] += 1; continue
        if c['flags'] & 0x8000: stats['capsule conditional (0x8000)'] += 1; continue
        if c['flags'] & NEVER_COMMON: stats['capsule common attacks never count'] += 1; continue
        w = capsule_world(c, bw)
        if w is None: stats['capsule unplaceable'] += 1; continue
        a, b = c['bones']
        caps.append((w[0], w[1], w[2], c['slot'], c['part'], a, b if c['shape'] == 2 else a))
    if not caps:
        stats['no capsule placed'] += 1
        return None, None
    hide = set(e.get('hideIdx') or [])
    joint_gid = []
    for nd in js['skins'][0]['joints']:
        mg = re.match(r'^(\d+):(\d+)', js['nodes'][nd].get('name', '') or '')
        joint_gid.append(int(mg.group(2)) if mg else -1)
    joint_gid = np.array(joint_gid)
    prims, blobs, pblobs, n, diag = [], [], [], 0, None
    for me in js.get('meshes', []):
        for pr in me['primitives']:
            if n in hide:
                n += 1; continue
            a = js['accessors'][pr['attributes']['POSITION']]
            raw = acc_raw(js, bin_, pr['attributes']['POSITION']).astype(np.float64)
            if a.get('normalized'): raw = raw / 32767.0
            P = (M @ np.hstack([raw, np.ones((len(raw), 1))]).T).T[:, :3]
            if diag is None:
                diag = float(np.linalg.norm(P.max(0) - P.min(0))) or 1.0
            dom = None
            if 'JOINTS_0' in pr['attributes'] and 'WEIGHTS_0' in pr['attributes']:
                J = acc_raw(js, bin_, pr['attributes']['JOINTS_0']).astype(np.int64)
                Wt = acc_raw(js, bin_, pr['attributes']['WEIGHTS_0']).astype(np.float64)
                dom = joint_gid[J[np.arange(len(J)), np.argmax(Wt, axis=1)]]
            sl, pt, dist = nearest_slot(P, caps, dom)
            stats['vertices'] += len(P)
            stats['vertices far (>5% of the model outside every capsule)'] += int((dist > 0.05 * diag).sum())
            prims.append((n, len(P)))
            blobs.append(sl.tobytes()); pblobs.append(pt.tobytes())
            n += 1
    blob = struct.pack('<I', len(prims)) + b''.join(struct.pack('<I', c) for _, c in prims)
    blob += b''.join(blobs) + b''.join(pblobs)
    used = sorted({int(x) for s in blobs for x in s})
    rec = {'prims': [p for p, _ in prims], 'slotsUsed': used,
           'partsUsed': sorted({int(x) for s in pblobs for x in s}),
           'slotsDefined': sorted({c['slot'] for c in d['capsules'] if c['slot'] not in dead})}
    return rec, blob


# TWO UNITS, ONE MODEL: Dalamadur. em083 (Shah: em111) shares em024's (em110's) model, its capsules hang off the
# rear bones 140-157 and em024's off 1-16 / 101-107 with none in common, every quest that has one spawns both, and
# em083's own rules include a severed tail -- it is the tail half, a unit with its own damage table, part records and
# state code (uEm083). The page draws one model with one table, so the halves are merged into one record: the tail
# half's slots and part records become 8-15, its rows follow the head half's, and its states are its own with
# 'Tail half:' before their names. The record is filed under both ids, so either dropdown entry shows the whole body.
UNITS = {'em024': 'em083', 'em110': 'em111'}
OFFSET = 8


def merge_units(front, rear, fstates, rstates, fbreaks, rbreaks):
    d = dict(front)
    d['zones'] = front['zones'] + rear['zones']
    d['alt'] = (front['alt'] or front['zones']) + (rear['alt'] or rear['zones'])
    d['parts'] = front['parts'] + rear['parts']
    d['capsules'] = front['capsules'] + [dict(c, slot=c['slot'] + OFFSET, part=c['part'] + OFFSET)
                                         for c in rear['capsules']]
    shifted = []
    for s in rstates:
        s = dict(s, slots={k + OFFSET: (v + OFFSET if isinstance(v, int) else v) for k, v in s['slots'].items()},
                 on=s['on'])
        named = dict(s, on=re.sub(r'(?<=part )\d', lambda m: str(int(m.group()) + OFFSET), s['on']))
        s['label'] = 'Tail half: ' + state_label(named, {(p + OFFSET, c) for p, c in rbreaks})
        shifted.append(s)
    return d, fstates + shifted, fbreaks + [(p + OFFSET, c) for p, c in rbreaks]


def main():
    mon = json.load(open(os.path.join(DOCS, 'monsters.json'), encoding='utf-8'))['monsters']
    files = hz.files()
    data = {em: hz.read(em, fb) for em, fb in files.items() if 'emd' in fb and 'etd' in fb}
    rears = set(UNITS.values())
    glob = hz.global_rows()
    stats = collections.Counter()
    out = {'_about': {'source': 'scripts/hitzones4u.py (4U code, addresses in its header); bake and contract: '
                                'the MHGU Monster Viewer build-hitzones.py; see scripts/build_hitzones.py',
                      'types': TYPES},
           'monsters': {}}
    blobs = {}
    for e in mon:
        ids = [(e['id'], e['id'])] + ([(e['apex']['id'], e['id'])] if e.get('apex') else [])
        for hid, _ in ids:
            d = data.get(hid)
            if not d or not e.get('glb'):
                stats['no 4U data (%s)' % hid] += 1
                continue
            if hid in rears:
                continue                  # filed with its head half below
            states = hz.states_of(hid)
            breaks = break_list(files[hid]['emd'])
            rear = UNITS.get(hid)
            if rear:
                d, states, breaks = merge_units(d, data[rear], states, hz.states_of(rear), breaks,
                                                break_list(files[rear]['emd']))
            rec, blob = bake(e, d, files[hid]['emd'], glob, stats)
            if rec is None:
                continue
            tables, names, notes = tables_of(d, states, glob, breaks)
            rec.update({'bin': 'hitzones/%s.bin' % hid, 'tables': tables, 'tableNames': names,
                        'tableNotes': notes, 'parts': part_rows(d, breaks), 'hp': d['hp'],
                        'capsules': [[c['slot'], c['part'], c['shape'], c['bones'][0], c['bones'][1],
                                      game_units(c['radius'])] + [game_units(x) for x in c['pa']]
                                     + [game_units(x) for x in c['pb']] for c in d['capsules']],
                        'capsuleFlags': [c['flags'] for c in d['capsules']],
                        'capsuleSever': [c['state'] for c in d['capsules']]})
            out['monsters'][hid] = rec
            blobs[hid] = blob
            if rear:
                rec['units'] = {'head half': hid, 'tail half': rear, 'tailSlotsFrom': OFFSET}
                out['monsters'][rear] = rec
    print('monsters baked', len(out['monsters']), 'of', len(mon), '(+ Apex forms)')
    for k, v in sorted(stats.items()):
        print('  %-58s %d' % (k, v))
    if stats['vertices']:
        print('  far share %.2f%%' % (100.0 * stats['vertices far (>5% of the model outside every capsule)']
                                      / stats['vertices']))
    if DRY:
        print('dry run: nothing written'); return
    os.makedirs(OUTDIR, exist_ok=True)
    for hid, blob in blobs.items():
        open(os.path.join(OUTDIR, hid + '.bin'), 'wb').write(blob)
    json.dump(out, open(OUTJSON, 'w', encoding='utf-8'), separators=(',', ':'))
    tot = os.path.getsize(OUTJSON) + sum(os.path.getsize(os.path.join(OUTDIR, f)) for f in os.listdir(OUTDIR))
    print('wrote hitzones.json + %d bins, %.1f MB' % (len(blobs), tot / 1e6))


if __name__ == '__main__':
    main()
