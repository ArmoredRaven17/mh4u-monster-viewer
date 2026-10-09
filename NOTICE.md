# Notices and attribution

## Game content

Monster Hunter 4 Ultimate, and all of its models, textures, animations and data tables, are
© CAPCOM CO., LTD. All rights reserved.

This is an unofficial, non-commercial fan project. It is not affiliated with, endorsed by, or
supported by Capcom. All game assets were extracted from a personally owned copy of the game and
are shown for reference only.

## Tools used to build this

- **RevilLib / RevilToolset** — PredatorCZ (Lukas Cone).
  Converted MT Framework `.mod` meshes to glTF, `.tex` textures to DDS and `.lmt` motion lists
  to animation. https://github.com/PredatorCZ/RevilLib
- **three.js** — rendering, `GLTFLoader`, `OrbitControls`, `SkeletonUtils`. https://threejs.org
- **Pillow** — texture conversion during the build. https://python-pillow.org
- The cart image, its archives, the text tables and the material files are read by this
  project's own scripts (see README.md).

## Data

- Monster **names** are the game's own: `emName`, one string per monster number; the variants it
  names after their base monster (Apex, Savage, Furious, Rusted...) take the names the MH4U Hunting
  Log gives them.
- Monster **species** names are the game's own (the Hunter's Notes); which monster has which is kept
  by hand, and `docs/monsters.json` says so.
- Everything else — models, textures, material bindings, animations — is read out of the game's
  own files. What is not decoded yet (shading, sizes, the parts table, hit zones) is left out
  rather than approximated; `docs/monsters.json` `_about` lists it.

## Assets

The theme and monster icons are the game's own (the MH4U Hunting Log's set). The MHFU font and the
UI textures are shared with the sibling MHGU and MH3U fan apps.

## Code

The viewer is a fork of the **MH3U Monster Viewer**, itself a fork of the **MHGU Monster Viewer**,
by the same author; its render modules are copies of those projects' files and are maintained here
independently.
