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

Both script headers are the long reference. Worth knowing:

- **A monster plays with what its own archive packs** (`manifest.json` per monster). Variants pack
  their base's lists; Apex forms pack the base's model. Don't pair models and lists by name.
- **LMT v67 rotation types 11/12/13 are bounded** (min + range * u14 / 16383) and RevilToolset reads
  them right -- the 3U viewer's `lmt_fix.py` patch does NOT apply to 4U.
- **Two vertex formats RevilToolset doesn't know** (Tigrex, Brute/Molten Tigrex, Akantor, Khezu,
  Red Khezu, Savage Deviljho) are repacked to the standard 36-byte one before conversion.
- `flip_v` and the ETC1A4 alpha re-expansion carry over from 3U unchanged (V flip verified on
  Rathian's eye material).
- New 3DS textures (`romfs/snake`) are shipped where they exist; `--standard-tex` for the others.
- **Species are hand-kept** (`scripts/species.py`); no table was found in the code. Say so wherever
  they're shown -- they are not ROM data.
- **The parts table is in each monster's `emd` file** (`em_data.arc`, `scripts/parts4u.py`), not the
  executable. It ships as `partTable` with group 255 on every row and 4U's modes 0/1 rewritten to the
  page's chain modes 2/3 (every row of a part counts -- inferred, see parts4u.py). Pieces carry
  `cutBit` (1 on a tail) because 4U rows have no group. **A 4U piece is never worn**: the body has its
  own whole tail (part 101), so the piece only shows once cut, as the tail on the ground. 3U's
  attachPiece path is not used for 4U. Conds 10/11 are 4U-only switches in
  render/monster.js.
- Monsters with no rows fall back to `noTable` in `applyPartState`: pieces hidden, eyelids
  (`eyesClosedParts`) hidden.
- Spawn defaults are 3U's (all inputs 0) except where `PART_UI` (build_viewer.py, the page's `partUi`)
  sets them from the MHGU viewer's choices: Kelbi Gender, Konchu unrolled, Bnahabra folded wings.
  Colour variants borrow their base's rows (`PARTS_FROM`).
- Effect layers (`userData.effect`: add / revsub meshes) are off by default when `inGU` (the monster is
  in the MHGU viewer, by name + `GU_ALIAS`), as GU does; 4U-only monsters draw them.
- **Borrowed lists are retargeted** (`retarget_lists`): the viewer binds tracks by node name
  "<index>:<gid>", and a borrower often has the same gids in another order. Without the renamed copy
  those bones never move (Crimson Fatalis' front legs and neck, Rathalos on Rathian's lists).

`scripts/mrl.py` is a copy of the MH4U Armor Viewer's; `build_viewer.py` imports that repo's
`scripts/mh4u.py` for LMD text.

## Conventions

- Storage keys are `mh4u-monster-viewer-*`, so an origin shared with the MHGU / MH3U viewers never
  reads their settings.
- The theme palette is the MH4U apps' shared list (the MH4U Hunting Log's `COLORS`); keep it identical.
- Monster names come from the game's text; never put user text into the DOM with `innerHTML`.
