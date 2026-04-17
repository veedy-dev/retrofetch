# DAT Snapshot Manifest

Snapshot date: 2026-04-17

## Sources

- No-Intro (cart systems): https://datomatic.no-intro.org + community mirror at https://github.com/unexpectedpanda/retool/tree/main/datafiles/No-Intro
- Redump (disc systems): http://redump.org/downloads/ (per-system dat zips)

## Layout

- `no-intro/<shortname>.dat` - one file per Class A console
- `redump/<shortname>.dat` - one file per Class B console

## Current snapshot

This bundle includes seed DAT files for testing and initial use:
- `no-intro/virtualboy.dat` (stub with 3 representative games for T7 parser testing)
- `no-intro/nes.dat` (stub with 3 representative games for T7 parser testing)

Hash values in stub DATs are representative but may not match real ROM dumps.
Real DAT fetch is a follow-up concern; users can replace these files with live
downloads from the sources above.

## Refresh

Currently a one-time manual snapshot. Future `retrofetch refresh-dats` command
may automate.
