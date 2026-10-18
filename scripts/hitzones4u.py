r"""MH4U hit zones, hit capsules and part records, read from romfs/data/em_data.arc
(enemy\emNNN\data\emNNN: the emd, rEnemyData 0x0a0e48d4, and the etd, rEnemyTuneData 0x3d8bbbac).

    python scripts/hitzones4u.py              # every monster summarised; checks the layout
    python scripts/hitzones4u.py em001        # one monster in full
    python scripts/hitzones4u.py --json PATH  # everything as JSON (not wired into the page yet)

Every meaning below is read from 4U's own code (addresses are the US exefs/code.decompressed.bin, VA).
Nothing is taken from MHGU: Raven's rule from the 3U viewer, "No basing Hit Zones on GU".

WHERE THE GAME FINDS THEM
  emd loader 0x1617a8: the file is kept at emdObj+0x64; it then loads the etd and stores etd+0x10 at
  emd+0xbc. The enemy-data table holds emd+8 (0x688f0c), read back by 0x6881c0, so a code offset X on
  that pointer is file offset X+8. Tune pointer P = etd+0x10 (getter 0x937f6c; a loaded override at
  work+0x580 replaces it). Per-enemy work = enemy+0xe28.

HIT ZONE VALUES (etd)
  P+0x0c = file +0x1c: the default table, 8 rows of 10 bytes. Spawn (0x92d0c4) points the 8 slot
  pointers work+0x460+4*i at row i; 0x9367d8(slot) points a slot back at its default row.
  P+0x10 = file +0x20: the alternate table, 8 rows, or 0 when the monster has none (Rathian). 0x933a8c
  (enemy, slot, row) points a slot at an alternate row -- the state changes. Who calls it and when is
  each monster class's own code: STATES below, read call by call.
  0x8c31cc (Gogmazios' class) points a slot at a row of an 8-row table in the exe at 0xff6fd4
  (GLOBAL_ROWS); no other code uses it.
  A per-quest resource set (0x930b20) can replace the tune data (work+0x580) and the capsules
  (work+0x57c) for a monster; only em_data.arc carries either type, so nothing on the cart does.
  Row bytes, from the hit function 0xbe9xxx (the row of slot [capsule+6] & 0xff, 0x922540):
    0 Cut      1 Impact   physical zone = the larger of (cut weight x byte 0) and (impact weight x
                          byte 1), 0xbedab8. Byte 0 is weighted when the attack has flag 2 at +0x3c;
                          flag 2 is also what severs a part whose record has mode 1 (0xbec0e4) -- cut.
    2 Shot     read on the third attack source (0xbea208: not the 0x10000 / 0x8000 sources that use
               0xbedab8). Named by elimination, not yet by the bullet code.
    3 Fire  4 Water  5 Ice  6 Thunder  7 Dragon
               byte 3/4/5/6/7 is read when the attack's element flags (+0x40) carry 0x10 / 0x20 /
               0x200 / 0x40 / 0x80 (0xbea904). The switches 0xcb7408 and 0x979af0 turn element code
               1-5 into 0x10 / 0x20 / 0x40 / 0x80 / 0x200; codes 1-5 are Fire Water Thunder Dragon Ice
               (the Collection Tracker's decode of the weapon records).
    8 Stun     0x92dd04: stun buildup (work+0x4f0) += byte 8 x value.
    9 ?        scales a second status buildup (work+0x4f8, 0xbec648 -> 0x93bf94). Not named yet.

HIT CAPSULES (emd)
  file +0x20 (code +0x18): 44-byte records to a record whose +0 is -1. Getter 0x921a98 (a loaded 'EAT'
  file, rEnemyAtari loader 0x23d808, replaces the list when work+0x57c is set; none ship). Stored at
  work+0x574 (0x9359c8). Fields by their readers:
    +0x00 s16 bone A   +0x02 s16 bone B    MOD joint ids, through the model's id->joint table at
                                           model+0x228 (0xb04db0); 255 and 1001 are special cases
    +0x04 u16 shape    0xbee6c4/0xbefb30: 0 sphere at M(A)*pa; 1 capsule M(A)*pa .. M(A)*pb;
                       2 capsule M(A)*pa .. M(B)*pb (3-5 exist in the builder, unused by Rathian)
    +0x06 u16 slot     low byte = hit-zone slot (0xbe97bc)
    +0x08 u16 part     low byte = part record (0xbec1d4: stun, breaks)
    +0x0a u16 flags    0x1000 scale the radius by bone A's matrix (0xbf0aec); 0x800 read by the hit
                       function (0xbe98a0). The weapon hit test (0xbedd3c): attack types 37-47 count a
                       capsule only with 0x4, type 8 with 0x3, type 9 with 0x18, every other type skips any
                       of 0x0152; 0x8000 counts only while work+0x7e64 > 0 and the attack has 0x4 (Congalala,
                       Kushala Daora, Teostra). Other queries mask 0x7ead / 0x7f2d / 0x7f4d (0x986500, 0xbbe3b8)
    +0x0c u16 sever    a severed-bit mask: the weapon hit test (0xbedd24) and the other capsule queries skip the
                       capsule while work+0x42c (severed bits) & this is set -- Rathian's tail tip carries 1.
                       Gogmazios' AI sets / clears bit 4 per part (0x8c6288, 0x8c9a7c)
    +0x0e u16          not read yet
    +0x10 f32 radius   +0x14 f32[3] pa   +0x20 f32[3] pb   (+0x2c next record)

PART RECORDS (etd)
  P+0x04 = file +0x14: 10 bytes per part. Spawn (0x93698c) gives each part 6 bytes at work+0x42e:
  +0 the times its damage pool ran out, +1 its sever count, +2 the pool (record +0 x a multiplier),
  +4 the sever pool (record +6 x the multiplier). 0x936390 returns record+2: 0x930750(part, type) is
  true while record+4 == type and the sever count is below the u16 at record+2. Type 1 is severed by
  cut (Rathian's tail, part 7: limit 1, sever pool 230); Dah'ren Mohran's parts 4/5 carry 126/127.
  +5 and +8 are not read yet.
"""
import collections, json, os, struct, sys

sys.path.insert(0, r'C:\MH4U-Extract\tools')
import arc4

# STATE CHANGES, read from each monster class's code (uEmNNN; a class serves its variants, told apart by
# work+0x1c0 = the em number). Each state: the ems it applies to, what turns it on, the kind, the code
# that does it, and {slot: row} -- an int is a row of the ALTERNATE table, 'g<n>' a row of GLOBAL_ROWS,
# None the slot's default row. Slots not named keep their default. The fields a condition reads:
#   enraged   work+0x530 == 1. Named by the parts table: cond 8 (evaluator 0x947ca8) is this test, and the
#             one Tigrex mesh it draws is part 4, material m01_angry (Akantor's is its vein mesh).
#   count p   work+0x42e+6p: the times part p's damage pool ran out (spawn fills the pool from part
#             record +0 at 0x93698c); the emd break list (+0x80, rows {part, count, ...}) fires at a count
#             -- Gold Rathian's head is (6, 2).
#   sever p   work+0x42f+6p (0x93e8c4). severed bits: work+0x42c (0x91a1b4; parts cond 1).
#   tier      quest byte +0x8b (0x69a7c0; a Guild Quest's from its level, 0x6adfe0). In the quest files
#             Low Rank quests carry 0-1, High Rank 2-3, G Rank 5-6.
#   variant   work+0x797e, the spawn variant (parts conds 4/5 test it: Kelbi's horns and gender).
#   action    work+0x244 (0x90f2c4), the action now playing; frame windows by 0x91a44c.
#   mode      work+0x1c9, a per-class mode byte with no shared meaning; class flags live at
#             enemy+0x8d88 (the class's own block).
#   tired     work+0x51c = 2 or 3 (setter 0x93e8e0). INFERRED name: it starts when a meter at work+0x520
#             runs out (0x925f2c), counts down a timer from the tune data (+0x40), cannot begin while
#             enraged (0x90e968) and is cleared when Zinogre charges (0x856620) -- the stamina system.
#   appearance bit b   work+0x7a14 & b, parts cond 7.
_A = lambda *s: {i: i for i in s}
STATES = [
    dict(ems=[5, 6], on='part 6 broken (count >= 2)', kind='break', src=0x6ea68c, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[9, 10], label='High / G Rank', on='quest tier >= 2 (High / G Rank), set at spawn', kind='rank', src=0x6fb640, slots=_A(0)),
    dict(ems=[11, 12, 121], on='enraged', kind='enraged', src=0x9365b8, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[80], label='Second state', on='work+0x530 == 2 (a second state only Molten Tigrex has: its tune data alone '
                      'carries the timer block at +0x88)', kind='state2', src=0x936654,
         slots=_A(0, 1, 2, 4, 5, 6, 7)),
    dict(ems=[80], on='part 0 count >= 3 (outside state 2)', kind='break', src=0x9366e8, slots={0: 3}),
    dict(ems=[17, 18], label='During one attack', on='action 0x20a inside its frame window', kind='action', src=0x72be00,
         slots=_A(0, 1, 2, 3, 4)),
    dict(ems=[17, 18], label='Spawn variant 100', on='spawn variant == 100', kind='variant', src=0x72beac, slots=_A(4)),
    dict(ems=[19, 45, 112], label='Flagged state (parts 12/13 shown)', on='class flag +4: set by motion event 0x32 with a timer (0x737c6c); the same '
                               'flag turns on appearance bit 64 = parts 12/13 (0x734fb0); not during action '
                               '0x218', kind='class', src=0x737abc, slots=_A(0, 1, 2, 3, 4)),
    dict(ems=[20, 90], on='part 2 count >= 1', kind='break', src=0x7452fc, slots=_A(3)),
    dict(ems=[90], label='Enraged (appearance bit 8 on)', on='enraged or class flag +0x14, with appearance bit 8', kind='enraged', src=0x745430,
         slots={0: 0}),
    dict(ems=[90], label='Enraged', on='enraged or class flag +0x14, without appearance bit 8', kind='enraged', src=0x745474,
         slots={0: 1}),
    dict(ems=[22, 92], label='Mode (pieces break back)', on='ice mode: work+0x1c9 bit 1 (entered at 0x759b98); breaking an ice piece puts '
                          'its slot back (piece 0 -> slot 0, 2 -> 3, 3 -> 4, 6 -> 6; 0x758f0c)',
         kind='mode', src=0x759b98, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[22, 92], label='Timed state', on='work+0x1c9 bit 2, timed (on 0x7594b4, off 0x75a2e4)', kind='mode', src=0x7594b4,
         slots=_A(5)),
    dict(ems=[23, 93, 120], on='tired, unless the Frenzy flag (work+0x7e80 & 0x20) is set', kind='tired',
         src=0x769940, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[24], on='enraged', kind='enraged', src=0x772474, slots={0: 5, 1: 6, 2: 7, 3: 4, 4: 4, 5: 1}),
    dict(ems=[24, 110], on='part 0 count >= 1 (em024: not enraged)', kind='break', src=0x7724ec, slots={0: 0}),
    dict(ems=[24, 110], on='part 3 count >= 1 (em024: not enraged)', kind='break', src=0x772538, slots={2: 2}),
    dict(ems=[24, 110], on='part 2 count >= 3 (em024: not enraged)', kind='break', src=0x772590, slots={3: 3}),
    dict(ems=[24, 110], on='part 1 count >= 3 (em024: not enraged)', kind='break', src=0x7725d0, slots={4: 3}),
] + [
    dict(ems=[110], label='Slot %d flag' % k, on='class flag +0x%x (with appearance bit %d)' % (0x6c + k, bit), kind='class',
         src=0x772620, slots={k: row})
    for k, (row, bit) in enumerate([(1, 1), (4, 16), (5, 8), (7, 4), (6, 2)])
] + [
    dict(ems=[26, 95], on='part %d count >= 1 (stays)' % p, kind='break', src=0x794918, slots={s: s})
    for p, s in [(2, 4), (4, 6), (3, 5), (5, 7)]
] + [
    dict(ems=[27, 96], on='part 2 count >= 2, class flag +0xa4 clear', kind='break', src=0x7a766c,
         slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[28], label='Mode', on='mode: work+0x1c9 != 0 (entered at 0x7bb898)', kind='mode', src=0x7baf40,
         slots=_A(0, 1, 2, 3, 4, 5, 6, 7)),
    dict(ems=[97], label='Flagged state', on='class flag +0x62 == 1', kind='class', src=0x7baee0, slots=_A(0, 1)),
    dict(ems=[29], on='part 3 count >= 1', kind='break', src=0x7baeac, slots=_A(3)),
    dict(ems=[31, 82], label='Mode', on='mode: work+0x1c9 = 2 or 3 with class flag +0x18 (0x7d3a98)', kind='mode',
         src=0x7d1e5c, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[32], on='enraged', kind='enraged', src=0x7dd1a0, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[33], on='part 1 count >= 2, class flag +4 clear', kind='break', src=0x7e5278,
         slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[34, 35], on='enraged (applied a frame later, class flags +6 / +7)', kind='enraged',
         src=0x7ed120, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[36, 37], label='State 5 / 6', on='work+0x1c8 = 5 or 6 (a shared state byte; it also picks tune set +0x84 entry 1 '
                          '/ 2 through 0x946d68)', kind='mode', src=0x7fcebc, slots=_A(0, 1, 2, 3, 4, 5)),
    dict(ems=[38, 39], on='part 6 count >= 1', kind='break', src=0x8081ac, slots=_A(3)),
    dict(ems=[40, 41, 115], on='part 6 count >= 2 (3 at quest tier >= 5)', kind='break', src=0x8081ac,
         slots=_A(3)),
    dict(ems=[40, 41, 115], on='part 0 count >= 1 (3 at quest tier >= 5)', kind='break', src=0x808248,
         slots=_A(2)),
    dict(ems=[40, 41, 115], on='part 5 count >= 1 (3 at quest tier >= 5)', kind='break', src=0x808290,
         slots=_A(0)),
] + [
    dict(ems=[40, 41, 115], on='part %d count >= 1' % p, kind='break', src=0x8082d8, slots={s: s})
    for p, s in [(1, 4), (2, 5), (3, 6), (4, 7)]
] + [
    dict(ems=[42, 43, 113], on='enraged', kind='enraged', src=0x814d64, slots=_A(0, 1, 2, 3, 4, 5)),
] + [
    dict(ems=[98], label='Slime %d at state 2' % (i + 1), on='slime record +0x%x == 2 (class block)' % off, kind='class', src=0x8255c8, slots=_A(*s))
    for i, (off, s) in enumerate([(0x50, (3,)), (0x5c, (7,)), (0x68, (0, 1)), (0x74, (5, 6))])
] + [
    dict(ems=[46], label='Part 5 severed', on='part 5 sever count >= 1 (record type 127)', kind='sever', src=0x833e48, slots=_A(2)),
    dict(ems=[46], label='Part 4 severed', on='part 4 sever count >= 1 (record type 126)', kind='sever', src=0x833e70, slots=_A(6)),
    dict(ems=[48, 49, 114], label='Timed state', on='timed class state (on 0x85658c, off 0x85683c; sets work+0x7e6b and clears '
                               'tired) -- likely the charge, not confirmed', kind='class', src=0x85658c,
         slots=_A(0, 1, 2, 3, 4, 5)),
    dict(ems=[73], label='During certain attacks', on='certain actions, inside their frame windows', kind='action', src=0x89029c, slots=_A(0)),
    dict(ems=[78, 79], on='enraged', kind='enraged', src=0x89bc4c, slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[117], on='enraged, spawn variant != 1', kind='enraged', src=0x89bc64,
         slots=_A(0, 1, 2, 3, 4, 5, 6)),
    dict(ems=[83], on='enraged', kind='enraged', src=0x8a196c, slots={2: 3, 3: 4, 4: 5}),
    dict(ems=[83, 111], on='part 7 count >= 1 (em083: not enraged)', kind='break', src=0x8a19b8,
         slots={2: 0, 3: 1}),
    dict(ems=[83, 111], on='tail severed (severed bit 1; em083: not enraged)', kind='sever', src=0x8a19f8,
         slots={3: 4}),
    dict(ems=[83, 111], on='part 5 count >= 1 (em083: not enraged)', kind='break', src=0x8a1a6c, slots={4: 2}),
    dict(ems=[88, 122], on='parts 1 and 2 both count >= 2', kind='break', src=0x8b28c4, slots=_A(5)),
    dict(ems=[89], label='Start state', on='set by its state setup (0x8b96ac; slots 2-4 back to default)', kind='class',
         src=0x8b96ac, slots={0: 0, 5: 5, 2: None, 3: None, 4: None}),
] + [
    dict(ems=[89], label='Part %d tarred%s' % (p, ' (hot)' if hot else ''), on='part %d tarred%s' % (p, hot), kind='class', src=0x8c2e5c, slots={s: row})
    for p, s in [(0, 0), (2, 2), (3, 3), (6, 4), (7, 5)]
    for hot, row in [('', s), (', tar value > 160', 'g%d' % s)]
] + [
    dict(ems=[103], label='Flagged state', on='appearance bit 1 set with it (on 0x8ec6e0 / 0x8ec788, off 0x8ecabc)', kind='class',
         src=0x8ea548, slots=_A(0, 1, 2, 3, 4, 5)),
    dict(ems=[107, 108], label='During certain moves', on='work+0x7e60 > 0: a 2-frame flag its own actions refresh (0x8fd964, 0x8ff0ec)',
         kind='action', src=0x901e8c, slots=_A(0, 1, 2, 3, 4, 5)),
    dict(ems=[107, 108], on='part 2 count >= 2 (wins over the row above)', kind='break', src=0x901ea4,
         slots={2: 6}),
    dict(ems=[107, 108], on='parts 5 and 6 both count >= 2 (wins over the row above)', kind='break',
         src=0x901eb8, slots={4: 6}),
    dict(ems=[116], on='part 2 count >= 2, class flag +0xc clear', kind='break', src=0x909864,
         slots=_A(0, 1, 2, 3, 4, 5, 6)),
]
# Monsters with an alternate table no code switches to: Tetsucabra and Berserk Tetsucabra (their class
# only records tusk stages, severed bits 0x8000 / 0x4000, at 0x759424).
CODE = r'C:\MH4U-Extract\exefs\code.decompressed.bin'
GLOBAL_ROWS_VA = 0xff6fd4

SRC = r'C:\MH4U-Extract\romfs\data\em_data.arc'
T_EMD, T_ETD = 0x0a0e48d4, 0x3d8bbbac
COLUMNS = ['cut', 'impact', 'shot', 'fire', 'water', 'ice', 'thunder', 'dragon', 'stun', 'col9']
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def files():
    """{em: {'emd': bytes, 'etd': bytes}}"""
    out = collections.defaultdict(dict)
    with open(SRC, 'rb') as f:
        for name, th, cs, ds, fl, off in arc4.entries(SRC):
            if th in (T_EMD, T_ETD):
                em = name.replace('/', '\\').lower().split('\\')[-1]
                out[em]['emd' if th == T_EMD else 'etd'] = arc4.read_entry(f, cs, ds, off)
    return out


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def rows(b, o, n=8):
    return [list(b[o + 10 * i:o + 10 * i + 10]) for i in range(n)] if o else None


def capsules(emd):
    o, out = u32(emd, 0x20), []
    while o and o + 44 <= len(emd):
        a, bb, shape, slot, part, flags, state, h7 = struct.unpack_from('<hhHHHHHH', emd, o)
        if a == -1:
            break
        r = struct.unpack_from('<7f', emd, o + 0x10)
        out.append({'bones': [a, bb], 'shape': shape, 'slot': slot & 0xff, 'part': part & 0xff,
                    'flags': flags, 'state': state, 'h7': h7, 'radius': r[0],
                    'pa': list(r[1:4]), 'pb': list(r[4:7]), 'hi': [slot >> 8, part >> 8]})
        o += 44
        assert len(out) < 256
    return out


def part_records(etd):
    o, n = u32(etd, 0x14), 8
    return [list(struct.unpack_from('<HHBBHH', etd, o + 10 * i)) for i in range(n)]


def read(em, fb):
    emd, etd = fb['emd'], fb['etd']
    assert emd[:4] == b'emd\0' and etd[:4] == b'etd\0', em
    return {'hp': u32(etd, 0x10), 'zones': rows(etd, u32(etd, 0x1c)), 'alt': rows(etd, u32(etd, 0x20)),
            'parts': part_records(etd), 'capsules': capsules(emd)}


def bones_of():
    try:
        m = json.load(open(os.path.join(ROOT, 'docs', 'monsters.json'), encoding='utf-8'))['monsters']
    except OSError:
        return {}
    return {e['id']: {g for _, g, _ in e.get('boneNodes', [])} for e in m}


def global_rows():
    with open(CODE, 'rb') as f:
        f.seek(GLOBAL_ROWS_VA - 0x100000)
        b = f.read(80)
    return [list(b[10 * i:10 * i + 10]) for i in range(8)]


def states_of(em):
    """The STATES rows for one monster, with their source address as hex."""
    n = int(em[2:])
    return [dict(on=s['on'], kind=s['kind'], src='%#x' % s['src'], slots=s['slots'],
                 **({'label': s['label']} if s.get('label') else {}))
            for s in STATES if n in s['ems']]


def check_states(data):
    """Every state names a monster that has an alternate table, slots 0-7 and rows that exist."""
    bad = []
    for s in STATES:
        for n in s['ems']:
            d = data.get('em%03d' % n)
            if not d or not d['alt']:
                bad.append(('no alternate table', n, s['on']))
            for slot, row in s['slots'].items():
                if not 0 <= slot <= 7 or (isinstance(row, int) and not 0 <= row <= 7):
                    bad.append(('slot/row', n, slot, row))
    return bad


def main():
    allf = files()
    data = {em: read(em, fb) for em, fb in sorted(allf.items()) if 'emd' in fb and 'etd' in fb}
    for em, d in data.items():
        d['states'] = states_of(em)
    if len(sys.argv) > 2 and sys.argv[1] == '--json':
        json.dump({'monsters': data, 'globalRows': global_rows(), 'columns': COLUMNS},
                  open(sys.argv[2], 'w', encoding='utf-8'), separators=(',', ':'))
        print('wrote', sys.argv[2], len(data), 'monsters')
        return
    if len(sys.argv) > 1:
        d = data[sys.argv[1]]
        print('HP', d['hp'])
        for name in ('zones', 'alt'):
            print(name, '(none)' if not d[name] else '')
            for i, r in enumerate(d[name] or []):
                print('  %d  %s' % (i, ' '.join('%3d' % v for v in r)))
        print('states')
        for s in d['states']:
            print('  %-8s %-8s %s  %s' % (s['kind'], s['src'], s['slots'], s['on']))
        print('parts  (+0 u16, +2 count, +4 mode, +5, +6 u16, +8 u16)')
        for i, r in enumerate(d['parts']):
            print('  %d  %s' % (i, r))
        print('capsules')
        for i, c in enumerate(d['capsules']):
            print('  %2d  bones %-10s shape %d slot %d part %d flags %#06x state %d  r %.1f  pa %s  pb %s' % (
                i, c['bones'], c['shape'], c['slot'], c['part'], c['flags'], c['state'], c['radius'],
                [round(v, 1) for v in c['pa']], [round(v, 1) for v in c['pb']]))
        return
    bones = bones_of()
    bad = collections.Counter()
    for em, d in data.items():
        caps = d['capsules']
        miss = sorted({b for c in caps for b in c['bones'][:1 + (c['shape'] == 2)]
                       if b not in (255, 1001) and em in bones and b not in bones[em]})
        bad['slot>7'] += sum(c['slot'] > 7 for c in caps)
        bad['hi bytes'] += sum(any(c['hi']) for c in caps)
        bad['shape>2'] += sum(c['shape'] > 2 for c in caps)
        bad['missing bone'] += bool(miss)
        print('%s HP %5d  capsules %3d  slots %s  alt %s%s' % (
            em, d['hp'], len(caps), ''.join(str(s) for s in sorted({c['slot'] for c in caps})),
            'yes' if d['alt'] else 'no ', '  bones not in model: %s' % miss if miss else ''))
    print(len(data), 'monsters;', dict(bad))
    print(len(STATES), 'state rows over', len({n for s in STATES for n in s['ems']}), 'monsters;',
          'problems:', check_states(data) or 'none')
    print('global rows (0xff6fd4):', global_rows())


if __name__ == '__main__':
    main()
