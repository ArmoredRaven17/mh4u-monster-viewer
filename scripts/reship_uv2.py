"""Re-ship only the models with 44-byte (uv2) meshes through build_viewer.ship_model, so their glbs carry
TEXCOORD_1 (glbtools.add_uv2) and materials.json their extend-map slot, without a full build: monsters.json is
not touched (the primitives and the mesh table are the same), and materials.json keeps every other entry.

    python scripts/reship_uv2.py
"""
import glob, json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_viewer as B
from glbtools import UV2_FMT


def has_uv2(mod):
    d = open(mod, 'rb').read()
    h = struct.unpack_from('<16I', d, 0)
    n = struct.unpack_from('<H', d, 8)[0]
    return any(struct.unpack_from('<I', d, h[13] + 48 * i + 0x14)[0] in UV2_FMT for i in range(n))


def main():
    docs = os.path.join(B.REPO, 'docs')
    B.SNAKE = True
    targets = sorted((os.path.basename(os.path.dirname(m)), os.path.basename(m)[:-4])
                     for m in glob.glob(os.path.join(B.CONV, 'em*', '*.mod')) if has_uv2(m))
    path = os.path.join(docs, 'materials.json')
    db = json.load(open(path, encoding='utf-8'))
    for folder, stem in targets:
        mats_db = {'monsters': {}, 'glb': {}}
        notes = []
        if not os.path.isfile(os.path.join(B.CONV, folder, stem + '.glb')):
            continue
        B.ship_model(folder, stem, docs, {}, mats_db, {}, notes)
        db['monsters'].update(mats_db['monsters'])
        db['glb'].update(mats_db['glb'])
        ext = [n for ref in mats_db['monsters'].values() for n, m in ref['mats'].items() if m.get('extendMap')]
        print(folder, stem, 'extend-map materials', ext, notes[:3])
    db['_about'] = db['_about'].replace('Normal, LUT and extend maps are not drawn.',
                                        'Normal and LUT maps are not drawn; t.extend is the tExtendMap binding, '
                                        'sampled through the glb\'s TEXCOORD_1 (UV_Extend).')
    json.dump(db, open(path, 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
