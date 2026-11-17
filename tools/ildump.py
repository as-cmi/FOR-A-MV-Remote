"""Mini-disassemblatore IL per assembly .NET (ECMA-335), solo libreria standard.
Uso: python3 -I ildump.py assembly.exe [filtro_regex_metodi_o_stringhe]
Stampa, per ogni metodo che usa stringhe-comando, le istruzioni con i token risolti."""
import re
import struct
import sys

data = open(sys.argv[1], "rb").read()
u8 = lambda o: data[o]
u16 = lambda o: struct.unpack_from("<H", data, o)[0]
u32 = lambda o: struct.unpack_from("<I", data, o)[0]

# ---------------------------------------------------------------- PE
pe = u32(0x3C)
nsec = u16(pe + 6)
opt = pe + 24
magic = u16(opt)
dd = opt + (96 if magic == 0x10B else 112)
cli_rva = u32(dd + 14 * 8)
sec_tab = opt + u16(pe + 20)
secs = []
for i in range(nsec):
    s = sec_tab + i * 40
    secs.append((u32(s + 12), u32(s + 8), u32(s + 20)))  # va, vsize, rawptr


def off(rva):
    for va, vs, raw in secs:
        if va <= rva < va + max(vs, 1):
            return rva - va + raw
    raise ValueError(hex(rva))


cli = off(cli_rva)
md = off(u32(cli + 8))
assert u32(md) == 0x424A5342
vlen = u32(md + 12)
p = md + 16 + vlen
nstreams = u16(p + 2)
p += 4
streams = {}
for _ in range(nstreams):
    o, sz = u32(p), u32(p + 4)
    p += 8
    e = data.index(b"\0", p)
    name = data[p:e].decode()
    p = (e + 4) & ~3
    streams[name] = (md + o, sz)

strings_off = streams["#Strings"][0]
us_off = streams["#US"][0]
blob_off = streams["#Blob"][0]
tab_off = streams.get("#~", streams.get("#-"))[0]


def sstr(i):
    o = strings_off + i
    return data[o:data.index(b"\0", o)].decode("utf-8", "replace")


def cint(o):
    b = data[o]
    if b & 0x80 == 0:
        return b, 1
    if b & 0xC0 == 0x80:
        return ((b & 0x3F) << 8) | data[o + 1], 2
    return ((b & 0x1F) << 24) | (data[o + 1] << 16) | (data[o + 2] << 8) | data[o + 3], 4


def usstr(i):
    n, k = cint(us_off + i)
    raw = data[us_off + i + k: us_off + i + k + n - 1]
    return raw.decode("utf-16-le", "replace")


# ---------------------------------------------------------------- tabelle
heap = u8(tab_off + 6)
valid = struct.unpack_from("<Q", data, tab_off + 8)[0]
rows = [0] * 64
q = tab_off + 24
for t in range(64):
    if valid >> t & 1:
        rows[t] = u32(q)
        q += 4
SZ_STR = 4 if heap & 1 else 2
SZ_GUID = 4 if heap & 2 else 2
SZ_BLOB = 4 if heap & 4 else 2

CODED = {
    "TDOR": (2, [2, 1, 0x1B]), "HasConst": (2, [4, 8, 0x17]),
    "HasCA": (5, [6, 4, 1, 2, 8, 9, 10, 0, 14, 0x17, 0x14, 0x11, 0x1A, 0x1B, 0x20, 0x23, 0x26, 0x27, 0x28, 0x2A, 0x2C, 0x2B]),
    "HasFM": (1, [4, 8]), "HasDS": (2, [2, 6, 0x20]), "MRP": (3, [2, 1, 0x1A, 6, 0x1B]),
    "HasSem": (1, [0x14, 0x17]), "MDOR": (1, [6, 10]), "MemFwd": (1, [4, 6]),
    "Impl": (2, [0x26, 0x23, 0x27]), "CAType": (3, [0, 0, 6, 10, 0]), "ResScope": (2, [0, 0x1A, 0x23, 1]),
    "TOMD": (1, [2, 6]),
}


def csize(kind):
    if isinstance(kind, int):  # indice semplice di tabella
        return 2 if rows[kind] < 0x10000 else 4
    bits, tabs = CODED[kind]
    return 2 if max(rows[t] for t in tabs) < (1 << (16 - bits)) else 4


S, G, B = "s", "g", "b"
SCHEMA = {
    0x00: [2, S, G, G, G], 0x01: ["ResScope", S, S], 0x02: [4, S, S, "TDOR", 4 + 0x100, 6 + 0x100],
    0x03: [4 + 0x100], 0x04: [2, S, B], 0x05: [6 + 0x100], 0x06: [4, 2, 2, S, B, 8 + 0x100],
    0x07: [8 + 0x100], 0x08: [2, 2, S], 0x09: [2 + 0x100, "TDOR"], 0x0A: ["MRP", S, B],
    0x0B: [2, "HasConst", B], 0x0C: ["HasCA", "CAType", B], 0x0D: ["HasFM", B], 0x0E: [2, "HasDS", B],
    0x0F: [2, 4, 2 + 0x100], 0x10: [4, 4 + 0x100], 0x11: [B], 0x12: [2 + 0x100, 0x14 + 0x100],
    0x13: [0x14 + 0x100], 0x14: [2, S, "TDOR"], 0x15: [2 + 0x100, 0x17 + 0x100], 0x16: [0x17 + 0x100],
    0x17: [2, S, B], 0x18: [2, 6 + 0x100, "HasSem"], 0x19: [2 + 0x100, "MDOR", "MDOR"], 0x1A: [S],
    0x1B: [B], 0x1C: [2, "MemFwd", S, 0x1A + 0x100], 0x1D: [4, 4 + 0x100], 0x1E: [4, 4], 0x1F: [4],
    0x20: [4, 2, 2, 2, 2, 4, B, S, S], 0x21: [4], 0x22: [4, 4, 4], 0x23: [2, 2, 2, 2, 4, B, S, S, B],
    0x24: [4, 0x23 + 0x100], 0x25: [4, 4, 4, 0x23 + 0x100], 0x26: [4, S, B], 0x27: [4, 4, S, S, "Impl"],
    0x28: [4, 4, S, "Impl"], 0x29: [2 + 0x100, 2 + 0x100], 0x2A: [2, 2, "TOMD", S], 0x2B: ["MDOR", B],
    0x2C: [0x2A + 0x100, "TDOR"],
}


def colsize(c):
    if c == S:
        return SZ_STR
    if c == G:
        return SZ_GUID
    if c == B:
        return SZ_BLOB
    if isinstance(c, str):
        return csize(c)
    if c >= 0x100:
        return csize(c - 0x100)
    return c


tables = {}
for t in range(0x2D):
    if not rows[t]:
        continue
    cols = SCHEMA[t]
    sizes = [colsize(c) for c in cols]
    rs = []
    for r in range(rows[t]):
        vals = []
        for sz in sizes:
            vals.append(u16(q) if sz == 2 else u32(q))
            q += sz
        rs.append(vals)
    tables[t] = rs


def decode_coded(kind, v):
    bits, tabs = CODED[kind]
    return tabs[v & ((1 << bits) - 1)], v >> bits


typedefs = tables[2]
typerefs = tables.get(1, [])
fields = tables.get(4, [])
methods = tables[6]
memberrefs = tables.get(10, [])


def typename_of(kind_tab, idx):
    if kind_tab == 2 and idx:
        return sstr(typedefs[idx - 1][1])
    if kind_tab == 1 and idx:
        return sstr(typerefs[idx - 1][1])
    return "?"


# metodo -> classe
method_class = {}
for i, td in enumerate(typedefs):
    start = td[5]
    end = typedefs[i + 1][5] if i + 1 < len(typedefs) else len(methods) + 1
    for m in range(start, end):
        method_class[m] = sstr(td[1])
field_class = {}
for i, td in enumerate(typedefs):
    start = td[4]
    end = typedefs[i + 1][4] if i + 1 < len(typedefs) else len(fields) + 1
    for f in range(start, end):
        field_class[f] = sstr(td[1])


def tok_name(tok):
    t, i = tok >> 24, tok & 0xFFFFFF
    try:
        if t == 0x70:
            return '"' + usstr(i) + '"'
        if t == 0x04:
            return sstr(fields[i - 1][1])
        if t == 0x06:
            return f"{method_class.get(i, '?')}::{sstr(methods[i - 1][3])}"
        if t == 0x0A:
            mr = memberrefs[i - 1]
            pt, pi = decode_coded("MRP", mr[0])
            return f"{typename_of(pt, pi)}::{sstr(mr[1])}"
        if t in (1, 2):
            return typename_of(t, i)
        if t == 0x2B:
            ms = tables[0x2B][i - 1]
            mt, mi = decode_coded("MDOR", ms[0])
            return tok_name((mt << 24) | mi) + "<>"
    except Exception:
        pass
    return f"tok{tok:08x}"


# ---------------------------------------------------------------- IL
NONE, I8, I32, I64, R4, R8, TOK, SW, U8, U16, BR8, BR32 = range(12)
OP1 = {i: NONE for i in range(256)}
OP1.update({0x0E: U8, 0x0F: U8, 0x10: U8, 0x11: U8, 0x12: U8, 0x13: U8, 0x1F: I8, 0x20: I32, 0x21: I64,
            0x22: R4, 0x23: R8, 0x27: TOK, 0x28: TOK, 0x29: TOK, 0x45: SW, 0xDD: BR32, 0xDE: BR8})
for o in range(0x2B, 0x38):
    OP1[o] = BR8
for o in range(0x38, 0x45):
    OP1[o] = BR32
for o in [0x6F, 0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x79, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F, 0x80, 0x81, 0x8C,
          0x8D, 0x8F, 0xA3, 0xA4, 0xA5, 0xC2, 0xC6, 0xD0]:
    OP1[o] = TOK
OP2 = {0x06: TOK, 0x07: TOK, 0x09: U16, 0x0A: U16, 0x0B: U16, 0x0C: U16, 0x0D: U16, 0x0E: U16, 0x12: U8,
       0x15: TOK, 0x16: TOK, 0x19: U8, 0x1C: TOK}
NAMES = {0x02: "ldarg.0", 0x03: "ldarg.1", 0x04: "ldarg.2", 0x06: "ldloc.0", 0x07: "ldloc.1", 0x08: "ldloc.2",
         0x09: "ldloc.3", 0x0A: "stloc.0", 0x0B: "stloc.1", 0x0C: "stloc.2", 0x0D: "stloc.3", 0x11: "ldloc.s",
         0x13: "stloc.s", 0x14: "ldnull", 0x1F: "ldc.i4.s", 0x20: "ldc.i4", 0x28: "call", 0x2A: "ret",
         0x6F: "callvirt", 0x72: "ldstr", 0x73: "newobj", 0x7B: "ldfld", 0x7D: "stfld", 0x7E: "ldsfld",
         0x80: "stsfld", 0x8C: "box", 0x8D: "newarr", 0xA2: "stelem.ref", 0x25: "dup", 0x26: "pop",
         0x45: "switch", 0x58: "add", 0x59: "sub", 0x5A: "mul", 0x5B: "div", 0x5D: "rem"}
for i in range(9):
    NAMES[0x16 + i] = f"ldc.i4.{i}"
for o in range(0x2B, 0x45):
    NAMES.setdefault(o, f"br{o:02x}")


def disasm(rva):
    o = off(rva)
    h = data[o]
    if h & 3 == 2:
        size, code = h >> 2, o + 1
    else:
        hs = (u16(o) >> 12) * 4
        size, code = u32(o + 4), o + hs
    out, i = [], code
    end = code + size
    while i < end:
        pos = i - code
        op = data[i]
        i += 1
        if op == 0xFE:
            op2 = data[i]
            i += 1
            kind = OP2.get(op2, NONE)
            name = f"fe{op2:02x}"
            if op2 == 0x01:
                name = "ceq"
        else:
            kind = OP1[op]
            name = NAMES.get(op, f"op{op:02x}")
        arg = ""
        if kind == TOK:
            arg = tok_name(u32(i))
            i += 4
        elif kind in (I8, BR8, U8):
            v = data[i]
            arg = str(v - 256 if (kind != U8 and v > 127) else v)
            if kind == BR8:
                arg = f"-> {pos + 2 + int(arg)}"
            i += 1
        elif kind in (I32, BR32):
            v = struct.unpack_from("<i", data, i)[0]
            arg = f"-> {pos + 5 + v}" if kind == BR32 else str(v)
            i += 4
        elif kind == U16:
            arg = str(u16(i))
            i += 2
        elif kind == I64:
            arg = str(struct.unpack_from("<q", data, i)[0])
            i += 8
        elif kind == R8:
            arg = repr(struct.unpack_from("<d", data, i)[0])
            name = "ldc.r8"
            i += 8
        elif kind == R4:
            arg = repr(struct.unpack_from("<f", data, i)[0])
            name = "ldc.r4"
            i += 4
        elif kind == SW:
            n = u32(i)
            base = (i + 4 + 4 * n) - code
            tg = [base + struct.unpack_from("<i", data, i + 4 + 4 * k)[0] for k in range(n)]
            i += 4 + 4 * n
            arg = f"[{n}] " + ",".join(map(str, tg))
        out.append((pos, name, arg))
    return out


pat = re.compile(sys.argv[2]) if len(sys.argv) > 2 else re.compile(r'^"[RS][A-Z]{2}')
for mi, m in enumerate(methods, 1):
    rva = m[0]
    if not rva:
        continue
    try:
        ins = disasm(rva)
    except Exception as e:
        continue
    full = f"{method_class.get(mi, '?')}::{sstr(m[3])}"
    anyop = len(sys.argv) > 3 and sys.argv[3] == "any"
    if any(pat.search(a) for _, n, a in ins if anyop or n == "ldstr") or pat.search(full):
        print(f"\n### {full}")
        for pos, n, a in ins:
            print(f"  {pos:5} {n:9} {a}")
