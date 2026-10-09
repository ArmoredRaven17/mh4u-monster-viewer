r"""Build the MH4U Monster Viewer's data from the converted cart -- the MH3U Monster Viewer's
build_viewer.py, for 4U.

    python scripts/build_viewer.py                     # every monster
    python scripts/build_viewer.py --only em001,em003  # a subset (monsters.json is rewritten from them)
    python scripts/build_viewer.py --standard-tex      # ship the standard textures, not the New 3DS ones

Reads  <EXTRACT>\conv\monster\emNNN\  (convert_monsters.py: RevilToolset output, the .mod/.mrl/.lmt it
                                       came from, and manifest.json, what the monster's archive packs)
Writes docs/:
  models/monsters/<stem>.glb    ONE skin per file (merge_skins): the 3DS limits a mesh to a small bone
                                palette, so mod_to_gltf writes several skins per model; the viewer reads
                                skins[0]. Each model ships once, however many monsters' archives pack it.
  poses/monsters/<stem>.glb     nodes + animations only, keys thinned by reduce_keys; one per motion list
                                file, shared by every monster whose archive packs that list
  tex/<md5[:16]>.webp           each unique base map once
  monsters.json, materials.json the MH3U viewer's data contract, 4U-sourced

WHAT A MONSTER PLAYS WITH is what its own archive packs (manifest.json): the model named after a monster
folder (its own, else another's -- Apex Rajang's em112.arc packs Rajang's em019 model), the pieces packed
beside it, and every motion list it packs, from whichever folder (Pink Rathian's em003.arc packs Rathian's
em001 lists). A list from another folder is that folder's own file, byte for byte (checked by md5), so it
ships once and is marked `shared`.

What is ROM-sourced and what is not is written into monsters.json's `_about`.
"""
import argparse, collections, datetime, glob, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, r'C:\Coding Repos\mh4u-armor-viewer\scripts')
import mrl
import reduce_keys
import species as species_mod
import parts4u
from glbtools import (glb_read, glb_write, merge_skins, flip_v, compact, joints_of, bone_nodes, mod_info,
                      prim_rows, strip_to_animation, clip_list, MASK_DRAWN)
import mh4u        # the 4U Armor Viewer's reader: lmd_messages (LMD text)

EXTRACT = r'C:\MH4U-Extract'
CONV = os.path.join(EXTRACT, 'conv', 'monster')
BLEND = {'BSSolid': 'opaque', 'BSBlendAlpha': 'blend', 'BSAddAlpha': 'add', 'BSRevSubAlpha': 'revsub'}
# revsub (reverse-subtract, Khezu's blood, a Fatalis face overlay) is new over 3U; render/material.js
# draws it as the MHGU viewer does
STATE = ['opaque', 'blend', 'add', 'revsub']
SNAKE = True
REUSE_POSES = False
REBUILD_TEX = False

# Monster numbers whose emName entry repeats the base monster's name -- the MH4U Hunting Log's VARIANTS
# (its build_data.py explains each); the game tells them apart by icon or quest text, not by emName.
# THE FATALIS ARE NAMED BY COLOUR, the players' names, not the game's (the game calls all four
# "Fatalis", in emName and in the quests, and gives them the "?" icon). Raven, 2026-10-08: "players call
# base Fatalis, Fatalis. The Red one is Crimson Fatalis. The White one is White or Old Fatalis", and the
# second red one "is called G Rank Crimson Fatalis". By the models: 77 black, 78 dark red, 79 white,
# 117 red-gold. (The Hunting Log's VARIANTS has 117 = White Fatalis and leaves 79 unnamed.)
VARIANTS = {
    43: 'Savage Deviljho', 45: 'Furious Rajang', 78: 'Crimson Fatalis', 79: 'White Fatalis',
    82: 'Rusted Kushala Daora', 97: 'Chaotic Gore Magala', 112: 'Apex Rajang', 113: 'Apex Deviljho',
    114: 'Apex Zinogre', 115: 'Apex Gravios', 117: 'G Rank Crimson Fatalis', 119: 'Apex Diablos',
    120: 'Apex Tidal Najarala', 121: 'Apex Tigrex', 122: 'Apex Seregios',
}


def manifest(em):
    return json.load(open(os.path.join(CONV, em, 'manifest.json')))


def main_model(em):
    """(folder, stem) of the body model the monster's archive packs: its own, else the one model named
    after its own folder"""
    mains = [(f, s) for f, s, _ in manifest(em)['models'] if s == f]
    own = [x for x in mains if x[0] == em]
    return own[0] if own else (mains[0] if len(mains) == 1 else None)


def md5(path):
    return hashlib.md5(open(path, 'rb').read()).hexdigest()


# ---- textures --------------------------------------------------------------------------------------

def dds_for(internal, folder):
    """The DDS for an .mrl texture path, from the conversion of the folder that carries it. The New 3DS
    copy (<name>.snake.tex.dds) when there is one and SNAKE is on."""
    parts = internal.replace('/', '\\').lower().split('\\')
    owner = parts[1] if len(parts) > 2 and parts[0] == 'enemy' else folder
    base = os.path.join(CONV, owner, parts[-1])
    for cand in ((base + '.snake.tex.dds', 'snake'), (base + '.tex.dds', 'standard')):
        if cand[1] == 'snake' and not SNAKE:
            continue
        if os.path.isfile(cand[0]):
            return cand
    return None, None


def stage_tex(dds, docs, pool):
    """The texture pool entry for a converted DDS. Alpha is re-expanded as in 3U: the 3DS widens an
    ETC1A4 texel's 4-bit alpha by replication (x17) while mtf_tex_to_dds shifts it (<< 4, 0..240);
    `a | a >> 4` is the replication for those values and leaves ETC1's constant 255 alone."""
    from PIL import Image
    import numpy as np
    digest = hashlib.md5(open(dds, 'rb').read()).hexdigest()[:16]
    rel = 'tex/%s.webp' % digest
    if digest not in pool:
        dst = os.path.join(docs, 'tex', digest + '.webp')
        if not os.path.isfile(dst) or REBUILD_TEX:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            px = np.array(Image.open(dds).convert('RGBA'))
            px[..., 3] |= px[..., 3] >> 4
            Image.fromarray(px, 'RGBA').save(dst, format='WEBP', quality=90, method=6, exact=True)
        pool[digest] = rel
    return rel


# ---- models ----------------------------------------------------------------------------------------

def ship_model(folder, stem, docs, tex_pool, mats_db, shipped, notes):
    """docs/models/monsters/<stem>.glb and its materials, once per (folder, stem)"""
    key = (folder, stem)
    if key in shipped:
        return shipped[key]
    d = os.path.join(CONV, folder)
    mod_path = os.path.join(d, stem + '.mod')
    info = mod_info(mod_path)
    js, bin_ = glb_read(os.path.join(d, stem + '.glb'))
    merge = merge_skins(js, bin_)
    flip_v(js, bin_)
    prims, hide, unmatched, ambiguous = prim_rows(js, info['table'])
    if unmatched:
        notes.append('%s: primitives with no mesh-table row %s' % (stem, unmatched[:4]))
    if ambiguous:
        notes.append('%s: rows sharing part+verts with different masks %s' % (stem, ambiguous[:4]))
    rel = 'models/monsters/%s.glb' % stem
    dst = os.path.join(docs, rel.replace('/', os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    js['asset'] = dict(js.get('asset', {}), generator='revil_toolset mod_to_gltf + build_viewer.py (skins merged)')
    compact(js, bin_)
    glb_write(dst, js, bin_)
    rec = {'glb': rel, 'joints': joints_of(js), 'boneNodes': bone_nodes(js, notes, stem),
           'hide': [[e['part'], e['verts']] for e in info['table'] if not (e['mask'] & MASK_DRAWN)],
           'hideIdx': hide, 'prims': len(prims), 'bones': info['bones'], 'verts': info['verts'],
           'meshes': info['meshes'], 'skinned': bool(js.get('skins')),
           'partIds': sorted({e['part'] for e in info['table'] if e['mask'] & MASK_DRAWN}),
           'skinsMerged': merge['skins'] if merge['merged'] else None}
    # materials: the .mrl beside the .mod, joined to the glb's material names by hash
    ref = 'em/%s' % stem[2:]
    m = mrl.read(mod_path[:-4] + '.mrl')
    tex, src = [], collections.Counter()
    for p in m['textures']:
        dds, which = dds_for(p, folder) if p else (None, None)
        if p and not dds:
            notes.append('%s: texture %s not found' % (stem, p))
        if which:
            src[which] += 1
        tex.append(stage_tex(dds, docs, tex_pool) if dds else None)
    mats = {}
    for mat in js.get('materials', []):
        name = mat.get('name', '')
        r = m['mats'].get(mrl.name_hash(name))
        if not r:
            notes.append('%s: material %s is not in its .mrl' % (stem, name))
            continue
        rec_m = {'t': {'albedo': r['slots'].get('tAlbedoMap', 0) or None}}
        b = BLEND.get(r['blend'])
        if b is None:
            notes.append('%s: material %s has blend state %s' % (stem, name, r['blend']))
        else:
            rec_m['s'] = STATE.index(b)
        if r['slots'].get('tExtendMap'):
            rec_m['extendMap'] = True      # a second albedo map the basic viewer does not draw
        mats[name] = rec_m
    mats_db['monsters'][ref] = {'tex': tex, 'mats': mats}
    mats_db['glb'][rel] = ref
    rec['texFrom'] = dict(src)
    shipped[key] = rec
    return rec


def piece_kind(suffix):
    # MHGU's kinds are tail / head / left / right / other
    return ('tail' if 'tail' in suffix else 'head' if 'head' in suffix
            else 'left' if suffix.startswith('l_') else 'right' if suffix.startswith('r_') else 'other')


# ---- motion lists ----------------------------------------------------------------------------------

def ship_list(folder, stem, digest, node_names, docs, shipped, notes):
    """docs/poses/monsters/<stem>.glb from the folder's conversion, once per list file (by content)"""
    if digest in shipped:
        shipped[digest]['users'] += 1
        return shipped[digest]
    rel = 'poses/monsters/%s.glb' % stem
    src = os.path.join(CONV, folder, 'anim', stem + '_out.glb')
    rec = {'file': rel, 'clips': [], 'users': 1}
    shipped[digest] = rec
    if not os.path.isfile(src):
        rec['error'] = 'lmt_to_gltf produced nothing'
        notes.append('%s: no converted animation' % stem)
        return rec
    dst = os.path.join(docs, rel.replace('/', os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if REUSE_POSES and os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        rec['clips'] = clip_list(dst)
        return rec
    dropped = strip_to_animation(src, dst, node_names)
    if dropped:
        rec['droppedChannels'] = dict(dropped)
        notes.append('%s: dropped channels %s' % (stem, dict(dropped)))
    reduce_keys.fix(dst)
    rec['clips'] = clip_list(dst)
    return rec


def gid_names(js):
    """{gid: node name} of a glb's posable bones and {gid: name} of its "_s" leaves"""
    pose, leaf = {}, {}
    for n in js['nodes']:
        m = re.match(r'^(\d+):(\d+)(_s)?$', n.get('name', ''))
        if m:
            (leaf if m.group(3) else pose)[int(m.group(2))] = n['name']
    return pose, leaf


def retarget_lists(index, docs, notes):
    """A LIST PLAYS ON THE MONSTER'S OWN SKELETON, NAMED BONE BY BONE. The viewer binds a clip's tracks
    to the monster's model by node name, "<index>:<gid>", and a monster that borrows another's lists
    (Rathalos plays Rathian's, Crimson Fatalis plays Fatalis') often has the same bones in another
    ORDER: same gids, other indices, so those tracks found nothing and the bones never moved (Raven,
    2026-10-08: Crimson's "front legs and neck are stiff"). Where any name differs, the list ships again
    as poses/monsters/<model>__<stem>.glb with every node renamed by gid to the model's own name; a gid
    the model does not have keeps its name (no node of the model can carry it)."""
    cache, done = {}, {}

    def load(rel):
        if rel not in cache:
            cache[rel] = glb_read(os.path.join(docs, rel.replace('/', os.sep)))
        return cache[rel]

    n = 0
    for e in index['monsters']:
        mpose, mleaf = gid_names(load(e['glb'])[0])
        for l in e['lists']:
            if 'error' in l:
                continue
            src = l.get('source', l['file'])
            js, bin_ = load(src)
            ppose, pleaf = gid_names(js)
            if all(mpose.get(g, nm) == nm for g, nm in ppose.items()):
                continue
            rel = 'poses/monsters/%s__%s' % (e['model'], os.path.basename(src))
            if rel not in done:
                js2 = json.loads(json.dumps(js))
                for node in js2['nodes']:
                    m = re.match(r'^(\d+):(\d+)(_s)?$', node.get('name', ''))
                    if m:
                        node['name'] = (mleaf if m.group(3) else mpose).get(int(m.group(2)), node['name'])
                js2['asset'] = dict(js2.get('asset', {}), generator='build_viewer.py retarget_lists (%s onto %s)' % (
                    os.path.basename(src), e['model']))
                glb_write(os.path.join(docs, rel.replace('/', os.sep)), js2, bytearray(bin_))
                done[rel] = sum(1 for g, nm in ppose.items() if mpose.get(g, nm) != nm)
            l['source'] = src
            l['file'] = rel
            l['retargeted'] = done[rel]
            n += 1
    notes.append('retarget_lists: %d lists play on a copy renamed to their monster\'s bones (%d files)' % (n, len(done)))


# ---- one monster -----------------------------------------------------------------------------------

def build_monster(em, docs, names, tex_pool, mats_db, shipped_models, shipped_lists, notes):
    man = manifest(em)
    mm = main_model(em)
    idx = int(em[2:])
    rom_name = names[idx] if idx < len(names) else None
    if not mm or not os.path.isfile(os.path.join(CONV, mm[0], mm[1] + '.glb')):
        notes.append('%s (%s): not listed -- its archive packs no model' % (em, rom_name))
        return None
    if not man['lists']:
        notes.append('%s (%s): not listed -- its archive packs no motion list (a static prop)' % (em, rom_name))
        return None
    name = VARIANTS.get(idx) or rom_name
    entry = {'id': em, 'em': em, 'small': None, 'name': name, 'nameRom': rom_name,
             'nameSource': 'emName' + (' + variant name' if idx in VARIANTS else ''),
             'icon': None, 'model': mm[1], 'sharesModelOf': mm[0] if mm[0] != em else None,
             'sizeBase': 1.0, 'groups': None, 'partTable': None, 'partCode': None,
             'parts': [], 'lists': []}
    icon = 'assets/MonsterIcons/MH4U-%s_Icon.png' % (name or '').replace(' ', '_')
    if name and os.path.isfile(os.path.join(docs, icon.replace('/', os.sep))):
        entry['icon'] = icon
    body = ship_model(mm[0], mm[1], docs, tex_pool, mats_db, shipped_models, notes)
    entry.update({k: v for k, v in body.items() if k != 'texFrom'})
    entry['texFrom'] = body['texFrom']
    node_names = {n.get('name', '') for n in glb_read(os.path.join(docs, body['glb'].replace('/', os.sep)))[0]['nodes']}
    # the pieces: every other model the archive packs, from the body's own folder
    for folder, stem, _ in man['models']:
        if (folder, stem) == mm or not stem.startswith(mm[1] + '_'):
            if (folder, stem) != mm:
                notes.append('%s: archive packs model %s\\%s beside the body; not shown' % (em, folder, stem))
            continue
        r = dict(ship_model(folder, stem, docs, tex_pool, mats_db, shipped_models, notes))
        r.pop('texFrom', None)
        suffix = stem[len(mm[1]) + 1:]
        r.update({'name': stem, 'kind': piece_kind(suffix), 'group': None})
        entry['parts'].append(r)
    for row in man['lists']:
        folder, stem, digest = row[:3]
        # converted where it was staged: its home folder, or this monster's when the home archive does
        # not carry it (convert_monsters.py: the 4th field)
        conv = em if len(row) > 3 and row[3] else folder
        src = os.path.join(CONV, conv, stem + '.lmt')
        if not os.path.isfile(src) or md5(src) != digest:
            notes.append('%s: packs list %s\\%s, which no conversion holds byte for byte' % (em, folder, stem))
            continue
        rec = ship_list(conv, stem, digest, node_names, docs, shipped_lists, notes)
        lid = stem.rsplit('_', 1)[1]
        e = {'id': lid if folder == em else '%s:%s' % (folder, lid), 'stem': stem, 'file': rec['file'],
             'shared': folder != em, 'clips': rec['clips']}
        if folder != em:
            e['label'] = 'List %s (%s)' % (lid, folder)
        if 'error' in rec:
            e['error'] = rec['error']
        entry['lists'].append(e)
    return entry


TAIL_CUT_BIT = 1

# COLOUR VARIANTS PLAY THEIR BASE'S ROWS. Bnahabra and Konchu come in four colours, by map (Raven,
# 2026-10-08), each its own archive and model; only the first of each, and Felyne for Melynx, ships an
# emd. The colours' models carry the base's part ids and skeleton exactly (checked in attach_parts), so
# they take its rows rather than drawing every pose at once.
PARTS_FROM = {'em069': 'em068', 'em070': 'em068', 'em071': 'em068',
              'em074': 'em073', 'em075': 'em073', 'em076': 'em073', 'em066': 'em065'}

# SPAWN DEFAULTS AND NAMES THE ROWS CANNOT GIVE, by the monster whose rows they are (`partsFrom`); the
# page's `partUi`: {control key: {label, value, options: [[value, text]]}}. The MHGU viewer's choices,
# relayed by the GU Monster Viewer session (2026-10-08) and asked for by Raven ("consult the GU app"):
#   Kelbi    the cond 5 variant is GU's spawn size type, read in GU (slot 0x210): 0 = body 4 + small horns 5,
#            1 = body 1 + small horns 2, 2 / 3 = the large-horn sets no GU quest spawns. 4U's rows give the
#            same four sets on the same part ids. GU shows it as Gender, Male (type 0, the most-spawned)
#            first; "Male" / "Female" are Raven's reading off the render, not the game's words.
#   Konchu   the cond 7 bits are POSES (GU: Unrolled / Rolled): bit 2 the rolled ball (parts 1, 101), bits
#            1 / 4 / 8 the walking form's shell, belly and legs. GU opens on Unrolled. A viewer choice: the
#            game sets the bits in class code, not read.
#   Bnahabra the cond 7 bits are wing poses (GU: Flapping / Open / Closed): bit 1 folded (part 3), bit 2
#            raised (1), bit 4 swept back (2). GU opens on Closed; bit 1 here. A viewer choice.
PART_UI = {
    'em064': {'variant': {'label': 'Gender', 'value': 0,
                          'options': [[0, 'Male (small horns)'], [1, 'Female (small horns)']]}},
    'em073': {'b795_1': {'value': 1}, 'b795_4': {'value': 1}, 'b795_8': {'value': 1}},
    'em068': {'b795_1': {'value': 1}},
}

# Monsters the MHGU viewer also has, by name: they hide their effect layers by default as GU does (Raven,
# 2026-10-08: "follow the GU Agent's advice for monsters that are in GU and 4U"). Two 4U names are GU's
# under another: White Fatalis is GU's Old Fatalis, G Rank Crimson Fatalis its Crimson Fatalis.
GU_MONSTERS = r'C:\MHGU-Extract\MHGU-Monster-Viewer\docs\monsters.json'
GU_ALIAS = {'White Fatalis': 'Old Fatalis', 'G Rank Crimson Fatalis': 'Crimson Fatalis'}
_gu_names = None


def attach_gu(entry):
    global _gu_names
    if _gu_names is None:
        _gu_names = {e.get('name') for e in json.load(open(GU_MONSTERS, encoding='utf-8'))['monsters']}
    base = entry['name'].split(' (')[0]
    entry['inGU'] = GU_ALIAS.get(base, base) in _gu_names


def attach_parts(entry, notes):
    """The monster's emd parts rows (parts4u.py) as the page's `partTable`: [part, group, cond, mode, param,
    threshold] with group 255 (the body) on every row -- 4U's rows carry no group. From the monster's own
    emd, else its model folder's (`partsFrom`).

    A PIECE'S CUT BIT. 3U ties a severed piece to its sever row through the piece's own group; 4U has no
    groups, so the piece gets `cutBit` here. Every 4U tail piece's body has cond 1 rows on bit 1 -- the tail
    end (101) drawn while it is clear, the stump while it is set -- which is 3U's convention too ("bit 0 =
    the tail on every tail row", mh3u_parts.py). So a `tail` piece takes bit 1 when the rows read it; any
    other piece (Gogmazios' gekiryusou, beside a second bit 8) takes none and stays a prop, as 3U does for
    a piece no row names (Nibelsnarf's).

    UNLIKE 3U, THE PIECE IS NEVER WORN: the 4U body draws its own whole tail (part 101) until the cut, so
    the page shows the piece only once its bit is set -- the tail that fell (index.html applyPartState)."""
    for em in (entry['em'], entry['model'].split('_')[0], PARTS_FROM.get(entry['em'])):
        rows = parts4u.rows(em) if em else None
        if not rows:
            continue
        if em == PARTS_FROM.get(entry['em']):
            # a colour variant borrows only from a base whose drawn part ids are its own
            theirs = sorted({r['part'] for r in mod_info(os.path.join(CONV, em, em + '.mod'))['table']
                             if r['mask'] & MASK_DRAWN})
            if theirs != entry['partIds']:
                notes.append('%s: parts %s differ from %s %s -- rows not borrowed' % (
                    entry['em'], entry['partIds'], em, theirs))
                continue
        # modes as the page's evaluator chains them (parts4u.CHAIN): every 4U row counts
        entry['partTable'] = [[p, 255, c, parts4u.CHAIN[m], prm, t] for p, c, m, prm, t in rows]
        entry['partsFrom'] = em
        break
    else:
        entry['partTable'], entry['partsFrom'] = None, None
        notes.append('%s: no emd parts rows' % entry['em'])
    entry['partUi'] = PART_UI.get(entry['partsFrom']) if entry['partsFrom'] else None
    bits = {r[4] & 0xffff for r in entry['partTable'] or [] if r[2] == 1}
    for piece in entry.get('parts', []):
        piece['group'] = None
        piece['cutBit'] = TAIL_CUT_BIT if piece['kind'] == 'tail' and TAIL_CUT_BIT in bits else None
        if piece['cutBit'] is None:
            notes.append('%s: piece %s has no cut bit -- shown only by the Debug switch' % (entry['em'], piece['name']))


def attach_eyes(entry, notes):
    """`eyesClosedParts`: the body's parts drawn only while the monster's eyes are closed (the blink),
    from the monster's own emd parts rows (parts4u.py), else its model folder's. The viewer hides them,
    so the eyes are open (Raven, 2026-10-08: "I would like to have monster eyes open")."""
    for em in (entry['em'], entry['model'].split('_')[0]):
        if parts4u.rows(em) is not None:
            entry['eyesClosedParts'] = parts4u.eyes_closed_parts(em)
            entry['eyesFrom'] = em
            return
    entry['eyesClosedParts'], entry['eyesFrom'] = [], None
    notes.append('%s: no emd parts rows' % entry['em'])


def attach_species(entry, notes):
    e = species_mod.of(entry['name'], int(entry['em'][2:]))
    entry.update(e)
    if e['speciesIdx'] is None:
        notes.append('%s (%s): no species' % (entry['em'], entry['name']))


ABOUT_SPECIES = species_mod.ABOUT
ABOUT_PARTS = ('the monster\'s emd parts rows (em_data.arc enemy\\emNNN\\data\\emNNN, type 0x0a0e48d4; '
               'parts4u.py), from its own emd else its model folder\'s (`partsFrom`), as [part, group, cond, '
               'mode, param, threshold] with group 255 on every row (4U rows have no group). Conds are read as '
               '3U\'s (mh3u_parts.py); 4U\'s own reader is not traced, and conds 10 and 11 are new in 4U and '
               'not decoded. MODES: every 4U row counts (inferred: 229 parts carry 2+ rows, dead under 3U\'s '
               'first-row rule), so 4U mode 0 ships as 2 (hidden while c) and mode 1 as 3 (hidden while not c). A severed piece is tied to its cut bit by `cutBit` (bit 1 for a tail, '
               'the 3U convention); a piece with none is a prop. null: no emd rows (the page then hides the '
               'pieces and only opens the eyes).')
ABOUT_EYES = ('the body parts drawn only while the eyes are closed -- the parts whose first row in the '
              'monster\'s emd parts table (em_data.arc, parts4u.py; `eyesFrom` names whose) is cond 0 '
              '(eyes closed) with mode 1. The viewer hides them, so every monster\'s eyes are open; the rest '
              'of the table is not applied yet. Monsters with no eyelids (Khezu, Gore Magala, the Seltas, '
              'Nerscylla, Zamtrios) have none.')
ABOUT_RETARGET = ('a list whose `retargeted` is set plays from a copy of `source` with that many bone nodes '
                  'renamed by global bone id to the monster\'s own model: the monster borrows the list from a '
                  'skeleton with the same bones in another order, and the viewer binds tracks by node name.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only')
    ap.add_argument('--standard-tex', action='store_true', help='ship the standard textures, not the New 3DS copies')
    ap.add_argument('--reuse-poses', action='store_true',
                    help='keep motion-list glbs already built from the same conversion')
    ap.add_argument('--rebuild-tex', action='store_true', help='rewrite pool textures that already exist')
    ap.add_argument('--refresh-only', action='store_true',
                    help='run the passes that need no conversion (retarget_lists, eyes) on the existing '
                         'monsters.json, nothing else')
    opt = ap.parse_args()
    if opt.refresh_only:
        docs = os.path.join(REPO, 'docs')
        path = os.path.join(docs, 'monsters.json')
        index = json.load(open(path, encoding='utf-8'))
        notes = []
        retarget_lists(index, docs, notes)
        for e in index['monsters']:
            attach_eyes(e, notes)
            attach_parts(e, notes)
            attach_gu(e)
        index['_about']['retargeted'] = ABOUT_RETARGET
        index['_about']['eyesClosedParts'] = ABOUT_EYES
        index['_about']['partTable'] = ABOUT_PARTS
        json.dump(index, open(path, 'w', encoding='utf-8'), indent=1)
        print('\n'.join(notes))
        return
    global SNAKE, REUSE_POSES, REBUILD_TEX
    SNAKE, REUSE_POSES, REBUILD_TEX = not opt.standard_tex, opt.reuse_poses, opt.rebuild_tex
    docs = os.path.join(REPO, 'docs')
    names = mh4u.lmd_messages('emName')
    ems = sorted(e for e in os.listdir(CONV) if re.fullmatch(r'em\d{3}', e))
    if opt.only:
        want = set(opt.only.split(','))
        ems = [e for e in ems if e in want]
    tex_pool, notes, monsters = {}, [], []
    shipped_models, shipped_lists = {}, {}
    mats_db = {'_about': 'MH4U .mrl v0x20 read through LtShaderPackage.lfx (MFX v52) by mrl.py (the 4U Armor '
                         'Viewer\'s): t.albedo is the tAlbedoMap binding (1-based into tex), s the blend-state '
                         'record (BSSolid/BSBlendAlpha/BSAddAlpha/BSRevSubAlpha). Normal, LUT and extend maps are not drawn.',
               'state': [{'blend': b} for b in STATE], 'monsters': {}, 'glb': {}}
    for em in ems:
        e = build_monster(em, docs, names, tex_pool, mats_db, shipped_models, shipped_lists, notes)
        if e:
            attach_species(e, notes)
            attach_eyes(e, notes)
            attach_parts(e, notes)
            attach_gu(e)
            monsters.append(e)
            print('%s %-24s model %-6s parts %d lists %d clips %d hidden %d' % (
                em, e['name'], e['model'], len(e['parts']), len(e['lists']),
                sum(len(l['clips']) for l in e['lists']), len(e['hideIdx'])), flush=True)
    index = {'monsters': monsters}
    retarget_lists(index, docs, notes)
    count = collections.Counter(m['name'] for m in monsters)
    for m in monsters:
        if count[m['name']] > 1:
            m['name'] = '%s (%s)' % (m['name'], m['id'])
    about = {
        'names': 'emName (core_common msg, LMD) at index = the monster number = the em number, the index '
                 'the MH4U Hunting Log reads quest monsters by. Where emName repeats the base monster\'s '
                 'name (Apex, Savage, Furious, Rusted ...) the name is the Hunting Log\'s VARIANTS one and '
                 'nameSource says so; nameRom keeps the game\'s word.',
        'model': 'the body model the monster\'s own archive packs; sharesModelOf names its folder when it is '
                 'another monster\'s. lists: every motion list the archive packs, `shared` when it is another '
                 'monster\'s file (same bytes).',
        'textures': ('the New 3DS (romfs/snake) copies where the game ships them, else the standard ones; '
                     'texFrom counts which') if SNAKE else 'the standard (Old 3DS) textures only',
        'hideIdx': 'mesh-table +0 bit 0 clear (the MHGU and MH3U draw-mask field); the 4U draw code that '
                   'tests it has not been read.',
        'species': ABOUT_SPECIES,
        'sizeBase': '1.0: the monster size tables are not decoded for 4U.',
        'groups': 'null: 4U ships no part-visibility (.mpm) file.',
        'partTable': ABOUT_PARTS,
        'boneNodes': 'every bone node of the model as [three.js name, global bone id, is a _s leaf].',
        'retargeted': ABOUT_RETARGET,
        'eyesClosedParts': ABOUT_EYES,
        'excluded': [n for n in notes if 'not listed' in n],
    }
    index = {'version': 1, 'generated': datetime.datetime.now().isoformat(timespec='seconds'),
             '_about': about, 'monsters': monsters}
    json.dump(index, open(os.path.join(docs, 'monsters.json'), 'w', encoding='utf-8'), indent=1)
    json.dump(mats_db, open(os.path.join(docs, 'materials.json'), 'w', encoding='utf-8'), indent=1)
    print('%d monsters, %d models, %d motion lists, %d textures' % (
        len(monsters), len(shipped_models), len(shipped_lists), len(tex_pool)))
    for n in notes:
        print('  NOTE', n)


if __name__ == '__main__':
    main()
