r"""Carry the MHGU viewer's part handling onto 4U controls where the two games' models agree.

    python scripts/gu_parts.py            # coverage report, monster by monster
    from gu_parts import gu_part_ui       # build_viewer.py: {control key: {label, options, value, hidden}}

Raven, 2026-10-09: "compare part IDs to GU monsters we have in 4U ... see if they match up ... If they do,
follow GU's handling of parts". GU's handling is its docs/part-review.json: per monster, rows keyed by the
part ids they switch ("4,5"), each with a name, options keyed by the parts an item draws ("4": "Intact",
"5": "Broken"; "2,13|3,15" for a multi-state item, "none" for drawing none), a default, an order, `sheds`
(a severed tail) and `hidden` (a row the code drives, not the user).

THE MODELS FIRST. A 4U part may carry a GU name only where both games have that part id and it is the same
piece of the model: its bounding box, as a fraction of the whole model's, within 0.05 on every side
(match_parts). The vertex count is NOT compared (Raven, 2026-10-25: "For monsters found in GU, can you see if
the part ids match. If they do, can you assign part labels accordingly?"): GU re-meshed most returning monsters,
so 131 of the parts the old 10% rule rejected sit exactly where 4U's do (box difference 0.0 on most) with 10-50%
more vertices -- the same part, re-tessellated. A part whose box moves more than 0.05 is still a different part.
4U's Frenzy parts (50, 51: cond 10 rows) have no GU counterpart and are left as they are.

THEN THE CONTROLS. A 4U control (render/monster.js partControls) is one input the emd rows read; each of
its values draws a set of its parts, evaluated here exactly as the page does (every row of a part counts,
modes 2 / 3; everything else at its spawn value). A control takes a GU row's NAME when the row covers all
its parts, and an item's name when the GU option draws the same of those parts. An item no GU option
matches keeps the page's own "on .. / off .." text.
"""
import collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from glbtools import glb_read

GU_DOCS = r'C:\MHGU-Extract\MHGU-Monster-Viewer\docs'
GU_ALIAS = {'White Fatalis': 'Old Fatalis', 'G Rank Crimson Fatalis': 'Crimson Fatalis'}
_gu = None


def gu():
    global _gu
    if _gu is None:
        mons = json.load(open(os.path.join(GU_DOCS, 'monsters.json'), encoding='utf-8'))['monsters']
        by = collections.defaultdict(list)
        for e in mons:
            by[e.get('name')].append(e)
        _gu = {'by_name': by, 'review': json.load(open(os.path.join(GU_DOCS, 'part-review.json'), encoding='utf-8'))}
    return _gu


def gu_entry(name):
    base = name.split(' (')[0]
    c = gu()['by_name'].get(GU_ALIAS.get(base, base))
    return c[0] if c else None


# ---- the models ------------------------------------------------------------------------------------

def _parts(path, hide):
    js = glb_read(path)[0]
    per = collections.defaultdict(lambda: [0, [1e18] * 3, [-1e18] * 3])
    idx = 0
    for nd in js['nodes']:
        if 'mesh' not in nd:
            continue
        m = re.match(r'^Group\[(\d+)\]', nd.get('name', ''))
        part = int(m.group(1)) if m else 0
        for pr in js['meshes'][nd['mesh']]['primitives']:
            a = js['accessors'][pr['attributes']['POSITION']]
            if idx not in hide and 'min' in a:
                r = per[part]
                r[0] += a['count']
                r[1] = [min(x, y) for x, y in zip(r[1], a['min'])]
                r[2] = [max(x, y) for x, y in zip(r[2], a['max'])]
            idx += 1
    lo = [min(r[1][k] for r in per.values()) for k in range(3)]
    hi = [max(r[2][k] for r in per.values()) for k in range(3)]
    sp = [max(1e-9, hi[k] - lo[k]) for k in range(3)]
    return {p: (r[0], [(r[1][k] - lo[k]) / sp[k] for k in range(3)] + [(r[2][k] - lo[k]) / sp[k] for k in range(3)])
            for p, r in per.items()}


def match_parts(entry, docs, g):
    """(the part ids both models have with the same geometry, every part id the 4U model draws)"""
    a = _parts(os.path.join(docs, entry['glb']), set(entry.get('hideIdx') or []))
    b = _parts(os.path.join(GU_DOCS, g['glb']), set(g.get('hideIdx') or []))
    out = set()
    for p in set(a) & set(b):
        (va, ba), (vb, bb) = a[p], b[p]
        if max(abs(x - y) for x, y in zip(ba, bb)) <= 0.05:
            out.add(p)
    return out, set(a)


# ---- the 4U controls, as render/monster.js builds and evaluates them ----------------------------------

def _key(cond, param, thr):
    if cond == 0: return 'eyes'
    if cond == 1: return 'cut%d' % (param & 0xffff)
    if cond == 3: return 'state3'
    if cond in (4, 5): return 'variant'
    if cond == 6: return 'break%d' % (param & 0xff)
    if cond == 7: return 'b795_%d' % param
    if cond == 8: return 'f954'
    if cond == 9: return 'bafd_%d' % param
    if cond in (10, 11): return 'c%d' % cond
    return None


def controls(table):
    """[{key, parts, values}] in first-appearance order"""
    out, by = [], {}
    for part, group, cond, mode, param, thr in table or []:
        k = _key(cond, param, thr)
        if not k:
            continue
        c = by.get(k)
        if not c:
            c = by[k] = {'key': k, 'parts': [], 'vals': {0}}
            out.append(c)
        if part not in c['parts']:
            c['parts'].append(part)
        if cond in (4, 5):
            c['vals'].add(param)
        elif cond == 6:
            c['vals'].add(thr)
        else:
            c['vals'].add(1)
    for c in out:
        c['values'] = sorted(c.pop('vals'))
        c['parts'].sort()
    return out


def _status(ctls, values):
    st = {'eyes': 0, 'cut': 0, 'state3': 0, 'variant': 0, 'breaks': {}, 'b795': 0, 'f954': 0, 'bafd': 0, 'c10': 0, 'c11': 0}
    for c in ctls:
        k, v = c['key'], values.get(c['key'], 0)
        if k == 'eyes': st['eyes'] = v
        elif k.startswith('cut'): st['cut'] |= int(k[3:]) if v else 0
        elif k == 'state3': st['state3'] = v
        elif k == 'variant': st['variant'] = v
        elif k.startswith('break'): st['breaks'][int(k[5:])] = v
        elif k.startswith('b795_'): st['b795'] |= int(k[5:]) if v else 0
        elif k == 'f954': st['f954'] = v
        elif k.startswith('bafd_'): st['bafd'] |= int(k[5:]) if v else 0
        elif k in ('c10', 'c11'): st[k] = v
    return st


def _cond(cond, param, thr, st):
    if cond == 0: return bool(st['eyes'])
    if cond == 1: return bool((param & 0xffff) & st['cut'])
    if cond == 3: return bool(st['state3'])
    if cond == 4: return st['variant'] == param
    if cond == 5: return (param & ~st['variant']) == 0
    if cond == 6: return st['breaks'].get(param & 0xff, 0) >= thr
    if cond == 7: return bool(st['b795'] & param)
    if cond == 8: return st['f954'] == 1
    if cond == 9: return bool(st['bafd'] & param)
    if cond == 10: return bool(st['c10'])
    if cond == 11: return bool(st['c11'])
    return False


def drawn(table, part, st):
    for p, g, cond, mode, param, thr in table:
        if p != part:
            continue
        c = _cond(cond, param, thr, st)
        if (mode == 2 and c) or (mode == 3 and not c):
            return False
    return True


def option_parts(table, ctls, c, v, spawn):
    vals = dict(spawn)
    vals[c['key']] = v
    st = _status(ctls, vals)
    return frozenset(p for p in c['parts'] if drawn(table, p, st))


# ---- GU's rows onto them -----------------------------------------------------------------------------

def _keyparts(k):
    """the parts a GU key draws IN ITS BASE STATE. A key's '|' alternatives are per state or per level
    (Nerscylla's Enraged Effect 'none|1,12': none calm, parts 1 and 12 enraged; Zinogre's Back
    '7|7|10,12' by charge level), the calm / base one first -- the state GU opens on and the one the 4U
    rows' other controls stand in at spawn. '+' joins two sub-clusters of one row ('6+8')."""
    first = k.split('|')[0]
    return frozenset() if first == 'none' else frozenset(int(x) for x in re.split(r'[,+]', first) if x.strip().isdigit())


def _drawn_set(table, ctls, parts, vals):
    st = _status(ctls, vals)
    return frozenset(p for p in parts if drawn(table, p, st))


def gu_part_ui(entry, docs, spawn_ui=None):
    """(partUi additions, report) for one 4U entry.

    ONE GU ROW, ONE 4U ROW. Each 4U control goes to the tightest GU row covering all its parts. A GU row
    that gets one control renames it (`label`, and `options` or, where only some items have a GU name,
    `optionNames`). A GU row that gets SEVERAL -- 4U splits one cluster across single-bit controls, as
    Kecha Wacha's wing flaps (bits 1 / 2 / 4) -- becomes one MERGED row, key 'merge:' + the members:
    {label, merge: [keys], options: [[{key: value}, name], ...], value: index}, each GU option the first
    combination of the members' values (fewest set first) that draws exactly that option's parts; the
    members' own rows are then not shown. GU's `hidden` rows stay hidden, its `default` is the spawn
    item -- unless a hand-kept spawn value (PART_UI) says otherwise, which wins."""
    import itertools
    g = gu_entry(entry['name'])
    rev = g and gu()['review'].get(g['id'])
    table = entry.get('partTable')
    if not g or not rev or not table:
        return {}, {'gu': g and g['id'], 'why': 'no GU review' if g else 'not in GU'}
    same, mine = match_parts(entry, docs, g)
    ctls = controls(table)
    spawn = {k: v['value'] for k, v in (spawn_ui or {}).items() if 'value' in v}
    ui, rep = {}, {'gu': g['id'], 'named': [], 'unnamed': []}
    # A GU ROW IS USED WHOLE OR NOT AT ALL: every part of it the 4U model has must be the same geometry, or
    # its items would be half GU's parts and half 4U's own (Rajang's Tail row: parts 6 and 7 differ, so
    # its Broken item would draw both tails)
    rows = [(k, r, K) for k, r, K in ((k, r, _keyparts(k)) for k, r in rev.get('rows', {}).items())
            if (K & mine) <= same]
    assigned = collections.OrderedDict()
    for c in ctls:
        P = frozenset(c['parts'])
        if not P <= same:
            rep['unnamed'].append((c['key'], sorted(P), 'parts differ from GU\'s: %s' % sorted(P - same)))
            continue
        hit = [(k, r, K) for k, r, K in rows if P <= K]
        if not hit:
            rep['unnamed'].append((c['key'], sorted(P), 'no GU row'))
            continue
        k, r, K = min(hit, key=lambda x: len(x[2]))          # the tightest row
        assigned.setdefault(k, (r, K, []))[2].append(c)
    for k, (r, K, members) in assigned.items():
        U = frozenset(p for c in members for p in c['parts'])
        gu_opts = list((r.get('options') or {}).items())
        src = '%s rows["%s"]' % (g['id'], k)
        if len(members) == 1:
            c = members[0]
            opts, default = [], None
            for v in c['values']:
                on = option_parts(table, ctls, c, v, spawn)
                name = next((t for ok, t in gu_opts if (_keyparts(ok) & U) == on), None)
                if name and next(ok for ok, t in gu_opts if t == name) == r.get('default'):
                    default = v
                opts.append([v, name])
            if not any(n for _, n in opts):
                rep['unnamed'].append((c['key'], sorted(U), 'no GU option draws these parts'))
                continue
            rec = {'label': r['name'], 'gu': src}
            if all(n for _, n in opts):
                rec['options'] = opts
            else:
                rec['optionNames'] = {str(v): n for v, n in opts if n}
            if default is not None and default != 0 and c['key'] not in spawn:
                rec['value'] = default
            if r.get('hidden'):
                rec['hidden'] = True
            ui[c['key']] = rec
            rep['named'].append((c['key'], r['name'], opts))
            continue
        # a merged row
        keys = [c['key'] for c in members]
        combos = sorted(itertools.product(*[c['values'] for c in members]), key=lambda t: (sum(1 for x in t if x), t))
        if len(combos) > 256:
            rep['unnamed'].append(('+'.join(keys), sorted(U), 'too many combinations to merge'))
            continue
        opts, default, cur = [], None, None
        spawn_combo = tuple(spawn.get(kk, 0) for kk in keys)
        for ok, text in gu_opts:
            want = _keyparts(ok) & U
            for t in combos:
                vals = dict(spawn)
                vals.update(zip(keys, t))
                if _drawn_set(table, ctls, U, vals) == want:
                    opts.append([dict(zip(keys, t)), text])
                    if t == spawn_combo:
                        cur = len(opts) - 1
                    if ok == r.get('default'):
                        default = len(opts) - 1
                    break
        if not opts:
            rep['unnamed'].append(('+'.join(keys), sorted(U), 'no GU option is a combination of these controls'))
            continue
        rec = {'label': r['name'], 'merge': keys, 'options': opts, 'gu': src}
        pick = cur if cur is not None else default
        if pick is not None:
            rec['value'] = pick
        if r.get('hidden'):
            rec['hidden'] = True
        ui['merge:' + '+'.join(keys)] = rec
        rep['named'].append(('+'.join(keys), r['name'], [t for _, t in opts]))
    return ui, rep


def extend_frozen(docs, path):
    """part_ui_frozen.json, extended with the GU names for controls it leaves unnamed -- nothing it already has is
    changed: a control already named keeps its name, and a GU row that would merge controls one of which is already
    named (alone or in another merge) is skipped and reported"""
    fz = json.load(open(path, encoding='utf-8'))
    m = json.load(open(os.path.join(docs, 'monsters.json'), encoding='utf-8'))['monsters']
    added, skipped = [], []
    for e in m:
        if not e.get('inGU') or not e.get('partTable'):
            continue
        ui, rep = gu_part_ui(e, docs, e.get('partUi'))
        have = fz['partUi'].setdefault(e['id'], {})
        taken = {k for k, v in have.items() if not k.startswith('merge:') and v.get('label')}
        for k, v in have.items():
            if k.startswith('merge:'):
                taken |= set(v.get('merge', []))
        for k, v in ui.items():
            if k in have:
                continue
            members = v.get('merge', [k])
            if set(members) & taken:
                skipped.append((e['id'], k, v.get('label'), sorted(set(members) & taken)))
                continue
            have[k] = v
            taken |= set(members)
            added.append((e['id'], e['name'], k, v.get('label')))
        if not have:
            del fz['partUi'][e['id']]
    fz['_about'] += (' Extended 2026-10-25 (Raven: "For monsters found in GU, can you see if the part ids match. If '
                     'they do, can you assign part labels accordingly?"): gu_parts.py --extend-frozen added the GU '
                     'names of controls left unnamed, matching parts by id and place (the vertex rule dropped); no '
                     'name already here was changed.')
    json.dump(fz, open(path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return added, skipped


SUB_RESHAPED = 0.35


def _raw_boxes(path, hide):
    """{part: (min xyz, max xyz)} in the model's own units"""
    js = glb_read(path)[0]
    per = collections.defaultdict(lambda: [[1e18] * 3, [-1e18] * 3])
    idx = 0
    for nd in js['nodes']:
        if 'mesh' not in nd:
            continue
        m = re.match(r'^Group\[(\d+)\]', nd.get('name', ''))
        part = int(m.group(1)) if m else 0
        for pr in js['meshes'][nd['mesh']]['primitives']:
            a = js['accessors'][pr['attributes']['POSITION']]
            if idx not in hide and 'min' in a:
                r = per[part]
                r[0] = [min(x, y) for x, y in zip(r[0], a['min'])]
                r[1] = [max(x, y) for x, y in zip(r[1], a['max'])]
            idx += 1
    return per


# a subspecies' base species, where its lists do not name it (the borrowed list ids name the rest: 'em001:0')
BASE_OF = {'em004': 'em002', 'em039': 'em038', 'em090': 'em020', 'em091': 'em021', 'em092': 'em022', 'em093': 'em023',
           'em094': 'em025', 'em095': 'em026', 'em096': 'em027'}


def base_of(e):
    if e['id'] in BASE_OF:
        return BASE_OF[e['id']]
    src = sorted({str(l['id']).split(':')[0] for l in e.get('lists', []) if ':' in str(l['id'])})
    return src[0] if len(src) == 1 else None


def extend_subspecies(docs, path):
    """part_ui_frozen.json, extended with each subspecies' BASE SPECIES' names (Raven, 2026-10-26: "Check Subspecies
    as their parts should be similar to the basis species"): a base control (or merged row) is copied when the
    subspecies has the same control over the same parts, its rows for those parts are the base's own (so every item
    draws what the base's does), and each part sits where the base's does (match_parts' box rule against the base's 4U
    model). Only controls the subspecies leaves unnamed take a name; nothing already there changes."""
    fz = json.load(open(path, encoding='utf-8'))
    m = {e['id']: e for e in json.load(open(os.path.join(docs, 'monsters.json'), encoding='utf-8'))['monsters']}
    added, skipped = [], []
    for e in m.values():
        if e.get('inGU') or not e.get('partTable'):
            continue
        b = m.get(base_of(e) or '')
        if not b or not b.get('partTable'):
            continue
        bu = fz['partUi'].get(b['id']) or {}
        # the boxes in the models' own units, as a share of the BASE's extent: a subspecies that adds a crystal or a
        # spike grows its own extent, which would move every part's normalised box (Ruby Basarios, Stygian Zinogre)
        a = _raw_boxes(os.path.join(docs, e['glb']), set(e.get('hideIdx') or []))
        bb = _raw_boxes(os.path.join(docs, b['glb']), set(b.get('hideIdx') or []))
        span = [max(1e-9, max(r[1][k] for r in bb.values()) - min(r[0][k] for r in bb.values())) for k in range(3)]
        diff = {p: max(max(abs(a[p][0][k] - bb[p][0][k]), abs(a[p][1][k] - bb[p][1][k])) / span[k] for k in range(3))
                for p in set(a) & set(bb)}
        # the same place (0.05), or the same part reshaped (to 0.35: Tigerstripe Zamtrios' head, Plum D.Hermitaur's
        # skull) -- accepted only with the base's own control and rows, so its role in the class is the base's
        same = {p for p, d in diff.items() if d <= SUB_RESHAPED}
        mine = {c['key']: c for c in controls(e['partTable'])}
        theirs = {c['key']: c for c in controls(b['partTable'])}
        rows_of = lambda t, parts: sorted(tuple(r) for r in t if r[0] in parts)
        have = fz['partUi'].setdefault(e['id'], {})
        taken = {k for k, v in have.items() if not k.startswith('merge:') and v.get('label')}
        for k, v in have.items():
            if k.startswith('merge:'):
                taken |= set(v.get('merge', []))
        for k, v in bu.items():
            if k in have:
                continue
            members = v.get('merge', [k])
            why = None
            for mk in members:
                c, cb = mine.get(mk), theirs.get(mk)
                if not c or not cb or c['parts'] != cb['parts']:
                    why = '%s: not the same control' % mk
                elif rows_of(e['partTable'], c['parts']) != rows_of(b['partTable'], cb['parts']):
                    why = '%s: its rows differ' % mk
                elif not set(c['parts']) <= same:
                    why = '%s: parts %s not where the base has them' % (mk, sorted(set(c['parts']) - same))
                if why:
                    break
            if not why and set(members) & taken:
                why = 'already named: %s' % sorted(set(members) & taken)
            if why:
                skipped.append((e['id'], e['name'], k, v.get('label'), why))
                continue
            rec = dict(v)
            rec['from'] = '%s (base species, 4U)' % b['id']
            reshaped = sorted(p for mk in members for p in mine[mk]['parts'] if diff.get(p, 0) > 0.05)
            if reshaped:
                rec['reshaped'] = reshaped                 # the subspecies' own shape of these parts
            have[k] = rec
            taken |= set(members)
            added.append((e['id'], e['name'], k, v.get('label')))
        if not have:
            del fz['partUi'][e['id']]
    fz['_about'] += (' Extended 2026-10-26 (Raven: "Check Subspecies as their parts should be similar to the basis '
                     'species"): gu_parts.py --extend-subspecies copied the base species’ names where the '
                     'subspecies’ control, rows and part places are the base’s; no name already here was '
                     'changed.')
    json.dump(fz, open(path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    return added, skipped


if __name__ == '__main__' and '--extend-subspecies' in sys.argv:
    docs = os.path.join(os.path.dirname(HERE), 'docs')
    added, skipped = extend_subspecies(docs, os.path.join(HERE, 'part_ui_frozen.json'))
    for a in added:
        print('added   %s %-22s %-34s %s' % a)
    for s_ in skipped:
        print('skipped %s %-22s %-34s %-18s %s' % s_)
    print('%d added, %d skipped' % (len(added), len(skipped)))
    sys.exit(0)


if __name__ == '__main__' and '--extend-frozen' in sys.argv:
    docs = os.path.join(os.path.dirname(HERE), 'docs')
    added, skipped = extend_frozen(docs, os.path.join(HERE, 'part_ui_frozen.json'))
    for a in added:
        print('added  %s %-24s %-28s %s' % a)
    for s_ in skipped:
        print('skipped %s %s %s (already named: %s)' % s_)
    print('%d added, %d skipped' % (len(added), len(skipped)))
    sys.exit(0)


if __name__ == '__main__':
    docs = os.path.join(os.path.dirname(HERE), 'docs')
    m = json.load(open(os.path.join(docs, 'monsters.json'), encoding='utf-8'))['monsters']
    tot_c = tot_n = 0
    for e in m:
        if not e.get('inGU') or not e.get('partTable'):
            continue
        ui, rep = gu_part_ui(e, docs, e.get('partUi'))
        n = len(rep.get('named', [])); u = len(rep.get('unnamed', []))
        tot_c += n + u; tot_n += n
        print('%s %-24s GU %-10s named %2d of %2d  %s' % (e['id'], e['name'][:24], rep.get('gu'), n, n + u,
              '; '.join('%s=%s' % (k, nm) for k, nm, _ in rep.get('named', []))[:150] or rep.get('why', '')))
    print('controls named from GU: %d of %d' % (tot_n, tot_c))
