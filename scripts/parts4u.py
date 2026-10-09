r"""MH4U part visibility rows: the per-monster `emd` file (type 0x0a0e48d4) in romfs/data/em_data.arc,
enemy\emNNN\data\emNNN.

    python scripts/parts4u.py              # every monster's rows, summarised; checks the layout
    python scripts/parts4u.py em001        # one monster, a row per line

3U keeps this table in the executable (the MH3U viewer's mh3u_parts.py); 4U moved it into the emd file.
Layout, read from the files (checked over all of them by this script):
  emd     'emd\0', u32 1, ...; the u32 at +0x88 is the offset of the parts rows
  rows    16 bytes each until part == -1:
          +0 s32 part, +4 u16 cond, +6 u16 mode, +8 u32 param, +0xc u32 threshold
          -- 3U's row (mh3u_parts.py) without its group byte.
The conditions and modes read like 3U's on Rathian (em001), part for part against her model:
  part 1, cond 0 (eyes closed), mode 1 (drawn = c)    the eyelid mesh, 18 vertices on the eyes
  parts 4/5, 6/7, 2/3, 102/10: cond 6 (break count of record `param` >= threshold), mode 0 / 1
                                                       the intact / broken pairs of each break
  parts 101/8: cond 1 (severed bit `param`), mode 0 / 1  the tail end / the stump
  parts 9, 50, 51 (the eye meshes): conds 10 and 11, which 3U does not have (not decoded)
The 4U code that reads the rows has not been traced; the meaning of each cond is 3U's.

EVERY ROW COUNTS, NOT JUST THE FIRST (inferred from the rows, not the code). 3U's evaluator lets the
first mode 0 / 1 row naming a part decide, and chains with modes 2 / 3. 4U has no modes 2 / 3, yet 229
parts carry two or more rows -- a break and an appearance bit, two break thresholds, Rathian's eyes
(9: (10, 0) + (11, 0); 50 and 51: (10, 1) + (11, 0)) -- every one of which would be dead under 3U's rule.
Read as "drawn only while every row allows it" they all mean something: the normal eye unless 10 or 11,
the angry eye and its glow on 10 unless 11. So a 4U row is: mode 0 hidden while c, mode 1 hidden while
not c, and a part no row hides is drawn -- 3U's modes 2 and 3 exactly (CHAIN below).
"""
import collections, os, struct, sys

sys.path.insert(0, r'C:\MH4U-Extract\tools')
import arc4

SRC = r'C:\MH4U-Extract\romfs\data\em_data.arc'
T_EMD = 0x0a0e48d4
_rows = None


def all_rows():
    """{em: [[part, cond, mode, param, threshold], ...]} for every emd file"""
    global _rows
    if _rows is None:
        _rows = {}
        with open(SRC, 'rb') as f:
            for name, th, cs, ds, fl, off in arc4.entries(SRC):
                if th != T_EMD:
                    continue
                b = arc4.read_entry(f, cs, ds, off)
                assert b[:4] == b'emd\0', name
                em = name.replace('/', '\\').lower().split('\\')[-1]
                o = struct.unpack_from('<I', b, 0x88)[0] if len(b) >= 0x8c else 0
                rows = []
                while 0 < o <= len(b) - 16:
                    part, cond, mode, param, thr = struct.unpack_from('<iHHII', b, o)
                    if part == -1:
                        break
                    rows.append([part, cond, mode, param, thr])
                    o += 16
                    assert len(rows) < 512, name
                _rows[em] = rows
    return _rows


def rows(em):
    return all_rows().get(em)


# 4U mode -> the 3U evaluator's mode with the same meaning when every row counts (header)
CHAIN = {0: 2, 1: 3}


def eyes_closed_parts(em):
    """parts drawn only while the eyes are closed: any part with a cond 0 (eyes closed) row in mode 1
    (hidden while the eyes are open) -- every row counts (header)"""
    return sorted({p for p, c, m, _, _ in rows(em) or [] if c == 0 and m == 1})


if __name__ == '__main__':
    R = all_rows()
    if len(sys.argv) > 1:
        for r in R[sys.argv[1]]:
            print(r)
        sys.exit()
    conds, modes = collections.Counter(), collections.Counter()
    for em, rs in sorted(R.items()):
        for p, c, m, prm, t in rs:
            conds[c] += 1
            modes[m] += 1
        print(em, len(rs), 'rows; eyes closed ->', eyes_closed_parts(em))
    print(len(R), 'files; conds', dict(sorted(conds.items())), 'modes', dict(sorted(modes.items())))
