"""Deterministic release and cover-art scoring for Preferred Cover Art.

This module is deliberately independent of Picard and Qt.  It translates raw
MusicBrainz and Cover Art Archive dictionaries into normalized score components,
then ranks release/image pairs using stable tie-breakers.  Keeping the policy in
this pure module makes the selection rules reusable and straightforward to test.

All component scores are normalized to ``0.0 .. 1.0`` before their weights are
applied.  Public helpers tolerate incomplete API payloads and return neutral
scores instead of raising for absent optional metadata.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional, Sequence


def _norm(value: Any) -> str:
    """Return a case-insensitive, whitespace-trimmed comparison value."""
    return str(value or "").strip().casefold()


def _date_value(value: Any) -> Optional[date]:
    """Parse a complete or partial MusicBrainz date.

    Missing month and day components default to January and the first day of the
    month respectively.  Invalid or empty values are represented by ``None``.
    """
    if not value:
        return None
    parts = str(value).split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def release_types(release: dict[str, Any]) -> tuple[str, ...]:
    """Return the primary type followed by all secondary release-group types."""
    group = release.get("release-group") or {}
    result = []
    primary = group.get("primary-type")
    if primary:
        result.append(str(primary))
    result.extend(str(item) for item in (group.get("secondary-types") or []))
    return tuple(result)


def release_formats(release: dict[str, Any]) -> tuple[str, ...]:
    """Return every non-empty medium format declared by a release."""
    return tuple(
        str(medium.get("format"))
        for medium in (release.get("media") or [])
        if medium.get("format")
    )


def release_artist_ids(release: dict[str, Any]) -> tuple[str, ...]:
    """Return artist MBIDs from the release-level artist credit."""
    return tuple(
        str((credit.get("artist") or {}).get("id"))
        for credit in (release.get("artist-credit") or [])
        if (credit.get("artist") or {}).get("id")
    )


def release_artist_names(release: dict[str, Any]) -> tuple[str, ...]:
    """Return credited names, falling back to canonical artist names."""
    return tuple(
        str(credit.get("name") or (credit.get("artist") or {}).get("name"))
        for credit in (release.get("artist-credit") or [])
        if credit.get("name") or (credit.get("artist") or {}).get("name")
    )


def is_various_artists(release: dict[str, Any], various_artists_id: str, configured_name: str) -> bool:
    """Report whether a release is credited to Picard's Various Artists identity.

    The stable MBID is authoritative.  The configured display name is retained
    as a case-insensitive fallback for localized or incomplete release credits.
    """
    if various_artists_id in release_artist_ids(release):
        return True
    target = _norm(configured_name)
    return bool(target and any(_norm(name) == target for name in release_artist_names(release)))


def track_lengths_for_recording(release: dict[str, Any], recording_id: str) -> list[int]:
    """Collect non-negative track lengths, in milliseconds, for a recording."""
    lengths = []
    for medium in release.get("media") or []:
        for track in medium.get("tracks") or []:
            if (track.get("recording") or {}).get("id") != recording_id:
                continue
            length = track.get("length")
            if isinstance(length, int) and length >= 0:
                lengths.append(length)
    return lengths


def ordered_preference_score(value: Any, ordered: Sequence[str], unlisted: float = 0.01) -> float:
    """Score a value according to its position in an ordered preference list.

    Args:
        value: Candidate value to compare.
        ordered: Values ordered from most to least preferred.
        unlisted: Score assigned to a present value absent from ``ordered``.

    Returns:
        ``1.0`` for the first preference, decreasing linearly to ``1 / n`` for
        the last.  Missing values score ``0.0``.
    """
    if not value:
        return 0.0
    total = len(ordered)
    if not total:
        return unlisted
    target = _norm(value)
    for index, item in enumerate(ordered):
        if _norm(item) == target:
            return (total - index) / total
    return unlisted


def release_type_score(release: dict[str, Any], enabled_types: Sequence[str]) -> float:
    """Return the best enabled primary or secondary release-type score."""
    return max(
        (ordered_preference_score(value, enabled_types, unlisted=0.0) for value in release_types(release)),
        default=0.0,
    )


def country_score(release: dict[str, Any], preferred: Sequence[str]) -> float:
    """Score a release country against Picard's ordered preferences."""
    return ordered_preference_score(release.get("country"), preferred)


def medium_score(release: dict[str, Any], preferred: Sequence[str]) -> float:
    """Return the best preference score among all media in a release."""
    return max(
        (ordered_preference_score(value, preferred) for value in release_formats(release)),
        default=0.0,
    )


def length_score(release: dict[str, Any], recording_id: str, target_ms: Optional[int]) -> float:
    """Score the closest recording duration using a five-second half-life."""
    if target_ms is None or target_ms <= 0:
        return 0.0
    lengths = track_lengths_for_recording(release, recording_id)
    if not lengths:
        return 0.0
    delta_ms = min(abs(value - target_ms) for value in lengths)
    return 2 ** (-delta_ms / 5000.0)


def date_score(release: dict[str, Any], earliest: Optional[date]) -> float:
    """Score release age relative to the earliest candidate using a five-year half-life."""
    released = _date_value(release.get("date"))
    if released is None or earliest is None:
        return 0.0
    delta_years = max(0, (released - earliest).days) / 365.2425
    return 2 ** (-delta_years / 5.0)


def is_front_image(image: dict[str, Any]) -> bool:
    """Return whether Cover Art Archive metadata marks an image as front art."""
    return image.get("front") is True or "front" in {
        _norm(value) for value in (image.get("types") or [])
    }


def cover_dimension_score(
    image: dict[str, Any],
    preferred_width: int,
    preferred_height: int,
    ratio_tolerance: float,
) -> float:
    """Score image size and aspect ratio against preferred dimensions.

    Size saturates once both preferred dimensions are met.  Images outside the
    accepted ratio tolerance receive an initial 50% penalty followed by
    exponential decay as the mismatch grows.
    """
    width = image.get("width")
    height = image.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return 0.0
    if preferred_width <= 0 or preferred_height <= 0:
        return 0.0

    # Requiring both axes to reach their targets prevents a large but narrow
    # image from receiving full credit merely because one dimension is large.
    size_score = min(1.0, width / preferred_width, height / preferred_height)
    actual_ratio = width / height
    preferred_ratio = preferred_width / preferred_height
    ratio_error = max(actual_ratio / preferred_ratio, preferred_ratio / actual_ratio) - 1.0
    if ratio_error <= ratio_tolerance:
        ratio_factor = 1.0
    else:
        ratio_factor = 0.5 * 2 ** (-(ratio_error - ratio_tolerance) / 0.25)
    return size_score * ratio_factor


def choose_front_images(images: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialize the subset of images eligible as front cover art."""
    return [image for image in images if is_front_image(image)]


def score_release_image(
    release: dict[str, Any],
    image: dict[str, Any],
    recording_id: str,
    target_length_ms: Optional[int],
    earliest: Optional[date],
    enabled_types: Sequence[str],
    preferred_countries: Sequence[str],
    preferred_media: Sequence[str],
    preferred_width: int,
    preferred_height: int,
    ratio_tolerance: float,
) -> dict[str, float]:
    """Calculate weighted score components for one release/image pair.

    Returns:
        A mapping containing each weighted component and their ``total``.  A
        perfect candidate scores 100 points.
    """
    components = {
        "release_type": 40.0 * release_type_score(release, enabled_types),
        "date": 25.0 * date_score(release, earliest),
        "cover_dimension": 15.0 * cover_dimension_score(
            image, preferred_width, preferred_height, ratio_tolerance
        ),
        "length": 10.0 * length_score(release, recording_id, target_length_ms),
        "country": 6.0 * country_score(release, preferred_countries),
        "medium": 4.0 * medium_score(release, preferred_media),
    }
    components["total"] = sum(components.values())
    return components


def rank_release_images(
    release_images: Iterable[tuple[dict[str, Any], dict[str, Any]]],
    recording_id: str,
    target_length_ms: Optional[int],
    enabled_types: Sequence[str],
    preferred_countries: Sequence[str],
    preferred_media: Sequence[str],
    preferred_width: int,
    preferred_height: int,
    ratio_tolerance: float,
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, float]]]:
    """Rank release/image pairs from strongest to weakest candidate.

    The date baseline is calculated only from releases that actually supplied
    an eligible image.  Equal totals prefer approved artwork, then stable API
    identifiers, making repeated runs deterministic.
    """
    pairs = list(release_images)
    # Image-less releases never reach this function and therefore cannot make
    # valid cover candidates appear artificially newer in the date component.
    dates = [_date_value(release.get("date")) for release, _image in pairs]
    known_dates = [value for value in dates if value is not None]
    earliest = min(known_dates) if known_dates else None
    scored = [
        (
            release,
            image,
            score_release_image(
                release,
                image,
                recording_id,
                target_length_ms,
                earliest,
                enabled_types,
                preferred_countries,
                preferred_media,
                preferred_width,
                preferred_height,
                ratio_tolerance,
            ),
        )
        for release, image in pairs
    ]
    return sorted(
        scored,
        key=lambda item: (
            -item[2]["total"],
            0 if item[1].get("approved") is True else 1,
            str(item[0].get("id") or ""),
            str(item[1].get("id") or item[1].get("image") or ""),
        ),
    )


def choose_front_image(
    images: Iterable[dict[str, Any]], square_tolerance: float = 0.10, trace=None
) -> Optional[dict[str, Any]]:
    """Choose one front image using the legacy image-only policy.

    This compatibility entry point predates global release/image scoring.  New
    integrations should prefer :func:`rank_release_images`.
    """
    all_images = list(images)
    if trace:
        trace("initial Cover Art Archive response", all_images)
    fronts = choose_front_images(all_images)
    if trace:
        trace("front images", fronts)
    if not fronts:
        return None
    return max(
        fronts,
        key=lambda image: (
            cover_dimension_score(image, 1, 1, square_tolerance),
            image.get("approved") is True,
            (image.get("width") or 0) * (image.get("height") or 0),
        ),
    )


def choose_release(
    releases: Iterable[dict[str, Any]],
    recording_id: str,
    target_ms: Optional[int],
    type_priority: Sequence[str] = (),
    country_priority: Sequence[str] = (),
    format_priority: Sequence[str] = (),
    trace=None,
) -> Optional[dict[str, Any]]:
    """Choose one release using only release-level score components.

    This compatibility helper omits cover dimensions because it receives no
    image metadata.  Ties are resolved by release MBID for deterministic output.
    """
    candidates = list(releases)
    if trace:
        trace("initial MusicBrainz response", candidates)
    if not candidates:
        return None
    known_dates = [_date_value(item.get("date")) for item in candidates]
    earliest = min((value for value in known_dates if value is not None), default=date.today())
    scored = sorted(
        candidates,
        key=lambda release: (
            -(
                40 * release_type_score(release, type_priority)
                + 25 * date_score(release, earliest)
                + 10 * length_score(release, recording_id, target_ms)
                + 6 * country_score(release, country_priority)
                + 4 * medium_score(release, format_priority)
            ),
            str(release.get("id") or ""),
        ),
    )
    if trace:
        trace("release-only score", scored)
    return scored[0]
