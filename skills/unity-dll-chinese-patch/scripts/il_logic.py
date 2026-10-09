# -*- coding: utf-8 -*-
"""
精确判定：level0 里哪些英文串被 DLL 的 IL 用作「逻辑字面量」
（ldstr 后紧跟 op_Equality / op_Inequality / SendMessage / Equals 等），
这些串绝不能翻译。
输出 _inventory/logic_literals.json
"""
import io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.StringIO()
import dnfile

FILES = ["_inventory/dll_v36_Assembly-CSharp.dll", "_inventory/dll_v41_firstpass.dll"]
CMP = ("op_Equality", "op_Inequality", "Equals", "StartsWith", "EndsWith",
       "Contains", "SendMessage", "GetMethod", "Invoke", "CompareTo", "SetActive")

def load(path):
    pe = dnfile.dnPE(path)
    n = pe.net
    mref_tok = {}
    for i, r in enumerate(n.mdtables.MemberRef.rows, 1):
        try:
            nm = str(r.Name)
        except Exception:
            continue
        mref_tok[0x0A000000 | i] = nm
    return pe, n, pe.__data__, mref_tok

def user_string(n, rid):
    try:
        raw = n.user_strings.get(rid)
        v = raw.value if hasattr(raw, 'value') else raw
        if isinstance(v, bytes):
            return v.decode('utf-16-le', errors='replace')
        return str(v)
    except Exception:
        return None

result = {}
for path in FILES:
    pe, n, d, mref_tok = load(path)
    found = {}
    for m in n.mdtables.MethodDef.rows:
        try:
            off = pe.get_offset_from_rva(m.Rva)
        except Exception:
            off = None
        if off is None:
            continue
        code = d[off:off + 16000]
        if not code:
            continue
        b0 = code[0]
        if (b0 & 3) == 2:
            il = code[1:1 + (b0 >> 2)]
        elif (b0 & 7) == 3:
            try:
                sz = int.from_bytes(code[4:8], 'little')
                il = code[12:12 + sz]
            except Exception:
                continue
        else:
            continue
        i = 0
        while i < len(il) - 5:
            if il[i] == 0x72 and il[i + 4] == 0x70:
                tok = int.from_bytes(il[i + 1:i + 5], 'little')
                s = user_string(n, tok & 0xFFFFFF)
                if s:
                    for k in range(i + 5, min(i + 5 + 30, len(il) - 4)):
                        if il[k] in (0x28, 0x6F):
                            mt = int.from_bytes(il[k + 1:k + 5], 'little')
                            nm = mref_tok.get(mt)
                            if nm and any(c.lower() in nm.lower() for c in CMP):
                                found.setdefault(s, set()).add(nm)
                                break
                i += 5
                continue
            i += 1
    result[path] = {k: sorted(v) for k, v in found.items()}
    print("%-40s -> %d 个逻辑字面量" % (path.split('/')[-1], len(result[path])))

json.dump(result, open("_inventory/logic_literals.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
allk = {}
for p in result:
    for k, v in result[p].items():
        allk.setdefault(k, set()).update(v)
print("\n并集: %d 个" % len(allk))
for k in sorted(allk):
    print("   %-34r <- %s" % (k, ",".join(sorted(allk[k]))))
