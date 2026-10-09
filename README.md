<div align="center">

# Unity 手游汉化技能包

**给老 Unity 安卓游戏做汉化的三件套：DLL 层文本、资源层文本、位图字体**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](./LICENSE)
![Platform](https://img.shields.io/badge/platform-Android%20%7C%20Unity%204.x%20~%205.x-3ddc84?style=flat-square&logo=android&logoColor=white)
![Lang](https://img.shields.io/badge/语言-简体中文-1f6feb?style=flat-square)
[![Last commit](https://img.shields.io/github/last-commit/lueuru/unity-game-localization-skills?style=flat-square)](https://github.com/lueuru/unity-game-localization-skills/commits)

</div>

---

## 这是什么

三个 **AI Agent 技能（Skill）**，解决 Unity 老游戏汉化里最容易翻车的三段：

| 难点 | 表面现象 | 这个技能做什么 |
|---|---|---|
| **DLL 层文本** | 翻了就闪退、或有东西死活翻不到 | 解析 .NET `#US` 字符串堆，用 IL 上下文判断**哪些能翻、哪些绝对不能翻** |
| **资源层文本** | 汉化后按钮文字变英文、功能失效 | 扫 SerializedFile 字符串字段，建立**三类禁译键**再写回 |
| **中文字体** | 汉化后全是方块 / 缺字 | 自制 BMFont 图集 + 描述文本，写回 `Texture2D` / `TextAsset` |

**共同的设计取向**：老游戏改错一个字节就可能启动即崩，所以三个技能都坚持
**不改变文件长度的原地替换** + **先判定再动手**，而不是"找到字符串就替换"。

## 三个技能

### 1. `unity-dll-chinese-patch` — DLL 层文本汉化

解析 `Assembly-CSharp.dll` / `*-firstpass.dll` 的 `#US` 字符串堆，
用 **IL 上下文**判定每一条英文是"界面显示文本"（可翻）还是"代码引用名 / 比较值"（禁译），
再做**块级原地替换**（文件长度、全部偏移零变化）。

触发场景：汉化 Unity 游戏的 DLL、抱怨"还有东西没汉化 / 翻了就闪退"。

> 附带两个脚本：`scripts/il_logic.py`（IL 上下文判定）、`scripts/fix_dll_logic.py`（写回）。

### 2. `unity-resource-text-localization` — 资源层文本汉化

扫描 `level0` / `sharedassets*.assets` 里的字符串字段，建立禁译键，把译文写回。
解决"汉化后按钮文字变英文""某些文本仍英文""翻了就崩 / 功能失效"。

**核心是禁译键**：老游戏里有大量**靠字符串比较驱动逻辑**的写法
（如 `if (shipData.shipclass == "Type XXI")`），这类字符串翻了等于把功能删掉。

### 3. `unity-bmfont-chinese-font` — 位图字体中文化

原版 BMFont 图集只含 ASCII，汉化后全是方块。
本技能自制 **2048² 图集 + `.fnt` 描述文本**，写回 `sharedassets*.assets` 里的
`Texture2D` / `TextAsset`。

触发场景：字体 / 方块字 / 图集 / `TextAsset(.fnt)` / 中文字体缺失。

## 安装

技能目录需要放在 Agent 的技能根目录下。以 WorkBuddy 为例（路径按你的环境调整）：

**方式一：整仓库克隆（推荐，三个技能一起用）**

```bash
git clone https://github.com/lueuru/unity-game-localization-skills.git
cp -r unity-game-localization-skills/skills/* ~/.workbuddy/skills/
```

**方式二：只取一个技能（每个技能都是独立可用的）**

```bash
# 只想要 DLL 汉化那一个
cp -r unity-game-localization-skills/skills/unity-dll-chinese-patch ~/.workbuddy/skills/
```

装好后，Agent 会在匹配到触发场景时自动加载；也可以直接点名（如"用 unity-dll-chinese-patch 处理这个 DLL"）。

## 使用示例

**例 1：DLL 里还有英文没翻，且改完就闪退**

> 「这个游戏的 `Assembly-CSharp.dll` 我用工具翻了，但界面还有英文，而且改完启动就闪退。」

技能会先解析 `#US` 堆定位真实偏移（**不是**用启发式扫描猜——猜会偏几十字节，读出乱码），
再逐条用 IL 上下文判定可译性，最后做等长替换。

**例 2：汉化后按钮文字变回英文、某个功能失灵**

> 「我汉化完，设置界面的按钮变英文了，而且有个功能点不动。」

这是典型的**禁译键被翻**：某个字符串既是显示文本、又被代码当查找键用。技能会先把这类键排除掉。

**例 3：汉化后字体全是方块**

> 「文字都翻成中文了，但显示全是方块。」

需要替换位图字体图集：技能会按"译文实际用到的字"生成图集（**零缺字**，且比塞入全字库字号更大更清晰）。

## 为什么值得用

这三条不是从文档里抄的，是**在一个真实的 Unity 老游戏汉化项目上反复踩出来的**：

- **偏移必须解析元数据，不能猜**：启发式扫描会偏 30+ 字节，读出 `敩r杲b` 这类错位乱码，而且不报错。
- **同一个字符串可能有双重身份**：既是显示文本、又是代码查找键 —— 一刀切两头都错，实测只有少数几个是查找键，必须逐条判。
- **`utf16_size` 是字符数不是字节数**：写成字节数时，纯 ASCII 串完全看不出问题，一换中文就启动即崩。
- **字体必须最后做**：字符集要取"汉化后实际用到的字"，顺序反了只能用全集，字号被迫变小。

## 仓库结构

```
unity-game-localization-skills/
├── README.md
├── LICENSE
├── .gitignore
└── skills/
    ├── unity-dll-chinese-patch/
    │   ├── SKILL.md
    │   └── scripts/
    │       ├── il_logic.py          # IL 上下文判定可译性
    │       └── fix_dll_logic.py     # 等长块级写回
    ├── unity-resource-text-localization/
    │   └── SKILL.md
    └── unity-bmfont-chinese-font/
        └── SKILL.md
```

每个 `skills/<名字>/` 都是**自包含**的：单独复制走也能用。

## 适用与不适用

**适用**：Unity 4.x ~ 5.x（Mono / .NET 3.5）安卓游戏的**文本与字体**汉化。

**不适用**：
- 加壳 / 加密资源的游戏（需要先脱壳）
- 非 Unity 引擎（那看 Android 原生那套技能）
- IL2CPP 打包的游戏（`Assembly-CSharp.dll` 不存在，走的是 `global-metadata.dat`，路径完全不同）

## 许可证

[MIT](./LICENSE) —— 自由使用、修改、再分发，保留版权声明即可。

