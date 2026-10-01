# Preferred Cover Art

Picard 2.13 cover-art provider that selects artwork from a preferred MusicBrainz
release associated with the current recording. Cover Art Archive is always used;
fanart.tv and Discogs are optional sources.

## Selection

The provider discovers every MusicBrainz release containing the recording and
normalizes front artwork from all enabled sources before scoring it:

- release type: 40 points;
- original release date: 25 points, halving every five years;
- cover dimensions and aspect ratio: 15 points;
- recording length: 10 points, halving every five seconds of difference;
- Picard preferred country: 6 points;
- Picard preferred medium: 4 points.

These established components produce a base score from 0 to 100. The final
score assigns 90% to that base and 10% to provenance confidence. An exact CAA
or MusicBrainz-linked Discogs image therefore wins an otherwise equal comparison
against a release-group-level fanart.tv image.

The score saturates at the configured preferred cover dimensions. Images outside
the configured aspect-ratio tolerance receive at most half of the dimension
score, followed by exponential decay as the mismatch grows. Releases without a
front image are excluded. Failure of one optional source does not discard valid
results returned by another source.

Picard runs cover-art providers once per loaded album. If album metadata does not
contain a recording MBID, the provider uses the first recording on the loaded
release as the source recording for candidate discovery.

Before querying artwork services, releases are grouped by every enabled release
type. Each group is ranked independently using date (25 points), recording
length (10), country (6), and medium (4). Only the best three releases from each
group continue. Multitype releases can qualify in several groups but are
deduplicated by release MBID before network requests. CAA therefore performs at
most three calls per enabled type; fanart.tv and Discogs enforce the same
per-type HTTP budget.

## Install

Create an archive named `preferred_cover_art.zip` whose top-level folder is also
`preferred_cover_art`, then select the ZIP using **Options > Plugins > Install
plugin...** in Picard 2. The matching underscore-based names are required by the
Picard 2 plugin loader; a versioned or hyphenated ZIP name will not load.

`MANIFEST.toml` and the commented entry-point example in `__init__.py` are retained
as migration notes for a future Picard 3 version; Picard 2 does not use them.

## Configuration

The **Plugins > Preferred Cover Art** page shows all Picard release types as a
checkable, reorderable list. Only Single, EP, Album, Compilation and Soundtrack
are enabled by default. Unchecked types remain candidates but contribute zero
type points. Country and medium preferences come from **Metadata > Preferred
Releases**. Preferred cover width and height default to 1200 × 1200 with a 10%
ratio tolerance. **Avoid Various Artists** is enabled by default and uses
Picard's configured Various Artists identity as a hard filter.

Discogs and fanart.tv each have an independent enable checkbox and API-key field.
Both are disabled by default. fanart.tv matches MusicBrainz release groups.
Its single field accepts either a project key or a personal key.
Discogs first uses an exact MusicBrainz URL relationship, then accepts only
strong barcode or catalogue-number matches; title-only guessing is excluded.
Keys are displayed in clear text on the options page, stored in Picard's
configuration, and sent in HTTP headers rather than request URLs.

## Tests

```bash
python -m unittest discover -s tests -v
```

The pure selection module has no Picard or Qt dependency.
