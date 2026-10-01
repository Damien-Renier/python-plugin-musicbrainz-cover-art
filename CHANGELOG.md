# Changelog

## 0.6.1

- Add a configurable one-to-ten cover return count, queue ranked unique images
  as Front artwork, and label them `Rank-SCORE = X-XX.XX`.

## 0.6.0

- Introduce a source-neutral artwork model and an abstract asynchronous source
  interface compatible with Picard 2.13.
- Move Cover Art Archive retrieval into its own release-exact source adapter.
- Add independently configurable fanart.tv and Discogs sources with masked API
  key fields; both remain disabled by default.
- Match fanart.tv artwork through MusicBrainz release groups and Discogs artwork
  through exact URL relationships, barcodes, or catalogue numbers.
- Keep credentials out of request URLs by attaching them as private headers to
  Picard 2.13 web-service requests.
- Reserve ten points for source and match provenance while retaining the
  established release/image score as ninety percent of the final result.
- Rank releases independently inside every enabled type using date, duration,
  country, and medium, then query artwork only for the best three per group.
- Deduplicate multitype releases and enforce a maximum of three CAA, fanart.tv,
  and Discogs HTTP calls per enabled release type.
- Display configured API keys in clear text and include every candidate image
  URL with the complete score breakdown in Debug logs.

## 0.5.3

- Reorganize options into native-style Various Artists, Cover dimensions and
  ratio, and Preferred release types groups; restore the type list to one
  ordered column and keep that group last in the normal page flow.

## 0.5.2

- Keep the complete options form compact and top-aligned, attach narrow move
  buttons to the release-type grid, and prevent control labels from wrapping.

## 0.5.1

- Display release types in a compact two-column grid without changing their
  stored priority order or scoring behaviour.

## 0.5.0

- Replace pass-based selection with a weighted global score: release type 40,
  original date 25, cover dimensions and ratio 15, recording length 10,
  preferred country 6 and preferred medium 4.
- Retrieve CAA metadata for every release candidate before scoring, exclude
  releases without front art, and report transient CAA failures as album errors.
- Add preferred width and height plus an enabled-by-default Avoid Various
  Artists hard filter using Picard's configured Various Artists identity.
- Show all release types but enable only Single, EP, Album, Compilation and
  Soundtrack by default.

## 0.4.6

- Add detailed debug logging for the initial MusicBrainz candidates, counts by
  release type, every filtering or ranking step, and all CAA images. Preferred
  countries and media are logged and applied strictly as ranking boosts.

## 0.4.5

- Keep Picard's album request counter active throughout the asynchronous
  MusicBrainz and Cover Art Archive lookup chain, preventing Picard 2.13 from
  finalizing the album before the selected image is downloaded.

## 0.4.0

- Source release types from Picard and expose them as a checkable, reorderable list.
- Default to Single, EP, Album, Compilation and Soundtrack before other Picard types.
- Reuse Picard's existing preferred countries and media formats.
- Correct duration passes to ±5% and ±10%.
- Add a 10% square-artwork tolerance setting.
- Change the project license to MIT.

## 0.3.3

- Register provider and options-page adapter classes from the package root so
  Picard associates them with the enabled `preferred_cover_art` plugin ID.

## 0.3.2

- Initialize the Picard 2 options UI explicitly, matching the working Last.fm
  plugin's `OptionsPage` lifecycle.

## 0.3.1

- Register the configuration page explicitly under Picard's Plugins options
  section so it is consistently visible in Picard 2.13.

## 0.3.0

- Add a Picard 2 cover-art provider configuration page for release-type,
  country and media-format priorities.

## 0.2.0

- Retarget the runtime adapter and packaging metadata to Picard 2.13.
- Support the Python 3.8 runtime bundled with Picard 2.13 on Windows.
- Remove an unused `dataclasses` import unavailable in Picard's bundled runtime.
- Preserve Picard 3 manifest and entry-point migration notes for later.
- Parse web-service responses as JSON and always advance the cover-art queue on failure.

## 0.1.0 — 2026-09-30

- Initial Picard Plugin API v3 implementation.
- MusicBrainz recording-to-release discovery.
- ±5 s, ±10 s, then duration-free selection passes.
- Deterministic release type, country, format, status and date ranking.
- Front Cover Art Archive selection with approved/square preference.
- Unit tests and GitHub Actions.
# 0.4.1

- Avoid a Picard 2 `QVariant` conversion failure when upgrading from the old
  comma-separated release-type option.
- Add debug traces for received candidates and the queued Cover Art Archive
  image so the complete provider path can be verified in Picard's log.
# 0.4.2

- Store release-type preferences as JSON text instead of nested Python
  objects in Qt's `QSettings`.
- Remove lambda-based Qt signal connections from the options UI shutdown path.
# 0.4.3

- Avoid creating adapter subclasses of the Qt-derived options page. Picard's
  plugin identity is now assigned to the original extension classes before
  registration, preventing a native Qt 5 crash during application shutdown.
# 0.4.4

- Define the registered Picard 2 extension classes directly in the plugin
  package root, with direct Picard base classes, matching official plugins.
