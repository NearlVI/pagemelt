# PDF 转换项目复核（2026-09-11 开始，2026-09-13 更新）

目标：检查之前 session 的 PDF 转换情况，并改进整个项目。
本报告记录已核实的结果和未完成事项；项目尚未完成全量质量验收。

当前结果：83 本 EPUB、5438 个导航项均通过审定规范的严格验收，
83 本源旁副本全部存在且 SHA-256 一致；3124 个图片引用检查未发现断链。
这些结论不等于全量 OCR 准确率或与原 PDF 逐页图文保真验收。

## 当前产物与历史

- `output/心理学书籍-fixed/` 有 77 本最终审阅版本；原始转换与各次修复备份仍保留。
- 历史批处理 `work/batch-psychology-books/summary.csv` 有 152 条 done、1 条 failed。
  按源 PDF 取最后一条记录，77 本全部为 done。唯一失败记录是
  《边缘性人格障碍治手册 玛莎林内翰》，之后已成功重试。
- `output/` 顶层有 6 本独立转换的 EPUB。
- 原验收器核对心理学 77 本、4745 项全部通过；修复验收器后，11 本暴露问题。
  经证据复核，8 本修正规范中的 28 个坐标，另 3 本修复正文起点；
  新规范现已全部通过。旧规范保留为历史记录，不应重新应用。
- 83 本的图片引用机械检查均为 0 断链：心理学 3060 个引用，独立书籍 64 个引用。
  这不证明原 PDF 每幅图片均被提取，也不证明 OCR 全文准确。
- `Z:/心理学书籍/` 初查缺少的 77 本同名 EPUB 副本已补齐，
  全量规范验收后发布，2026-09-13 再次核对全部哈希一致。
- 5 本来自 `P:/Downloads/` 的独立 EPUB，核查时输出和源旁副本哈希相同。
  《五十年来的中国近代史研究》的项目源 PDF 在 `input/`，已补齐源旁 EPUB 并核对哈希。
- `.git/` 当前为空，`git status` 不能使用；未初始化仓库或覆盖用户数据。
- 开始核查时未发现可确认属于本项目的活跃转换进程；其他 Python 服务未改动。

## 本次已经完成

1. 修复 NCX 目标解析：支持 NCX 相对路径、标题自身的 id、按 DOM 对象身份计算块坐标。
   旧实现使用 BeautifulSoup 的内容相等比较，会将相同标题映射到第一次出现的位置。
2. 严格验收增加 mimetype 内容、重复 ZIP 条目、正文顺序、共享正文块、重复 id、
   `expect` 文本检查。损坏 EPUB 会记录失败并继续检查剩余书籍。
3. 坐标应用前拒绝空规范、空标签、无 expect、非 spine 目标、逆序和重复坐标；
   备份目录不能位于输入目录内。目标链接按 NCX 路径正确生成。
4. 新增 `tools/ebook_artifacts.py`：EPUB 包完整性/AZW3 文件头检查、备份旧成品、
   临时文件发布、源目录同步、SHA-256 回执。
5. 转换脚本在全部目标格式生成之后才开始发布；失败时保留中间结果。
   支持项目内便携版 Calibre；重跑保留旧工作目录；明确拒绝非 PDF 输入和无缓存跳过 OCR。
6. 批处理检查已有成品并同步副本后才跳过；一批中任何转换失败都会返回失败。
7. setup 检查每个外部安装命令的退出码，安装 TOC 依赖；Force 重建环境时备份旧环境。
8. 修复清理页码后再判断印刷目录导致误升标题的问题、异目录图片路径和粗体二次转义。
9. 《邓小平政治评传》由 16 项错误/残缺导航重建为 49 项：前置内容、9 章和各章小节、译后记。
   已逐项对照印刷目录与正文，完成 resolve、只读 validate、带备份 apply、严格验收、
   发布到 output 和 P:/Downloads，并确认 SHA-256 一致。
   规范为 `toc-workflow/specs/deng.search.json` 与 `deng.coordinates.json`。
   两个原成品均备份在 `work/project-audit-20260911/publish-backups/`。
10. 心理学修复：核对原 PDF 恢复《完美伴侣》四个章标题、《做自己的咨询师》附录标题，
    分离《情绪的语言》的篇/章起点；其余 74 本 canonical 二进制未改动。
    完整规范为 `toc-workflow/specs/reviewed-psychology-77-20260911.json`。
    审阅依据见 [心理学复核记录](psychology-review-20260911.md)。
11. 《写作课》1→68 项、《巴黎神话》16→19 项、《诙谐的断代史》299→315 项。
    后者补齐作者分组、子分组及此前漏掉的第 7 则故事；正文未重写。
    六本共 693 项，统一规范为 `toc-workflow/specs/reviewed-standalone-6-20260913.json`。
    依据见 [六本独立书籍复核](standalone-review-20260913.md)。全部已备份发布、同步源旁副本。
12. 新增提取/构建来源记录：`-SkipMinerU` 校验 PDF 内容哈希、有效参数、MinerU 版本、
    retained source.pdf 及全部提取文件。新发布回执绑定 PDF、构建配置、工具哈希与成品哈希。
    批处理只有匹配回执才跳过；旧成品无凭据、被修改或格式不齐时保留文件并返回失败，
    不自动重建经过人工审阅的 EPUB。明确 `-Force` 才重建；模型权重及所有依赖尚未逐一哈希。

## 已执行验证

- 单元回归覆盖损坏 EPUB、NCX 子目录、直接标题 id、相同 DOM 文本、重复目标/顺序、
  过期 expect、非法备份目录、文件发布失败恢复、页码误判、资源路径和文本转义。
  新增 7 项来源校验回归，当前 25 项全部通过：包括同名不同 PDF、配置变化、提取文件
  增删改、无凭据旧缓存、来源/成品哈希不匹配、发布前源 PDF 改变等拒绝场景。
- Windows PowerShell 脚本语法检查通过。
- 真实端到端样本：从《五十年来的中国近代史研究》抽取 PDF 第 101、102 页，
  渲染确认样本可读，GPU MinerU vlm-engine 完成 2/2 页，Calibre 完成 EPUB 和 AZW3。
  两个格式的输出副本与源旁副本 SHA-256 分别一致。
- 实际运行批处理入口：已有两个样本成品成功通过检查、同步和跳过。
- 2026-09-13 在新来源校验流程下重新完成同一两页样本的 GPU MinerU + EPUB/AZW3，
  随后真实运行 `-SkipMinerU`，校验提取缓存后重建两个格式成功。
  批处理将 Backend 改成 pipeline 时如期非零退出且不重建；恢复 vlm-engine 后正常跳过和同步。
- 最终 canonical 心理学 77 本、4745 项以及独立 6 本、693 项，均按新版审定规范通过验收。
  《五十年来的中国近代史研究》的 26 项规范现已持久保存至 `toc-workflow/specs/wushinian.coordinates.json`。
- 2026-09-13 全量图片检查：心理学 3060 引用、独立 64 引用，断链均为 0。
  同日全量双副本哈希检查：83 本，0 不一致。
- 本次不是完整书籍的重新 OCR 测试，也未执行环境重装或大模型下载。

## 尚待完成（保持目标进行中）

1. 两页端到端样本发现分页会让一个自然段在页末脚注前中断、下页再续接。
   需要对正文/脚注和分页重排作更深入处理及代表性验证；当前未解决。
2. 将目录验收后的源旁同步整合为可选的一体化入口（目前通过单独 sync 命令完成）。
3. 扩大代表性阅读检查，覆盖更多分页、脚注、表格和公式；目前不能声称完整 83 本逐页保真。

## 证据位置

- `work/project-audit-20260911/psychology-acceptance.csv`：原验收器结果。
- `work/project-audit-20260913/psychology-acceptance.csv`：77 本最终 canonical 严格验收。
- `work/project-audit-20260913/standalone-acceptance.csv`：6 本最终 canonical 严格验收。
- `work/project-audit-20260913/delivery-verification.json`：83 本双副本哈希复核。
- `work/project-audit-20260913/*-quality.csv`：修复发布后的全量图片引用检查。
- `work/project-audit-20260913/provenance-{smoke,reuse,reject,skip}.log`：新来源校验端到端、
  缓存复用、参数不符拒绝及匹配跳过的实际入口记录。
- `work/project-audit-20260911/baseline-differences.json`：坐标变化/共享块及上下文。
- `work/project-audit-20260911/*-quality.csv`：图片引用检查。
- `work/project-audit-20260911/standalone/`：六本独立书籍审阅包。
- `work/project-audit-20260911/deng-apply/acceptance.csv`：49 项规范验收。
- `work/project-audit-20260911/deng-publication.json`：邓小平书籍双副本哈希。
- `work/project-audit-20260911/wushinian-publication.json`：五十年书籍双副本哈希。
- `work/project-audit-20260911/smoke-input/`、`smoke-output/`：真实两页转换样本。
- `work/conversion-receipts/16a172f8-cc38-4ace-9e3e-a6641b4ad97c.json`：样本双格式发布回执。
