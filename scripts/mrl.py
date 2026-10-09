"""MH4U (3DS) material files (.mrl v0x20) read through the shader package (MFX v52) -- the MH3U
Armor Viewer's mh3u_mrl.py; 4U keeps both formats, only the package moved (romfs/system/ltshader).

    import mrl
    mrl.read(path) -> {'textures': [path|None, ...], 'mats': {nameHash: {...}}}
    mrl.name_hash(name) -> the u32 an .mrl keys a material by
    mrl.words(path) -> {nameHash: the material record's word +0x18 (its colour type, bits 23-30)}

Layout, as read from the files (em001.mrl, checked across the library by build_viewer.py):
  MRL   'MRL\\0', u32 version 0x20, u32 materialCount, u32 textureCount, u32 shaderPackageHash,
        u32 textureTableOff, u32 materialTableOff
  tex   76 bytes: u32 type hash (0x241f5deb = rTexture, 0 = a reserved slot), u32, u32, char path[64]
  mat   60 bytes: +0 class hash, +4 name hash = crc32(name) ^ 0xFFFFFFFF, +8 parameter-list size,
        +12.. state words, +0x34 parameter-list offset
  word  (tag20 << 12) | record: the low 12 bits index the MFX record table (1-based), as in MHGU
  param 12-byte descriptors [u32 (record << 20) | ..., u32 value, u32 word] until an all-zero one;
        for a texture slot the value is the 1-based texture-table index (0 = unbound)

MFX v52 (LtUserShaderPackage.lfx): 'MFX\\0', u16 52, u16 99, u32 hash, u32 recordCount (+1),
  ..., u32 stringTableOff @0x20, u32 shaderBinaryOff @0x24; record offsets from 0x2C (the last slot
  overlaps record 1, as in MHGU's v53); a record is [u32 nameOff, u32 classOff, u32, u32 idx << 16, ...]
  with both offsets relative to the string table.
"""
import os, struct, zlib

MFX_PATH = r'C:\MH4U-Extract\romfs\system\ltshader\LtShaderPackage.lfx'
_REC = None


def records():
    global _REC
    if _REC is None:
        l = open(MFX_PATH, 'rb').read()
        assert l[:4] == b'MFX\0' and struct.unpack_from('<H', l, 4)[0] == 52
        nrec = struct.unpack_from('<I', l, 0x0C)[0]
        STR = struct.unpack_from('<I', l, 0x20)[0]
        offs = [struct.unpack_from('<I', l, 0x2C + 4 * i)[0] for i in range(nrec)]
        cstr = lambda o: l[o:l.find(b'\0', o)].decode('latin1')
        _REC = {}
        for o in offs[:-1]:
            w = struct.unpack_from('<6I', l, o)
            _REC[w[3] >> 16] = (cstr(STR + w[0]), cstr(STR + w[1]))
    return _REC


def rec_name(word):
    r = records().get(word & 0xFFF)
    return r[0] if r else None


def name_hash(name):
    return zlib.crc32(name.encode('ascii')) ^ 0xFFFFFFFF


def read(path):
    d = open(path, 'rb').read()
    magic, ver, nmat, ntex, pkg, toff, moff = struct.unpack_from('<4sIIIIII', d, 0)
    assert magic == b'MRL\0' and ver == 0x20, (path, magic, ver)
    textures = []
    for i in range(ntex):
        e = d[toff + 76 * i: toff + 76 * (i + 1)]
        th = struct.unpack_from('<I', e, 0)[0]
        p = e[12:76].split(b'\0')[0].decode('ascii', 'replace')
        textures.append(p if th == 0x241F5DEB else None)      # 0 = reserved (the LUT slots)
    mats = {}
    for m in range(nmat):
        w = struct.unpack_from('<15I', d, moff + 60 * m)
        states = [rec_name(x) for x in w[3:13]]
        blend = next((s for s in states if s and s.startswith('BS')), None)
        pl, ps = w[13], w[2]
        slots = {}
        for o in range(pl, pl + ps, 12):
            a, val, word = struct.unpack_from('<III', d, o)
            if a == 0 and val == 0 and word == 0:
                break
            n = rec_name(word)
            if n and n.startswith('t'):
                slots[n] = val
        mats[w[1]] = {'class': w[0], 'blend': blend, 'slots': slots,
                      'states': [s for s in states if s]}
    return {'textures': textures, 'mats': mats}



def words(path):
    """{name hash: record word +0x18} -- bits 23-30 are the material's colour type"""
    d = open(path, 'rb').read()
    _, _, nmat, _, _, _, moff = struct.unpack_from('<4sIIIIII', d, 0)
    return {struct.unpack_from('<I', d, moff + 60 * m + 4)[0]: struct.unpack_from('<I', d, moff + 60 * m + 0x18)[0]
            for m in range(nmat)}


def colour_type(word):
    return ((word << 1) & 0xffffffff) >> 24


if __name__ == '__main__':
    import sys, json
    r = read(sys.argv[1])
    print(json.dumps({'textures': r['textures'],
                      'mats': {hex(k): v for k, v in r['mats'].items()}}, indent=1))
