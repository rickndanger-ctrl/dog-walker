# Finding the right project files

When a walk has **Project tools** enabled, the model can find its way around your
project before making changes. There is no index to maintain and no extra model
to download. Your existing review and verification steps stay in charge.

The project map shows source files, likely starting points, package manifests,
and tests. Code search finds exact text or filenames and returns short excerpts
with line numbers. The model then reads the actual files it needs. Both tools
inspect the current working copy, so new edits appear on the next call.

These tools work during walks. Ordinary chat is unchanged in this release.
Dog Walk handles the local runtime's tool compatibility automatically; there
is no additional tool-connection setting to manage.

## Tool interface

- `project_map {}` returns `files` with relative `path`, `kind`, and `bytes`.
- `project_search {"query": "normalize_name"}` returns `matches` with relative
  `path`, `match` (`filename` or `content`), and `line`/`excerpt` for content.
- Both return `files_scanned`, `bytes_scanned`, `truncated`, and `limits`.
  Labels such as “entrypoint” are filename hints, not architectural conclusions.

Search is literal and case sensitive. Filename matches come first; paths and
line numbers have stable ordering. Results stay structured when truncated.
Tools use the existing `project` grant and recorded tool receipts; a paused or
stale worker cannot call them.

## Limits

Discovery skips symlinks, credentials such as `.env` and `.ssh`, Git metadata,
dependencies, caches, generated output, binaries, and invalid UTF-8. In a Git
project it also respects Git ignore rules. Files over 64 KiB are omitted;
the existing shell tools remain available for deliberate inspection within
the walk's permissions.

Each call scans at most 5,000 supported files and 20 MiB of file data, with a
10-second scan budget, a 20,000-directory-entry guard, and a depth limit of 40.
Search returns at most 200 content matches. Responses use at most 15,000
characters before the broker envelope. Omitted supported files or hits are
reported explicitly. Nothing is cached persistently or sent to a cloud service.
