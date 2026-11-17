"""Estrae le risorse stringa (.resources di WinForms) da un assembly .NET.
Uso: python3 -I resdump.py assembly.exe [regex_nome]"""
import re
import struct
import sys

data = open(sys.argv[1], "rb").read()
flt = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None


def r7(b, o):
    """intero 7-bit (BinaryReader.Read7BitEncodedInt)."""
    v = sh = 0
    while True:
        x = b[o]
        o += 1
        v |= (x & 0x7F) << sh
        sh += 7
        if not x & 0x80:
            return v, o


def parse(b):
    o = 4
    _hv, skip = struct.unpack_from("<ii", b, o)
    o += 8 + skip
    _ver, n, ntypes = struct.unpack_from("<iii", b, o)
    o += 12
    types = []
    for _ in range(ntypes):
        ln, o = r7(b, o)
        types.append(b[o:o + ln].decode("utf-8", "replace"))
        o += ln
    o = (o + 7) & ~7
    o += 4 * n  # hash
    o += 4 * n  # posizioni
    data_off, = struct.unpack_from("<i", b, o)
    o += 4
    out = []
    for _ in range(n):
        ln, o = r7(b, o)
        name = b[o:o + ln].decode("utf-16-le", "replace")
        o += ln
        pos, = struct.unpack_from("<i", b, o)
        o += 4
        p = data_off + pos
        tc, p = r7(b, p)
        if tc == 1:  # String
            sl, p = r7(b, p)
            out.append((name, b[p:p + sl].decode("utf-8", "replace")))
        elif tc >= 0x40 and tc - 0x40 < len(types) and "String" in types[tc - 0x40]:
            sl, p = r7(b, p)
            out.append((name, b[p:p + sl].decode("utf-8", "replace")))
    return out


for m in re.finditer(b"\xce\xca\xef\xbe", data):
    start = m.start()
    size, = struct.unpack_from("<I", data, start - 4)
    blob = data[start:start + size]
    try:
        items = parse(blob)
    except Exception:
        continue
    for name, val in items:
        if flt is None or flt.search(name):
            print(f"{name}\t{val!r}")
