---
name: unity-bmfont-chinese-font
description: 给 Unity（4.x~5.x）安卓老游戏替换 BMFont 位图字体实现中文显示 —— 自制 2048² 图集 + .fnt 描述文本，写回 sharedassets*.assets 里的 Texture2D / TextAsset。解决"原版字体只有 ASCII、汉化后全是方块"的问题。当任务涉及 Unity 汉化的字体/方块字/图集/TextAsset(.fnt)/中文字体缺失时使用。
agent_created: true
---

# Unity BMFont 中文字体替换

## 何时用

- Unity 老游戏（NGUI 时代，v4.x~5.x）汉化后中文全是**方块/豆腐块**。
- 原版字体是**位图字体**（BMFont）：`TextAsset` 存 `.fnt` 描述文本 + `Texture2D` 存字形图集。
- 需要在不改代码的前提下，让游戏显示中文。

不适用：`Font` 资源（TTF 动态字体）——那种直接换 ttf 即可；TextMeshPro SDF 字体是另一套。

## 识别特征

在 `sharedassets*.assets` 里：
- `TextAsset` 名字形如 `agencyfb30` / `arial36`，内容是 `info ... / common ... / page ... / chars count=N` + N 行 `char id=...`
- 对应 `Texture2D` 同名，尺寸很小（256x128 / 256x256），`char id` 只有 95~100 个（纯 ASCII）
- 图集格式通常是 `TextureFormat.RGBA32`（枚举值 4）或 DXT

### ★★ 字体往往不止一套，也不止一个文件

实测《大西洋舰队》：**5 个字体纹理分布在 2 个 assets 文件里**
```
sharedassets1.assets : agencyfb30 / agencyfb36 / agencyfb36_ns / agencyfb30_ns   （30/36 号，正文 UI）
sharedassets0.assets : agencyfb46                                                 （46 号大字，主菜单/标题）
```
**只替换 sharedassets1 的后果**：主菜单等用 46 号大字的界面仍走原版 ASCII 字形 → **中文全成方块**，
而按钮依然可点 —— 表现就是「按钮能点但文字不对」，极易误判成逻辑 bug。

**全盘清点字体的方法**（别只看一个文件）：
```python
for n in z.namelist():
    if not n.startswith('assets/bin/Data/'): continue
    raw = C.read_entry(z, C.zip_base(n))
    # ① 找 .fnt 特征串
    if b'page id=0 file=' in raw or b'common lineHeight=' in raw: ...
    # ② 或按 Texture2D 名字匹配 font/agency/arial/fb
```
更快的办法：**与一个「已知字体已换全」的历史版本做文件级大小差分** ——
字体被替换的文件会明显膨胀（一张 2048² RGBA32 图集 ≈ +16 MB）。
若某个文件在历史版里大了 16 MB 而你没改它，那就是漏掉的字体文件。

**另一个高发漏点**：纹理数 ≠ `.fnt` 数。例如 `agencyfb30_ns` 可能只有 Texture2D、没有配套 TextAsset
（与 `agencyfb30` 共用同一份 `.fnt`）。此时把两个纹理都替换成同一张图集即可，不必强求一对一。

---

## ★★ 三个致命坑

### 坑 1：PIL 锚点 —— 默认 `"la"`（ascender）不是 baseline

```
draw.text((x, y), ch, font=f)          # 默认 anchor="la"：(x,y) 是 ascender 线
draw.text((x, y), ch, font=f, anchor="ls")   # ★ "ls" = left + baseline，才是 BMFont 语义
```

**本机 msyh 的 `ascent + descent ≈ 1.39 × px_size`，通常大于 cell 边长。**
若用默认锚点 + `yoffset=0`：
- 小写 `g / y / p` 的 **descender 会溢出 cell**，像素画进**下方单元格**，污染别的字；
- 字形整体相对基线偏移，与 BMFont 语义不符。

**正确做法**（原版就是这么做的）：
```python
x0, y0, x1, y1 = draw.textbbox((0, 0), ch, font=font, anchor="ls")
# y0 < 0 = 基线之上；y1 > 0 = descender 深度
xoffset = x0                 # 字形左缘相对光标 x
yoffset = base + y0          # ★ 字形上缘相对【行顶】；基线固定在 base 处
```
自检：`yoffset + height` 应落在 `base .. base+8` 区间（无下伸的字 == base）。
若算出 `base+28` 这种值，就是锚点用错了。

### 坑 2：`ImageDraw.textlength()` **没有 `anchor` 参数**

Pillow 12 会抛 `TypeError: got an unexpected keyword argument 'anchor'`。
**千万不要用 `except Exception:` 兜底** —— 它会把 TypeError 和真错误一起吞掉，
让整块降级到 `font.getbbox()`（ascender 锚点），于是 `yoffset` 全表算错且**毫无报错**。

```python
# ✗ 静默降级，错得很安静
try:
    bbox = d.textbbox((0,0), ch, font=f, anchor="ls")
    adv  = d.textlength(ch, font=f, anchor="ls")     # ← 抛 TypeError
except Exception:
    bbox = f.getbbox(ch); adv = f.getlength(ch)      # ← 偷偷走这里

# ✓
x0, y0, x1, y1 = d.textbbox((0, 0), ch, font=f, anchor="ls")
adv = int(round(d.textlength(ch, font=f)))            # 不传 anchor
```

### 坑 3：固定网格装不下超宽符号

`'‰' '…' '—'` 之类的全角符号宽度可能**超过 em**（26px 字号 → 34px 宽）。
若按 `cell = 固定边长` 的网格装箱会直接溢出。

**改「行式自由装箱」** —— BMFont 的 `x/y/width/height` 本就是**自由矩形**，不要求网格对齐：
```python
cur_x = cur_y = row_h = 0
for ch in chars:
    w, h = 字形尺寸
    if cur_x + w > atlas:      # 本行放不下 -> 换行
        cur_x = 0; cur_y += row_h + spacing; row_h = 0
    if cur_y + h > atlas:
        die("图集满")
    放置到 (cur_x, cur_y)
    cur_x += w + spacing
    row_h = max(row_h, h)
```
比网格省空间得多：2048² 可放 6000+ 个 26px 字形。

---

## 字符集与字号：先算容量，再定字号

**不要盲目把整个 GB2312（7550 字）塞进去** —— 那会把 cell 压到 ≤23，字号只能到 21px，
字形明显小于原版（原版 30 号字 cap 高 21px）。

**正确策略**：
```
字符集 = GB2312 一级(3850) ∪ 【已汉化资源文件里实际扫出的全部字符】 ∪ 保险符号
```
- 第二项是关键：译文用字是从**汉化后的 level0 / 场景文件**里扫出来的，
  **游戏要显示的中文必然在其中** → 收窄字符集不会缺字。
- 再用 `06_verify` 式的 **Tofu Check** 兜底：`已用字符 ⊆ 图集 char id 集合`，缺字必须为 0。

实测参数（2048² 图集）：
| px_size | 字形高 | cell/间距 | 可容字形 | 字符集 3993 是否够 |
|---|---|---|---|---|
| 18 | ~14 | 20 | ~9000 | 够，但字偏小 |
| **26** | **~19** | **1** | **~5753** | **够，余 609px 高** |

---

## `.fnt` 头部参数：一律照抄原版

**不要自己编** `lineHeight` / `base` / `size` —— 它们决定 UI 行距与基线位置，
写错会让所有文本错位。做法：从原版 `.fnt` 解析出这几个值，只替换 `scaleW/scaleH` 和 `chars` 段。

```
info face="Agency FB" size=<原版 size> ... padding=0,2,2,0 spacing=1,1 outline=0
common lineHeight=<原版> base=<原版> scaleW=<新图集宽> scaleH=<新图集高> pages=1 packed=0 alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4
page id=0 file="<原版 page file 名>"
chars count=<N>
char id=.. x=.. y=.. width=.. height=.. xoffset=.. yoffset=.. xadvance=.. page=0 chnl=15
kernings count=0
```
- `alphaChnl/redChnl/greenChnl/blueChnl` 原版有就**必须补回**（别漏）。
- `page file` 名照抄原版：NGUI 运行时不按它找纹理（原版自己就对不上纹理名），
  但保持最小差异更安全。
- **`.fnt` 必须用二进制写**（`open(path, "wb")`）：文本模式在 Windows 下会把 `\n` 变成 `\r\n`。

## 写回资源

```python
import functools
if not hasattr(functools, 'cache'):        # UnityPy 需要
    functools.cache = functools.lru_cache(maxsize=None)
import UnityPy

env = UnityPy.load(src_path)               # src 是合并分卷后的原始文件
for obj in env.objects:
    if obj.type.name == 'Texture2D':
        o = obj.read()
        if o.m_Name in 字体纹理名集合:
            o.image = atlas_img; o.save()          # UnityPy 自动同步 m_TextureFormat 等
    elif obj.type.name == 'TextAsset':
        o = obj.read()
        if o.m_Name in fnt_映射:
            o.m_Script = fnt_text; o.save()
env.file.save(out_path)
```

## 交付前验收清单

| # | 检查 | 判据 |
|---|---|---|
| 1 | SerializedFile 头部 `ver` / `unityVersion` / `platform` / `dataOffset` | 与原版逐字段一致（UnityPy 不应改动） |
| 2 | 对象表 `pathID` / `typeID` | 与原版**逐项零差异**；只有字体相关的 `size` 变 |
| 3 | 纹理 `m_TextureFormat` | 前后一致（如都是 RGBA32=4） |
| 4 | `m_CompleteImageSize` == `w × h × 每像素字节` | 相等 |
| 5 | Tofu Check：已用字符 ⊆ 图集 `char id` | 缺字 **0** |
| 6 | `yoffset + height - base` 取值范围 | 约 `0 .. +8`（>20 说明锚点用错） |
| 7 | `.fnt` 无 `\r` | 无 CRLF |
| 8 | `.fnt` 的 `lineHeight/base/size/page file` | 与原版一致 |

## 反例与教训

- **别用 `except Exception` 兜底绘图测量** —— 会把"参数不支持"和真错误一起藏掉，产出静默错误的全表。
- **别用默认 `"la"` 锚点** 去算 BMFont 的 `yoffset`。
- **别用固定网格装箱**（超宽符号会溢出；且浪费空间）。
- **别自己编 `lineHeight/base`**，也不要漏 `alphaChnl/redChnl/greenChnl/blueChnl`。
- **别用文本模式写 `.fnt`**。
- **别为了字号而硬塞全量 GB2312** —— 优先收窄到"实际用字 + 一级字库"，保住字号。
- 改完**必须**跑 Tofu Check；它是唯一能自动发现"某字没进图集"的闸门。
