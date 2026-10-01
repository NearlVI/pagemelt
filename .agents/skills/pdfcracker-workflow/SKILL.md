---
name: pdfcracker-workflow
description: Operate and maintain PdfCracker's Windows workflow for converting PDF books with MinerU into EPUB/AZW3, reviewing or repairing EPUB navigation, and testing the related PowerShell and Python tools. Use for PDF conversion, MinerU backend selection, ebook output checks, TOC review/spec/application, or changes under scripts/, tools/, tests/, and toc-workflow/.
---

# PdfCracker Workflow

Work from the repository root and preserve user data under `input/`, `output/`,
`work/`, and `.venv/`. Inspect existing artifacts before replacing or deleting them.

## Convert books

1. Run `scripts/setup-mineru.ps1` only when the local environment is missing or
   the user asks to refresh it; model downloads can be large.
2. Convert with:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\convert-pdfbook.ps1 -InputPath 'C:\Books\book.pdf' -Format epub
   ```

3. Keep the default `vlm-engine` for GPU-backed accuracy. Use `-Backend pipeline`
   for a CPU-friendly run and `-Method ocr` only when OCR is needed.
4. Add `-KeepWork` when intermediates are needed for diagnosis. The conversion
   script copies every generated EPUB/AZW3 from `output/` to the source PDF's
   directory. Verify both copies exist and have matching hashes before reporting
   success.

## Review EPUB navigation

Follow `review -> resolve -> validate -> apply -> accept` through
`scripts/toc-workflow.ps1`; read `toc-workflow/README.md` for command arguments.
Treat printed TOC text as evidence, never as the navigation target. Targets must
resolve to real body blocks. Never apply without a successful read-only validation
and a backup directory outside the EPUB input directory. Regenerate coordinates
after EPUB structure or OCR text changes. Run `freeze` only when explicitly asked,
because it overwrites the destination specification.

After TOC application and final acceptance, copy the accepted canonical EPUB
from `output/` to the source PDF's directory again and verify matching hashes;
TOC application changes the EPUB after the converter's initial source-side copy.

## Modify and verify

Prefer focused changes in the existing PowerShell entry points or Python tools.
Run the TOC unit tests after relevant edits:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

If `.venv` is unavailable, use a Python 3.11 environment with
`requirements-toc.txt`. Do not claim a full conversion test unless MinerU and
Calibre actually completed against a representative PDF.
