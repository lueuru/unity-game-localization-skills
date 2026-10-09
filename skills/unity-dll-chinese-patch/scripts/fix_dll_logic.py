# -*- coding: utf-8 -*-
"""
恢复主程序集里被误翻的「逻辑字面量」为英文原版。

原理：
  dll_v36 ↔ base_Assembly-CSharp.dll 是等长替换（同为 409088 字节），
  #US 池条目的偏移完全一致。被误翻的条目 = [长度前缀][中文UTF16][尾字节]
                                            + 原英文尾部残留（未清 0）
  只需用 base 的 [前缀][英文UTF16][尾字节] 覆盖同一偏移区间即可。

判定条件（自动配对，不依赖手工表）：
  base 在 p 处有 en，且 base[p-1] == len(en)+1（长度前缀）
  且 current 在 p 处的内容不是 en 而是中文（长度更短）
"""
import io, sys, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "_tmp_dll/base_Assembly-CSharp.dll"
CUR = "_inventory/dll_v36_Assembly-CSharp.dll"
OUT = "_inventory/dll_v37_Assembly-CSharp.dll"

# 待恢复的英文串（= base 有、当前被翻成中文的逻辑字面量）
TARGETS = [
    "Battleship", "Battlecruiser", "Heavy Cruiser", "Light Cruiser", "Auxiliary Cruiser",
    "Destroyer", "Escort Carrier", "Aircraft Carrier", "Submarine", "Torpedo Boat", "Merchant",
    "Dawn", "Evening", "Night",
    " Save Game.\nContinue?", " Renown?", "U-Boat Attack", "Insufficient Renown",
    "Enemy Ships", "Leaving Combat", "Fleet Full", "Fleet full", "Ship already in Fleet or Sunk",
]

B = open(BASE, "rb").read()
C = bytearray(open(CUR, "rb").read())

def positions(d, s):
    b = s.encode("utf-16-le")
    out = []; p = 0
    while True:
        j = d.find(b, p)
        if j < 0: break
        out.append(j); p = j + 1
    return out

log = []
done = set()
for en in TARGETS:
    eb = en.encode("utf-16-le")
    n = len(eb)
    for p in positions(B, en):
        if (p, en) in done:
            continue
        # base 处的长度前缀必须正好是 字节长度+1（= 内容字节数 + 尾字节）
        if p < 1 or B[p - 1] != n + 1:
            continue
        # current 同一位置必须已被改成中文（内容不再等于 en）
        if C[p:p + n] == eb:
            continue                       # 没被改，跳过
        seg = C[p:p + n]
        if not re.search(r'[\u4e00-\u9fff]', seg.decode("utf-16-le", errors="replace")):
            continue                       # 不是中文，跳过（可能是别处）
        # 覆盖：[前缀][英文UTF16][尾字节]，并清掉残留
        start = p - 1
        end = p + n + 1
        old = bytes(C[start:end])
        C[start:end] = B[start:end]
        done.add((p, en))
        log.append((en, p, old[:24].hex(' '), bytes(C[start:end])[:24].hex(' ')))

open(OUT, "wb").write(bytes(C))
print("=== 恢复 %d 处逻辑字面量 (base -> %s) ===" % (len(log), OUT))
for en, p, o, nw in log:
    print("   %-32r @%-7d  %s -> %s" % (en, p, o, nw))

x = bytes(C)
print("\n=== 校验 ===")
for en in TARGETS:
    print("   %-32r 英文在:%s" % (en, en.encode("utf-16-le") in x))
zh_left = []
for zh in ["战列舰", "驱逐舰", "航空母舰", "潜艇", "晨", "夜晚", "敌方舰船", "舰队已满", "脱离战斗", "声望不足"]:
    c = x.count(zh.encode("utf-16-le"))
    zh_left.append((zh, c))
print("   剩余中文（op_Equality 类应大幅减少/为 0）:", zh_left)
print("   文件大小: %d (应与 %d 相同: %s)" % (len(x), len(B), len(x) == len(B)))
