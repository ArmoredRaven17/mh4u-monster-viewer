# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A static single-page web app: every MH4U monster in 3D with its own motion lists. The **basic
version**, forked from the MH3U Monster Viewer (`ArmoredRaven17/mh3u-monster-viewer`, local copy in
`C:\MH3U-Extract\MH3U-Monster-Viewer`), meant as the base for a full app like the MHGU Monster Viewer.

No build step for the app, no framework. `docs/index.html` holds markup, styles and logic;
`docs/render/*.js` is the render core (ES modules, three.js). Serve `docs/` with `dev/serve.py`.

## Data pipeline

    python scripts/convert_monsters.py   # romfs archives -> C:\MH4U-Extract\conv\monster\emNNN
    python scripts/build_viewer.py       # conv -> docs/
    python scripts/build_hitzones.py     # em_data.arc + docs/ models -> docs/hitzones.json, docs/hitzones/*.bin

Both script headers are the long reference. Worth knowing:

- **A monster plays with what its own archive packs** (`manifest.json` per monster). Variants pack
  their base's lists; Apex forms pack the base's model. Don't pair models and lists by name.
- **Apex forms are folded into their base** (`fold_apex`: `apex` = {id, name, lists}); the page's Apex
  switch (`state.apex`, `listsOf`) swaps the lists in and sets cond 10 + effect layers. Furious Rajang,
  Savage Deviljho and the other variants stay entries (Raven).
- **LMT v67 rotation types 11/12/13 are bounded** (min + range * u14 / 16383) and RevilToolset reads
  them right -- the 3U viewer's `lmt_fix.py` patch does NOT apply to 4U.
- **Two vertex formats RevilToolset doesn't know** (Tigrex, Brute/Molten Tigrex, Akantor, Khezu,
  Red Khezu, Savage Deviljho) are repacked to the standard 36-byte one before conversion.
- `flip_v` and the ETC1A4 alpha re-expansion carry over from 3U unchanged (V flip verified on
  Rathian's eye material).
- New 3DS textures (`romfs/snake`) are shipped where they exist; `--standard-tex` for the others.
- **Alpha-blended materials carry `f` (feat AlphaConstant)** so render/material.js blends them by their
  texture's alpha. 4U MRLs select no features, so the BSBlendAlpha state decides; without it every
  blend layer drew its transparent texels solid (Najarala's black fins, Savage Deviljho's back slab).
- **Species are hand-kept** (`scripts/species.py`); no table was found in the code. Say so wherever
  they're shown -- they are not ROM data.
- **The parts table is in each monster's `emd` file** (`em_data.arc`, `scripts/parts4u.py`), not the
  executable. It ships as `partTable` with group 255 on every row and 4U's modes 0/1 rewritten to the
  page's chain modes 2/3 (every row of a part counts -- inferred, see parts4u.py). Pieces carry
  `cutBit` (1 on a tail) because 4U rows have no group. **A 4U piece is never worn**: the body has its
  own whole tail (part 101), so the piece only shows once cut, as the tail on the ground. 3U's
  attachPiece path is not used for 4U. Conds 10/11 are 4U-only switches in
  render/monster.js.
- **Part and hit-zone names are Raven's to label by hand** (2026-10-18: "Leave the part names and hit
  zones names alone since I will need to manually label them"). Don't rename, generate, import or copy
  any. The Parts-panel controls are FROZEN as they shipped in `scripts/part_ui_frozen.json`; the build
  starts from that file and no longer runs `scripts/gu_parts.py` (which made them from GU's part-review
  rows where the models match), so a change in GU cannot rename a 4U control. Hand-kept `PART_UI` and
  `SPAWN_BITS` win. partUi kinds the page understands: per control
  {label, value, options | optionNames, hidden}, and merged rows 'merge:a+b' {label, merge, options:
  [[{key: value}, name]], value}. GU option keys are per state ('a|b'): only the first (base) counts.
- Monsters with no rows fall back to `noTable` in `applyPartState`: pieces hidden, eyelids
  (`eyesClosedParts`) hidden.
- Spawn defaults are 3U's (all inputs 0) except where `PART_UI` (build_viewer.py, the page's `partUi`)
  sets them from the MHGU viewer's choices: Kelbi Gender, Konchu unrolled, Bnahabra folded wings.
  **The cond 7 appearance bits are the class's own spawn values** (`SPAWN_BITS`, each with the code
  address: the class's spawn setup is vtable slot 39, its per-frame update slot 48). Every monster with
  cond 7 rows was read (2026-10-20); the ones not listed there spawn with 0, and its comment lists the
  few kept as chosen rather than read (Nerscylla's web, Furious Rajang, Savage Deviljho) and Dah'ren's
  random back pieces.
  Colour variants borrow their base's rows (`PARTS_FROM`).
- Effect layers (`userData.effect`: add / revsub meshes) are off by default when `inGU` (the monster is
  in the MHGU viewer, by name + `GU_ALIAS`), as GU does; 4U-only monsters draw them. `effectsDefault`
  (build_viewer.py `EFFECTS_AT_SPAWN`) overrides that where GU itself draws them at spawn: Savage
  Deviljho's body glow, Raging Brachydios' slime. For a monster GU also has, check GU's
  `docs/part-review.json` and `materials.json` before deciding a look.
- **Borrowed lists are retargeted** (`retarget_lists`): the viewer binds tracks by node name
  "<index>:<gid>", and a borrower often has the same gids in another order. Without the renamed copy
  those bones never move (Crimson Fatalis' front legs and neck, Rathalos on Rathian's lists).

- **Hit zones are read from 4U's code, never from MHGU** (Raven's rule from the 3U viewer: "No basing Hit
  Zones on GU"). `scripts/hitzones4u.py` is the reader: zone rows, capsules, part records and every state
  change (`STATES`, each with its code address); its header is the reference, and the decode trail is
  `C:\MH4U-Extract\notes\hitzones.md`. GU is used only for what to build: `build_hitzones.py` writes GU's
  hitzones.json contract and bakes with GU's viewer rule, so the GU Hit Zones panel reads it. 4U adds a table
  per state (`tableNames` / `tableNotes`, the "Hit Zone State" dropdown), Apex records under the Apex id
  (`zoneRec`), and Dalamadur's two units (em024 + em083, em110 + em111) merged into one record, tail half
  at slots 8-15. Column 9 is `col9`, unnamed: don't call it Exhaust until the code says so.

- **The second UV is put back** (`glbtools.add_uv2`, run by `ship_model`): 44-byte meshes (0x866B6018: Tigrex,
  Brute Tigrex, Akantor, Khezu, Red Khezu, Molten Tigrex) are repacked to 36 bytes for mod_to_gltf, which drops
  their uv2; the build copies it back from the .mod as TEXCOORD_1. The shaders take it as UV_Extend
  (LtShaderPackage.lfx IABGBase), the UV of the second albedo map (`tExtendMap`, materials.json `t.extend`),
  which monster.js `applyExtendMap` modulates in (GU's TypeExtendModulate for the same layer; 4U's own combiner
  is not read). Without it Molten Tigrex's rage veins drew as large white layers (Raven, 2026-10-25).
  `scripts/reship_uv2.py` re-ships just those models without a full build.
- **Motion effects are recorded from 4U's own effect code** (GU's method; Raven, 2026-10-24, Flying Wyverns
  first). Two steps, both needing `C:\MH4U-Extract`:
  `python scripts/build_effects.py --flying` writes `docs/effects/<em>.json` (the `.mef` records with paths
  from the game's own resolver, each clip's effect page as bit spans, loop frames), the raw effect files
  under `docs/effects/files/` and their textures into `docs/tex/`; then
  `python C:\MH4U-Extract\tools\fx\record_effects.py docs/effects/<em>.json` runs every effect under the
  unicorn harness (`tools\fx\emu.py` and friends) and writes `<em>.play.json`, the GPU records the Billboard
  draw wrote per frame. `docs/render/effects.js` replays them (Animation panel, Show Motion Effects).
  The decode trail, what is READ and what is approximated (the quad size, blend, colour order, follow modes,
  undrawn Model / Polyline / Polygon / Filter generators), is `C:\MH4U-Extract\notes\effects.md`; the
  module's header lists the approximations too. `__view.effects.meter(renderer)` counts drawn pixels (GU's
  draw meter): report draws, not starts.
- **Shells** (fireballs, ground fires, puffs; Raven, 2026-10-25) are `docs/effects/<em>.shells.json`, from
  `python C:\MH4U-Extract\tools\shells\build_shells.py <class> ...` (rath tigrex akantor khezu gravios seregios
  diablos monoblos ukanlos): every action of the class run under the harness with the shells it makes run for
  real -- the spawn table per clip, each shell kind's motion / landing / effects, their recordings, and the rage
  entry clips (`states`). Build shells BEFORE `build_effects.py`, which walks their `.efl`s for textures.
  Notes: `C:\MH4U-Extract\notes\shells.md`; runtime: effects.js SHELLS and THE RAGE ENTRY.

`scripts/mrl.py` is a copy of the MH4U Armor Viewer's; `build_viewer.py` imports that repo's
`scripts/mh4u.py` for LMD text.

## Conventions

- Storage keys are `mh4u-monster-viewer-*`, so an origin shared with the MHGU / MH3U viewers never
  reads their settings.
- The theme palette is the MH4U apps' shared list (the MH4U Hunting Log's `COLORS`); keep it identical.
- Monster names come from the game's text; never put user text into the DOM with `innerHTML`.
