r"""Export a monster's effects for the viewer: docs/effects/<em>.json, the raw effect files under docs/effects/files/,
and their textures as webp in docs/tex/ (the viewer's texture pool).

    python scripts/build_effects.py em001 [em002 ...]
    python scripts/build_effects.py --flying          # every Flying Wyvern in docs/monsters.json, with its Apex

Read from 4U's code (C:\MH4U-Extract\notes\effects.md has the addresses):
  .mef  rMhMotionEffect (148b6f89), loader 0x398e6c: 'MEF\0', version 9, u32 count, 0x48-byte records. A key in
        2000..8999 resolves in the second file (0x390abc), any other key in the first. Record fields: +0 u8 condition
        (0 = always; else the bit of the driver's per-frame condition word +0x30 that must be set, 0x3918c8 -- the
        enemy base sets bits 30 / 31 from its state, 0x393368; class code sets the rest), +3 u8 type,
        +4 u16 key, +6 u16 set, +8 u16 file, +0xa s16 joint, +0xc u32 flags (0x400 = the 900.0 spawn-height check),
        +0x18 / +0x28 / +0x38 f32 x3 position / rotation / scale (0x3917dc).
  the path: READ, by running the spawn's own resolver (0x391a00) under the MH4U-Extract harness
        (tools\fx\mef_paths.py): group = u16 table 0xeede7c[type] (type 4: + set; types 5 / 0xb / 0xc map the set
        through 0x390dd0), index from 0x390b20, path = [[0xef895c + 4*group] + 4*index] (0xc09c30). On the Flying
        Wyverns: type 5 = effect\efl\em\em<set>, type 1 = effect\efl\qe\qe<set>, type 0 set 0 = effect\efl\cm\cm000.
  motion events: each LMT v67 motion has 4 "sequence pages" (+0x34; rMotionList loader 0x23e3d8 fixes them up), each
        u16 id[32] + (bits, frames) runs. READ, the driver cMhMotionEffect (enemy+0xc78):
        - its ctor 0x3933fc sets page 2, first bit 0, bit count 32 (+0x13 / +0x14 / +0x15);
        - its update 0x39329c ORs the page's runs over the frames (previous, current] (0x95fda8) into +0x24, and
          pending = bits & ~last frame's bits (+0x2c); a motion change clears last frame's bits, so a bit on at the
          first frame fires at the start;
        - the walker 0x3915bc takes each pending bit's key, ids[bit]; for an enemy it stops after bit 16, and key
          1100 is a marker (clears driver+0x11), not an effect;
        - 0x3918c8 spawns the key's record (0x391a00) when its condition is met.
        So an effect fires once, on the first frame its bit turns on.

Files an effect names are found by the paths written inside it (texture, .ean, model, material), looked up in the
archive index and taken from the monster's archive or the shared core archive.
"""
import collections, hashlib, json, os, re, struct, subprocess, sys

sys.path.insert(0, r'C:\MH4U-Extract\tools')
import arc4

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DOCS = os.path.join(ROOT, 'docs')
EXTRACT = r'C:\MH4U-Extract'
ROMFS = os.path.join(EXTRACT, 'romfs')
CORE = [os.path.join(ROMFS, 'eng', 'data', a + '.arc') for a in ('core_quest', 'core_common', 'core_lobby')]
WORK = os.path.join(EXTRACT, 'work', 'fx-export')
T_MEF, T_EFL, T_EAN, T_TEX, T_MOD, T_MRL = 0x148b6f89, 0x6d5ae854, 0x4e397417, 0x241f5deb, 0x58a15856, 0x2749c8a8
EXT = {T_EFL: 'efl', T_EAN: 'ean', T_TEX: 'tex', T_MOD: 'mod', T_MRL: 'mrl', T_MEF: 'mef'}
EFFECT_PAGE = 2      # the driver's default page (ctor 0x3933fc)
MARKER = 1100        # an enemy's page key that is not an effect (0x3916e0)


def arc_index(path):
    """{(internal path lower, type): (name, cs, ds, fl, off)}"""
    out = {}
    for name, th, cs, ds, fl, off in arc4.entries(path):
        out[(name.replace('/', '\\').lower(), th)] = (name, cs, ds, fl, off)
    return out


class Source:
    """The monster's archive (and the New 3DS copy) first, then the shared core archives."""

    def __init__(self, em, more=()):
        """`more`: other monsters' archives the effects name (a base monster's .mef also lists its Apex's set)"""
        self.arcs = [p for e in (em,) + tuple(more) for p in (os.path.join(ROMFS, 'data', e + '.arc'),
                     os.path.join(ROMFS, 'snake', 'data', e + '_.arc')) if os.path.isfile(p)] + CORE
        self.idx = [(p, arc_index(p)) for p in self.arcs]

    def get(self, path, th):
        key = (path.replace('/', '\\').lower(), th)
        for p, idx in self.idx:
            if key in idx:
                name, cs, ds, fl, off = idx[key]
                with open(p, 'rb') as f:
                    return arc4.read_entry(f, cs, ds, off), p
        return None, None

    def listing(self, th, em):
        return sorted({k[0] for p, idx in self.idx if os.path.basename(p).startswith(em) for k in idx if k[1] == th})


def mef_records(b):
    assert b[:4] == b'MEF\0' and b[4] == 9
    n = struct.unpack_from('<I', b, 8)[0]
    out = []
    for i in range(n):
        r = b[12 + 0x48 * i: 12 + 0x48 * (i + 1)]
        key, st, fi, joint = struct.unpack_from('<HHHh', r, 4)
        out.append({'key': key, 'cond': r[0], 'type': r[3], 'set': st, 'file': fi, 'joint': joint,
                    'flags': struct.unpack_from('<I', r, 0xc)[0],
                    'pos': [round(v, 4) for v in struct.unpack_from('<3f', r, 0x18)],
                    'rot': [round(v, 4) for v in struct.unpack_from('<3f', r, 0x28)],
                    'scale': [round(v, 4) for v in struct.unpack_from('<3f', r, 0x38)],
                    'bytes': r.hex()})
    return out


_RESOLVE = None


def efl_path(rec):
    """the game's own path for a record (see the header); None when its resolver refuses"""
    global _RESOLVE
    if _RESOLVE is None:
        sys.path.insert(0, os.path.join(EXTRACT, 'tools', 'fx'))
        import mef_paths
        _RESOLVE = mef_paths.resolver()
    p, err = _RESOLVE(rec['type'], rec['set'], rec['file'])
    return p


def lmt_pages(path):
    """{motion index: (frames, loop frame, [(ids[32], runs)] x 4)}; a clip `_start` covers [0, loop), `_loop`
    [loop, frames)"""
    b = open(path, 'rb').read()
    ver, n = struct.unpack_from('<HH', b, 4)
    offs = struct.unpack_from('<%dI' % n, b, 8)
    out = {}
    for mi, o in enumerate(offs):
        if not o:
            continue
        frames, loop = struct.unpack_from('<Ii', b, o + 8)
        flags = struct.unpack_from('<I', b, o + 0x30)[0]
        ev = struct.unpack_from('<I', b, o + 0x34)[0]
        pages = []
        if ev and not flags & 0x2000000:
            for g in range(4):
                go = ev + g * 0x48
                ids = struct.unpack_from('<32H', b, go)
                cnt, ro = struct.unpack_from('<II', b, go + 0x40)
                pages.append((ids, [struct.unpack_from('<II', b, ro + 8 * r) for r in range(cnt)]))
        out[mi] = (frames, loop, pages)
    return out


def page_bindings(ids, runs, last_bit=16):
    """[{bit, key, on: [[first, last], ...]}] for every bit up to `last_bit` (an enemy's, 0x3915bc) with an id that
    is set somewhere; an effect fires at each span's first frame"""
    spans = collections.defaultdict(list)
    t = 0
    for bits, fr in runs:
        for i in range(32):
            if bits >> i & 1:
                s = spans[i]
                if s and s[-1][1] == t - 1:
                    s[-1][1] = t + fr - 1
                else:
                    s.append([t, t + fr - 1])
        t += fr
    return [{'bit': i, 'key': ids[i], 'on': spans[i]} for i in sorted(spans) if ids[i] and i <= last_bit]


PATH_RE = re.compile(rb'(?:effect|enemy)\\[A-Za-z0-9_\\]+')


def named_paths(b):
    return sorted({m.group().decode() for m in PATH_RE.finditer(b)})


def convert_textures(texes, pool):
    """{effect path: 4U .tex bytes} -> {effect path: 'tex/<md5>.webp'}: one mtf_tex_to_dds (N3DS) run over a folder,
    then the build's alpha re-expansion (build_viewer.py stage_tex)"""
    from PIL import Image
    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import convert_monsters
    d = os.path.join(WORK, 'tex')
    os.makedirs(d, exist_ok=True)
    stems = {}
    for path, raw in texes.items():
        stem = path.replace('/', '\\').replace('\\', '~')
        stems[path] = stem
        if not os.path.isfile(os.path.join(d, stem + '.tex.dds')):
            open(os.path.join(d, stem + '.tex'), 'wb').write(raw)
    if any(not os.path.isfile(os.path.join(d, s + '.tex.dds')) for s in stems.values()):
        convert_monsters.run('mtf_tex_to_dds', '--platform', 'N3DS', d, timeout=600)
    out = {}
    for path, stem in stems.items():
        dds = os.path.join(d, stem + '.tex.dds')
        if not os.path.isfile(dds):
            out[path] = None
            continue
        digest = hashlib.md5(open(dds, 'rb').read()).hexdigest()[:16]
        dst = os.path.join(DOCS, 'tex', digest + '.webp')
        if digest not in pool and not os.path.isfile(dst):
            px = np.array(Image.open(dds).convert('RGBA'))
            px[..., 3] |= px[..., 3] >> 4
            Image.fromarray(px, 'RGBA').save(dst, format='WEBP', lossless=True, exact=True)
        pool[digest] = 1
        out[path] = 'tex/%s.webp' % digest
    return out


def export(e, lists, pool, stats):
    em = e['id']
    src = Source(em)
    mefs = src.listing(T_MEF, em)
    banks = []
    for p in mefs:
        b, _ = src.get(p, T_MEF)
        banks.append((p, mef_records(b)))
    if not banks:
        stats['no .mef'] += 1
        return None
    # bank 0: keys outside 2000..8999; bank 1: keys inside (0x390abc). Files are em<set>_0 / _1.
    records = {}
    for p, recs in banks:
        for r in recs:
            r['bank'] = 1 if 2000 <= r['key'] < 9000 else 0
            r['efl'] = efl_path(r)
            r['mef'] = p
            records[str(r['key'])] = r
    sets = sorted({'em%03d' % r['set'] for r in records.values() if r['type'] == 5} - {em})
    if sets:
        src = Source(em, sets)
    files, resources, texes = {}, {}, {}
    todo = collections.deque(sorted({r['efl'] for r in records.values() if r['efl']}))
    # the shells' effects (effects/<em>.shells.json, MH4U-Extract tools\shells\build_shells.py): their files and
    # textures go in with the .mef's
    shells = os.path.join(DOCS, 'effects', em + '.shells.json')
    if os.path.isfile(shells):
        todo.extend(json.load(open(shells, encoding='utf-8')).get('efls', []))
    seen = set()
    while todo:
        path = todo.popleft()
        if path in seen:
            continue
        seen.add(path)
        for th in (T_EFL, T_EAN, T_TEX, T_MOD, T_MRL):
            b, frm = src.get(path, th)
            if b is None:
                continue
            if th == T_TEX:
                texes[path] = b
                resources[path] = {'from': os.path.basename(frm)}
                stats['textures'] += 1
                continue
            rel = 'effects/files/%s.%s' % (path.replace('\\', '/').lower(), EXT[th])
            dst = os.path.join(DOCS, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'wb').write(b)
            files[path + '.' + EXT[th]] = rel
            stats[EXT[th]] += 1
            for q in named_paths(b):
                todo.append(q)
        if not any(k.startswith(path + '.') for k in files) and path not in resources:
            stats['missing'] += 1
            files[path + '.missing'] = None
    for path, rel in convert_textures(texes, pool).items():
        resources[path]['tex'] = rel
        if rel is None:
            stats['texture failed'] += 1
    clips = {}
    for l in lists:
        lmt = os.path.join(EXTRACT, 'conv', 'monster', l['stem'].split('_')[0], l['stem'] + '.lmt')
        if not os.path.isfile(lmt):
            stats['no lmt'] += 1
            continue
        motions = {}
        for mi, (frames, loop, pages) in lmt_pages(lmt).items():
            if len(pages) > EFFECT_PAGE:
                binds = [x for x in page_bindings(*pages[EFFECT_PAGE]) if str(x['key']) in records]
                other = [x for x in page_bindings(*pages[EFFECT_PAGE])
                         if str(x['key']) not in records and x['key'] != MARKER]
                if binds or other:
                    motions['Motion[%d]' % mi] = {'frames': frames, 'loop': loop, 'bits': binds,
                                                  'unbound': [{'bit': x['bit'], 'key': x['key']} for x in other]}
        if motions:
            clips[l['id']] = motions
    return {'_about': 'scripts/build_effects.py: 4U effects for the viewer, read as its header says',
            'monster': em, 'mef': [p for p, _ in banks], 'records': records, 'clips': clips,
            'files': files, 'resources': resources}


def main():
    mon = json.load(open(os.path.join(DOCS, 'monsters.json'), encoding='utf-8'))['monsters']
    by = {e['id']: e for e in mon}
    ids = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--flying' in sys.argv:
        ids = [e['id'] for e in mon if e.get('species') == 'Flying Wyvern']
    pool, stats = {}, collections.Counter()
    os.makedirs(os.path.join(DOCS, 'effects'), exist_ok=True)
    for em in ids:
        e = by[em]
        targets = [(em, e, e['lists'])]
        if e.get('apex'):
            targets.append((e['apex']['id'], dict(e, id=e['apex']['id']), e['apex']['lists']))
        for hid, ent, ls in targets:
            out = export(ent, ls, pool, stats)
            if out is None:
                print(hid, 'no effects')
                continue
            json.dump(out, open(os.path.join(DOCS, 'effects', hid + '.json'), 'w', encoding='utf-8'),
                      separators=(',', ':'))
            nb = sum(len(m['bits']) for c in out['clips'].values() for m in c.values())
            print('%s %-24s records %3d  clip bindings %4d  files %3d  resources %3d' % (
                hid, e['name'], len(out['records']), nb, len(out['files']), len(out['resources'])))
    print(dict(stats))


if __name__ == '__main__':
    main()
