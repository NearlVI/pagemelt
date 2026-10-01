<div align="center">

# Pagemelt（熔页）

**把固定版式的 PDF 图书"熔"成自由重排的 EPUB —— 再用基于证据、LLM 参与审定的方式重建导航。**

[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#环境要求)
[![Platform](https://img.shields.io/badge/platform-Windows-blue.svg)](#环境要求)
[![CI](https://github.com/NearlVI/pagemelt/actions/workflows/ci.yml/badge.svg)](https://github.com/NearlVI/pagemelt/actions/workflows/ci.yml)

[English](README.md) · [简体中文](README.zh-CN.md)

MinerU 负责读 · Calibre 负责装订 · 审定回路负责导航

</div>

---

## 为什么做这个项目

把一本 PDF 书转换成*好用*的电子书，至今仍是件麻烦事：

- **Calibre 直接 PDF → EPUB** 对扫描件和复杂版式的书效果很差：页眉页脚焊进正文、分栏串行、标题全无。
- **文档解析器**（如 [MinerU](https://github.com/opendatalab/MinerU)）擅长把 PDF *读*成 Markdown/JSON，但到此为止。电子书还需要书脊、真正的标题，以及最重要的一样东西——正确的目录。
- **现有的 PDF → EPUB 转换器**（[pdf2epub 系列](https://github.com/topics/pdf-to-epub)）解决了解析，但导航要么照搬 PDF 书签（扫描书常常缺失或错误），要么靠正则猜测，事后没有人验证。

Pagemelt 用一条流水线和一条铁律补上整个缺口：**目录条目必须对照正文证据逐条审定、解析为精确 DOM 坐标、带备份写入、并通过机械验收 —— 否则这本书按失败上报。**

```text
PDF ──▶ MinerU 结构化解析 ──▶ 适配电子书的 Markdown ──▶ Calibre 生成 EPUB / AZW3
                                                              │
              目录编纂回路：review ▸ resolve ▸ validate ▸ apply ▸ accept
```

## 差异点在哪

### 1. 导航是"重建"出来的，不是猜出来的
[目录编纂工作流](toc-workflow/README.md)把导航修复变成可审阅、基于证据的流程：

```text
   每本书一份证据包（当前导航 · 印刷目录窗口 · 正文结构性标题）
                    │
                    ▼
        LLM / 人工审定（标签、层级、顺序）
                    │  搜索规范
                    ▼
        resolve ▶ 坐标规范（文件 + 正文块 + 期望文本）
                    │
                    ▼
        只读预检 validate（此时尚未改动 EPUB）
                    │
                    ▼
        apply：备份 ▸ 写入锚点 + NCX ▸ 严格验收
                    │
                    ▼
        freeze 冻结为下一批的审定基准
```

**印刷目录只是编纂依据，绝不能作为导航目标** —— 每个条目都必须落到正文里真实存在的标题或内容块。严格验收逐项核对 EPUB/ZIP 完整性、`mimetype` 合规、NCX 可解析、`playOrder` 连续、无共享目标、标签无页码、目标身份、层级与正文顺序。

### 2. 溯源回执，绝不静默覆盖
每次转换都会写一份回执，把输出 SHA-256 与源 PDF 字节、书名/作者、解析选项、工具哈希和 Calibre 可执行文件哈希绑定。批量重跑只有在溯源完全匹配时才跳过。你手工修复过的 EPUB 会**作为失败项上报待审，而不是被覆盖**。没有匹配 `extraction-provenance.json` 的中间产物一律重新生成，遗留缓存绝不推断采信。（这是缓存与成品保护，不是逐位可复现保证 —— 模型权重和 Calibre 依赖不在哈希范围内。）

### 3. 以 VLM 解析为默认，保留退路
默认使用 MinerU 的 `vlm-engine` 后端（GPU 加持、精度优先）；`-Backend pipeline` 走 CPU 友好路径，`-Method ocr` 处理扫描件。页码、页眉、页脚会被剥离；标题变成真正的 Markdown 标题；表格和图片保留给 Calibre。公式和表格密集的书可用 [`tools/build_high_fidelity_ebook.py`](tools/build_high_fidelity_ebook.py) 构建高保真版本：正文保持重排，展示公式保留为 MinerU 裁切图，表格同时收录图像版与识别出的 HTML 版。

### 4. 在真实书库上验证过
已验收书库以**可复现的坐标规范**形式（而非二进制 EPUB）保存在仓库中：77 本心理学书籍（4,745 个导航条目）加 6 本独立书籍（693 项）—— 共 83 本 EPUB、5,438 个条目全部通过严格验收，3,124 个图片引用检查零断链。2026 年 9 月的审计（[docs](docs/project-audit-20260911.md)）记录了验收器自身如何被加固：它暴露出旧导出器隐藏的 28 处错误坐标记录。

## 与同类项目对比

依据 2026 年 10 月各项目公开 README：

| 能力 | Pagemelt | [MinerU](https://github.com/opendatalab/MinerU) | [CodeListening/pdf2epub](https://github.com/CodeListening/pdf2epub) | [bernardotorres/pdf2epub](https://github.com/bernardotorres/pdf2epub) | Calibre |
| --- | :---: | :---: | :---: | :---: | :---: |
| 重排 EPUB 输出 | ✅ | ❌ 仅 Markdown/JSON | ✅ | ✅ | ⚠️ 扫描件效果差 |
| AZW3 / Kindle 输出 | ✅ | ❌ | ❌ | ❌ | ✅ |
| VLM 版面解析 | ✅ | ✅ | ✅ | ❌ | ❌ |
| LLM/人工审定重建目录 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 导航机械验收关卡 | ✅ | ❌ | ❌ | ✅ 无障碍检查 | ❌ |
| 溯源回执 / 安全批量重跑 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 公式/表格高保真模式 | ✅ | — | ❌ | ❌ | ❌ |

若只是对单个 EPUB 手工做目录手术，[Sigil](https://github.com/Sigil-Ebook/Sigil) 仍是手动首选；Pagemelt 的价值在于可复现、书库规模、带审计记录地做这件事。

## 环境要求

- Windows（入口脚本是 PowerShell；`tools/` 下的 Python 工具本身跨平台）
- Python 3.11（也可让 [`uv`](https://docs.astral.sh/uv/) 自动下载）
- [Calibre](https://calibre-ebook.com/) 提供 `ebook-convert`
- 默认 `vlm-engine` 后端可选配：NVIDIA 驱动 + 支持 CUDA 的 PyTorch

## 快速开始

```powershell
git clone https://github.com/NearlVI/pagemelt.git
cd pagemelt

# 一次性：创建 .venv，安装 MinerU 与目录工具依赖
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mineru.ps1

# 转换一本书（产物落在 .\output\，并同时复制到源 PDF 旁边）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\convert-pdfbook.ps1 `
  -InputPath "G:\Books\book.pdf" -Title "书名" -Author "作者"
```

可选：预下载 MinerU 模型，首次正式转换不用等待：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mineru.ps1 -DownloadModels -ModelType vlm
```

默认模型源是 `modelscope`（中国大陆推荐）；生成的 MinerU 配置写入 `%USERPROFILE%\mineru.json`。其他地区可用 `-ModelSource huggingface`。

## 使用方法

转换单个 PDF 或整个文件夹：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\convert-pdfbook.ps1 -InputPath "G:\Books" -Format both
```

| 选项 | 取值 | 含义 |
| --- | --- | --- |
| `-Format` | `epub`（默认）/ `azw3` / `both` | 输出格式；`both` 同时出 Kindle 版 |
| `-Backend` | `vlm-engine`（默认）/ `pipeline` / `hybrid-engine` | MinerU 后端；`pipeline` 走 CPU |
| `-Method` | `auto`（默认）/ `txt` / `ocr` | `ocr` 用于扫描或乱码 PDF |
| `-Lang` | `ch`（默认）、`en` 等 | 解析/OCR 语言提示 |
| `-ModelSource` | `modelscope`（默认）/ `huggingface` / `local` | 模型来源 |
| `-Title` / `-Author` | 字符串 | 生成电子书的元数据 |
| `-OutputDir` | 路径 | 默认 `output\` |
| `-SkipMinerU` | 开关 | 复用留存的中间产物；溯源必须完全匹配 |
| `-KeepWork` | 开关 | 保留 `work\` 中间产物便于诊断 |

每次转换的安全机制：

- 所有格式先在暂存目录构建；发布前检查 EPUB 包完整性（AZW3 查文件头），通过后才会替换现有文件。
- 有差异的现有文件先备份到 `work/artifact-backups/`；回执写入 `work/conversion-receipts/`。
- 每个成品复制到源 PDF 旁，两份副本经 SHA-256 核对一致后才报告成功。
- 重跑时旧解析目录归档到 `work/previous-conversions/`。

目录修复验收通过后，同步最终 EPUB 并生成新回执：

```powershell
.\.venv\Scripts\python.exe tools/ebook_artifacts.py sync "output/book.epub" `
  --source-pdf "G:/Books/book.pdf" --backup-dir "work/artifact-backups" `
  --receipt "work/book-sync.json"
```

## 重建导航（目录工作流）

完整文档见 **[`toc-workflow/README.md`](toc-workflow/README.md)**，LLM 审定提示词在 [`toc-workflow/LLM_REVIEW_PROMPT.md`](toc-workflow/LLM_REVIEW_PROMPT.md)。速览版 —— 所有命令经 `scripts/toc-workflow.ps1` 执行：

```powershell
# 1. 生成每本书的证据包，交给 LLM 或人工审定
.\scripts\toc-workflow.ps1 review "output\books" -WorkDir "work\toc-batch"

# 2. 把审定搜索规范解析为稳定的正文坐标
.\scripts\toc-workflow.ps1 resolve "output\books" `
  -SearchSpec "toc-workflow\specs\batch.search.json" `
  -OutputSpec "toc-workflow\specs\batch.coordinates.json"

# 3. 只读预检
.\scripts\toc-workflow.ps1 validate "output\books" -Spec "toc-workflow\specs\batch.coordinates.json"

# 4. 带完整备份应用，随后自动严格验收
.\scripts\toc-workflow.ps1 apply "output\books" -Spec "toc-workflow\specs\batch.coordinates.json" `
  -BackupDir "output\books-before-toc"

# 5. 验收通过并人工抽查后，才冻结新基准
.\scripts\toc-workflow.ps1 accept "output\books" -Spec "toc-workflow\specs\batch.coordinates.json"
.\scripts\toc-workflow.ps1 freeze "output\books" -OutputSpec "toc-workflow\specs\accepted-batch.json"
```

工具强制执行的规则：重复标题必须用 `occurrence`、`start_file`、`max_file` 或显式坐标消歧；坐标绑定 EPUB 的 spine 与正文块结构，HTML 拆分或 OCR 修订后必须重新解析；备份目录绝不能放在待处理目录内部；`freeze` 会覆盖目标文件，只能有意执行。

## 测试与验证

```powershell
# 单元测试（纯 Python —— 不需要 MinerU、Calibre 或 GPU）
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 对照审定基准的严格验收
.\.venv\Scripts\python.exe tools/validate_epub_toc_acceptance.py "output/心理学书籍-fixed" `
  --spec toc-workflow/specs/reviewed-psychology-77-20260911.json `
  --csv-output work/current-acceptance.csv
```

验收命令对失败书返回非零，遇到损坏 EPUB 记录后继续检查其余书籍。除非 MinerU 和 Calibre 真的对一本有代表性的 PDF 完整跑通，否则不要宣称完成了全量转换测试。

## 项目结构

```text
scripts/        PowerShell 入口：环境安装、转换、目录工作流
tools/          Python 工具：解析转 Markdown、目录编纂、审计、回执
tests/          单元测试（25 个，仅依赖 bs4 + lxml）
toc-workflow/   审定提示词、工作流文档、已验收的坐标规范
docs/           83 本书库的审计与复核记录
input/          源 PDF               （不入库）
output/         生成的 EPUB/AZW3     （不入库）
work/           中间产物、回执、备份 （不入库）
```

## 局限

- Windows 优先：编排入口是 PowerShell 脚本。`tools/` 下的 Python 工具跨平台、随处可测。
- AZW3 只做文件头检查，不是完整内容校验。
- 回执验证的是交付与缓存一致性，不是 OCR 准确率或与源 PDF 的逐页保真 —— 目录完整性与正确性来自审定流程。
- 目录回路需要 LLM（或有耐心的人）做审定；脚本有意拒绝用正则猜测整本书的目录。

## 致谢

- [MinerU](https://github.com/opendatalab/MinerU)（OpenDataLab）—— 解析引擎。
- [Calibre](https://calibre-ebook.com/)（Kovid Goyal）—— 电子书构建与格式转换。
- Beautiful Soup / lxml —— EPUB 手术刀。

## 许可证

[MIT](LICENSE) © The Pagemelt Authors
