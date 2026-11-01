"""GS2 bytecode disassembler (container + op stream), written from gs2parser's GS2Bytecode.cpp.

Container: repeated segments  [u32be type][u32be length][data]  type 1 = GS1 event flags, 2 = function table, 3 = string table, 4 = bytecode.
  function table: (u32be opIndex, name\\0)*     string table: name\\0 ...     bytecode: ops, then a trailing '\\n'.
Operands exist only after number/string/var/index pushes: marker 0xF0/F1/F2 = u8/u16/u32 string-table index (string, var);
0xF3/F4/F5 = i8/i16/i32 number (also jump targets after SET_INDEX); 0xF6 = NUL-terminated decimal text (float literal).
Jumps and function entries use *op indices* (count of opcodes), not byte offsets."""
import struct, sys
from gs2ops import OPS

HAS_OPERAND = {20: "num", 21: "str", 22: "var", 1: "num", 2: "num"}

def segments(data):
    i, out = 0, {}
    while i + 8 <= len(data):
        t, n = struct.unpack_from(">II", data, i); i += 8
        if t not in (1, 2, 3, 4) or i + n > len(data): break
        out[t] = data[i:i + n]; i += n
    return out, data[i:]

def parse_table(b):
    out = []
    for s in b.split(b"\0")[:-1] if b.endswith(b"\0") else b.split(b"\0"): out.append(s.decode("latin1"))
    return out

def parse_functions(b):
    out, i = [], 0
    while i + 5 <= len(b):
        idx = struct.unpack_from(">I", b, i)[0]; j = b.index(b"\0", i + 4)
        out.append((idx, b[i + 4:j].decode("latin1"))); i = j + 1
    return out

def disassemble(data, strings=None):
    """-> dict(functions, strings, ops=[(opindex, byteoffset, name, operand)], problems=[...])"""
    segs, tail = segments(data)
    strs = parse_table(segs.get(3, b"")); funcs = parse_functions(segs.get(2, b""))
    code = segs.get(4, b""); ops, problems = [], []
    if code.endswith(b"\n"): code = code[:-1]
    i = 0; n = 0
    while i < len(code):
        off, op = i, code[i]; i += 1; operand = None
        name = OPS.get(op)
        if name is None: problems.append(f"unknown opcode {op} at byte {off}"); name = f"?{op}"
        kind = HAS_OPERAND.get(op)
        if kind:
            if i >= len(code): problems.append(f"{name} at {off} lacks an operand"); break
            m = code[i]; i += 1
            try:
                if m in (0xF0, 0xF1, 0xF2) and kind in ("str", "var"):
                    sz = {0xF0: 1, 0xF1: 2, 0xF2: 4}[m]; idx = int.from_bytes(code[i:i + sz], "big"); i += sz
                    operand = ("str", idx, strs[idx] if idx < len(strs) else None)
                    if idx >= len(strs): problems.append(f"string index {idx} out of range at {off}")
                elif m in (0xF3, 0xF4, 0xF5) and kind == "num":
                    sz = {0xF3: 1, 0xF4: 2, 0xF5: 4}[m]; v = int.from_bytes(code[i:i + sz], "big", signed=True); i += sz; operand = ("num", v)
                elif m == 0xF6 and kind == "num":
                    j = code.index(b"\0", i); operand = ("float", code[i:j].decode("latin1")); i = j + 1
                else: problems.append(f"bad operand marker {m:#x} after {name} at {off}"); operand = ("?", m)
            except (ValueError, IndexError) as e: problems.append(f"operand error at {off}: {e}"); break
        elif op in (3, 4, 5, 10, 150, 163) and i < len(code) and code[i] == 0xF4:
            tgt = int.from_bytes(code[i + 1:i + 3], "big"); i += 3; operand = ("target", tgt)
        ops.append((n, off, name, operand)); n += 1
    return dict(functions=funcs, strings=strs, ops=ops, problems=problems, flags=segs.get(1), trailing=tail)

def fmt(res):
    lines = [f"; {len(res['strings'])} strings, {len(res['functions'])} functions, {len(res['ops'])} ops, problems: {len(res['problems'])}"]
    fn = {idx: name for idx, name in res["functions"]}
    for n, off, name, operand in res["ops"]:
        if n in fn: lines.append(f"\n{fn[n]}:")
        o = ""
        if operand:
            o = f"  {operand[2]!r}" if operand[0] == "str" and operand[2] is not None else (f"  -> {operand[1]}" if operand[0] == "target" else f"  {operand[1]}")
        lines.append(f"{n:5d} {off:5d}  {name.replace('OP_', ''):<18}{o}")
    return "\n".join(lines)

if __name__ == "__main__":
    r = disassemble(open(sys.argv[1], "rb").read()); print(fmt(r))
    for p in r["problems"]: print("PROBLEM:", p)
