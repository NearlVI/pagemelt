# Contributing to Pagemelt

Thanks for your interest in improving Pagemelt. This project has a few hard
invariants that keep its outputs trustworthy — please read them before opening
a PR.

## Development setup

```powershell
git clone https://github.com/NearlVI/pagemelt.git
cd pagemelt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mineru.ps1

# TOC-tool dependencies only (enough to run the unit tests)
.\.venv\Scripts\python.exe -m pip install -r .\requirements-toc.txt
```

## Running the tests

The unit tests are pure Python (Beautiful Soup + lxml) and run in seconds
without MinerU, Calibre, or a GPU:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

CI runs the same command on Windows and Ubuntu for every push and PR.
If `.venv` is unavailable, any Python 3.11 with `requirements-toc.txt`
installed works.

## Design invariants (do not break these)

1. **The printed TOC is evidence, never a navigation target.** Every
   navigation entry must resolve to a real heading or content block in the
   body. Never add code that batch-guesses a whole-book TOC from regex hits.
2. **No application without validation and an external backup.** `apply`
   always re-validates read-only first, backs up the affected EPUBs outside
   the input directory, and runs strict acceptance afterwards.
3. **No silent overwrites.** Batch conversion skips a book only on matching
   provenance receipts. A hand-repaired EPUB with stale hashes is a failure
   to review, not something to rebuild in place.
4. **Coordinates bind to structure.** Body coordinates assume the EPUB's
   spine split and body-block layout; any HTML split, OCR revision, or
   reflow requires re-resolving and re-reviewing the specification.
5. **Provenance is never inferred.** Intermediates without a matching
   `extraction-provenance.json` are regenerated, not trusted.
6. **Report success only with evidence.** Don't claim a conversion works
   unless MinerU and Calibre actually completed against a representative
   PDF and both output copies verified by SHA-256.

## What makes a good change

- **Focused.** Prefer a small change in an existing PowerShell entry point or
  Python tool over a new parallel path.
- **Tested.** Changes to `tools/` should come with unit tests under `tests/`
  (see `test_toc_coordinates.py` for the pattern of exercising tools
  directly).
- **Documented.** If you change command behavior, update both `README.md`
  and `README.zh-CN.md`, plus `toc-workflow/README.md` when the TOC workflow
  is affected.
- **Honest about limits.** Verification docs should say what was checked and
  what was *not* (see `docs/project-audit-20260911.md` for the tone).

## Pull requests

1. Fork, create a feature branch.
2. Make your change; add or update tests.
3. Run the unit tests and make sure they pass.
4. Open the PR describing what changed, why, and what you verified —
   including what you did *not* verify.

## Reporting bugs

Include: the command you ran, the platform, MinerU backend/method, relevant
receipts or CSVs from `work/`, and (for TOC issues) whether the coordinate
spec was derived before or after a structural change to the EPUB.
