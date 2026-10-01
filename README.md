# Preferred Cover Art

Picard 2.13 cover-art provider that selects artwork from a preferred MusicBrainz release associated with the current recording.

## Selection

The provider retrieves Cover Art Archive metadata for every release containing
the recording and scores every available front image:

- release type: 40 points;
- original release date: 25 points, halving every five years;
- cover dimensions and aspect ratio: 15 points;
- recording length: 10 points, halving every five seconds of difference;
- Picard preferred country: 6 points;
- Picard preferred medium: 4 points.

The score saturates at the configured preferred cover dimensions. Images outside
the configured aspect-ratio tolerance receive at most half of the dimension
score, followed by exponential decay as the mismatch grows. Releases without a
front image are excluded. A transient CAA failure is reported as an album error
instead of producing a result from incomplete data.

Picard runs cover-art providers once per loaded album. If album metadata does not
contain a recording MBID, the provider uses the first recording on the loaded
release as the source recording for candidate discovery.

## Install

Create a ZIP whose top-level folder is `preferred_cover_art`, then select the
ZIP using **Options > Plugins > Install plugin...** in Picard 2.

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

## Tests

```bash
python -m unittest discover -s tests -v
```

The pure selection module has no Picard or Qt dependency.
