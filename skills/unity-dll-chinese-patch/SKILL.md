---
name: unity-dll-chinese-patch
description: 汉化 Unity 安卓游戏的 Assembly-CSharp.dll / *-firstpass.dll：解析 .NET #US 字符串堆、用 IL 上下文判定哪些英文能翻（显示文本）哪些绝对不能翻（代码引用名/比较值），再做不改变文件长度的块级原地替换。当用户要汉化/翻译 Unity 游戏的 DLL、或抱怨"还有东西没汉化/翻了就闪退"时使用。
agent_created: true
---

# Unity 游戏 DLL 汉化（#US 堆块级替换）

## 核心原则

**翻译前必须先判定每个字符串的用途**。翻错代码引用名 → 进 loading 后闪退；翻错比较值 → 数据显示空白。
判定依据不是猜，而是**扫 IL 看每个 `ldstr` 后面紧跟的 call**。

## 环境

```bash
PY="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
"$PY" -m pip install dnfile      # .NET 元数据解析（装一次即可）
```

## 步骤 1：解析 #US 字符串堆

### ★★★★ 堆起点**必须从 PE 元数据解析**，绝对不要"猜"

~~找堆起点：从任意已知串反推，或扫描"能连续解析 ≥30 个条目"的最早位置。~~
**↑ 这句过时且有害。** 实测用启发式定位会偏 30+ 字节，读出 `敩r杲b`（`ie`+`rg`+`b` 字节错位）
这类乱码，而且**能"解析"出很多条目、看不出错**，极难察觉：

| 方法 | 得到的起点 | 判定 |
|---|---|---|
| 「连续解析最多条目」 | 378488 | ✗ 错，差 36 字节 |
| 「ldstr rid 命中率最高」 | 377457 | ✗ 更错 |
| **PE 元数据解析** | **378524** | ✓ 权威（且条目数 577 与记载完全吻合）|

**偏移本来就写在元数据里**，解析路径（ECMA-335）：
```
DOS header   -> e_lfanew @0x3C
PE header    -> NumberOfSections @coff+2, SizeOfOptionalHeader @coff+16
Section[]    -> (VirtualSize, VirtualAddress, SizeOfRawData, PointerToRawData)，用于 RVA->文件偏移
OptionalHeader.DataDirectory[14] -> CLI Header RVA（PE32 起点 opt+96，PE32+ 起点 opt+112）
CLI Header   -> Metadata RVA/Size @cli+8
Metadata Root-> "BSJB" 签名；版本串长度 @md+12；Flags(2)；StreamCount(2)
StreamHeader[] -> (Offset, Size) + 以 0 结尾的名字（**每条后 4 字节对齐**）
              -> 找名字为 "#US" 的那条
```
现成实现：`AtlanticFleetCN/src/dotnet_us.py`。

### ★★ 两个必踩的收尾细节
1. **`#US` 堆开头有 1 字节保留空串**，真实条目从 `us_off + 1` 开始。
   从 `us_off` 直接解析会得到 **0 条** —— 最容易卡死的一步。
2. **`ldstr` 的正则是 `72 <3字节 rid 小端> 70`**（`0x70` 是 token 的表类型字节）。
   写成 `72 (.{4}) 70` 会多取 1 字节，扫出的 rid 高达百万级（远超文件大小）。

### 条目结构
```
[压缩长度前缀 1~2 字节][UTF-16LE 文本][尾字节 0x00 或 0x01]
```
```python
def dec_prefix(d, p):
    b0 = d[p]
    if b0 < 0x80: return 1, b0                                    # 1 字节
    if b0 < 0xC0: return 2, ((b0 & 0x3F) << 8) | d[p + 1]         # 2 字节
    return 4, ((b0 & 0x1F) << 24) | (d[p+1] << 16) | (d[p+2] << 8) | d[p+3]
```
★ 前缀值 = **内容字节数 + 1**（含尾字节）。

### 从 PE 解析出的流布局（实测参考）
```
Assembly-CSharp.dll (408576B): #~ 300952/35244  #Strings 336196/42328
                               #US 378524/20884  #GUID 399408/16  #Blob 399424/7408
firstpass.dll       (343040B): #~ 214580/75924  #Strings 290504/30076
                               #US 320580/9004   #Blob 329584/11772  #GUID 341356/16
```

> 关卡/资源文件（level0、sharedassets）用 4 字节小端长度前缀 + UTF-8，不是这套。

## 步骤 2（最关键）：IL 上下文判定

全文件扫 `ldstr` 指令 = `72 <rid 3字节> 70`，**正则必须加 `re.S`**：

```python
for m in re.finditer(rb'\x72(...)\x70', d, re.S):   # 不加 re.S 会漏掉含 0x0A 的 rid！
```

`rid` → 文件偏移 = 堆起点 + rid → 查条目表得字符串。

从 `m.end()` 起用 opcode 长度表解析后续 5~7 条指令，收集 `call/callvirt`(0x28/0x6F) 的目标方法名
（token 高位 0x0A=MemberRef、0x06=MethodDef、0x2B=MethodSpec，用 dnfile 查名字）。

判定：

| 后续调用 | 结论 |
|---|---|
| `set_Text` / `Concat`+`set_Text` / `ToString` | **显示文本 → 可翻** |
| `op_Equality` / `op_Inequality` | 比较值 → 通常**不翻** |
| `BringIn` / `BringInImmediate` / `StartTransition` | 面板/UI 名 → **不翻** |
| `GetButton` / `GetAxis` | 输入轴名 → **不翻** |
| `SendMessage` | 消息名 → **不翻** |
| `SetToggleState` / `SetEnvironmentVariable` / `Resources.Load` | **不翻** |
| 无 call，直接 `stloc`+`br` | **返回值（显示名）→ 可翻** |

**陷阱**：`GetFullDesignation` 这类方法里 `if (arg=="SS") return "Submarine";`
—— 比较值（`SS`/`DD`/`CL`）和显示值（`Submarine`）是**两个不同条目**，只翻显示值即可安全。
不要因为"附近有 op_Equality"就整组放弃，要按条目逐条看。

另一个陷阱：战役事件长文案常是**多行整块**（`主句\n副句` 共 87~186 字符），
`find` 会命中块中间导致长度前缀校验失败，**必须整块替换**。

### 2b. 批量审计：一次揪出「所有被误翻的逻辑字面量」（强烈推荐，别手工逐条看）

把**原版 DLL** 与**汉化后 DLL** 各跑一遍同一个收集函数，返回 `{串: {用到它的方法名}}`，再做差集：

```
onlyB = base 有、current 没有的英文  → 就是我翻掉的（原样暴露）
onlyC = current 有、base 没有的中文  → 一一对应还原
```

实测（大西洋舰队）：base = 144 个逻辑字面量（含中文 0），汉化版 = 177 个（含中文 22），
差集 **22 对完全对上**，无一遗漏。命中判定用方法名关键字即可：
`op_Equality / op_Inequality / Equals / StartsWith / EndsWith / Contains / CompareTo / SendMessage / SetActive / Find`

实现要点：`ldstr` = `72 <tok 4字节> 70`；`MemberRef` 的 rid 用 `enumerate(rows, 1)`（**`row.rid` 属性不存在**，
用它会抛异常被 except 吞掉 → 结果恒为 0，很难发现）；token = `0x0A000000 | rid`。

**典型被误翻清单（务必逐条核对）**：
- 舰种全名：`Battleship / Battlecruiser / Heavy Cruiser / Light Cruiser / Auxiliary Cruiser / Destroyer / Escort Carrier / Aircraft Carrier / Submarine / Torpedo Boat / Merchant`
- 天气：`Dawn / Evening / Night`
- **GameObject 名**（`Find`/`SetActive` 的参数）：`Enemy Ships / Fleet Full / U-Boat Attack / Leaving Combat / Insufficient Renown / Ship already in Fleet or Sunk / " Save Game.\nContinue?" / " Renown?"`
  ⚠️ 这类最隐蔽：**对象名在场景文件里仍是英文**，DLL 改成中文 → `Find` 失败 → **该对象永不显示**
  （用户表面描述是"勾选了却不出现 / 条目渲染不出来"，其实与 UI 绑定无关）
- 挂载配置名（`机型\n弹药`）：**只有单个 `\n` 的版本**不能翻（`Lancaster\nGrand Slam / Condor\nBomb`）；
  `\r\n` 版本是显示用，可以翻

### 2c. 等长文件：直接按偏移恢复（最快的修法）

若汉化产物与原版**字节数完全相同**（如都是 409088），说明当初是「等长替换」→
**`#US` 池条目偏移完全一致**，不必重建，直接覆盖：

```python
eb = en.encode('utf-16-le')
p = base.find(eb)
assert base[p-1] == len(eb) + 1          # ★ 前缀 = 字节数 + 1（不是字符数+1！）
cur[p-1 : p+len(eb)+1] = base[p-1 : p+len(eb)+1]
```

**两个坑**：
1. `#US` 长度前缀 = **字节长度 + 1**（含尾字节）。按「字符数+1」判定会 0 命中，且不报错。
2. 等长替换后**原字符串尾部不会自动清 0**（`Battleship`→`战列舰` 会残留 `leship`），
   所以「可用空间」正好等于**原英文的占用**，恢复时放得回去、不会溢出。

## 步骤 3：块级原地替换（不改文件长度）

```python
def enc_len_fixed(n, plen):        # 关键：前缀字节数必须与原来一致！
    if plen == 1: return bytes([n]) if n < 0x80 else None
    if plen == 2: return bytes([0x80 | (n >> 8), n & 0xFF]) if n < 0x4000 else None
```

条目起点偏移**必须保持不变**（元数据按偏移引用）。新前缀字节数与旧的一致，
中文更短时后面剩余字节成为不被引用的垃圾。中文字符数 ≤ 英文字符数，否则跳过。
写完中文后**尾字节置 1**（含非 ASCII）。

`n < 0x80` 也能编码成 2 字节（`0x80, n`），解码值不变 —— 这正是缩短 2 字节前缀条目的办法。

## ★★ 三个必踩的坑（血泪）

### 坑 1：链式解析只能用于「未打补丁的原件」

条目表靠 `p += plen + L` 链式推进。一旦打过补丁，长度前缀被改小，累加立刻错位——
实测 V10 主程序集只解析出 33 条（原件 577）、V12 firstpass 只解析出 919 条（原件 2115），
于是块级替换只命中 19/130。

**修法**：`patch_blocks(..., entries=ENTS)` 传入由**原件**建立的完整条目表（偏移不变）：
V13 用 `dll_v8_firstpass_cn.dll` 的 2115 条表去打 V12 → 726/726 全中。
每轮补丁都**从原件重新起步**并合并前几轮词表，比在已打补丁文件上累加更稳。

### 坑 2：扫 ldstr 的正则必须加 `re.S`

```python
re.finditer(rb'\x72(...)\x70', d, re.S)   # 不加 re.S：`.` 不匹配 0x0A，含该字节的 rid 全漏
```
漏检会让"比较值"那一条 ldstr 消失，于是下一个 ldstr（其实是返回值）被误判成比较值，
导致整组舰种名被错误放弃。

### 坑 3：判定「是否真的显示」要用 dnfile 权威接口，别自己算堆偏移

逐方法解析 IL + `n.user_strings.get(rid)` 才是准的。
自己用「堆起点 + rid」反查在 firstpass 上匹配率只有 160/2877，权威法是 **1492** —— 差 9 倍，
会严重低估未翻译量。

### 附带结论：条数变少 ≠ 文件坏了

打补丁后链式解析条数下降是**缩短长度前缀的预期结果**。
CLR 按 token 偏移索引条目，不做链式遍历，所以不影响运行。
真正该做的是**字节级审计**：确认所有差异字节落在 #US 堆范围内，且按原偏移能读出中文。

### ★★★ 审计「已打补丁的 DLL」必须按偏移寻址（否则数字全是假的）

上一条说"要做字节级审计"，但**怎么审**才是关键。`entries()` 那种链式解析
一旦用在**产物**上就会提前 `break`，给出的数字完全失真：

| 对象 | 链式解析读到 | 真实值 |
|---|---|---|
| 原版 Assembly-CSharp.dll | 577 条 | 577 ✔ |
| 产物 Assembly-CSharp.dll | **34 条** | 577 |

原因：替换用「等长覆盖 + `0x00` 填充」，形如
`[前缀=15][14B 中文][14× 0x00][0x01]`（实占 30 字节）。
链式解析读到 `v=15` 后 `p += 16`，**把后面 14 个填充 0x00 当成下一条** → `v==0` → break。
只要有一条被替换，其后所有条目就全读不到。

由此还引出一个更隐蔽的后果：**审计报告会说"剩下的都是插件调试串，玩家看不到"** ——
实测这份残缺清单里躺着战役结局、历史事件、战报、舰船数据标签，
把它们当成"不用翻"就会长期漏翻而不自知。

**正确做法 = 按偏移寻址**（等长覆盖不改变任何条目的起始偏移）：

```python
# 1) 用【原件】建条目表（此时链式解析是准的）
us_off, us_size, _ = find_us(orig_bytes)
ents = entries(orig_bytes, us_off, us_size)          # (p, plen, vlen, text)

# 2) 拿每个条目的 p 去【产物】同一偏移读，与原版比对
for (p, pl, v, t) in ents:
    pl2, v2 = dec_prefix(new_bytes, p)
    assert pl2 == pl, "前缀宽度变了 → 违反等长约束"   # 这条断言是安全阀
    t2 = new_bytes[p + pl2 : p + pl2 + v2 - 1].decode("utf-16-le")
    # t2 == t     → 未动（禁译 / 技术串）
    # t2 含 CJK   → 已译
    # 其它        → 异常，必须查
```

三态输出（已译 / 未变 / 异常）才是可信的验收。
**「前缀宽度变化」必须为 0** —— 不为 0 说明等长约束被破坏，CLR 可能按原偏移读到错误的串。

现成脚本：`tools/audit_dll_real.py`（`--json` 出报告，`--list-left` 列未变条目）。

### ★ 形态过滤规则会误伤真文本（别拿它替代词表）

早期 patch 器除了 MUST 禁译表，还叠了三条「形态规则」自动跳过：
`ORDNANCE_PAIR`（`^A\nB$` 形状）、`TECH_ONLY`（全小写标识符 / 短大写 / 纯符号）、
以及「含 `\n` 且长度 > 60 则跳过（视作长简报）」。

**实测它们挡掉的正是该翻的东西**：
- `' Save Game.\nContinue?'`、`' Campaign.\nContinue?'` 恰合 `^A\nB$` → 整条跳过
- 战役结局、历史事件、战报（含 `\n` 且 > 60 字符）全被长度规则挡掉
- `' damage.\nCurrent repairs delayed by '` 这类**拼接片段**同样被误杀

**正解**：只留「MUST 禁译表」做结构保护，
**要不要翻完全由词表决定**（有译文且不长于原文就翻，没有就自然落空）。
形态规则最多用于**审计分类**，不要用于**跳过**。

### ★ 两张词表的优先级要一致

DLL 侧和资源侧如果对「项目词表 vs 遗留大表」的覆盖顺序相反，
同一句话在 level0 和 DLL 里会得到不同译文 → 界面出现两种说法。
本项目实测：`03_patch_resources.py` 只用项目表，而 `07_patch_dll.py` 让遗留大表覆盖项目表。
**统一为「项目表最后加载 = 最高优先级」，大表只作补充。**

## 步骤 4：交叉验证 level0 用词

翻之前先查 `translation_master.json`，**与关卡数据已用的中文保持一致**，否则两边对不上会显示空白。

## 步骤 5：打包签名

```bash
JAVA="<ws>/tools/jre/jdk-17.0.20+8-jre/bin/java.exe"
"$JAVA" -jar "<ws>/tools/uber-apk-signer.jar" --apks X_unsigned.apk \
  --ks "<ws>/uruban.keystore" --ksAlias uruban --ksPass <你的密钥库口令> --ksKeyPass <你的密钥口令> -o signed_x
```

替换 `assets/bin/Data/level0`、`Managed/Assembly-CSharp.dll`、`Managed/Assembly-CSharp-firstpass.dll`，
跳过 `META-INF/`。打包后必做：`testzip()` + 抽样验证中文在位 + 验证 `Dive`/`Zoom In`/`Main Menu`
等引用名仍在。

## 已验证产物（大西洋舰队）

- `_inventory/patch_blocks.py` — 块级替换器（可复用）
- `_inventory/build_v10.py` / `build_v11.py` — 主程序集 / firstpass 构建脚本
- 堆起点：Assembly-CSharp `378853`，firstpass `357501`
- 主程序集 577 条目 / firstpass 2118 条目

## 译名必须用「历史标准译名」，不能机翻

游戏舰船/地名都有约定俗成的中译，且游戏本身往往有命名规律。动手前先摸清规律：

- **花级（Flower class）护卫舰 → 一律译花名**：Abelia 六道木、Alisma 泽泻、Alyssum 庭荠、
  Arbutus 杨梅、Aster 紫菀、Calendula 金盏花、Cyclamen 仙客来、Delphinium 飞燕草、Dianthus 石竹。
- **城堡级（Castle class）→ 译"XX城堡"**：Allington Castle 阿林顿城堡。
- **部族级（Tribal class）驱逐舰 → 译部族名**：Ashanti 阿散蒂、Bedouin 贝都因、Eskimo 爱斯基摩。
- **主力舰/航母 → 历史标准音译**：Illustrious 光辉、Belfast 贝尔法斯特、Barham 巴勒姆、
  Prince of Wales 威尔士亲王、Duke of York 约克公爵。

**实战查出的误译**（词表机翻导致）：`Acasta→金合欢`（那是 A 级驱逐舰，金合欢是 Acacia）、
`Aubretia→水母`（花级，应为南庭霁）、`Dahlia→戴利娅`（应为大丽花）、
`Bluebell→风信子`（应为蓝铃花，Hyacinth 才是风信子）。**词表也要审，不能照抄。**

## ★★ 译名必须联网查证，不能凭模型记忆

用户原话："你的联网搜索呢？" —— 这条必须遵守。模型记忆里的舰名/地名译名**不可靠**，
且游戏圈还流传着以讹传讹的译名。动手前用 WebSearch 逐个核实，重点查：
百度百科 / 中文维基、NGA 或专业论坛的**译名勘误帖**、军事媒体（凤凰网等）。

**血泪案例**：`Acasta` 有"阿卡斯塔"与"阿卡司塔"两派，模型记忆倾向后者（碧蓝航线/战舰少女）。
实际查 NGA《战舰世界全系舰名翻译勘误》才确认：
**"阿卡司塔"是《战舰少女》2016 年的笔误**，后被国服与碧蓝航线沿用才扩散，正确译名是**"阿卡斯塔"**。

**再查深一层**：`Bellwort` 与 `Campanula` 词表都译"风铃草"（重名）。
联网才知 Bellwort = **Uvularia（秋水仙科，垂铃草）**，与 Campanula（桔梗科风铃草）**是两种植物**。
`Candytuft` 同理：= Iberis，**十字花科屈曲花属**，正名"屈曲花"，"白烛葵"只是花语别名。

## 用「反向索引」查重名

建 `中文 -> [英文列表]`，长度 >1 即冲突：
```python
rev = collections.defaultdict(list)
for en in ships: rev[idx[en]].append(en)
dups = {cn: v for cn, v in rev.items() if len(v) > 1}
```
单复数（Air Strike/Airstrike、Depth Charge/Charges、Fighter/Fighters）属正常；
**不同舰同译名是真 bug**（如 Gallant 与 Valiant 都译"英勇" → Valiant 应改"勇士"，
且词表内已有 `BB Valiant→BB 勇士`，必须自洽）。

## ★ 注意「双条目」机制：改一处会显示两个译名

有些 DLL 里每个名字有**两份**条目：
1. 英文条目（代码引用 / 查表键）
2. 早期汉化**新增的中文条目**（常带 18 个前导空格，供 UI 列表显示）

只改英文 → 同一艘船在列表里是旧译名、别处是新译名。
**必须加同步步骤**：遍历相邻条目对（英文舰名 + 中文），若 `词表[英文] != 中文` 就同步；
中文变长时**削减前导空格**保证 `len(new) <= len(原条目)`，否则跳过（硬约束，强改会覆盖下一条目）。

## ★ 同一舰名可能在「禁译表」里 —— 但它仍有可翻的那份

诊断时常发现舰名同时出现在 `must_keep_english` / `all_object_names`（因为它是 GameObject 名，
翻了会让 `GameObject.Find` 失败），于是整名被 BLOCK 拦下、界面上仍是英文。

但堆里它往往有**两份条目**，必须分开对待：
- **带 18 空格缩进** → UI 舰名列表显示用 → **可翻**
- **无缩进** → GameObject 名 / `==` 比较用 → **必须保留英文**

```python
lead = t[:len(t) - len(t.lstrip())]
if len(lead) < 4:      # 无缩进 = 代码用的那份
    continue           # 跳过，保留英文
```

**反向的坑**：为了补译而做 `BLOCK -= {'Illustrious','Triton'}` 这类整名放行时，
会把**无缩进那份也翻掉**（破坏 GameObject 名）。放行后务必再剔除：
```python
for k in list(ALL.keys()):
    if k.strip() in GUI_NAMES and len(k) == len(k.strip()):
        del ALL[k]
```
（实战中我就是这样误伤了 Illustrious，V16 才修回。）

**另需注意**：`Active/Normal/Over/Disabled/State/Start/Back/Continue/Campaign` 这类词
既是舰名又是 EZ GUI 状态/按钮名，**风险高于收益，保持英文**。

## ★★★ 最重要：无缩进的英文条目 = 查表的 KEY，绝对不能翻

这是本项目踩过**两次**的坑（V7 的 `Bomb Release` 俯冲 bug、V18 的"前进不显示" bug）：

很多 DLL 里存在**成对的「英→中」对照表**：
```
Smiter(英文,无缩进) → 自惭形秽(中文)
Smoke (英文,无缩进) → 烟雾(中文)
Somali(英文,无缩进) → 索马里(中文)
```
- **无缩进的英文条目 = 代码查表用的 KEY**
- 紧随其后的中文条目 = 显示用的 VALUE

把 KEY 翻成中文 → 代码仍拿英文去查 → **查不到 → 界面空白**。
症状很典型：**功能完全正常（逻辑走索引），但某个词不显示**。

**判据**：`len(t) == len(t.strip())`（无前导/尾随空白）→ 极可能是 KEY。
**只翻带缩进的那份**（UI 列表显示用），KEY 原样保留。
V18 就是因为翻了 `Ahead Full` 这个 KEY，导致车钟"前进"不显示；
而 `Smoke` 没翻所以"烟雾"正常——两者对照正好印证了机制。

**必须保留英文的机制标识**（档位/动作/武器，常被当 KEY 或比较值）：
`Ahead 1/3 / Ahead 2/3 / Ahead Standard / Ahead Full / Flank / Back / Stop / Smoke /
Movement / Move All / Action / Firing / Search / Surface / Diving / Periscope Depth /
Shallow / Deep / Very Deep / No Action / Air Strike / Depth Charge(s) / Torpedo(es) / Guns / Shells`

**排查"某词不显示"的步骤**：
1. 先查字体：BMFont `chars count` / CJK 码位，确认不是缺字（大概率不是）。
2. 查该词是否被翻 — 用 V8 条目表的偏移去读新文件的当前值，对比原文。
3. 若被翻且无缩进 → 几乎可以断定是 KEY 被改，恢复英文即可。

### ★★★★★ 第三次（代价最大）：firstpass 整表被翻 → **卡 loading**

**症状**：装得上、**卡在 loading**（不是闪退，是卡住不动）。

**定位（对照法，一步锁定）**：对比"能跑的旧版"与"卡住的新版"的 3 个关键文件 md5 ——
**能跑的版本用的是 `base` 的「未汉化 firstpass」，卡住的版本用的是汉化版** → 元凶立刻暴露。
（别在汉化产物内部反复推理，先和「已知能跑的版本」逐文件比对。）

**根因**：firstpass 里 `[英文KEY][中文VALUE]` 成对存储的查表（#US 堆起点 @357501，共 2850 条），
**汉化时把英文侧一起翻了**：
```
#0   A Class Destroyer  ->  A级驱逐舰   ★KEY 被翻 → table["A Class Destroyer"] 查不到 → 卡
#1   A级驱逐舰           ->  A级驱逐舰   VALUE，正确
#2   A Turret           ->  A炮塔      ★KEY 被翻
```

**自检（汉化完必做，30 秒 —— 我这次就是漏了它）**：
```python
be = entries(base, 堆起点)              # [(off, plen, vlen, text)]  ← 用【原版】建偏移表
for k,(off,plb,vlb,tb) in enumerate(be):
    plv,val = parse_at(v72, off)        # 用【原版偏移】去读汉化版
    tv = v72[off+plv:off+plv+val-1].decode('utf-16-le')
    if tb and not is_cn(tb) and is_cn(tv):
        print("★KEY 被翻", k, off, tb, "->", tv)
```
**实测命中：firstpass 868 条、Assembly-CSharp 165 条 —— 全部必须恢复英文。**

**判据（怎么区分 KEY 与可翻的显示文本）**：该表是 **`[EN][CN][EN][CN]…` 成对存储** →
- **英文条目的下一条是中文** → 它是 **KEY**（中文是它的 VALUE）→ **必须恢复英文**
- **连续两条都是英文** → 独立显示文本 → **可以翻**

**务实策略**：先出一版"回退到已知能跑 DLL"的包让用户先玩上，
再逐步把汉化补回来 —— 比死磕一个 DLL 一次到位更靠谱。

## ★★★ 修 bug 不等于回退翻译：必须精确到「哪一个字符串、哪一个方法、怎么用」

**踩过的坑**：为了修"飞机不能俯冲"，我把 `None/Star Shell/Guns/Glide Bomb/Bomber/Depth Charge/
Torpedo/Bomb/Fighter` **整批从翻译表删掉**回退英文 —— 结果 bug 修了，**但已经翻好的词全变回英文**，
被用户斥为偷懒。

**正解**：逐方法 dump IL，**只有被 `op_Equality`/`op_Inequality` 比较的那个词才保英文**：

```
DropOrdnance :  'Dive' [op_Equality]  ← 只有它必须英文（else 飞机不能俯冲）
                'Guns' [set_Text]     ← 显示，应当翻
NextMoveAction: 'None' 'Surface' 'Dive' 'Smoke' [全 set_Text]  ← 应当翻
NextAction    : 'Star Shell' [set_Text]  ← 应当翻
```

**双份结构是两全的正解**：若 DLL 里存在「英文 KEY + 中文 VALUE」成对条目
（如 `Bomb` + `炸弹`、`Ahead Full` + `全速前进`），则
**KEY 保英文（代码查表用）、VALUE 照翻（显示用）** → 功能与汉化兼得。
`KEY` 特征：无前导空白、紧跟一个中文条目。

**判据速查**：
- `op_Equality` 操作数 → 保英文
- `set_Text` / `Concat` 结果直接显示 → 翻
- `BringIn*` / `StartTransition` / `GetButton` / `GetAxis` / `SendMessage` → 保英文
- `Resources.Load` 路径、`(Clone)` 资源名 → 保英文

## ★★★ 动手前先确认「原版文件」是真的原版

**踩过的坑**：项目里有个 `dll_orig_Assembly-CSharp.dll` 我一直当原版用，
后来查天气名才发现它的 `GetWeather` 里已经是**中文**"黎明/夜晚"，
而真正的原版 `_tmp_base/Assembly-CSharp.dll` 里是 `Dawn`/`Evening`/`Night`。
→ **整套 IL 分析和补丁都建立在一个被污染的文件上**。

**校验方法**（开工前必做）：挑一个**确定该为英文**的串，在两个候选原版里对比：
```bash
grep -c "Dawn"        _tmp_base/Assembly-CSharp.dll   # 有 → 真原版
grep -c "黎明"        _inventory/dll_orig_....dll     # 有 → 已被污染
```
原版错了，后面全错；发现污染立刻换回真原版重建。

## ★★★ 改文件时要同步改词表，否则重建会把老 bug 带回来

**踩过的坑**：V8 修「教程超出文本框」时，是**直接对 level0 文件**做
`<br>` → `\n`+3空格 的等字节替换（因为 `SpriteText` 只认 `\n`，不解析 `<br>`），
**但 `translation_master.json` 里的译文一直留着 `<br>`，没同步改**。
后来用护栏脚本**重建** level0 时，译文从词表读入 → **`<br>` 又回来了**（48 处）→ 教程再次溢出。

**规则**：任何"就地修补"都要**同时更新词表**，否则下次重建就会重现。
更稳妥的做法是**在构建脚本里内置规范化步骤**，例如：
```python
for k in list(T):
    if '<br>' in T[k]:
        T[k] = T[k].replace('<br>', '\n   ')   # 等字节/等字符替换，与历史处理一致
```
**重建后必须校验**：`d.count(b'<br>') == 0`。

## 排查「按名匹配」的四类用法（不止 op_Equality）

1. **`op_Equality`/`op_Inequality`** —— 最常见，逐方法扫 `ldstr` 后紧邻的 call
2. **`SendMessage` / `Invoke` / `StartCoroutine`** 的字符串参数（消息名/方法名）
3. **`GameObject.Find` / `Resources.Load` / `GetComponent`** 的名称与路径
4. **`Contains` / `StartsWith` / `EndsWith` / `IndexOf`** 的子串匹配

批量 CHECK：扫出所有**已翻成中文**的字符串，看它是否出现在上述调用的参数位置 ——
若不是 `set_Text`，就是潜在 BUG。（实测本项目第 2~4 类均为 0，第 1 类揪出 5 处。）

## ★★★ 译文超框（文字挤出文本框）的排查与修法

**框宽怎么定**：框宽 = **原英文文本的最长行宽**（汉字按 2、其余按 1 计）。用它去筛「行宽 > 框宽」的译文行。

处理顺序：
1. 算框宽 → 2. 筛超宽行 → 3. **精简译文 + 插换行**（保持译文总字节 ≤ 原英文总字节，省出的空间就是"加页"）→ 4. 替换后**把条目内剩余字节清 0**。

**两个必踩的坑**：
- **补位填空格 = 自己制造超框**：等长替换补位一律填 `0x00`，绝不填 `0x20`（空格是可见字符，会让每行多占宽度）。本项目中把 `<br>` 换成 `"\n"+3空格`，结果每行平白多 3 宽 → 中文被挤出框，排查了很久才找到。
- **替换后不清 0 残留**：新译文更短时，条目尾部仍是旧译文尾巴，会和新译文拼在一起显示成一团。清 0 范围要用**替换前**记录的前缀值 `pv_old`：`entry_end = st + plen + (pv_old - 1)`，若用替换后的新前缀值会算出空范围 → 根本没清。

**SpriteText 不解析 `<br>`，只认 `\n`** —— 词表里的译文若含 `<br>`，构建脚本里要统一替换成 `\n`（+ 补 `0x00`）。

另注：判断"是否真的超框"要用**框宽**比，别用"该行相对原英文行宽的超出量"比 —— 原英文某些行是空行（0 宽），中文在那写了字会显示成"超出 N 宽"的假阳性。

## ★★★ 最后一道关：批量校验「被 op_Equality 比较的串是否仍为英文」

修完一轮后**必须**跑这个检查，能一网打尽同类型错误（我靠它一次揪出 5 处误翻）：

```python
# 1) 扫出所有 ldstr，记录「紧邻下一条指令是 op_Equality/op_Inequality」的字符串及其方法
# 2) 再到**已经打过补丁**的文件里查这个字符串是否还以原样存在
# 3) 不存在的 = 已被翻译 = 潜在 BUG，逐一恢复英文
```
实战战果：`No Target`(LookAtTarget)、`DONE`(BringInCompleteButton)、
`Kormoran Class Auxiliary Cruiser`(PopulateInShipInfo)、
`German forces successfully occupy France./Norway.`(CheckZones) 全部被揪出。

**注意**：比较值可能是**多行长块**（`…France.\nFrench ports…`），剔除时要按**前缀匹配整块**，
只删单句无效。

## ★★★ level0 里的「连续短串数组」必须整体保英文

资源文件里常有一串**连续的长度前缀短串**，那是代码按名匹配的**枚举数组**，例如武器/动作表：
```
AP Shell | HE Shell | Star Shell | Torpedo | Homing Torpedo | Depth Charge
Hedgehog | Squid | Airstrike | Ready | Launch | Recover | Unready | Surface | Dive | None
```
**半翻半留最危险**（如 `照明弹 / Torpedo / 声导鱼雷 / 深水炸弹…`），
代码匹配到的类型忽中忽不中，表现为"鱼雷没发射却扣数量""武器切换后不生效"这类诡异 bug。
**整体保持英文**，显示中文交给 DLL 的英中对照表 → 功能与汉化两不误。

**识别方法**：解析连续条目，若出现「长度前缀 + ≤20 字符短串」密集排列，且成员是
武器/动作/弹药类型名，即为枚举数组，一律不翻。

**⚠️ 判据的边界（我在这里栽过一次）**：判定「连续段」时，**段长必须 ≥3**。
用「有 1 个短英文邻居」太宽松，会**误伤战役简报**——
简报结构是 `[日期][时段][长文]`，只有 2 个短英文串（日期 + `Morning`），
宽松判据会把它当数组，把简报的日期字段也恢复成英文，汉化白做。
实测对比（同一份数据）：`≥1 邻居` 命中 315 处（含误伤），`≥3 连续` 命中 285 处（**零误伤**）。

**用「原版」建表、用「汉化版」读值**：
```python
sa = scan(原版对象)                 # 判据必须在【原版】上算，不能在汉化版上算
flags = array_flags(sa)             # 连续 ≥3 个短英文串 → True
for k,(p,L,E) in enumerate(sa):
    if E in MUST or flags[k]:       # 该位置该是英文
        if sc[k][2] != E: 恢复成 E
```

## ★★★ 「全量翻译」≠「什么都翻」——禁译表必须一直带着

**踩过的坑（代价最大的一次）**：用户要求"不能回退任何翻译，必须全量翻译"，
我于是**删掉了 V7 辛苦建起来的禁译表**（1653 条）→ 弹药/挂载标识被翻 →
**飞机又无法俯冲攻击**（V7 修过的 bug 原样复发）。

**正确认识**：
- **该翻的**：UI 文本、教程、简报、舰名、地名、天气名、车钟档位 → 玩家看得到的全是中文
- **绝不能翻的**：被代码按名匹配的**标识**（弹药/挂载/动作类型数组、组件名、物件名、输入轴/消息名）
  → 翻了程序就找不到对象/匹配不上，功能直接坏
- **两者共存**才叫"全量翻译"：level0 里标识保英文，玩家看到的中文由 DLL 侧显示条目/对照表提供

**禁译表怎么建（照抄这份来源即可）**：
```python
MUST  = set(json.load(open("_inventory/must_keep_english.json")))       # 人工确认的必须英文
MUST |= set(json.load(open("_inventory/all_object_names.json")))        # UnityPy 读出的全部物件名
MUST |= set(json.load(open("_inventory/gameobject_names.json")))        # 全部 GameObject 名
MUST |= ORDNANCE   # 弹药/挂载/动作集（见下）
MUST |= {C# 反编译源码里 ==/!= 与 SendMessage/Invoke 的字面量}
MUST |= set(json.load(open("_inventory/logic_keys.json")))              # IL 里 op_Equality 的操作数
MUST |= set(json.load(open("_inventory/shipclass_keys.json")))          # 舰级/舰名/型号键
# 构建时：T = {k:v for k,v in T.items() if k.strip() not in MUST}
```

> ★★★ **三张结构表缺一不可**（2026-10-01 实测踩到）：
> `logic_keys.json`（代码比较/分支的枚举值）、`shipclass_keys.json`（舰级/舰名/型号键）、
> `object_ref_keys.json`（按名查找的对象/按钮名）**必须全部并入 MUST**。
> 我这次只加载了第三张 —— 结果 `Kormoran Class Auxiliary Cruiser`、`Pinguin Class Auxiliary Cruiser`、
> `No Target`、`Select Handle`、`Dive`、`Smoke` 全在 `logic_keys` 里却没被保护，
> 差点被当普通文本翻掉（`No Target` 在表里的值就是 `无目标`，看着像"该翻"）。
> **一张表只能挡住一类错，别只接一张。**

> ★★★ **形态启发式是禁译表最大的污染源**（2026-10-01 实测踩到，代价是一次返工）
> 除了"三表都要接"，**表的生成判据本身也必须有证据**。本项目 `01c` 曾额外并入两类无证据判据：
> · `singleton`：`^[A-Z]{1,5}$` / `^(?:…)?Aircraft$` / `^[A-Za-z\-]+-Based\s+[A-Za-z]+$`
>   纯形态匹配 → 把 `Aircraft`、`Land-Based Aircraft`、`Carrier-Based Aircraft` 判成"分类 KEY"
> · `MANUAL_BLOCK`：42 条手工清单
>
> 拿源码逐条复核 94 条后：**43 条源码里根本没有字面量**、**43 条只出现在 `.Text =` 右侧**，
> 真正被引用的只有 **10 条**。误伤名单与用户实机反馈（照明弹 / depth charge / hedgehog /
> 训练任务名 / 帮助里的 camera·movement·aircraft 仍是英文）**逐条对应** ——
> 也就是说，**不是我漏翻了，是禁译表把它们锁死了**。
>
> **裁定方法（行级，别用形态）**：取字面量所在**整行**，看它左侧 60 字符
> · 含 `== ` / `!= `                          → 比较值 → 禁译
> · 含 `BringIn(` / `SendMessage(` / `.Find(` /
>   `Resources.Load(` / `SetActive(` …        → 按名引用 → 禁译
> · 其余（`=` 赋值 / `return`）                → 显示文本 → **放开**
>
> ⚠️ 两个易错点：
> 1. **别用单 `=` 判赋值** —— `== ` 里也含 `=`，会把比较值误判成显示文本。
> 2. **必须扫该串的所有出现，任一处是 REF 就禁译** —— 见下面的反例。
>
> 现成脚本：`tools/refine_blocklist.py`（`--report` 只出报告 / `--apply` 写回并自动备份 `.bak`）。

> ★★ **反例：代码可能把 UI 文本当状态标志来比较**
> ```csharp
> this.uifunctions.bombbutton.Text = "Dive";                 // 赋值：看起来是纯显示
> ...
> if (this.uifunctions.bombbutton.Text == "Dive") { ... }    // 又拿来当状态判断
> ```
> 同一个字符串**既是显示文本又是比较值**。只看到赋值那一处就放开 → 按钮状态机立刻失灵。
> 这正是 `Dive` 必须保持英文、而 `Glide Bomb`（只有赋值、无任何比较）可以安全翻译的原因。
> **判据落点：不是"这个串像不像显示文本"，而是"这个串有没有被比较过"。**

> ★★ **再补一刀：短通用词与 UI 控件状态名，一律不翻**（2026-10-01 实测，我自己引入又回退）
> 「源码里没有这个字面量」**不等于**「可以安全翻译」。还要过一道**风险—收益**：
> · `YES` `NO` `On` `Off` `Back` `Stop` `Flank` `TEXT` 这类短通用词
> · EZ GUI `UIStateToggleBtn` 的 `states[].name`，在 level0 里长这样：
>   `obj#8713 = ['Off','On','Secondary','Disabled','Off']`、`obj#8696 = ['State 1', … ,'State 7']`
>
> 这些词**玩家本来就看得懂，翻译收益接近于零**；而一旦组件内部按状态名做默认态/查找，
> 就会坏掉一整排开关按钮（本项目 level0 里有 **20+ 个**这样的对象，涉及 `tid=-4/-5`）。
>
> 实测教训：首版行级裁定把 `YES`/`NO` 判为 NOQUOTE 放开 → 产物里这些开关对象的
> "是 / 否 / 文本 / 返回"被改掉，两版 level0 出现 **74 个对象差异**。
>
> **落地方式**：裁定脚本里维护一个 `ALWAYS_KEEP` 强制保护集，并**从原始表重新裁定**
> （不要在已被改过的结果上二次裁定，否则被删掉的项永远回不来）。
> 本项目该集合 = `YES NO TEXT On Off Active Normal Over Disabled Secondary
> Filled Empty Pressed Selected Highlighted Back Stop Flank State 1..7`。

`ORDNANCE = {AP Shell, HE Shell, Star Shell, Star shell, Torpedo, Homing Torpedo, Depth Charge,
Hedgehog, Squid, Airstrike, Ready, Launch, Recover, Unready, Guns, Glide Bomb, Fighter, Bomber,
Bomb, Rocket, Surface, Dive, Smoke, None, Submerge, Periscope Depth}`

**判据**：拿不准就**对比"当年能跑的版本"**（本项目是 `level0_v8`），
找出"曾经是英文、现在变中文"的串 —— 那些就是被误翻的标识。

## ★★★ 禁翻总清单（同类错误我犯过 3 次，务必逐条核对）

以下字符串**一律保持英文**，翻了一定出 bug（功能失灵/选项消失/界面空白）：

**A. 军械与挂载名**（`DropOrdnance` 等按名匹配）：
`None` `Dive` `Star Shell` `Guns` `Glide Bomb` `Torpedo` `Torpedoes` `Homing Torpedo`
`Depth Charge` `Depth Charges` `AP Shell` `HE Shell` `Bomb` `Fighter` `Bomber` `Rocket`
`Bomb Release` `Dud Torpedo` `4x` `8x` `64x`

**B. 动作与档位**（HUD 状态机 / 车钟）：
`Ahead 1/3` `Ahead 2/3` `Ahead Standard` `Ahead Full` `Flank` `Back` `Stop`
`Action` `Movement` `Move All` `Firing` `Search` `Surface` `Diving` `Periscope Depth`
`Shallow` `Deep` `Very Deep` `No Action` `Air Strike` `Smoke`

**C. 飞机挂载配置名**（`机型\n弹药` 两行式，代码按名匹配以列出可选弹药）：
`Lancaster\nGrand Slam` `Dornier Do217\nFritz X` `Condor\nHs293` `Ju87 Stuka\nBomb` …
**识别法**：两行、每行 ≤22 字符、总长 ≤42 → 一律不翻。

**C2. ★★ 飞机分类标识**（独立一条，代码按分类查资源 / 做过滤）：
`Land-Based Aircraft` `Carrier-Based Aircraft`
**识别法**：对象里**只有它一个字符串**，形如"某某 Aircraft / 某某-Based" → 分类 KEY。
翻了 → 该分类的飞机**完全不显示**（本项目表现为"战斗界面看不到陆基飞机"）。
⚠️ 这类最容易漏：它长得像普通 UI 文本（"陆基飞机"很自然），但其实是 KEY。

**C3. ★★ EZ GUI 按钮状态名**（常与 `Active`/`Disabled`/`Normal`/`Over` 并列出现）：
`Bomb Release` 以及同组的 `Active` `Normal` `Over` `Disabled` `State 1`~`State 7`
**识别法**：某字符串与 `Active`/`Disabled`/`Normal` 在同一个对象里并列 → 是按钮状态名。
翻了 → 按钮点不动 / 动作触发不了（本项目表现为"**俯冲投弹失效**"）。

**D. 面板/输入/消息名**：`Main Menu` `Fleet Manager` `Bring In Forward` `Dismiss Back`
`Start` `Zoom In` `Zoom Out` `Horizontal` `Vertical` `Mouse X/Y` `Fire1`

### 换行符也能是 bug 源
重建资源文件时若把 `\n`(0x0A) 写成 `\r\n`(0x0D0A)，**字符串长度 +1 且内容不匹配**，
代码按名匹配直接失败（本例：`Lancaster\nGrand Slam` 20B→21B，导致"大满贯"选项消失）。
重建后务必校验关键串的**原始字节**与原件一致。

### 重建 level0 时排除「两行式短串」的写法
```python
for _k in list(T):
    if "\n" not in _k: continue
    p = _k.replace("\r\n","\n").split("\n")
    if len(p) != 2: continue                      # 只要两行式，避免伤及教程长文
    if len(p[0]) <= 22 and len(p[1]) <= 22 and len(_k) <= 42:
        del T[_k]
```

## ★★ 教程文本＝「标题区 + 正文」两套，且 firstpass 里英文/中文副本并存

教程在游戏里有**两个存放处**，汉化时**两处都要改**，否则会出现"菜单是英文、进去是中文"：

| 位置 | 结构 | 换行 | 用途 |
|---|---|---|---|
| `level0` | `标题\r\n\r\n描述\r\n\r\nTopics:\r\n- 项` | `\r\n` | 教程菜单列表 |
| `Assembly-CSharp-firstpass.dll` | 同一套内容的 `\n` 版 | `\n` | 教程正文页 |

**firstpass 里的坑**：同一个教程会**同时存在英文副本和中文副本**（成对存储）。
只翻了其中一份，另一份仍显示英文。定位法：搜英文首句（如 `Demonstration of naval gunnery`），
读它**前面 1~4 字节**当 #US 长度前缀（值必须 `== 内容字节数 + 1`），命中即为独立条目。

**firstpass 的 #US 前缀可能是 2 字节**：`0x80|(len>>8), len&0xFF`。
替换时**保持前缀字节数不变**（擅自改成 1 字节会让后续数据整体前移）。

## ★★ 术语一致性检查（打磨期必做）

同一概念被译成两种写法，是"机翻感"的主要来源。批量查：

```python
for variants in [["目标解算","目标方案"], ["潜艇","潜水艇"], ["刺猬炮","刺猬弹","刺猬"], ...]:
    # 在 level0(UTF-8) 与 DLL(UTF-16-LE) 里分别 count；两边都出现 → 必须统一
```

本次实修：`目标方案→目标解算`(22) / `电报→车钟`(3，telegraph 曾被误译为"电报") /
`刺猬弹→刺猬炮`(8) / `鱿鱼弹→乌贼炮`(6) / `反潜战→反潜作战` / `舰船移动→舰船机动` / `介绍→简介`。

**等长替换的硬规矩**：
- **等长**（UTF-16 字节数相同）→ 直接覆盖，安全。
- 改**更短** → 会留下 `\x00\x00`（NUL），在**句子中间**显示异常（`潜水艇`→`潜艇` 正因此放弃）；
  只有**独立条目**才能改短（同时改长度前缀 + 剩余清 0）。
- 改**更长** → 只能在独立条目里做，且条目原空间要够。

**错别字审计**：机翻残留常见 `在一栋时` / `脸上红色圆圈` / `靠近智` / `制定深度` 这类**形近字错位**，
靠批量搜可疑词 + 人工通读中文长文本抓。

## ★★★ 批量替换短词前，必须先 dump 全部出现位置看上下文（我踩过）

我按词表把 `舰队 → 军团`（对应英文 `Legion`，某驱逐舰名）批量替换，
**结果 26 处全被改** —— 而 `舰队` 在别处是**常用词**（`舰队模式`、`舰队：`、`巡逻舰队`），**全被误伤**。
幸好复检时发现并回滚。

**规矩**：
- 替换 **≤3 个汉字**的短词前，先把它**所有出现位置**打印出来（前后各 60 字节），
  确认**每一处都是同一语义**才批量替换
- 长串（≥8 字）或有明显语境的（含换行/标点）一般安全
- 替换后**必须复检**：目标词残留 = 0 **且**同形常用词数量不变

```python
for m in re.finditer(re.escape("舰队".encode('utf-16-le')), d):
    print(d[max(0,m.start()-60):m.start()+60].decode('utf-16-le','replace'))
# 逐条确认后再决定是否 replace_all
```

## ★★★ 词表「短键误匹配」——一个键是另一个键的前缀时，会改错字段

**最隐蔽的一类错译**（大西洋舰队 V72 才挖出的真根因）：

`translation_master.json` 里同时存在
```
"8 April 1940"                 -> 整条简报中文     ★错：这是"日期"字段的键
"8 April 1940\r\n\r\nThe …"    -> 同一条简报        ★对：但文件里是 \r\n\r\n
```
真实对象结构是 `[日期 12B][时段][简报 218B]`。构建器拿短键 `find` 时**先命中了 12 字节的「日期」字段**
→ 把 274 字节的简报中文塞进日期槽，**真正的简报槽仍是英文**。

症状：**日期栏显示一大段简报** + **简报残留英文**，但结构检查**全过**（不报错、不崩）—— 所以极难查。

**防范四条**：
1. **键必须取自「完整字段内容」**（含其真实换行符），绝不要用「前缀/日期/首行」当键
2. **换行符必须统一**：文件里是 `\r\n`、词表里写成 `\n` → **长键永远匹配不上**（本例简报全漏就是因此）
3. **替换前校验唯一性**：某键在文件里出现多次时，逐处 dump 上下文再决定
4. **复核用「逐对象对比原版字段数与长度」**（见上文判据），能直接暴露这类错误

**同类判据速查**（判断一个键是否危险）：
```python
risky = [k for k in T if any(k != k2 and k2.startswith(k) for k2 in T)]   # 是别的键的前缀
```
危险键的特征是**短、且是另一个更长键的前缀** —— 这类键要么删掉，要么把值改成对应的短译文。

## ★★★ 「同一个中文被多个英文共用」时，必须带指纹精确替换

`辉煌` 同时是 `Brilliant` 和 `Illustrious` 的译文，我按 `辉煌 → 光辉` 全量替换，
**把 `Brilliant` 也连带了**（它应该叫"卓越"，不该变"光辉"）。
同类事故还有 `舰队`（既是常用词、又是 `Legion` 的译文）。

### 指纹技巧：用「中文 + 尾字节 + 英文残留」精确定位

等长替换后**会残留原英文的尾部**，正好当指纹用：
```
光辉\x01lliant      ← 残留 "lliant"   ⇒ 其实是 Brilliant
光辉\x01ustrious    ← 残留 "ustrious" ⇒ 才是 Illustrious
舰队\x01egion       ← 残留 "egion"    ⇒ 其实是 Legion
```
```python
pat = "光辉".encode('utf-16-le') + b"\x01\x00" + "lliant".encode('utf-16-le')
while True:
    k = d.find(pat, pos)
    if k < 0: break
    d[k:k+4] = "卓越".encode('utf-16-le')   # 只命中 Brilliant，不碰 Illustrious
    pos = k + len(pat)
```

**动手前自查**：这个中文在池里**对应几个不同的英文**？（用上述残留反查）
- 只有一个 → 可以全量替换
- **多于一个** → 必须带指纹精确替换

## ★★ 解析 firstpass 的「名字池」（#US 字节级）

池是 `[前缀][UTF-16 内容][尾字节]` **紧密串接**的，#US 前缀编码：
```python
b0 = buf[i]
if   (b0 & 0x80) == 0:      plen, v = 1, b0                                   # 1 字节
elif (b0 & 0xC0) == 0x80:   plen, v = 2, ((b0 & 0x3F) << 8) | buf[i+1]        # 2 字节
elif (b0 & 0xE0) == 0xC0:   plen, v = 4, ((b0 & 0x1F)<<24)|...                # 4 字节
内容 = buf[i+plen : i+plen+v-1]      # ★ v = 内容字节数 + 1
下一条起点 = i + plen + v
```
从锚点（如 `A Class Destroyer`）的条目起点开始扫，可得到几千条；
相邻的 `[英文][中文]` 对就是**英中对照表**（大西洋舰队里拿到 816 组）。

**替换约束**：条目紧邻 → **只能等长替换**。
更短要改小前缀（会让后续条目前移）；更长直接放不下。
**等长替代技巧**：中文长度不匹配时，用「加"号"字」凑等长
（`小天狼星`→`天狼星号`、`自惭形秽`→`打击者号`、`反潜水艇`→`反潜作战`，都是 4 字换 4 字）。

## ★ DLL 里的武器名≠逻辑标识（别过度恢复）

看到 `Search/Depth Charge/Hedgehog/Squid/Torpedo/Guns/Glide Bomb` 在 DLL 里被翻成中文，
**不要**立刻判为"破坏功能"——先看它 ldstr 后面跟什么调用：

- 跟 `set_Text` / `Concat`+`set_Text` → **纯显示，翻译是对的**
- 跟 `op_Equality` / `Find` / `SetActive` → 逻辑标识，必须英文

实测：上面这 13 个**全是 `set_Text`**，翻译安全。真正必须保英文的是 **level0 侧的
`ordnanceNames` 数组**（代码按名读取的数据），与 DLL 侧的显示文本是**两套东西**。

## ★★★★ 铁律：level0 里「长度变化」的替换必须重建对象，绝不能原地改前缀

**症状**：游戏能装、**一启动就卡在 logo/黑屏后**（数据初始化阶段）。

**结构真相**（大西洋舰队实测）：
`level0`（Unity SerializedFile）里字符串是
```
[4字节长度][内容][对齐 pad]     ← 长度 = 内容字节数，没有尾字节
```
**pad = `(4 - (4 + L) % 4) % 4` 个 `0x00`**（让 `4+L+pad` 对齐到 4 —— Unity 读字符串后会 **Align4**）。
**对象起始偏移也要求 `rel % 4 == 0`**，且对象之间按 4 字节对齐 —— 重建时这三处都必须重算。
实例：`L=7` → pad 1；`L=12` → pad 0；`L=218` → pad 2；`L=274` → pad 2。
且**对象内部的字段是顺序紧跟的**——字符串字段后面就是下一个字段。

**踩的坑**：我做"原地替换"时**保持对象总长**、把译文写短、**同步把小长度前缀**
（`d[p-4:p] = len(new)`），以为"总长不变就安全"。
**错**：后续字段**并没有前移**，游戏读完新内容后**接着从填充区读下一个字段**
→ **对象内字段全部错位** → 启动即卡。

**实例**（共 28 处，全都改坏了）：
`Lancaster\nGrand Slam`（前缀 21→20，**后面还有 1044 字节**）、
`Condor\nBomb`（12→11，**后面 929 字节**）、20+ 条简报、6 个教程。
前两个正是 `DropOrdnance` 里按名找弹药的位置 → 投放链路直接断。

**正确做法（二选一）**：
1. **重建对象**：替换后把后续数据前移、更新对象 `size`、重排所有 `rel` 偏移
   （`build_v43_run.py` 的 `translate_strings` 就是对的：它用 `raw[:pos] + pack(len(cb)) + cb + pad + raw[pos+old_total:]`，
   即**删除旧长度、插入新长度**，后续自然前移，对象长度随之变化）
2. **长度不变的替换**：只有**等长**（字节数完全相同）时才能原地覆盖

**判断自己有没有踩坑**（改完必做）：
```python
# 用干净基线对比同一对象的字符串前缀
e1 = scan(baseline_obj); e2 = scan(current_obj)
for (p1,L1,_),(p2,L2,_) in zip(e1,e2):
    if L1 != L2: print("★已错位: 对象#%d 前缀 %d -> %d" % (obj, L1, L2))
```
**前缀不一致 = 已经错位**（除非该字符串是对象内**最后一个**字段，后面全是 0 填充）。

**补救（首选重建，次选写回前缀）**：

**A. 重建（唯一干净的做法）** —— 用与构建器相同的 `translate_strings` 逻辑重放：
```python
def translate_strings(raw, table):
    changes = []
    for name, cn in table.items():
        nb, cb = name.encode('utf-8'), cn.encode('utf-8')
        old_total = 4 + len(nb) + (4 - (4+len(nb)) % 4) % 4
        pos = 0
        while True:
            j = raw.find(nb, pos)
            if j < 0: break
            if j >= 4 and struct.unpack_from('<i', raw, j-4)[0] == len(nb):   # 前缀校验
                changes.append((j-4, old_total, cb))
            pos = j + 1
    uniq.sort(key=lambda c: c[0], reverse=True)          # 从后往前改，避免偏移失效
    for pos, old_total, cb in uniq:
        pad = (4 - (4+len(cb)) % 4) % 4
        raw = raw[:pos] + struct.pack('<i', len(cb)) + cb + b'\x00'*pad + raw[pos+old_total:]
    return raw                                            # ★ 后续数据自然前移
```
外层对**每个对象**重算：`pack_into(nd, e+4, cur)`（新 rel）、`pack_into(nd, e+8, len(new_raw))`（新 size）、
`while len(nd) % 4: nd.append(0)`（对齐）、最后 `pack_into(nd, 4, len(nd))`（文件大小）。
**先做硬校验**：**空补丁重建必须与原文件逐字节一致**，否则说明基底或对齐假设有误，**不要继续**。

**B. 写回前缀（应急，有副作用）**：把前缀改回基线值、内容之后清 0
→ 反序列化读回原字节数、位置恢复；**代价是字符串尾部有 NUL**（对**按名匹配**的条目有风险）。
注意 scanner 返回的 `p` 就是**前缀位置**，内容 = `[p+4, p+4+L)`（**L = 内容字节数，无尾字节**）。

**C. 对象级重建（只坏了少数对象时的最佳选择）**：

```
基底         = 内容最全的那个版本（本例 v61：23/24 中文项）
布局参照     = 结构最正的那个版本（本例 v43：字段数/长度与英文原版逐字段一致）
非字符串字节  = 从【布局参照】原样复制     ← 数值字段一个字节都不动
字符串字节    = 按目标内容重写，pad 重算   ← 长度变化被正确吸收
```
逐段拼接：`ov[last:p]`（原样）+ `pack(len(新内容)) + 新内容 + pad`，
最后套同一套对象表重算（新 rel / 新 size / 对象间 4 字节对齐 / 文件头大小）。
**只替换目标对象**，其余对象字节完全不动 —— 可用 diff 验证「差异对象数 == 目标数」。

> ★ **选基底的教训**：先做了一版以 `v43`（结构基线）为基底的修复，**结构全对但内容只有 9/24 中文项** ——
> 因为 v43 本身就缺大量翻译。**基底要用「内容最全」的那个，别用「结构最正」的那个。**

**★★★ 验证判据（这个坑我踩了三次，务必用这条）**：

> **「抽查字符串不含 `\x00`」是无效判据** —— 含 NUL 的字段**根本解析不成字符串**，永远统计不到它。
> （V71 就是这么被误判成"干净"的，实际有 11 个对象字段被打碎。）
>
> **正确判据：逐对象对比【英文原版】的「字段个数」与「字段长度」。**

```python
sa = scan(原版对象字节); sb = scan(当前对象字节)
if len(sa) != len(sb):
    print("★字段数变化", i, len(sa), len(sb))          # 一定有字段被破坏/误替换
for (_,L1,_),(_,L2,_) in zip(sa, sb):
    if abs(L2-L1) > max(30, L1*3):
        print("★长度暴增", i, L1, L2)                   # 误替换的典型特征
```
外加三条硬指标：**末地址 == 文件大小**、零越界、`rel % 4 == 0`。

**不受此影响的**：**DLL 的 `#US` 池** —— 它是**按偏移索引**（`ldstr` 的 token 即偏移），
改某条目的长度前缀只影响该条目自己；其**顺序自洽性**可用 `[前缀][utf16][尾字节]` 顺扫验证。

## ★★ level0 的舰名是「键」，中文由 firstpass 的池提供（别乱改）

`Assembly-CSharp-firstpass.dll` 里有一张 **`[英文名][中文名]` 成对存储**的名字池：
```
A Class Destroyer | A级驱逐舰 | Abelia | 六道木 | Acasta | 金合欢 | Achates | 阿凯提斯 | ...
Admiral Graf Spee | 施佩伯爵海军上将号 | Admiral Hipper | 希佩尔海军上将号 | ...
```
**判断方法**：数一下各文件的中文数量——
`base_firstpass` 有 269 处中文，而 `base_level0` / `base_Assembly-CSharp` 都是 0。
**结论**：`level0` 里的舰名是**查找键**，保持英文是**正常的**，**不是漏翻**。
（例：`level0` 里 `Bismarck` 2 处独立条目 + `firstpass` 池里 `俾斯麦`，两者配合工作。）

**副作用提醒**：V43 构建脚本里有这么一条
```python
if s != 'Loading' and (' ' not in s and '\n' not in s): continue   # 单个单词不翻
```
所以 `Bismarck`/`Hood`/`Rodney` 这类**单字舰名不会被翻**，而 `Admiral Graf Spee`（带空格）会被翻。
这条规则本意是保护代码标识（`Bomb`/`Zoom`/`None`），副作用是漏掉单字舰名——
但如上所述，**level0 的舰名本就是键，不影响显示**，不必强行补翻。

## ★★ 舰名错译的三种高发模式（打磨期重点查）

1. **形近词误认**：`Acasta`↔`Acacia`（→"金合欢"）、`Gneisenau`↔`Gniezno`（→"格涅兹诺"）
2. **同姓氏军官混淆**：`Admiral Scheer` 被译成 `施佩海军上将号`（那是 `Admiral Graf Spee` 的人）
3. **普通词误当专名**：`Repulse`(反击号) → "浅水"、`Leipzig` → "莱比锡城"

**查法**：
```python
# 从中文文本里抓所有 "<2~8汉字>号"，再与 base 的英文名逐一对照
re.findall(r'([\u4e00-\u9fff]{2,8}号)', 中文文本)
```
另外顺手看 `translation_master.json`——词表本身也可能带错译（本次发现 `Repulse→浅水`）。

## ★★ 接手「别人已汉化过的基底」时，必查这四类遗留错译

大西洋舰队的 `base_firstpass.dll` 是 3DM 汉化版（含 269 处中文）。
逐条过它的名字池后，错译**密集且成规律**，四类都要扫：

| 类型 | 实例 |
|---|---|
| **同根词混淆** | `Scuttle`(凿沉) → "撤离"；`Points`(分数) → "地点" |
| **专名当普通词** | `Renown`(舰名+游戏货币) → "名声"；`Illustrious` → "辉煌" |
| **跨洋/跨域联想** | `Atlantis`(亚特兰蒂斯) → "大西洋"；`Queen Elizabeth`(战舰) → "女王伊丽莎白二世" |
| **形近误认** | `Pinguin`(企鹅) → 菠萝；`Acasta` ↔ `Acacia`(金合欢)；`Gneisenau` ↔ `Gniezno`(格涅兹诺) |

**系统查法**：把池解析成英中对照（见上），按「英文→中文」通读一遍。
**重点盯**：`Scuttle/Scuttled`、`Points`、`Renown`、`Sinking XXX`、`Scuttle XXX`、
`XXX Class YYY`（舰级名）、`Player 2: ON/OFF`、`Primary/Secondary Guns` 这类**固定句式**。

**等长替换的凑字技巧**（池条目紧邻，只能等长）：
- 加「号」字：`天狼星` → `天狼星号`、`打击者` → `打击者号`
- 用同义长词：`反潜` → `反潜作战`、`主炮` → `首要火炮`
- 全角空格补位：`女王伊丽莎白二世`(8) → `伊丽莎白女王号　`(7 字 + 1 全角空格 = 8)

## ★★★★★ 最重要的一条方法论：以「实机验证能跑的版本」为基底做最小增补

**这个项目在"卡 loading"上绕了整整两天，根本原因就是违反了这条。**

### 反面教材（别学）
我一直在**汉化产物内部反复推理**：改前缀、修对象错位、重建字段、换词表……
每一步"自检"都通过，但**实机每次都还卡**。因为：
* **自检判据再全，也可能没覆盖真实故障模式**（我查了新改的 22 个对象，漏了继承下来的 28 处错位）
* **只要基底本身带着你没发现的问题，在它上面做什么都是白费**

### 正解：三步
1. **先找出「实机验证能跑的版本」**（本项目 = `final_full_cn_OK.apk`），
   它的 3 个关键文件就是**黄金基线**，记下 md5。
2. **把当前版本与它逐文件比对**：
   ```python
   b={i.filename:(i.file_size,i.CRC) for i in zipfile.ZipFile(能跑的包).infolist()}
   v={i.filename:(i.file_size,i.CRC) for i in zipfile.ZipFile(当前的包).infolist()}
   diff=[k for k in b if k in v and b[k]!=v[k]]
   ```
   → **只有 3~6 个文件不同** = 找到变量了；**差异一大堆** = 基底根本不是一条路线。
   再逐一算 md5 确认每个文件"来自哪个版本"，**能跑/不能跑的分水岭一眼可见**。
3. **以能跑的版本为基底做最小增补**：非目标字节一律不动，只重建要改的对象，
   改完验证「**差异对象数 == 预期数**」。

### 分步实验：判断是哪个文件的锅
```
能跑的包                   → 基线
能跑的包 + 只换 A 文件      → 若卡，A 是元凶
能跑的包 + 只换 B 文件      → 若卡，B 是元凶
```
本项目实测：`只换 DLL 后卡` + `只换 level0 后卡` → **两个文件都有问题**。

### 血泪金句
> **"自检通过" ≠ "能跑"。**
> 找不到方向时，**第一件事就是和「已知能跑的版本」逐文件比对**，
> 不要在产物内部继续推理。

## 排查顺序（用户说"还有没汉化的"时）

1. 主程序集 #US 堆全量扫 → 80 条战斗 HUD + 12 舰种 + 8 港口 + 12 战役长块
2. firstpass 别漏：教程虽已翻，但**仍被 ldstr 引用的英文条目**（这里 87 条）才是真在显示的
3. 最后用 ldstr 引用表反查："未被任何 ldstr 引用"的英文条目 = 残留，不会显示，可不管
