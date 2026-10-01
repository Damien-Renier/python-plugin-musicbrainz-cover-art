"""Asynchronous artwork-source adapters for Picard 2.13.

Each adapter owns the fan-out and completion accounting required by its remote
API, normalizes successful responses into ``ArtworkCandidate`` values, and
reports recoverable source failures without making ranking decisions.
"""

from __future__ import annotations

from functools import partial
import re
from typing import Any, Iterable
from urllib.parse import urlencode

from PyQt5.QtNetwork import QNetworkRequest
from picard.webservice import WSRequest

from .artwork import ArtworkCandidate, ArtworkSource, CompletionCallback, positive_int


CAA_BASE = "https://coverartarchive.org"
FANART_BASE = "https://webservice.fanart.tv/v3.2/music"
DISCOGS_BASE = "https://api.discogs.com"
DISCOGS_RELEASE_PATTERN = re.compile(r"(?:discogs\.com)/(?:[^/]+/)?release/(\d+)", re.IGNORECASE)


def _get_json(webservice, url: str, handler, headers=None) -> None:
    """Schedule a Picard 2.13 JSON request with optional private headers."""
    request = WSRequest(
        method="GET",
        url=url,
        handler=handler,
        parse_response_type="json",
        priority=True,
        important=False,
    )
    for name, value in (headers or {}).items():
        request.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
    webservice.add_request(request)


def _http_status(reply) -> int | None:
    """Extract an HTTP status code from a Qt reply when available."""
    try:
        value = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        return int(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _error_text(reply, error) -> str:
    """Return a stable diagnostic for a Picard network failure."""
    return reply.errorString() if reply is not None else str(error)


def _release_group_id(release: dict[str, Any]) -> str:
    """Return a release's MusicBrainz release-group MBID."""
    return str((release.get("release-group") or {}).get("id") or "")


def _artist_ids(release: dict[str, Any]) -> tuple[str, ...]:
    """Return MusicBrainz artist MBIDs from release-level credits."""
    return tuple(
        str((credit.get("artist") or {}).get("id"))
        for credit in (release.get("artist-credit") or [])
        if (credit.get("artist") or {}).get("id")
    )


class _FanOutSource(ArtworkSource):
    """Shared exactly-once completion barrier for multi-request adapters."""

    def __init__(self, webservice):
        """Initialize shared request accounting for one Picard web service."""
        self.webservice = webservice
        self._pending = 0
        self._completed = None
        self._candidates = []
        self._failures = []

    def _start(self, count: int, completed: CompletionCallback) -> None:
        """Initialize one adapter run with ``count`` scheduled units."""
        self._pending = count
        self._completed = completed
        self._candidates = []
        self._failures = []
        if count == 0:
            self._finish()

    def _unit_finished(self) -> None:
        """Release one unit and complete the adapter at the zero barrier."""
        self._pending -= 1
        if self._pending == 0:
            self._finish()

    def _finish(self) -> None:
        """Invoke the registered callback exactly once with accumulated state."""
        completed, self._completed = self._completed, None
        if completed is not None:
            completed(self._candidates, self._failures)


class CoverArtArchiveSource(_FanOutSource):
    """Retrieve release-exact front images from Cover Art Archive."""

    NAME = "cover_art_archive"

    def _finish(self) -> None:
        """Discard partial CAA data when any release request failed transiently."""
        if self._failures:
            self._candidates = []
        super()._finish()

    def fetch(self, releases: Iterable[dict[str, Any]], completed: CompletionCallback) -> None:
        """Request CAA metadata once for each MusicBrainz release."""
        valid = [release for release in releases if release.get("id")]
        self._start(len(valid), completed)
        for release in valid:
            release_id = release["id"]
            try:
                self.webservice.get_url(
                    url="%s/release/%s/" % (CAA_BASE, release_id),
                    handler=partial(self._downloaded, release),
                    parse_response_type="json",
                    priority=True,
                    important=False,
                )
            except Exception as exc:
                self._failures.append("CAA %s: %s" % (release_id, exc))
                self._unit_finished()

    def _downloaded(self, release, data, reply, error) -> None:
        """Normalize one CAA response and release its pending unit."""
        release_id = str(release.get("id") or "")
        try:
            status = _http_status(reply)
            if error and status != 404:
                self._failures.append("CAA %s: %s" % (release_id, _error_text(reply, error)))
                return
            images = data.get("images", []) if isinstance(data, dict) else []
            for image in images:
                front = image.get("front") is True or "front" in {
                    str(value).strip().casefold() for value in (image.get("types") or [])
                }
                if not front or not image.get("image"):
                    continue
                thumbnails = image.get("thumbnails") or {}
                candidate = ArtworkCandidate(
                    source=self.NAME,
                    image_id=str(image.get("id") or image.get("image")),
                    image_url=str(image["image"]),
                    thumbnail_url=str(thumbnails.get("1200") or thumbnails.get("large") or ""),
                    width=positive_int(image.get("width")),
                    height=positive_int(image.get("height")),
                    front=True,
                    approved=image.get("approved") is True,
                    source_confidence=1.0,
                    match_confidence=1.0,
                    comment=str(image.get("comment") or ""),
                    metadata=image,
                )
                self._candidates.append((release, candidate))
        except Exception as exc:
            self._failures.append("CAA %s: %s" % (release_id, exc))
        finally:
            self._unit_finished()


class FanartTvSource(_FanOutSource):
    """Retrieve release-group artwork from fanart.tv API v3.2."""

    NAME = "fanart_tv"

    def __init__(self, webservice, api_key: str):
        """Initialize the adapter with a fanart.tv project API key."""
        super().__init__(webservice)
        self.api_key = api_key.strip()
        self._releases_by_group = {}
        self._group_budget = {}

    def fetch(self, releases: Iterable[dict[str, Any]], completed: CompletionCallback) -> None:
        """Request each relevant artist and map albums back to release groups."""
        release_list = list(releases)
        self._releases_by_group = {}
        artist_groups = {}
        for release in release_list:
            group_id = _release_group_id(release)
            if group_id:
                self._releases_by_group.setdefault(group_id, []).append(release)
                shortlist_groups = release.get("_preferred_cover_art_groups", ())
                for artist_id in _artist_ids(release):
                    artist_groups.setdefault(artist_id, set()).update(shortlist_groups)
        self._group_budget = {
            group: 3
            for groups in artist_groups.values()
            for group in groups
        }
        artists = []
        for artist_id in sorted(artist_groups):
            available = [
                group for group in artist_groups[artist_id] if self._group_budget.get(group, 0) > 0
            ]
            if not available:
                continue
            charged_group = max(available, key=lambda value: (self._group_budget[value], str(value)))
            self._group_budget[charged_group] -= 1
            artists.append((artist_id, charged_group))
        self._start(len(artists), completed)
        for artist_id, charged_group in artists:
            self._request_artist(artist_id, charged_group, personal=False)

    def _request_artist(self, artist_id: str, group: str, personal: bool) -> None:
        """Request one artist using project-key or personal-key authentication."""
        header = "client-key" if personal else "api-key"
        try:
            _get_json(
                self.webservice,
                "%s/%s" % (FANART_BASE, artist_id),
                partial(self._downloaded, artist_id, group, personal),
                {header: self.api_key},
            )
        except Exception as exc:
            self._failures.append("fanart.tv %s: %s" % (artist_id, exc))
            self._unit_finished()

    def _downloaded(self, artist_id, group, personal, data, reply, error) -> None:
        """Normalize album covers for release groups returned for one artist."""
        try:
            status = _http_status(reply)
            if error:
                if status == 401 and not personal:
                    if self._group_budget.get(group, 0) <= 0:
                        self._failures.append("fanart.tv %s: authentication failed" % artist_id)
                        return
                    self._group_budget[group] -= 1
                    self._request_artist(artist_id, group, personal=True)
                    return
                if status != 404:
                    self._failures.append("fanart.tv %s: %s" % (artist_id, _error_text(reply, error)))
                return
            albums = data.get("albums", []) if isinstance(data, dict) else []
            if isinstance(albums, dict):
                albums = [dict(value, release_group_id=key) for key, value in albums.items()]
            for album in albums:
                group_id = str(album.get("release_group_id") or album.get("id") or "")
                releases = self._releases_by_group.get(group_id, ())
                for image in album.get("albumcover") or []:
                    if not image.get("url"):
                        continue
                    candidate = ArtworkCandidate(
                        source=self.NAME,
                        image_id=str(image.get("id") or image.get("url")),
                        image_url=str(image["url"]),
                        width=positive_int(image.get("width") or image.get("size")),
                        height=positive_int(image.get("height") or image.get("size")),
                        front=True,
                        approved=True,
                        source_confidence=0.80,
                        match_confidence=0.75,
                        popularity=float(positive_int(image.get("likes")) or 0),
                        metadata=image,
                    )
                    self._candidates.extend((release, candidate) for release in releases)
        except Exception as exc:
            self._failures.append("fanart.tv %s: %s" % (artist_id, exc))
        finally:
            # A 401 project-key response schedules a personal-key retry for the
            # same logical unit; only the final response releases the barrier.
            if not (error and _http_status(reply) == 401 and not personal):
                self._unit_finished()


def discogs_release_id(release: dict[str, Any]) -> str:
    """Extract an exact Discogs release ID from MusicBrainz URL relations."""
    for relation in release.get("relations") or []:
        resource = str((relation.get("url") or {}).get("resource") or relation.get("target") or "")
        match = DISCOGS_RELEASE_PATTERN.search(resource)
        if match:
            return match.group(1)
    return ""


def _normalized_identifier(value: Any) -> str:
    """Normalize a barcode or catalogue number for exact comparisons."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _release_barcodes(release: dict[str, Any]) -> set[str]:
    """Return normalized MusicBrainz barcodes for a release."""
    values = release.get("barcode") or []
    if isinstance(values, str):
        values = [values]
    return {_normalized_identifier(value) for value in values if _normalized_identifier(value)}


def _release_catalog_numbers(release: dict[str, Any]) -> set[str]:
    """Return normalized catalogue numbers from MusicBrainz label information."""
    return {
        _normalized_identifier(item.get("catalog-number"))
        for item in (release.get("label-info") or [])
        if _normalized_identifier(item.get("catalog-number"))
    }


def discogs_match_confidence(release: dict[str, Any], result: dict[str, Any]) -> float:
    """Score a Discogs search result using strong edition identifiers only."""
    expected_barcodes = _release_barcodes(release)
    result_barcodes = result.get("barcode") or []
    if isinstance(result_barcodes, str):
        result_barcodes = [result_barcodes]
    actual_barcodes = {_normalized_identifier(value) for value in result_barcodes}
    if expected_barcodes.intersection(actual_barcodes):
        return 0.95

    expected_catalog = _release_catalog_numbers(release)
    actual_catalog = {_normalized_identifier(result.get("catno"))}
    if expected_catalog.intersection(actual_catalog):
        return 0.85
    return 0.0


class DiscogsSource(_FanOutSource):
    """Retrieve Discogs images using exact or strong edition identifiers."""

    NAME = "discogs"

    def __init__(self, webservice, api_key: str):
        """Initialize the adapter with a Discogs personal access token."""
        super().__init__(webservice)
        self.api_key = api_key.strip()
        self._group_budget = {}

    def fetch(self, releases: Iterable[dict[str, Any]], completed: CompletionCallback) -> None:
        """Resolve exact relations first, then identifier-based search matches."""
        release_list = list(releases)
        groups = {
            group
            for release in release_list
            for group in release.get("_preferred_cover_art_groups", ())
        }
        self._group_budget = {group: 3 for group in groups}
        linked = [(release, discogs_release_id(release)) for release in release_list]
        linked = [(release, release_id) for release, release_id in linked if release_id]
        linked_release_ids = {release.get("id") for release, _discogs_id in linked}
        searchable = [
            release
            for release in release_list
            if release.get("id") not in linked_release_ids
            and (_release_barcodes(release) or _release_catalog_numbers(release))
        ]
        # Keep speculative requests bounded under Discogs' comparatively strict
        # API rate limits, preferring releases with a barcode over catalogue-only
        # matches and then stable MusicBrainz identifiers.
        searchable.sort(
            key=lambda release: (
                0 if _release_barcodes(release) else 1,
                str(release.get("id") or ""),
            )
        )
        tasks = []
        for release, release_id in linked:
            group = self._reserve_group_call(release)
            if group:
                tasks.append(("release", release, release_id, group))
        for release in searchable:
            group = self._reserve_group_call(release)
            if group:
                tasks.append(("search", release, "", group))

        self._start(len(tasks), completed)
        for task, release, release_id, group in tasks:
            if task == "release":
                self._fetch_release(release, release_id, 1.0, group)
            else:
                self._search_release(release, group)

    def _reserve_group_call(self, release: dict[str, Any]) -> str:
        """Reserve one HTTP call from the best available release-group budget."""
        groups = release.get("_preferred_cover_art_groups", ())
        available = [group for group in groups if self._group_budget.get(group, 0) > 0]
        if not available:
            return ""
        group = max(available, key=lambda value: (self._group_budget[value], str(value)))
        self._group_budget[group] -= 1
        return group

    def _reserve_specific_group_call(self, group: str) -> bool:
        """Reserve a follow-up call from the same group's remaining budget."""
        if self._group_budget.get(group, 0) <= 0:
            return False
        self._group_budget[group] -= 1
        return True

    def _headers(self) -> dict[str, str]:
        """Return authenticated Discogs headers without exposing the token in URLs."""
        return {
            "Authorization": "Discogs token=%s" % self.api_key,
            "User-Agent": "PreferredCoverArtPicardPlugin/0.6",
        }

    def _search_release(self, release: dict[str, Any], group: str) -> None:
        """Search Discogs by one strong identifier for a MusicBrainz release."""
        barcodes = sorted(_release_barcodes(release))
        catalogue_numbers = sorted(_release_catalog_numbers(release))
        query = {"type": "release", "per_page": "10"}
        if barcodes:
            query["barcode"] = barcodes[0]
        else:
            query["catno"] = catalogue_numbers[0]
        try:
            _get_json(
                self.webservice,
                "%s/database/search?%s" % (DISCOGS_BASE, urlencode(query)),
                partial(self._search_downloaded, release, group),
                self._headers(),
            )
        except Exception as exc:
            self._failures.append("Discogs search %s: %s" % (release.get("id") or "", exc))
            self._unit_finished()

    def _search_downloaded(self, release, group, data, reply, error) -> None:
        """Select the strongest search result and continue with its release details."""
        if error:
            self._failures.append(
                "Discogs search %s: %s" % (release.get("id") or "", _error_text(reply, error))
            )
            self._unit_finished()
            return
        results = data.get("results", []) if isinstance(data, dict) else []
        ranked = sorted(
            (
                (discogs_match_confidence(release, result), result)
                for result in results
                if result.get("id")
            ),
            key=lambda item: (-item[0], str(item[1].get("id"))),
        )
        if not ranked or ranked[0][0] < 0.80:
            self._unit_finished()
            return
        confidence, result = ranked[0]
        if not self._reserve_specific_group_call(group):
            self._unit_finished()
            return
        self._fetch_release(release, str(result["id"]), confidence, group)

    def _fetch_release(self, release, release_id: str, confidence: float, group: str) -> None:
        """Request full Discogs image metadata for a resolved release ID."""
        try:
            _get_json(
                self.webservice,
                "%s/releases/%s" % (DISCOGS_BASE, release_id),
                partial(self._downloaded, release, release_id, confidence),
                self._headers(),
            )
        except Exception as exc:
            self._failures.append("Discogs %s: %s" % (release_id, exc))
            self._unit_finished()

    def _downloaded(self, release, release_id, confidence, data, reply, error) -> None:
        """Normalize primary Discogs images from one exact release match."""
        try:
            if error:
                self._failures.append("Discogs %s: %s" % (release_id, _error_text(reply, error)))
                return
            images = data.get("images", []) if isinstance(data, dict) else []
            primary = [image for image in images if str(image.get("type") or "").casefold() == "primary"]
            selected = primary or images[:1]
            for image in selected:
                url = image.get("uri") or image.get("resource_url")
                if not url:
                    continue
                candidate = ArtworkCandidate(
                    source=self.NAME,
                    image_id=str(image.get("id") or url),
                    image_url=str(url),
                    width=positive_int(image.get("width")),
                    height=positive_int(image.get("height")),
                    front=True,
                    approved=True,
                    source_confidence=0.90,
                    match_confidence=confidence,
                    metadata=image,
                )
                self._candidates.append((release, candidate))
        except Exception as exc:
            self._failures.append("Discogs %s: %s" % (release_id, exc))
        finally:
            self._unit_finished()
