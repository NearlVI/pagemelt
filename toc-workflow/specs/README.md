# TOC specifications

- `reviewed-psychology-77-20260911.json` is the current default exact-coordinate baseline for the 77-book psychology corpus (4,745 entries).
- `reviewed-standalone-6-20260913.json` combines reviewed specifications for the six standalone books (693 entries).
- `accepted-psychology-77.json` is the historical baseline; its duplicate-title coordinates were affected by the old DOM equality bug. Do not apply it to the current corpus.
- Treat accepted specifications as immutable review artifacts. Create a new file for a new corpus or revision.
- Search specifications are reviewer-friendly intermediate files. Coordinate specifications are the only inputs allowed for `validate` and `apply`.
- Do not commit EPUB files, backups, review packets, or generated evidence; those remain under `output` and `work`.
