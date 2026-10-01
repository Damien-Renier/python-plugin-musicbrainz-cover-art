"""Unit tests for source-neutral artwork models and API adapters."""

import sys
import types
import unittest

from preferred_cover_art.artwork import ArtworkCandidate, positive_int


class _QNetworkRequest:
    """Minimal Qt request constant used by adapter error handling."""

    HttpStatusCodeAttribute = 1


class _WSRequest:
    """Capture the Picard request contract without importing Picard or Qt."""

    def __init__(self, **kwargs):
        """Record constructor arguments and initialize captured headers."""
        self.kwargs = kwargs
        self.headers = {}

    def setRawHeader(self, name, value):
        """Capture one raw HTTP header exactly as Qt would receive it."""
        self.headers[name] = value


pyqt = types.ModuleType("PyQt5")
qt_network = types.ModuleType("PyQt5.QtNetwork")
qt_network.QNetworkRequest = _QNetworkRequest
pyqt.QtNetwork = qt_network
sys.modules.setdefault("PyQt5", pyqt)
sys.modules.setdefault("PyQt5.QtNetwork", qt_network)

picard = types.ModuleType("picard")
picard_webservice = types.ModuleType("picard.webservice")
picard_webservice.WSRequest = _WSRequest
sys.modules.setdefault("picard", picard)
sys.modules.setdefault("picard.webservice", picard_webservice)

from preferred_cover_art.sources import (
    CoverArtArchiveSource,
    DiscogsSource,
    FanartTvSource,
    discogs_match_confidence,
    discogs_release_id,
)


class _WebService:
    """Record both public ``get_url`` and explicit ``WSRequest`` calls."""

    def __init__(self):
        """Initialize an empty request capture list."""
        self.calls = []

    def get_url(self, **kwargs):
        """Capture a public Picard ``get_url`` request."""
        self.calls.append(kwargs)

    def add_request(self, request):
        """Capture an explicit Picard ``WSRequest`` instance."""
        self.calls.append(request)


class _Reply:
    """Provide the minimal Qt reply API needed for status and error tests."""

    def __init__(self, status, message="error"):
        """Store one HTTP status and diagnostic string."""
        self.status = status
        self.message = message

    def attribute(self, _attribute):
        """Return the configured HTTP status for any requested attribute."""
        return self.status

    def errorString(self):
        """Return the configured network diagnostic."""
        return self.message


def _release():
    """Return a release containing identifiers needed by every adapter."""
    return {
        "id": "release-id",
        "release-group": {"id": "group-id"},
        "artist-credit": [{"artist": {"id": "artist-id"}}],
        "_preferred_cover_art_groups": ("Album",),
        "relations": [{
            "url": {"resource": "https://www.discogs.com/release/12345-Example"},
        }],
    }


class ArtworkModelTests(unittest.TestCase):
    """Verify normalization behavior shared by all adapters."""

    def test_positive_int_accepts_numeric_api_strings(self):
        """String dimensions from fanart.tv normalize to positive integers."""
        self.assertEqual(1000, positive_int("1000"))
        self.assertIsNone(positive_int(None))
        self.assertIsNone(positive_int(0))

    def test_candidate_exposes_legacy_scoring_fields(self):
        """The common model remains compatible with the established scorer."""
        candidate = ArtworkCandidate("source", "image", "https://image", width=600, height=595)
        self.assertEqual(600, candidate.get("width"))
        self.assertEqual("https://image", candidate.get("image"))


class SourceAdapterTests(unittest.TestCase):
    """Verify API-specific normalization and credential handling."""

    def test_caa_normalizes_only_front_images(self):
        """CAA retains release-exact front images and ignores back images."""
        webservice = _WebService()
        results = []
        source = CoverArtArchiveSource(webservice)
        source.fetch([_release()], lambda candidates, failures: results.append((candidates, failures)))
        handler = webservice.calls[0]["handler"]
        handler({"images": [
            {"id": 1, "image": "https://front", "front": True, "approved": True},
            {"id": 2, "image": "https://back", "front": False},
        ]}, None, 0)
        self.assertEqual(1, len(results[0][0]))
        self.assertEqual("cover_art_archive", results[0][0][0][1].source)
        self.assertEqual(1.0, results[0][0][0][1].match_confidence)

    def test_fanart_uses_private_header_and_release_group_mapping(self):
        """fanart.tv credentials stay out of URLs and albums map by release group."""
        webservice = _WebService()
        results = []
        source = FanartTvSource(webservice, "secret")
        source.fetch([_release()], lambda candidates, failures: results.append((candidates, failures)))
        request = webservice.calls[0]
        self.assertNotIn("secret", request.kwargs["url"])
        self.assertEqual(b"secret", request.headers[b"api-key"])
        request.kwargs["handler"]({"albums": [{
            "release_group_id": "group-id",
            "albumcover": [{"id": "f1", "url": "https://fanart", "width": "1000", "height": "1000"}],
        }]}, None, 0)
        candidate = results[0][0][0][1]
        self.assertEqual((1000, 1000), (candidate.width, candidate.height))
        self.assertEqual(0.75, candidate.match_confidence)

    def test_fanart_retries_a_project_key_as_a_personal_key(self):
        """A 401 transparently retries the single configured key as ``client-key``."""
        webservice = _WebService()
        results = []
        source = FanartTvSource(webservice, "personal")
        source.fetch([_release()], lambda candidates, failures: results.append((candidates, failures)))
        webservice.calls[0].kwargs["handler"]({}, _Reply(401), 1)
        self.assertEqual(2, len(webservice.calls))
        self.assertEqual(b"personal", webservice.calls[1].headers[b"client-key"])
        webservice.calls[1].kwargs["handler"]({"albums": []}, _Reply(200), 0)
        self.assertEqual([([], [])], results)

    def test_fanart_limits_http_calls_to_three_per_type(self):
        """Four artists in one selected type schedule only three fanart.tv calls."""
        releases = []
        for index in range(4):
            candidate = _release()
            candidate["id"] = "release-%d" % index
            candidate["release-group"] = {"id": "group-%d" % index}
            candidate["artist-credit"] = [{"artist": {"id": "artist-%d" % index}}]
            releases.append(candidate)
        webservice = _WebService()
        FanartTvSource(webservice, "key").fetch(releases, lambda _candidates, _failures: None)
        self.assertEqual(3, len(webservice.calls))

    def test_fanart_uses_the_configured_per_type_call_limit(self):
        """The options-page value replaces fanart.tv's historical fixed limit."""
        releases = []
        for index in range(3):
            candidate = _release()
            candidate["id"] = "release-%d" % index
            candidate["release-group"] = {"id": "group-%d" % index}
            candidate["artist-credit"] = [{"artist": {"id": "artist-%d" % index}}]
            releases.append(candidate)
        webservice = _WebService()
        FanartTvSource(webservice, "key", max_calls_per_type=1).fetch(
            releases,
            lambda _candidates, _failures: None,
        )
        self.assertEqual(1, len(webservice.calls))

    def test_discogs_requires_exact_musicbrainz_relation(self):
        """Discogs IDs come from explicit release relations, never title guessing."""
        self.assertEqual("12345", discogs_release_id(_release()))
        self.assertEqual("", discogs_release_id({"relations": []}))

    def test_discogs_matches_only_strong_edition_identifiers(self):
        """Barcode and catalogue matches qualify; title-only matches do not."""
        release = {
            "barcode": "7 24384-84952 8",
            "label-info": [{"catalog-number": "ABC-123"}],
        }
        self.assertEqual(0.95, discogs_match_confidence(release, {"barcode": ["724384849528"]}))
        self.assertEqual(0.85, discogs_match_confidence(release, {"catno": "ABC 123"}))
        self.assertEqual(0.0, discogs_match_confidence(release, {"title": "Artist - Album"}))

    def test_discogs_uses_private_authorization_header(self):
        """Discogs tokens stay out of URLs and primary images retain dimensions."""
        webservice = _WebService()
        results = []
        source = DiscogsSource(webservice, "token")
        source.fetch([_release()], lambda candidates, failures: results.append((candidates, failures)))
        request = webservice.calls[0]
        self.assertNotIn("token", request.kwargs["url"])
        self.assertEqual(b"Discogs token=token", request.headers[b"Authorization"])
        request.kwargs["handler"]({"images": [{
            "type": "primary",
            "uri": "https://discogs",
            "width": 1408,
            "height": 1411,
        }]}, None, 0)
        candidate = results[0][0][0][1]
        self.assertEqual((1408, 1411), (candidate.width, candidate.height))
        self.assertEqual(1.0, candidate.match_confidence)

    def test_discogs_limits_http_calls_to_three_per_type(self):
        """Four exact releases in one group schedule only three Discogs calls."""
        releases = []
        for index in range(4):
            candidate = _release()
            candidate["id"] = "release-%d" % index
            candidate["relations"] = [{
                "url": {"resource": "https://www.discogs.com/release/%d-Example" % (100 + index)},
            }]
            releases.append(candidate)
        webservice = _WebService()
        DiscogsSource(webservice, "token").fetch(releases, lambda _candidates, _failures: None)
        self.assertEqual(3, len(webservice.calls))

    def test_discogs_uses_the_configured_per_type_call_limit(self):
        """The options-page value replaces Discogs' historical fixed limit."""
        releases = []
        for index in range(3):
            candidate = _release()
            candidate["id"] = "release-%d" % index
            candidate["relations"] = [{
                "url": {"resource": "https://www.discogs.com/release/%d-Example" % (100 + index)},
            }]
            releases.append(candidate)
        webservice = _WebService()
        DiscogsSource(webservice, "token", max_calls_per_type=2).fetch(
            releases,
            lambda _candidates, _failures: None,
        )
        self.assertEqual(2, len(webservice.calls))


if __name__ == "__main__":
    unittest.main()
