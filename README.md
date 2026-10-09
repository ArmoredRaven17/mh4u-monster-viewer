# MH4U Monster Viewer

A fan-made 3D viewer for the monsters of Monster Hunter 4 Ultimate (3DS). Pick a monster and
watch its own animations, with the game's own models and textures.

**Basic version**, live at https://armoredraven17.github.io/mh4u-monster-viewer/. Forked from the MH3U Monster Viewer (itself the MHGU Monster
Viewer cut down) as the base for a full app like the MHGU one: monster rendering and animation,
the MHGU viewers' Lighting, Camera and Effects panels, and the game's own parts table. Sizes and
hit zones are not decoded yet.

## What it does

- Every monster whose archive packs a model and motion lists (see `monsters.json` `_about.excluded`
  for the props and placeholders left out)
- What each monster plays with is what **its own archive packs**: Pink Rathian's `em003.arc` packs
  its own model and Rathian's motion lists, Apex Rajang's packs Rajang's model and lists, Apex
  Zinogre's packs Zinogre's model with three lists of its own. A shared model or list ships once.
- The monster's motion lists, clip by clip, with looping and frame-by-frame stepping
- The game's own base textures, bound to each material by the game's own material files,
  including which materials are additive or alpha-blended. Where the cart carries a **New 3DS
  copy** of a monster's textures (`romfs/snake`, twice the texels), that copy is shown.
- **The game's own parts table** (each monster's `emd` file in `romfs/data/em_data.arc`, read by
  `scripts/parts4u.py`) drives the Parts panel: breaks, the tail cut, the eyelids (open at spawn),
  state meshes (rage, charge, inflation) and 4U's own conditions 10/11. Every control starts at the
  spawn state. Conditions are read as 3U's code reads them; 4U's reader is not traced, and that every
  row of a part counts (not just the first) is inferred from the rows.
- The body carries its own whole tail; cutting it in the Parts panel swaps it for the stump and drops
  the severed tail model on the ground (tied to cut bit 1, the 3U convention).
  The Bnahabra, Konchu and Melynx colour variants use their base's rows; the few monsters with no
  rows at all hide their pieces and only have their eyes opened.
- Spawn choices the rows can't give follow the MHGU viewer: Kelbi's Gender (Male first), Konchu
  unrolled, Bnahabra with folded wings.
- Effect layers (additive and reverse-subtractive overlays: rage veins, Frenzy layers, glows) are
  off by default on every monster the MHGU viewer also has, as GU draws them; the Parts panel's Show
  Effect Layers turns them on.
- Monsters that borrow another's motion lists play them renamed to their own skeleton's bone order
  (`retargeted` in `monsters.json`)
- The Species Type dropdown groups by the game's own type names (Hunter's Notes) -- but which
  monster has which type is **hand-kept** (`scripts/species.py`); no table for it has been found
  in 4U's code

**Lighting is generic three.js lighting, not the game's.** MH4U's shading is not decoded.

## Running it

No build step for the app. Serve `docs/` with any static file server:

    python dev/serve.py 5597

## Rebuilding the data

The scripts read the unpacked cart in `C:\MH4U-Extract` (see its `unpack_cci.py` and
`tools\arc4.py`) and run [RevilToolset](https://github.com/PredatorCZ/RevilLib) read-only from
`C:\MHGU-Extract\tools\reviltoolset`:

    python scripts/convert_monsters.py   # archives -> conv\monster\emNNN (glb, dds, motion lists), checked
    python scripts/build_viewer.py       # conv -> docs/ (models, poses, tex, monsters.json, materials.json)

`scripts/mrl.py` is the MH4U Armor Viewer's material reader; `build_viewer.py` also imports that
repo's `scripts/mh4u.py` for the game's text.

Neither the extract nor the game's files are part of this repository.

## Contents

    docs/index.html        the app: markup, styles and logic
    docs/monsters.json     per monster: model, pieces, motion lists; `_about` says what is
                           read from the game, what is hand-kept, and what is not decoded yet
    docs/materials.json    each material's base texture and blend state, from its .mrl
    docs/models/monsters/  one glb per model (the monster, and its severed pieces)
    docs/poses/monsters/   one glb per motion list, animations only
    docs/tex/              textures, deduplicated by content hash
    docs/render/           the render core, copied from the MH3U Monster Viewer

## Credits

See NOTICE.md, and the About dialog in the app.

Monster Hunter 4 Ultimate is © CAPCOM CO., LTD. This is an unofficial fan project and is not
affiliated with or endorsed by Capcom.
