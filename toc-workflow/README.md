# EPUB 目录编纂流程

这套流程用于把 EPUB 的印刷目录、现有导航和正文结构交给 LLM/人工共同审定，再用精确正文坐标重建 NCX。核心边界是：

- **印刷目录定义条目集**（哪些条目、叫什么、什么层级、什么顺序）；**正文定义落点**（导航目标必须解析到正文真实标题或内容块）。页码一律丢弃。
- LLM/人工默认逐条还原印刷目录。任何删、并、改写、调层级、增补都必须声明（条目级 `deviation` 或书级 `dropped`），并通过 `coverage` 门禁核验；无声偏离即验收失败。
- 脚本提取证据、解析坐标、写入 EPUB、备份和执行机械验收。
- 印刷目录行绝不能作为导航目标。
- 不根据标题正则批量猜测整本书的目录。

当前默认验收基准是 [`specs/reviewed-psychology-77-20260911.json`](specs/reviewed-psychology-77-20260911.json)，包含 77 本心理学书籍的 4745 个目录项、层级和精确正文坐标。
六本独立书籍使用 [`specs/reviewed-standalone-6-20260913.json`](specs/reviewed-standalone-6-20260913.json)，共 693 项。
旧 [`specs/accepted-psychology-77.json`](specs/accepted-psychology-77.json) 和 [`accepted-review-status.csv`](accepted-review-status.csv) 保留为历史记录。

2026-09-11 复核发现旧导出器会把内容相同的不同 DOM 节点当成同一个节点，
部分重复标题的坐标因此被错误记录。经逐项审阅，修正 28 处坐标记录、恢复五个源文档确认的标题，
并分离原有共享导航起点后，新规范已通过 77 本全量严格验收；不能重新应用旧规范。
进度与待处理项见 [`../docs/project-audit-20260911.md`](../docs/project-audit-20260911.md)。

## 环境

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-toc.txt
```

PDF OCR/版面解析阶段可使用 MinerU 的 GPU 后端。目录编纂阶段处理的是 EPUB 文本和结构，脚本本身不需要 GPU；使用本地 LLM 审阅时是否走 GPU 由模型运行器决定。

## 标准流程

以下命令都从项目根目录运行。

### 1. 生成审阅材料

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  review "output\待处理书籍" -WorkDir "work\toc-批次名"
```

每本书会生成一个 Markdown 审阅包，包含当前导航、印刷目录窗口、正文中的结构性标题及上下文。把审阅包连同 [`LLM_REVIEW_PROMPT.md`](LLM_REVIEW_PROMPT.md) 交给 LLM，逐本审定；不要让模型只看正则命中结果。

### 2. 编写并解析审定规范

LLM 可以先给出按正文顺序搜索的规范：

```json
{
  "books": [
    {
      "file": "书名.epub",
      "entries": [
        {
          "label": "第二章 确诊之后怎么办？",
          "search": "第二章 确诊之后怎么办？",
          "children": [
            {"label": "我们可能需要吃药", "search": "我们可能需要吃药", "exact": true}
          ]
        }
      ]
    }
  ]
}
```

将它解析为稳定的 `file + block + expect` 坐标：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  resolve "output\待处理书籍" `
  -SearchSpec "toc-workflow\specs\批次名.search.json" `
  -OutputSpec "toc-workflow\specs\批次名.coordinates.json"
```

重复标题必须通过 `occurrence`、`start_file`、`max_file` 或直接坐标消歧。解析成功不代表语义正确，生成的坐标规范仍需人工抽查证据。

审定规范还应携带还原声明：未还原的印刷目录行记入书级 `dropped` 数组（`line` + `reason`）；改写、调层级、合并或增补的条目加 `deviation` 字段。这些字段会随 resolve 透传进坐标规范。

### 3. 覆盖度门禁

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  coverage "output\待处理书籍" `
  -Spec "toc-workflow\specs\批次名.coordinates.json"
```

门禁逐本核对还原契约：每条印刷目录行要么还原为目录条目、要么在 `dropped` 中声明原因；静默丢失任何一行都会以退出码 3 失败并列出书名与示例行。加 `-StrictAdditions` 时，印刷目录中没有、又无 `deviation` 声明的增补条目也会失败（退出码 4）。印刷目录无法检测（无导线、页码被拆散）的书报告为不可测，不做猜测。建议在 validate 之前先跑一次，把静默偏离消灭在写入之前。

### 4. 只读预检

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  validate "output\待处理书籍" `
  -Spec "toc-workflow\specs\批次名.coordinates.json" `
  -WorkDir "work\toc-批次名"
```

预检会逐项验证目标文件、正文块编号和 `expect` 文本，并输出证据文件，不修改 EPUB。任何失败都必须回到审阅/坐标规范修正，不能跳过。

坐标规范绑定到 EPUB 的 spine 文件划分和正文块结构。HTML 拆分、OCR 修订或正文重排后必须重新解析并审阅规范；不能把旧坐标直接套到结构不同的 EPUB。

### 5. 带备份应用

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  apply "output\待处理书籍" `
  -Spec "toc-workflow\specs\批次名.coordinates.json" `
  -WorkDir "work\toc-批次名" `
  -BackupDir "output\待处理书籍-before-toc"
```

应用命令先再次预检，然后完整备份命中的 EPUB，写入正文锚点和 NCX，最后自动执行严格验收。不要把备份目录设在待处理目录内部。

### 6. 验收与冻结

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  accept "output\待处理书籍" `
  -Spec "toc-workflow\specs\批次名.coordinates.json" `
  -WorkDir "work\toc-批次名-final"
```

严格验收要求 EPUB/ZIP 完整、`mimetype` 合规、NCX 可解析、目标文件和片段存在、标签无页码及 `text` 前缀、目标不是印刷目录行、`playOrder` 连续、无共享目标，并且实际层级/顺序/正文坐标与审定规范逐项一致。

正文坐标按 DOM 节点身份定位；直接位于标题上的 `id` 指向标题自身。
NCX 链接按 NCX 所在目录解析。不同锚点落在同一正文块也会报告共享目标。
预检要求每项包含 `expect` 并与正文吻合，同时拒绝重复坐标与正文逆序，
避免在写入 EPUB 后才发现问题。验收会对损坏书籍记录失败并继续检查其余书籍。

只有完成人工抽查、`accept` 为 0 失败、且 `coverage` 无静默丢失后，才能冻结新的基准：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  freeze "output\待处理书籍" `
  -OutputSpec "toc-workflow\specs\accepted-批次名.json"
```

`freeze` 会覆盖指定文件，因此应写入新文件并经代码审查后再替换已有基准。

## 日常审计与恢复

没有审定规范时，可以运行通用结构审计：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\toc-workflow.ps1 `
  audit "output\待处理书籍" -WorkDir "work\toc-audit"
```

通用审计只能发现机械问题，不能证明目录语义或顺序正确。最终结论必须来自 LLM/人工审定规范的精确比对。

应用失败或验收不通过时，停止继续处理并从 `-BackupDir` 恢复对应 EPUB。证据和 CSV 都保存在 `work` 下，便于定位具体书和目录项。
