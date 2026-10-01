"""Regression tests for deterministic Preferred Cover Art scoring.

The fixtures model only the MusicBrainz and Cover Art Archive fields consumed
by the pure selection module.  Tests emphasize scoring boundaries, fallback
behavior, and invariants that could otherwise change the selected cover.
"""

from datetime import date
import unittest

from preferred_cover_art.artwork import ArtworkCandidate
from preferred_cover_art.selection import (
    choose_front_images,
    cover_dimension_score,
    date_score,
    is_various_artists,
    length_score,
    ordered_preference_score,
    rank_release_images,
    release_type_score,
    shortlist_releases_by_type,
)


RID = "11111111-1111-4111-8111-111111111111"
VA_ID = "89ad4ac3-39f7-470e-963a-56509c546377"


def release(
    mbid,
    *,
    length=180000,
    primary="Album",
    secondary=None,
    country="GB",
    fmt="Digital Media",
    released="2020-01-01",
    artist_id="artist-id",
    artist="Artist",
):
    """Build a minimal MusicBrainz release fixture for the shared recording."""
    return {
        "id": mbid,
        "country": country,
        "date": released,
        "artist-credit": [{"artist": {"id": artist_id, "name": artist}, "name": artist}],
        "release-group": {
            "primary-type": primary,
            "secondary-types": secondary or [],
        },
        "media": [{
            "format": fmt,
            "tracks": [{"length": length, "recording": {"id": RID}}],
        }],
    }


def image(identifier, width=1200, height=1200, front=True, approved=True):
    """Build a minimal Cover Art Archive image fixture."""
    return {
        "id": identifier,
        "image": "https://example.test/%s.jpg" % identifier,
        "front": front,
        "approved": approved,
        "width": width,
        "height": height,
    }


class ScoringTests(unittest.TestCase):
    """Verify weighted components and deterministic candidate eligibility."""

    def test_five_preferences_have_linear_scores(self):
        """Preference scores decrease linearly and handle absent values."""
        ordered = ("a", "b", "c", "d", "e")
        self.assertEqual([1.0, 0.8, 0.6, 0.4, 0.2], [
            ordered_preference_score(value, ordered) for value in ordered
        ])
        self.assertEqual(0.01, ordered_preference_score("other", ordered))
        self.assertEqual(0.0, ordered_preference_score(None, ordered))

    def test_unchecked_release_type_scores_zero(self):
        """A release type outside the enabled list contributes no points."""
        candidate = release("x", primary="Broadcast")
        self.assertEqual(0.0, release_type_score(candidate, ("Single", "EP", "Album")))

    def test_secondary_type_uses_best_enabled_score(self):
        """The strongest matching primary or secondary type wins."""
        candidate = release("x", primary="Album", secondary=["Soundtrack"])
        self.assertEqual(1.0, release_type_score(candidate, ("Soundtrack", "Album")))

    def test_date_score_halves_every_five_years(self):
        """The date component follows its documented five-year half-life."""
        original = release("original", released="2000-01-01")
        later = release("later", released="2005-01-01")
        self.assertEqual(1.0, date_score(original, date(2000, 1, 1)))
        self.assertAlmostEqual(0.5, date_score(later, date(2000, 1, 1)), places=3)

    def test_length_score_halves_for_five_second_difference(self):
        """The duration component follows its documented five-second half-life."""
        candidate = release("x", length=185000)
        self.assertAlmostEqual(0.5, length_score(candidate, RID, 180000))

    def test_dimensions_saturate_at_preferred_size(self):
        """Extra resolution does not score beyond the preferred dimensions."""
        self.assertEqual(1.0, cover_dimension_score(image("large", 3000, 3000), 1200, 1200, 0.10))
        self.assertEqual(0.5, cover_dimension_score(image("small", 600, 600), 1200, 1200, 0.10))

    def test_square_600_beats_wrong_ratio_1200_by_800(self):
        """Aspect-ratio quality can outweigh additional raw resolution."""
        square = cover_dimension_score(image("square", 600, 600), 1200, 1200, 0.10)
        wrong_ratio = cover_dimension_score(image("wide", 1200, 800), 1200, 1200, 0.10)
        self.assertGreater(square, wrong_ratio)

    def test_only_front_images_are_eligible(self):
        """Non-front Cover Art Archive images are excluded."""
        images = [image("front"), image("back", front=False)]
        self.assertEqual(["front"], [item["id"] for item in choose_front_images(images)])

    def test_various_artists_detected_by_mbid_or_configured_name(self):
        """Various Artists matching supports stable identity and localized name."""
        by_id = release("id", artist_id=VA_ID, artist="Divers")
        by_name = release("name", artist="Artistes variés")
        self.assertTrue(is_various_artists(by_id, VA_ID, "Artistes variés"))
        self.assertTrue(is_various_artists(by_name, VA_ID, "Artistes variés"))

    def test_date_reference_uses_only_releases_with_images(self):
        """Image-less releases cannot shift the eligible date baseline."""
        no_cover = release("old-no-cover", released="1990-01-01")
        first_with_cover = release("first-cover", released="2000-01-01")
        later = release("later", released="2005-01-01")
        ranked = rank_release_images(
            [(first_with_cover, image("a")), (later, image("b"))],
            RID,
            180000,
            ("Album",),
            ("GB",),
            ("Digital Media",),
            1200,
            1200,
            0.10,
        )
        self.assertNotIn(no_cover, [item[0] for item in ranked])
        self.assertEqual(25.0, ranked[0][2]["date"])
        self.assertAlmostEqual(12.5, ranked[1][2]["date"], places=2)

    def test_perfect_candidate_scores_100(self):
        """A candidate matching every preference receives all 100 points."""
        candidate = release("perfect", released="2000-01-01")
        ranked = rank_release_images(
            [(candidate, image("cover"))],
            RID,
            180000,
            ("Album",),
            ("GB",),
            ("Digital Media",),
            1200,
            1200,
            0.10,
        )
        self.assertEqual(100.0, ranked[0][2]["total"])

    def test_missing_dates_score_zero_without_excluding_candidates(self):
        """Unknown dates are neutral rather than grounds for exclusion."""
        candidate = release("undated", released=None)
        ranked = rank_release_images(
            [(candidate, image("cover"))],
            RID,
            180000,
            ("Album",),
            ("GB",),
            ("Digital Media",),
            1200,
            1200,
            0.10,
        )
        self.assertEqual(0.0, ranked[0][2]["date"])

    def test_exact_source_wins_when_relevance_is_equal(self):
        """Provenance breaks equal-quality candidates toward the exact release source."""
        candidate = release("same", released="2000-01-01")
        exact = ArtworkCandidate(
            "cover_art_archive",
            "exact",
            "https://exact",
            width=1200,
            height=1200,
            approved=True,
            source_confidence=1.0,
            match_confidence=1.0,
        )
        group_match = ArtworkCandidate(
            "fanart_tv",
            "group",
            "https://group",
            width=1200,
            height=1200,
            approved=True,
            source_confidence=0.8,
            match_confidence=0.75,
        )
        ranked = rank_release_images(
            [(candidate, group_match), (candidate, exact)],
            RID,
            180000,
            ("Album",),
            ("GB",),
            ("Digital Media",),
            1200,
            1200,
            0.10,
        )
        self.assertIs(exact, ranked[0][1])
        self.assertEqual(10.0, ranked[0][2]["provenance"])

    def test_shortlist_keeps_three_releases_per_enabled_type(self):
        """Every enabled type contributes at most three independently ranked releases."""
        releases = [release("single-%d" % index, primary="Single") for index in range(4)]
        releases.extend(release("album-%d" % index, primary="Album") for index in range(4))
        shortlisted = shortlist_releases_by_type(
            releases,
            RID,
            180000,
            ("Single", "Album"),
            ("GB",),
            ("Digital Media",),
        )
        self.assertEqual(6, len(shortlisted))
        self.assertEqual(
            {"Single": 3, "Album": 3},
            {
                group: sum(group in item["_preferred_cover_art_groups"] for item in shortlisted)
                for group in ("Single", "Album")
            },
        )

    def test_shortlist_deduplicates_releases_selected_in_multiple_groups(self):
        """A multitype release can win multiple groups but produces one API candidate."""
        multitype = release("shared", primary="Album", secondary=["Soundtrack"])
        shortlisted = shortlist_releases_by_type(
            [multitype],
            RID,
            180000,
            ("Album", "Soundtrack"),
            ("GB",),
            ("Digital Media",),
        )
        self.assertEqual(1, len(shortlisted))
        self.assertEqual(("Album", "Soundtrack"), shortlisted[0]["_preferred_cover_art_groups"])

    def test_shortlist_date_outweighs_medium_preference(self):
        """The 25-point date component outweighs the four-point medium component."""
        original = release("original", released="2000-01-01", fmt="Cassette")
        preferred_medium = release("preferred-medium", released="2005-01-01", fmt="Digital Media")
        shortlisted = shortlist_releases_by_type(
            [preferred_medium, original],
            RID,
            180000,
            ("Album",),
            ("GB",),
            ("Digital Media",),
            limit_per_type=1,
        )
        self.assertEqual("original", shortlisted[0]["id"])


if __name__ == "__main__":
    unittest.main()
