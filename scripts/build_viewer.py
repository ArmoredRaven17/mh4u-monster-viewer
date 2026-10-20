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
import argparse, collections, copy, datetime, glob, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, r'C:\Coding Repos\mh4u-armor-viewer\scripts')
import mrl
import reduce_keys
import species as species_mod
import parts4u
import gu_parts      # made part_ui_frozen.json; not run by the build since 2026-10-20 (see attach_parts)
FROZEN_UI = json.load(open(os.path.join(HERE, 'part_ui_frozen.json'), encoding='utf-8'))['partUi']
from glbtools import (glb_read, glb_write, merge_skins, flip_v, compact, joints_of, bone_nodes, mod_info,
                      prim_rows, strip_to_animation, clip_list, MASK_DRAWN)
import mh4u        # the 4U Armor Viewer's reader: lmd_messages (LMD text)

EXTRACT = r'C:\MH4U-Extract'
CONV = os.path.join(EXTRACT, 'conv', 'monster')
BLEND = {'BSSolid': 'opaque', 'BSBlendAlpha': 'blend', 'BSAddAlpha': 'add', 'BSRevSubAlpha': 'revsub'}
# revsub (reverse-subtract, Khezu's blood, a Fatalis face overlay) is new over 3U; render/material.js
# draws it as the MHGU viewer does
STATE = ['opaque', 'blend', 'add', 'revsub']
# AN ALPHA-BLENDED MATERIAL BLENDS BY ITS TEXTURE'S ALPHA. The page's material code (GU's) takes a texture's
# alpha into a blend only when the record names a transparency feature, which GU reads from its MRLs. 4U's
# MRLs select no features (their records are blend / depth / raster states, the CB class and texture slots
# only -- mrl_features scratch scan, 2026-10-09), so the BSBlendAlpha state is the whole answer: the 3DS
# blends by the fragment alpha, the map's. Without this every blend layer drew its transparent texels solid
# -- Najarala's fin overlay as black over the scales (Raven, 2026-10-09: "They have black portions on their
# texture"). 'AlphaConstant' is the feature that is the map's alpha alone (no fTransparency constant, which
# is not read here); no alpha test.
FEAT = [{'transp': 'AlphaConstant'}]
FEAT_TEX_ALPHA = 0
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
        if b == 'blend':
            rec_m['f'] = FEAT_TEX_ALPHA
        mats_db.setdefault('feat', FEAT)
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
    # Rajang's cond 7 bits are its fur and tail (by its own meshes: m00_hair the normal fur, m02_hair_a and
    # m01_hairline the enraged gold): 1 body fur, 2 gold fur; 4 / 16 the intact tail in normal / gold fur
    # with the tail end 101, 8 / 32 the broken tail in normal / gold fur with the stump 8; 64 swaps parts
    # 12 / 13 (not identified). Rajang has no tail piece: its tail breaks through these bits. All bits off
    # drew it with neither fur nor tail. Rajang (and Apex Rajang, its state) spawns calm and whole: 1 + 4.
    'em019': {'b795_1': {'value': 1}, 'b795_4': {'value': 1}},
    # Furious Rajang: "always enraged, has a broken tail from the start of the quest" (Raven, 2026-10-09):
    # gold fur 2, broken tail in gold fur 32.
    'em045': {'b795_2': {'value': 1}, 'b795_32': {'value': 1}},
    # Savage Deviljho: cond 7 bit 1 draws part 12, the neck glow (XfBA_IW_1__m00) -- his second level of
    # rage in GU's review (part-review.json em043_05), off at spawn.
    'em043': {'b795_1': {'label': 'Neck Glow, second rage'}},
}

# THE APPEARANCE BITS A MONSTER SPAWNS WITH (parts cond 7 = work+0x7a14), read from its class's code
# (2026-10-20, Raven: "review each monster and ensure their default parts are enabled"). Keyed like PART_UI (by
# the parts source, so colour variants follow their base). Every cond-7 bit of a listed monster is set from this:
# on if listed, off if not -- values only, no control is renamed. A merged row (gu_parts.py) gets the same bits
# written into the option it opens on. Monsters not listed spawn with 0, or keep their PART_UI choice, as read:
#   0 at spawn, matching the page: Gypceros, Tigrex / Brute (bit 1 = enraged eyes, 0x710a94), Congalala (the item
#     held, none at spawn, 0x729f74), Zamtrios, Gore Magala, Kushala Daora (Rusted's bit 2 only in quest 1002,
#     0x7cd518), Teostra, Deviljho (bit 1 = enraged, 0x817580), Altaroth, Zamite (spawn variant 1 only), both
#     Dalamadurs, Seregios (its class word +0xc8 from motion / rage flags, 0x8b5880), Gogmazios.
#   Already the class's bits: Konchu and Bnahabra (PART_UI; spawn 0x88c11c = 0xd, 0x884eb8 = 1), Rajang (calm and
#     whole: 1 + 4, 0x735018), Kecha Wacha and Zinogre (GU's merged rows open on the class's bits).
#   NOT the game's, kept as chosen: Nerscylla's bit 1 (on only in some actions, 0x7a7720; GU opens it "web on"),
#     Furious Rajang (Raven), Savage Deviljho (bit 1 = enraged; his spawn rage is not read).
#   Dah'ren Mohran picks 4 of his 7 back pieces at random at spawn (0x82a74c): no single default, left off.
SPAWN_BITS = {
    # slot 48 0x786f04: one of 0x20 / 0x40 / 0x100 / 0x80 by class +0x38 (spawn 0.0, 0x77c55c -> 0x20), and 0x200
    # unless work+0x53a is set; spawn 0x77c540 = 0x200
    'em025': 0x20 | 0x200, 'em094': 0x20 | 0x200,
    # spawn 0x78b898 = 1, kept by 0x796704
    'em026': 1, 'em095': 1,
    # spawn 0x87cac4: bic 0xb0, orr 0x40
    'em065': 0x40,
    # 0x710c7c: calm and outside its second state, 2 | 4
    'em080': 2 | 4,
    # 0x73c8b0 / 0x73c92c: no special action 1, not enraged or tired 0x20 (Kecha's merged rows already do this)
    'em090': 1 | 0x20,
    # 0x859250: back intact 0x20 (Zinogre's merged row already does this)
    'em049': 0x20,
    # 0x825df4: slime +0x94 below 10 at spawn, horn intact -> 0x10
    'em044': 0x10,
}


def apply_spawn_bits(entry, ui):
    bits = SPAWN_BITS.get(entry.get('partsFrom'))
    if bits is None or not entry.get('partTable'):
        return ui
    have = {r[4] for r in entry['partTable'] if r[2] == 7}
    merged = set()
    for k, row in ui.items():
        if k.startswith('merge:') and row.get('options'):
            opt = row['options'][row.get('value') or 0][0]
            for key in row['merge']:
                if key.startswith('b795_'):
                    opt[key] = 1 if bits & int(key[5:]) else 0
                    merged.add(key)
    for b in sorted(have):
        key = 'b795_%d' % b
        if key not in merged and (b & (b - 1)) == 0:
            ui[key] = dict(ui.get(key, {}), value=1 if bits & b else 0)
    return ui

# Monsters the MHGU viewer also has, by name: they hide their effect layers by default as GU does (Raven,
# 2026-10-08: "follow the GU Agent's advice for monsters that are in GU and 4U"). Two 4U names are GU's
# under another: White Fatalis is GU's Old Fatalis, G Rank Crimson Fatalis its Crimson Fatalis.
GU_MONSTERS = r'C:\MHGU-Extract\MHGU-Monster-Viewer\docs\monsters.json'
GU_ALIAS = {'White Fatalis': 'Old Fatalis', 'G Rank Crimson Fatalis': 'Crimson Fatalis'}
_gu_names = None


def label_apex_lists(base):
    """the Apex lists as the base's list dropdown shows them: id = the file stem (unique, stable), 'List N'
    for a list the base plays too, 'Apex list N' for one only the Apex has"""
    own = {l['file'] for l in base['lists']}
    for l in base['apex']['lists']:
        n = l['stem'].rsplit('_', 1)[1]
        l['id'] = l['stem']
        l['label'] = ('List ' if l['file'] in own else 'Apex list ') + n


def fold_apex(monsters, notes):
    """AN APEX IS A STATE OF ITS BASE, NOT A MONSTER OF ITS OWN (Raven, 2026-10-09: "we don't need to list
    Apex <monster> we can simply apply the Apex state to a model and effects"). An Apex archive packs its
    base's body model, materials, textures and parts rows byte for byte; what it adds is the Frenzy state
    (cond 10, the Virus layer and the angry eyes -- set by class code, not data), particle effects, stats,
    and on two of them a motion list (Apex Rajang's list 4, Apex Diablos' list 4; Apex Zinogre's three
    lists are filed under its own name but are Zinogre's, byte for byte). So each Apex entry becomes `apex` on the base entry -- {id, name, lists:
    every list the Apex's archive packs} -- and leaves the monster list; the page's Apex switch swaps the
    lists in (Raven's choice) and turns the Frenzy state on. Furious Rajang is not an Apex and stays."""
    by_id = {e['id']: e for e in monsters}
    out = []
    for e in monsters:
        if not (e.get('name') or '').startswith('Apex '):
            out.append(e)
            continue
        base = by_id.get(e['sharesModelOf'] or '')
        if not base or base.get('apex'):
            notes.append('%s: no base entry to fold into -- kept' % e['id'])
            out.append(e)
            continue
        base['apex'] = {'id': e['id'], 'name': e['name'], 'lists': e['lists']}
    for e in out:
        if e.get('apex'):
            label_apex_lists(e)
    folded = [e['apex']['id'] for e in out if e.get('apex')]
    notes.append('fold_apex: %d Apex entries folded into their base (%s)' % (len(folded), ', '.join(folded)))
    return out


# ...EXCEPT WHERE GU ITSELF DRAWS THEM AT SPAWN (Raven, 2026-10-09: "Savage and Raging are both in GU, so we
# may be able to use what the GU agent learned"; both "look incorrect currently"). Their identity IS an
# additive layer, and GU keeps it lit:
#   Savage Deviljho   m02_body_k, the body glow (parts 3 / 6 / 9): "Savage is always in the enraged state";
#                     GU's ROM_SPAWN_CLIP pins its material clip to Angry_Start for em043_05 alone, so it
#                     never fades (GU part-review.json em043_05). The neck glow, part 12 (cond 7 bit 1), is
#                     his second rage and stays off at spawn, as in GU.
#   Raging Brachydios the four nenkin slime layers (arms, body, tail) and m05_add: GU opens it in its Yellow
#                     Slime state (part-review.json em063_05). Red Slime is a material colour this build
#                     does not export.
# THE REST, FROM GU'S OWN SPAWN STATE (Raven, 2026-10-09: "Go through them and check GU's records"). For every
# 4U monster GU also has, each effect material GU's same model carries was checked two ways: GU's live viewer
# with the monster mounted (is the mesh shown -- its part and rage sets), and GU's materials.json clips by
# GU's own policy (ROM_SPAWN_CLIP pin, else the auto clip, else the authored fConstantColor alpha x
# fTransparency). Drawn at spawn in GU -- shown AND lit -- and so on here:
#   Gypceros (GU em009_00 XfBA0__m01_light), Seltas Queen (em069_00 m03_add), Gore Magala and Chaotic Gore
#   Magala (em071_00 / em071_05 m01_kasan), Brachydios (em063_00 nenkin arms + body), Chameleos (em025_00
#   m01_light).
# Off in GU at spawn, so left off: Tigrex's m01_angry, Kecha Wacha, Seltas, Akantor, Gravios, Deviljho, and
# Teostra (shown, but authored fTransparency 0). Nerscylla's layer is held off by 4U's own rows. Khezu's blood
# and White Fatalis' face_sub ARE drawn in GU, but through a second-map modulation this build does not have;
# drawn raw they read black (White Fatalis' blobs), so they stay off. Raging's m05_add (part 9) is hidden
# in GU but drawn here with the rest of its layers. The Frenzy Virus layers have no GU record (GU has no
# Frenzy) and are held off by cond 10.
EFFECTS_AT_SPAWN = {'em043', 'em098', 'em009', 'em026', 'em028', 'em097', 'em044', 'em103'}


def attach_gu(entry):
    global _gu_names
    if _gu_names is None:
        _gu_names = {e.get('name') for e in json.load(open(GU_MONSTERS, encoding='utf-8'))['monsters']}
    base = entry['name'].split(' (')[0]
    entry['inGU'] = GU_ALIAS.get(base, base) in _gu_names
    if entry['em'] in EFFECTS_AT_SPAWN:
        entry['effectsDefault'] = True
    else:
        entry.pop('effectsDefault', None)


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
    manual = PART_UI.get(entry['partsFrom']) if entry['partsFrom'] else None
    # THE CONTROLS AS THEY SHIPPED (part_ui_frozen.json), not a fresh read of GU's part-review.json: Raven, 2026-10-18,
    # "Leave the part names and hit zones names alone since I will need to manually label them". gu_parts.py made
    # them (GU's handling where the models match) and is no longer run, so a change in GU's review cannot rename a
    # 4U control. The hand-kept entries win as before.
    ui = {}
    if entry['partTable']:
        ui = copy.deepcopy(FROZEN_UI.get(entry['id']) or {})
    for k, v in (manual or {}).items():
        ui[k] = dict(ui.get(k, {}), **v)
    ui = apply_spawn_bits(entry, ui)
    entry['partUi'] = ui or None
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
ABOUT_APEX = ('an Apex is a state of its base monster, not an entry: {id, name, lists}. Its archive packs the '
              'base\'s model, materials, textures and parts rows byte for byte; the page\'s Apex switch plays '
              '`lists` (every list the Apex archive packs: the base\'s, plus Apex Rajang\'s and Apex Diablos\' '
              'list 4; Apex Zinogre\'s three are Zinogre\'s, byte for byte, under its own name) and turns on cond 10, the Frenzy state (the Virus layer and '
              'angry eyes), with the effect layers. That cond 10 is the Apex look is inferred: no Apex data sets '
              'it. The Apex particle effects (efl) are not drawn.')
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
        index['monsters'] = fold_apex(index['monsters'], notes)
        for e in index['monsters']:
            if e.get('apex'):
                label_apex_lists(e)
        index['_about']['apex'] = ABOUT_APEX
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
    monsters = fold_apex(monsters, notes)
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
        'apex': ABOUT_APEX,
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
