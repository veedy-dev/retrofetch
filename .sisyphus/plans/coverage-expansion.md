# coverage-expansion — more ROM source providers

Expand retrofetch's wantlist coverage beyond the current `romsfun` + `romsretro` + `archive_org` mix.

## Why

After the `fix(consoles)` slug commit, 45 Class A/B/C consoles still return 0 titles because romsfun/romsretro do not carry them. Research (see research notes below) identified three high-value adds:

1. **archive.org collection identifiers** - our existing adapter works, but `archive_org_identifier: null` for most consoles. A data-only audit populates these and fixes ~30 consoles with zero new code.
2. **Vimm's Lair (vimm.net)** - nonprofit since 2001, 100% vault completion for major retro consoles, No-Intro hash-verified. Cleanest legal posture of any option. Covers Atari 2600, NES, SNES, Genesis, N64, PS1, PSP, GBA, DS, 3DS, GameCube.
3. **CoolROM (coolrom.com.au)** - the only candidate site with a real "Top 25 Downloaded" ranking (exactly the metric we need). Cloudflare + Nintendo-takedown risk, but high-quality signal when it works.

## What NOT to add (and why)

- emuparadise.me: removed all ROMs in 2018, only guides remain
- romsgames.net: no usable popularity ranking signal
- romspedia.com: no consolidated "top N per console" page
- switchrom.net: Nintendo-litigation target, high churn

## Phases

- [ ] P1. Archive.org identifier audit (data-only, `consoles.yml`) [deep]
- [ ] P2. Vimm's Lair adapter (`retrofetch/sources/vimm.py` + ranker registration + vimm_slug per console) [deep]
- [ ] P3. CoolROM adapter (`retrofetch/sources/coolrom.py` + ranker registration + coolrom_slug per console) [deep]
- [ ] P4. Integration smoke + regression [self]

## Must Have

- Use Serena exclusively (per project CLAUDE.md)
- Preserve `consoles.yml` with the project's `_yaml_rt` config (avoid reformatting drift)
- New adapters inherit the SourceAdapter Protocol shape: `list_popular`, `find_url_for_game`, `download`, plus a `name` class attribute
- Reuse `retrofetch.sources._cloudflare_base.make_scraper` + `health()` pattern for Cloudflare-protected sites
- New per-console YAML fields follow the `<source>_slug` or `<source>_identifier` pattern
- All new adapters fail gracefully (empty list / None, never crash ranker)
- Add to `ranking_sources_by_class` for appropriate classes

## Must NOT Have

- No new Config fields (stay within current Config schema)
- No new exception types (stick to `SourceUnavailable`)
- No mouse handlers / emojis / non-ASCII in new files
- No pre-fetch of all 178 consoles on startup
- No modifications to `retrofetch/events.py` / `retrofetch/ranker.py` beyond `_SOURCE_FACTORIES` registration
- No attribution trailers in commits
