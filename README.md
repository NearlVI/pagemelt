<div align="center">

# Pagemelt

**Melt fixed-layout PDF books into free-flowing EPUBs — then rebuild their navigation with evidence-based, LLM-adjudicated precision.**

[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#requirements)
[![Platform](https://img.shields.io/badge/platform-Windows-blue.svg)](#requirements)
[![CI](https://github.com/NearlVI/pagemelt/actions/workflows/ci.yml/badge.svg)](https://github.com/NearlVI/pagemelt/actions/workflows/ci.yml)

[English](README.md) · [简体中文](README.zh-CN.md)

MinerU does the reading · Calibre does the binding · an adjudicated review loop does the navigation

</div>

---

## Why this exists

Converting a PDF book into a *usable* ebook is still an unsolved chore:

- **Calibre's direct PDF → EPUB** produces broken output for scanned or complex books — page furniture baked into paragraphs, columns interleaving, no usable headings.
- **Document parsers** such as [MinerU](https://github.com/opendatalab/MinerU) do an excellent job of *reading* a PDF into Markdown/JSON, but stop there. An ebook needs a spine, real headings, and above all a correct table of contents.
- **Existing PDF → EPUB converters** ([pdf2epub family](https://github.com/topics/pdf-to-epub)) handle extraction, but navigation is either taken from PDF bookmarks (often missing or wrong in scanned books) or guessed by regex. Nobody verifies it afterwards.

Pagemelt closes the whole gap with one pipeline and one hard rule: **navigation entries are adjudicated against evidence from the actual body text, resolved to exact DOM coordinates, applied with backups, and mechanically accepted — or the book is reported as failed.**

```text
PDF ──▶ MinerU structured extraction ──▶ ebook-friendly Markdown ──▶ Calibre EPUB / AZW3
                                                                          │
              TOC curation loop: review ▸ resolve ▸ validate ▸ apply ▸ accept
```

## What makes it different

### 1. Navigation is restored, not guessed
The [TOC curation workflow](toc-workflow/README.md) turns navigation repair into a reviewable, evidence-based process with one contract: **the printed TOC defines the entry set (labels, hierarchy, order); the body defines the targets; page numbers are discarded.**

```text
   evidence packet per book (current nav · printed-TOC window · structural headings)
                    │
                    ▼
        LLM / human adjudication  (restore the printed TOC; declare deviations)
                    │  search spec + deviation/dropped declarations
                    ▼
        resolve ▶ coordinate spec (file + body block + expected text)
                    │
                    ▼
        coverage gate  (every printed line restored or declared, else fail)
                    │
                    ▼
        read-only validate  (nothing touches the EPUB yet)
                    │
                    ▼
        apply: backup ▸ write anchors + NCX ▸ strict acceptance
                    │
                    ▼
        freeze as the reviewed baseline for the next batch
```

The **printed table of contents is the specification for what the TOC should contain — but never a navigation target**: every entry must resolve to a real heading or content block in the body. Any deviation (dropped line, renamed label, releveling, addition) must be declared in the spec (`deviation` / `dropped` with reasons) and passes the `coverage` gate, which fails on any silent deviation. Strict acceptance additionally checks EPUB/ZIP integrity, `mimetype` compliance, NCX parseability, `playOrder` continuity, shared targets, page numbers in labels, target identity, hierarchy, and body order — entry by entry against the approved specification.

### 2. Provenance receipts, never silent overwrites
Every conversion writes a receipt binding output SHA-256 hashes to the source PDF bytes, title/author, extraction options, tool hashes, and the Calibre executable hash. Batch reruns skip a book only when provenance matches. An EPUB you hand-repaired is **reported as a failure to review, not overwritten**. Intermediates without a matching `extraction-provenance.json` are regenerated; legacy caches are never trusted. (This is cache/output protection, not a bit-for-bit reproducibility guarantee — model weights and Calibre dependencies are not hashed.)

### 3. VLM-native parsing with an escape hatch
The default backend is MinerU's `vlm-engine` for GPU-backed accuracy; `-Backend pipeline` gives a CPU-friendly path, and `-Method ocr` handles scanned books. Page numbers, headers, and footers are stripped; headings become real Markdown headings; tables and images are preserved for Calibre. For equation- and table-heavy books, [`tools/build_high_fidelity_ebook.py`](tools/build_high_fidelity_ebook.py) builds a higher-fidelity variant: body text stays reflowable while display equations are kept as MinerU crop images and tables ship as both image and recognized HTML.

### 4. Battle-tested on a real corpus
The accepted corpus lives in the repo as **reproducible coordinate specifications, not binaries**: 77 psychology books (4,745 navigation entries) plus 6 standalone books (693 entries) — 83 EPUBs, 5,438 entries all passing strict acceptance, with 3,124 image references checked and zero broken. The September 2026 audit ([docs](docs/project-audit-20260911.md)) documents how the acceptance checker itself was hardened when it exposed 28 misrecorded coordinates hidden by the old exporter.

## How it compares

Based on public READMEs as of October 2026:

| Capability | Pagemelt | [MinerU](https://github.com/opendatalab/MinerU) | [CodeListening/pdf2epub](https://github.com/CodeListening/pdf2epub) | [bernardotorres/pdf2epub](https://github.com/bernardotorres/pdf2epub) | Calibre |
| --- | :---: | :---: | :---: | :---: | :---: |
| Reflowable EPUB output | ✅ | ❌ Markdown/JSON only | ✅ | ✅ | ⚠️ poor on scanned books |
| AZW3 / Kindle output | ✅ | ❌ | ❌ | ❌ | ✅ |
| VLM layout parsing | ✅ | ✅ | ✅ | ❌ | ❌ |
| TOC rebuilt via LLM/human adjudication | ✅ | ❌ | ❌ | ❌ | ❌ |
| Mechanical acceptance gate on navigation | ✅ | ❌ | ❌ | ✅ accessibility checks | ❌ |
| Provenance receipts / safe batch reruns | ✅ | ❌ | ❌ | ❌ | ❌ |
| Equation/table high-fidelity mode | ✅ | — | ❌ | ❌ | ❌ |

For interactive one-off TOC surgery on an existing EPUB, [Sigil](https://github.com/Sigil-Ebook/Sigil) remains the manual alternative; Pagemelt is about doing it reproducibly, at corpus scale, with an audit trail.

## Requirements

- Windows (entry points are PowerShell; the Python tools are platform-neutral)
- Python 3.11 (or let [`uv`](https://docs.astral.sh/uv/) download it)
- [Calibre](https://calibre-ebook.com/) for `ebook-convert`
- Optional for the default `vlm-engine` backend: NVIDIA driver + CUDA-capable PyTorch

## Quick start

```powershell
git clone https://github.com/NearlVI/pagemelt.git
cd pagemelt

# One-time: create .venv, install MinerU + TOC dependencies
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mineru.ps1

# Convert one book (output lands in .\output\ and next to the source PDF)
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\convert-pdfbook.ps1 `
  -InputPath "G:\Books\book.pdf" -Title "Book Title" -Author "Author"
```

Optional: pre-download MinerU models so the first real conversion doesn't wait:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mineru.ps1 -DownloadModels -ModelType vlm
```

The default model source is `modelscope` (recommended in mainland China); the generated MinerU config lands in `%USERPROFILE%\mineru.json`. Use `-ModelSource huggingface` elsewhere.

## Usage

Convert a single PDF or a whole folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\convert-pdfbook.ps1 -InputPath "G:\Books" -Format both
```

| Option | Values | Meaning |
| --- | --- | --- |
| `-Format` | `epub` (default) / `azw3` / `both` | Output formats; `both` for Kindle |
| `-Backend` | `vlm-engine` (default) / `pipeline` / `hybrid-engine` | MinerU backend; `pipeline` is CPU-friendly |
| `-Method` | `auto` (default) / `txt` / `ocr` | `ocr` for scanned or garbled PDFs |
| `-Lang` | `ch` (default), `en`, … | Language hint for parsing/OCR |
| `-ModelSource` | `modelscope` (default) / `huggingface` / `local` | Where models come from |
| `-Title` / `-Author` | strings | Metadata for the generated ebook |
| `-OutputDir` | path | Defaults to `output\` |
| `-SkipMinerU` | switch | Reuse retained intermediates; provenance must match exactly |
| `-KeepWork` | switch | Keep `work\` intermediates for diagnosis |

How a conversion run protects you:

- All formats build in a staging directory first; publication checks EPUB archive/package integrity (or the AZW3 header) before anything replaces an existing file.
- Differing existing files are backed up under `work/artifact-backups/`; receipts land in `work/conversion-receipts/`.
- Every generated file is copied next to its source PDF and both copies are verified by SHA-256 before success is reported.
- Reruns archive previous extraction directories under `work/previous-conversions/`.

After a repaired TOC is accepted, synchronize the final EPUB with backups and a fresh receipt:

```powershell
.\.venv\Scripts\python.exe tools/ebook_artifacts.py sync "output/book.epub" `
  --source-pdf "G:/Books/book.pdf" --backup-dir "work/artifact-backups" `
  --receipt "work/book-sync.json"
```

## Rebuilding navigation (the TOC workflow)

Full documentation in **[`toc-workflow/README.md`](toc-workflow/README.md)** (Chinese) with the LLM adjudication prompt in [`toc-workflow/LLM_REVIEW_PROMPT.md`](toc-workflow/LLM_REVIEW_PROMPT.md). The short version — all commands run via `scripts/toc-workflow.ps1`:

```powershell
# 1. Generate per-book evidence packets, adjudicate with an LLM or by hand
.\scripts\toc-workflow.ps1 review "output\books" -WorkDir "work\toc-batch"

# 2. Resolve the adjudicated search spec into stable body coordinates
.\scripts\toc-workflow.ps1 resolve "output\books" `
  -SearchSpec "toc-workflow\specs\batch.search.json" `
  -OutputSpec "toc-workflow\specs\batch.coordinates.json"

# 3. Coverage gate: every printed-TOC line restored or declared, else fail
.\scripts\toc-workflow.ps1 coverage "output\books" -Spec "toc-workflow\specs\batch.coordinates.json"

# 4. Read-only preflight validation
.\scripts\toc-workflow.ps1 validate "output\books" -Spec "toc-workflow\specs\batch.coordinates.json"

# 5. Apply with a full backup, then automatic strict acceptance
.\scripts\toc-workflow.ps1 apply "output\books" -Spec "toc-workflow\specs\batch.coordinates.json" `
  -BackupDir "output\books-before-toc"

# 6. Accept, then (only after human spot checks) freeze a new baseline
.\scripts\toc-workflow.ps1 accept "output\books" -Spec "toc-workflow\specs\batch.coordinates.json"
.\scripts\toc-workflow.ps1 freeze "output\books" -OutputSpec "toc-workflow\specs\accepted-batch.json"
```

Rules the tools enforce: the printed TOC is the specification for the entry set and deviations must be declared (`deviation` / `dropped`) and pass the coverage gate; repeated titles must be disambiguated (`occurrence`, `start_file`, `max_file`, or explicit coordinates); coordinates bind to the EPUB's spine and body-block structure and must be re-derived after any HTML split or OCR revision; backups may never live inside the directory being processed; `freeze` overwrites its target and is only run deliberately.

## Testing & verification

```powershell
# Unit tests (pure Python — no MinerU, Calibre, or GPU needed)
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Strict acceptance against a reviewed baseline
.\.venv\Scripts\python.exe tools/validate_epub_toc_acceptance.py "output/心理学书籍-fixed" `
  --spec toc-workflow/specs/reviewed-psychology-77-20260911.json `
  --csv-output work/current-acceptance.csv
```

The acceptance command returns nonzero for failed books and keeps going after an unreadable EPUB. Don't claim a full conversion test unless MinerU and Calibre actually completed against a representative PDF.

## Project layout

```text
scripts/        PowerShell entry points: setup, conversion, TOC workflow
tools/          Python tools: extraction-to-Markdown, TOC curation, auditing, receipts
tests/          Unit tests (34 tests, bs4 + lxml only)
toc-workflow/   Review prompt, workflow docs, accepted coordinate specifications
docs/           Audit and review records from the 83-book corpus
input/          Your source PDFs        (not tracked)
output/         Generated EPUB/AZW3     (not tracked)
work/           Intermediates, receipts, backups (not tracked)
```

## Limitations

- Windows-first: the orchestration entry points are PowerShell scripts. The Python tools under `tools/` are platform-neutral and testable anywhere.
- The AZW3 check is a header check, not a full content validation.
- Receipts verify file delivery and cache consistency, not OCR accuracy or page-by-page fidelity to the source PDF — directory completeness and correctness come from the TOC review process.
- The TOC loop needs an LLM (or a patient human) for adjudication; the scripts deliberately refuse to guess whole-book TOCs by regex.

## Acknowledgements

- [MinerU](https://github.com/opendatalab/MinerU) (OpenDataLab) — the parsing engine.
- [Calibre](https://calibre-ebook.com/) (Kovid Goyal) — ebook construction and format conversion.
- Beautiful Soup / lxml for EPUB surgery.

## License

[MIT](LICENSE) © The Pagemelt Authors
