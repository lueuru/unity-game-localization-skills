---
name: unity-resource-text-localization
description: 汉化 Unity（4.x/5.x）安卓游戏的**资源层文本** —— 扫描 SerializedFile 里的字符串字段、建立三类禁译键、区分「代码引用名」与「界面显示文本」，并把译文写回 level0 / sharedassets*.assets。解决"汉化后按钮文字变英文""某些文本仍英文""翻了就崩/功能失效"等问题。当任务涉及 Unity 游戏资源层文案汉化、界面文本遗漏排查、翻译后功能异常时使用。
agent_created: true
---

# Unity 资源层文本汉化

## 何时用

- Unity 老游戏（NGUI / uGUI 时代），文本存在 `level0`、`sharedassets*.assets` 等
  SerializedFile 的 MonoBehaviour 字段里。
- 已经翻了一部分，但**界面上仍有英文**，或**翻了之后功能失效 / 按钮文字异常**。

## 一、先定位文本在哪

### 字符串字段的存储格式
```
[4 字节 LE 长度][UTF-8 字节][padding 到 4 字节]
```
替换要求：**长度前缀必须等于新串字节数**，否则会误伤前缀相同的串
（`"Kormoran"` vs `"Kormoran Class Auxiliary Cruiser"`）。

### 资源文件的组织
```
assets/bin/Data/
├── level0                    主场景（最多文本）
├── sharedassets0/1/2.assets   共享资源（**字体可能在这里**）
├── resources.assets / mainData
└── <32位十六进制哈希>          每艘舰/每个单位一个资源文件（容易漏！）
```

**★ 最容易漏的三处**：
1. **只改了 `level0`**，没改 `sharedassets*.assets` 和那些哈希文件。
2. **`sharedassets0` 里的另一套字体**（只换 `sharedassets1` → 部分界面中文是方块）。
3. **每单位一个的哈希资源文件**（舰名与单位数据在里面）。

**查到漏网文件的两个办法**（实测都有效）：
- **与一个"已知能跑"的历史版本做文件级差分**：改了的地方大小/内容会不同。
  字体被替换的文件会**膨胀约 +16 MB**（一张 2048² RGBA32 图集）。
- **扫描「未处理文件是否含词表键」**：含就说明该文件也有待翻译文本。
  > 注意：此法只能发现「词表里已有键」的文件；词表本身缺失的文本发现不了。

## 二、★★ 核心难点：名字的双重身份

Unity 里**同一个字符串**可能既是「代码查找键」又是「界面显示文本」，
而 GameObject 的名字尤其危险 —— 老项目常直接拿对象名当按钮文案：

```csharp
// 用途 A：查找键 —— 翻了就崩/失效
panelManager.BringInImmediate("Main Menu");    // 按名激活面板
otherObject.name == "Select Handle";           // 按名比较
Input.GetButton("Zoom In");                    // 输入轴名
GameObject.Find("Fleet Manager");

// 用途 B：界面文本 —— 不翻就是英文
this.withdrawText.Text   = "Withdraw";
this.missionTitle.Text   = "Single Battle";
this.uifunctions.bombbutton.Text = "Guns";
enemyactionText2.Text   += "Movement";
```

**两种极端做法都是错的：**
| 策略 | 后果 |
|---|---|
| 全部翻译 | 对象名变中文 → 查找失败 → 脚本抛 NullReferenceException 中断 |
| 全部跳过（跳过所有 `m_Name`）| **按钮文字全变英文**（因为按钮文案就是对象名） |

### 正确做法：按**调用上下文**分类

```python
REF_CALL = re.compile(
    r'(?:'
    r'\.\s*(?:Find|FindChild|BringIn|BringInImmediate|SendMessage|Invoke|'
    r'GetButton|GetAxis|Load|Play)'
    r'|GameObject\s*\.\s*Find'
    r'|\.\s*name\s*(?:==|!=)'
    r'|\.\s*tag\s*(?:==|!=)'
    r')\s*\(\s*$', re.I)
TEXT_ASSIGN = re.compile(r'\.\s*(?:Text|text|mText)\s*(?:\+?=)\s*$')
```
扫一遍反编译 `.cs`：对每个字面量看它前面 ~90 字符的上下文。
- 命中 `REF_CALL` → **禁译**
- 只命中 `TEXT_ASSIGN` → **可译**
- 都没命中但出现在源码里 → 保守禁译

实测某项目 1048 个对象名：**只有 5 个是查找键**（且都是面板名/输入轴名，不显示给用户），
**7 个是纯界面文本**。一刀切会误伤 1000+ 个。

## 三、按 typeID 统计「词表命中率」自动分离文本组

SerializedFile 的对象表第 4 个字段是 typeID（可能是**负数** = 本地类型索引）。
把每个 typeID 组的「字符串命中现有词表的比例」算出来：

| 命中率 | 组性质 |
|---|---|
| **90 ~ 100%** | **显示文本组**（UILabel / 数据字段）← 重点看这些组的未翻译项 |
| < 10% | NGUI 状态机名（`From Over`/`Bring In Back`/`Knob, Normal`）、资源路径、32 位哈希 |

这一步能瞬间把"几千条疑似英文"收敛成"几十条真漏网"，**比逐条人工判断快一个数量级**。

## 四、三类禁译键（缺一不可）

| 表 | 来源 | 例子 |
|---|---|---|
| `logic_keys` | 源码里 `x.name==` / `x.Text==` / `shipclass==` 直接比较的串 | `Type XXI`（被比较 42 处）、`Dive` |
| `shipclass_keys` | 舰级/型号名（UI 显示，但代码也用来判断） | `DD` `BB` `CV` `Type XXI` |
| `object_ref_keys` | **被源码字面量引用的 GameObject 名**（按调用上下文筛） | `Main Menu` `Select Handle` |

外加一条通用规则：**不要翻对象头部的 `m_Name`** —— 除非确认它是界面文本
（这条与上面第 3 张表配合使用：先按上下文筛出"是文本的"，再放行它们的 `m_Name`）。

## 五、交付前验收闸门

| # | 检查 | 判据 |
|---|---|---|
| 1 | 空翻译重建逐字节一致 | 用空词表重建 SerializedFile，结果必须与源文件**完全相同**（否则重建流程有损） |
| 2 | 结构自检 | `DOFF + max(rel+size) == 文件大小`（逐文件） |
| 3 | **禁译键 0 条被误翻** | 遍历全部目标文件，禁译表里的串必须**仍是英文** |
| 4 | 显示文本组命中率 | 显示文本组的词表命中率应 > 90%；未翻译项逐条人工确认 |
| 5 | **Tofu Check** | 全部已汉化文件用到的字符 ⊆ 字体图集 `char id` 集合，**缺字必须为 0** |
| 6 | 目标文件覆盖 | 扫描「未处理文件是否含词表键」应为 0 |
| 7 | 对象表一致性 | `pathID`/`typeID` 与原版**逐项零差异**，只有 `size` 变 |

## 七、别忘了 DLL 层（"翻完资源还是英文"的头号原因）

**资源层只能翻「存在资源文件里的静态文本」。** 游戏里大量界面文案是**运行时由 C# 代码赋值**的：

```csharp
this.withdrawText.Text        = "Withdraw";
this.uifunctions.bombbutton.Text = "Guns";
this.missionTitle.Text        = "Single Battle";
```

这些字面量编译在 `Assembly-CSharp.dll` / `Assembly-CSharp-firstpass.dll` 的
**`#US`（用户字符串）堆**里 —— **翻资源对它们完全无效**。

### 穷尽判据：源码里所有 Label 赋值
```python
ASSIGN = re.compile(r'\.\s*(?:Text|text|mText|label|Label|mCaption|caption)\s*(?:\+?=)\s*"([^"]*)"')
```
扫一遍 `.cs` 得到的就是**全部运行时界面文本**。
（实测某项目 284 种，其中 246 种未翻译 —— 这就是"翻完资源还满屏英文"的答案。）

> ⚠️ **不要**用「词表命中率」去定义"显示文本组"再验证覆盖 —— 那是**循环论证**：
> 命中率低的组（正因词表缺得多）会被排除，永远发现不了。第一版就是这么漏掉的。

### 改 `#US` 堆：必须整段等长覆盖 + 硬自检
条目结构 = `[压缩长度前缀][UTF-16LE 内容][尾字节 0x00/0x01]`，
**前缀值 = 内容字节数 + 1**（含尾字节）。CLR 按 token 偏移索引，所以**条目起点必须不变**。

```python
old_total = pl + v                              # v 来自旧前缀
new_blob  = plb + nb + b"\x00"*(v-1-len(nb)) + b"\x01"
assert len(new_blob) == old_total               # ★ 必须等长
raw[pos : pos+old_total] = new_blob
...
assert len(raw) == orig_len, "长度变了 → 条目边界被破坏，不要输出这个文件"
```

**两个血泪坑**：
1. **分段切片赋值会差 1 字节** —— 把「清 0 区」长度写成 `v-1-len(nb)`、
   而原切片长度是 `v-len(nb)`，每条少 1 字节，累积后文件长度漂移，直接破坏索引。
   **一次性拼好等长 blob 覆盖**才对。
2. **`#US` 堆起点必须用已知值**，不能靠"能连续解析最多条目"自动定位
   （实测会差 100 多字节 → `堆起点 + rid` 与 token 偏移不对应 → **改错位置**）。
   起点可用「从任意已知串反推」得到，并写进项目记忆。

### 禁翻约束（DLL 侧）
`op_Equality` / `Find` / `BringIn` / `GetButton` / `SendMessage` 的操作数必须保英文。
`Hedgehog` / `Squid` / `Depth Charge` / `AP Shell` / `Dive` / `No Action` / `Ahead Full`
这类**军械与动作档位标识**，代码按名匹配，翻了会导致「鱼雷没发射却扣数量」
「无法俯冲投弹」「选项消失」。**要在脚本里写成显式黑名单**，不能靠临时判断。

---

## 八、反例与教训

- **别一刀切对象名** —— 先看调用上下文（本节第二条）。
- **别只改 level0** —— 哈希资源文件里也有大量文本（每单位一个）。
- **别只看「文件长度没变」** —— 长度不变可以掩盖内容错位、字段单位错。
- **别用 `except Exception` 兜底测量代码** —— 会把"参数不支持"和真错误一起吞掉，
  产出静默错误的全表。
- **中文按 em 全高渲染，同字号下视觉比英文大** —— 要视觉协调，中文字号应比原版
  BMFont 的 `size` 略小一档（实测 30 号 → 24px、46 号 → 27px）。
- 改完**必须**跑第 3、5 项闸门：一个防功能失效，一个防方块字。
