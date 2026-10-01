"""Picard 2 integration for selecting preferred Cover Art Archive artwork.

The provider coordinates two asynchronous stages: discovering MusicBrainz
releases for the current recording, then collecting front-image metadata from
Cover Art Archive for every eligible release.  Once all requests complete, the
pure scoring module ranks the combined release/image candidates and this module
queues the winner through Picard's standard cover-art pipeline.

This file also owns the persisted plugin settings and their options-page adapter.
Network callbacks must always converge on ``_complete_provider`` so Picard's
album request counter and provider queue remain balanced.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import Optional
from urllib.parse import urlencode

from picard import config, log
from picard.coverart.image import CoverArtImage
from picard.coverart.providers import CoverArtProvider
from picard.config import BoolOption, IntOption, TextOption
from picard.const import RELEASE_PRIMARY_GROUPS, RELEASE_SECONDARY_GROUPS, VARIOUS_ARTISTS_ID
from PyQt5.QtNetwork import QNetworkRequest
from picard.ui.options import OptionsPage

from .selection import (
    choose_front_images,
    is_various_artists,
    rank_release_images,
    release_formats,
    release_types,
)
from .ui_options import Ui_PreferredCoverArtOptionsPage

MB_HOST = "musicbrainz.org"
CAA_BASE = "https://coverartarchive.org"

# The versioned key deliberately avoids a legacy QSettings value whose QString
# representation cannot be converted safely to the current serialized list.
TYPE_PRIORITY_KEY = "preferred_cover_art_release_types_v4"
SQUARE_TOLERANCE_KEY = "preferred_cover_art_square_tolerance"
PREFERRED_WIDTH_KEY = "preferred_cover_art_preferred_width"
PREFERRED_HEIGHT_KEY = "preferred_cover_art_preferred_height"
AVOID_VARIOUS_ARTISTS_KEY = "preferred_cover_art_avoid_various_artists"


def _debug_logs_enabled():
    """Return whether Picard 2.13 currently accepts debug-level records."""
    return log.get_effective_level() <= logging.DEBUG


def _picard_release_types():
    """Return Picard's primary and secondary release types in native order."""
    return list(RELEASE_PRIMARY_GROUPS) + list(RELEASE_SECONDARY_GROUPS)


def _default_type_settings():
    """Build the default ordered ``(release_type, enabled)`` configuration."""
    preferred = ["Single", "EP", "Album", "Compilation", "Soundtrack"]
    all_types = _picard_release_types()
    ordered = [value for value in preferred if value in all_types]
    ordered.extend(value for value in all_types if value not in ordered)
    return [(value, value in preferred) for value in ordered]


def _configured_type_settings(value):
    """Deserialize and validate persisted release-type settings.

    Args:
        value: JSON text or an already-decoded sequence supplied by Picard.

    Returns:
        A non-empty list of ``(name, enabled)`` pairs.  Malformed or obsolete
        values fall back to the current defaults.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return _default_type_settings()
    if isinstance(value, (list, tuple)):
        valid = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                valid.append((str(item[0]), bool(item[1])))
        if valid:
            return valid
    return _default_type_settings()


class PreferredCoverArtOptionsPage(OptionsPage):
    """Adapt persisted Picard settings to the plugin's Qt options form."""

    NAME = "preferred_cover_art"
    TITLE = "Preferred Cover Art"
    PARENT = "plugins"
    options = [
        TextOption("setting", TYPE_PRIORITY_KEY, json.dumps(_default_type_settings())),
        IntOption("setting", SQUARE_TOLERANCE_KEY, 10),
        IntOption("setting", PREFERRED_WIDTH_KEY, 1200),
        IntOption("setting", PREFERRED_HEIGHT_KEY, 1200),
        BoolOption("setting", AVOID_VARIOUS_ARTISTS_KEY, True),
    ]

    def __init__(self, parent=None):
        """Initialize widgets and connect release-type ordering controls."""
        super(PreferredCoverArtOptionsPage, self).__init__(parent)
        self.ui = Ui_PreferredCoverArtOptionsPage()
        self.ui.setupUi(self)
        self.ui.move_up.clicked.connect(self._move_up)
        self.ui.move_down.clicked.connect(self._move_down)

    def _move_up(self, checked=False):
        """Move the selected release type one position toward higher priority."""
        self.ui.move_selected(-1)

    def _move_down(self, checked=False):
        """Move the selected release type one position toward lower priority."""
        self.ui.move_selected(1)

    def load(self):
        """Populate controls from settings while incorporating new Picard types."""
        settings = _configured_type_settings(config.setting[TYPE_PRIORITY_KEY])
        saved = dict(settings)
        saved_order = [value for value, _enabled in settings]
        all_types = _picard_release_types()
        ordered = [value for value in saved_order if value in all_types]
        # Append types introduced by newer Picard versions without disturbing
        # the user's saved ordering for types that still exist.
        ordered.extend(value for value in all_types if value not in ordered)
        self.ui.release_types.clear()
        self.ui.set_release_types(ordered, saved)
        self.ui.square_tolerance.setValue(config.setting[SQUARE_TOLERANCE_KEY])
        self.ui.preferred_width.setValue(config.setting[PREFERRED_WIDTH_KEY])
        self.ui.preferred_height.setValue(config.setting[PREFERRED_HEIGHT_KEY])
        self.ui.avoid_various_artists.setChecked(config.setting[AVOID_VARIOUS_ARTISTS_KEY])

    def save(self):
        """Persist the current scoring preferences through Picard's config API."""
        config.setting[TYPE_PRIORITY_KEY] = json.dumps(self.ui.release_type_settings())
        config.setting[SQUARE_TOLERANCE_KEY] = self.ui.square_tolerance.value()
        config.setting[PREFERRED_WIDTH_KEY] = self.ui.preferred_width.value()
        config.setting[PREFERRED_HEIGHT_KEY] = self.ui.preferred_height.value()
        config.setting[AVOID_VARIOUS_ARTISTS_KEY] = self.ui.avoid_various_artists.isChecked()


class PreferredCoverArtProvider(CoverArtProvider):
    """Asynchronously choose CAA artwork for the current recording.

    The instance owns one logical request chain.  ``_caa_pending`` acts as a
    fan-out barrier for per-release CAA calls, while ``_provider_request_active``
    guards exactly-once release of Picard's manually retained request slot.
    """

    NAME = "Preferred Cover Art"
    TITLE = "Preferred Cover Art"

    def enabled(self):
        """Return whether the provider is enabled and has a usable recording MBID."""
        return bool(CoverArtProvider.enabled(self) and self._recording_id())

    def _recording_id(self) -> Optional[str]:
        """Resolve the recording MBID from metadata or the loaded release tracks."""
        metadata_id = (
            self.metadata.get("musicbrainz_recordingid")
            or self.metadata.get("musicbrainz_trackid")
            or None
        )
        if metadata_id:
            return metadata_id
        for medium in (self.release or {}).get("media", []):
            for track in medium.get("tracks", []):
                recording_id = (track.get("recording") or {}).get("id")
                if recording_id:
                    return recording_id
        return None

    def _target_length_ms(self) -> Optional[int]:
        """Resolve the target recording duration in milliseconds when available."""
        for key in ("~length", "length"):
            raw = self.metadata.get(key)
            if raw is None:
                continue
            try:
                value = int(float(raw))
                # Picard commonly exposes lengths in milliseconds. If a small
                # value is encountered, treat it as seconds defensively.
                return value * 1000 if 0 < value < 10000 else value
            except (TypeError, ValueError):
                continue
        recording_id = self._recording_id()
        for medium in (self.release or {}).get("media", []):
            for track in medium.get("tracks", []):
                if (track.get("recording") or {}).get("id") != recording_id:
                    continue
                length = track.get("length")
                if isinstance(length, int) and length >= 0:
                    return length
        return None

    def queue_images(self):
        """Start release discovery and retain Picard until the request chain ends.

        Returns:
            ``FINISHED`` when no recording can be resolved; otherwise ``WAIT``
            while MusicBrainz and Cover Art Archive callbacks run.
        """
        recording_id = self._recording_id()
        if not recording_id:
            return self.FINISHED

        query = urlencode({
            "recording": recording_id,
            "inc": "release-groups+media+recordings",
            "limit": "100",
            "fmt": "json",
        })
        url = f"https://{MB_HOST}/ws/2/release?{query}"
        if _debug_logs_enabled():
            log.debug("Preferred Cover Art: requesting all candidate releases: %s", url)

        # Picard can finalize an album as soon as its request counter reaches
        # zero.  Keep one request pending for the complete MB -> CAA lookup
        # chain, otherwise _new_tracks can be deleted before the selected
        # image has finished downloading.
        self.album._requests += 1
        self._provider_request_active = True
        try:
            self.album.tagger.webservice.get_url(
                url=url,
                handler=self._releases_downloaded,
                parse_response_type="json",
                priority=True,
                important=False,
            )
        except Exception:
            self._provider_request_active = False
            self.album._requests -= 1
            raise
        return self.WAIT

    def _releases_downloaded(self, data, http, error):
        """Process MusicBrainz releases and fan out CAA metadata requests.

        Args:
            data: Parsed MusicBrainz JSON response.
            http: Picard network reply object.
            error: Network error indicator supplied by Picard.
        """
        try:
            if error:
                self.error("MusicBrainz release browse failed: %s" % http.errorString())
                self._complete_provider()
                return
            releases = data.get("releases", []) if isinstance(data, dict) else []
            debug_logs = _debug_logs_enabled()
            if debug_logs:
                log.debug(
                    "Preferred Cover Art: initial query returned %d candidate releases for recording %s",
                    len(releases),
                    self._recording_id() or "",
                )
                for index, release in enumerate(releases, 1):
                    log.debug(
                        "Preferred Cover Art: candidate %d/%d: id=%s title=%r "
                        "types=%s country=%s formats=%s status=%s date=%s",
                        index,
                        len(releases),
                        release.get("id") or "",
                        release.get("title") or "",
                        ", ".join(release_types(release)) or "Other",
                        release.get("country") or "",
                        ", ".join(release_formats(release)) or "",
                        release.get("status") or "",
                        release.get("date") or "",
                    )

                type_counts = {}
                for release in releases:
                    types = release_types(release) or ("Other",)
                    for release_type in types:
                        type_counts[release_type] = type_counts.get(release_type, 0) + 1
                for release_type in sorted(type_counts, key=str.casefold):
                    log.debug(
                        "Preferred Cover Art: all %s candidates: %d",
                        release_type,
                        type_counts[release_type],
                    )

            if config.setting[AVOID_VARIOUS_ARTISTS_KEY]:
                va_name = config.setting["va_name"]
                filtered = [
                    release for release in releases
                    if not is_various_artists(release, VARIOUS_ARTISTS_ID, va_name)
                ]
                if debug_logs:
                    log.debug(
                        "Preferred Cover Art: hard filter [Avoid Various Artists]: %d -> %d candidates",
                        len(releases),
                        len(filtered),
                    )
                releases = filtered

            releases = [release for release in releases if release.get("id")]
            if not releases:
                if debug_logs:
                    log.debug("Preferred Cover Art: no release candidates remain")
                self._complete_provider()
                return

            # One counter covers both successful callbacks and synchronous
            # scheduling failures, allowing a single completion barrier.
            self._caa_pending = len(releases)
            self._caa_results = []
            self._caa_failures = []
            for release in releases:
                release_id = release["id"]
                if debug_logs:
                    log.debug("Preferred Cover Art: requesting all CAA images for release %s", release_id)
                try:
                    self.album.tagger.webservice.get_url(
                        url=f"{CAA_BASE}/release/{release_id}/",
                        handler=partial(self._caa_candidate_downloaded, release),
                        parse_response_type="json",
                        priority=True,
                        important=False,
                    )
                except Exception as exc:
                    self._caa_failures.append("%s: %s" % (release_id, exc))
                    self._caa_pending -= 1
            if self._caa_pending == 0:
                self._finish_caa_collection()
        except Exception as exc:
            self.error("Release selection failed: %s" % exc)
            self._complete_provider()

    @staticmethod
    def _http_status(http):
        """Extract an integer HTTP status from a Qt network reply, if possible."""
        try:
            value = http.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            return int(value) if value is not None else None
        except (AttributeError, TypeError, ValueError):
            return None

    def _caa_candidate_downloaded(self, release, data, http, error):
        """Collect front images returned for one release.

        A 404 is a valid “no cover art” result.  Other CAA failures invalidate
        the complete ranking because scoring a partial candidate set could pick
        a result that would not have won had all requests succeeded.
        """
        release_id = release.get("id") or ""
        try:
            status = self._http_status(http)
            if error and status != 404:
                message = http.errorString() if http is not None else str(error)
                self._caa_failures.append("%s: %s" % (release_id, message))
                log.error(
                    "Preferred Cover Art: transient CAA error for release %s; 0 images: %s",
                    release_id,
                    message,
                )
                return
            images = data.get("images", []) if isinstance(data, dict) else []
            debug_logs = _debug_logs_enabled()
            if debug_logs:
                log.debug(
                    "Preferred Cover Art: CAA release %s returned %d image(s)",
                    release_id,
                    len(images),
                )
                for index, candidate in enumerate(images, 1):
                    log.debug(
                        "Preferred Cover Art: CAA release %s image %d/%d: id=%s types=%s approved=%s size=%sx%s url=%s",
                        release_id,
                        index,
                        len(images),
                        candidate.get("id") or "",
                        ", ".join(candidate.get("types") or []),
                        candidate.get("approved"),
                        candidate.get("width") or "?",
                        candidate.get("height") or "?",
                        candidate.get("image") or "",
                    )
            fronts = choose_front_images(images)
            if debug_logs:
                log.debug(
                    "Preferred Cover Art: hard filter [front image] for release %s: %d -> %d images",
                    release_id,
                    len(images),
                    len(fronts),
                )
            self._caa_results.extend((release, image) for image in fronts)
        except Exception as exc:
            self._caa_failures.append("%s: %s" % (release_id, exc))
        finally:
            # Every scheduled request reaches this barrier exactly once,
            # including parsing and logging failures inside the callback.
            self._caa_pending -= 1
            if self._caa_pending == 0:
                self._finish_caa_collection()

    def _finish_caa_collection(self):
        """Rank the complete candidate set and enqueue its winning front image."""
        try:
            if self._caa_failures:
                self.error(
                    "Preferred Cover Art: temporary Cover Art Archive error; "
                    "0 images retrieved: %s" % "; ".join(self._caa_failures)
                )
                return
            if not self._caa_results:
                if _debug_logs_enabled():
                    log.debug("Preferred Cover Art: no candidate release has a front image")
                return

            type_settings = _configured_type_settings(config.setting[TYPE_PRIORITY_KEY])
            enabled_types = tuple(value for value, enabled in type_settings if enabled)
            ranked = rank_release_images(
                self._caa_results,
                self._recording_id() or "",
                self._target_length_ms(),
                enabled_types,
                tuple(config.setting["preferred_release_countries"]),
                tuple(config.setting["preferred_release_formats"]),
                config.setting[PREFERRED_WIDTH_KEY],
                config.setting[PREFERRED_HEIGHT_KEY],
                max(0, config.setting[SQUARE_TOLERANCE_KEY]) / 100.0,
            )
            if not ranked:
                if _debug_logs_enabled():
                    log.debug("Preferred Cover Art: no scorable release/image candidate")
                return

            debug_logs = _debug_logs_enabled()
            if debug_logs:
                for position, (release, image, scores) in enumerate(ranked, 1):
                    log.debug(
                        "Preferred Cover Art: score %d/%d release=%s image=%s total=%.3f "
                        "T=%.3f D=%.3f C=%.3f L=%.3f P=%.3f M=%.3f",
                        position,
                        len(ranked),
                        release.get("id") or "",
                        image.get("id") or image.get("image") or "",
                        scores["total"],
                        scores["release_type"],
                        scores["date"],
                        scores["cover_dimension"],
                        scores["length"],
                        scores["country"],
                        scores["medium"],
                    )

            release, image, scores = ranked[0]
            # Prefer CAA's bounded derivative to avoid downloading an oversized
            # original; fall back progressively when that derivative is absent.
            thumbnails = image.get("thumbnails") or {}
            url = thumbnails.get("1200") or thumbnails.get("large") or image.get("image")
            if not url:
                return
            cover = CoverArtImage(url, types=["front"], comment=image.get("comment") or "")
            cover.is_front = True
            self.queue_put(cover)
            if debug_logs:
                log.debug(
                    "Preferred Cover Art: selected release %s image %s with score %.3f; queued %s",
                    release.get("id") or "",
                    image.get("id") or "",
                    scores["total"],
                    url,
                )
        except Exception as exc:
            self.error("Cover art scoring failed: %s" % exc)
        finally:
            self._complete_provider()

    def _complete_provider(self):
        """Release Picard's retained request slot and advance the provider queue.

        The active flag makes cleanup idempotent across normal completion and
        multiple error paths.
        """
        if not getattr(self, "_provider_request_active", False):
            return
        self._provider_request_active = False
        self.album._requests -= 1
        self.next_in_queue()
