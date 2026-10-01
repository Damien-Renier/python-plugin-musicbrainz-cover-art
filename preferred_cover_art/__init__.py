"""Plugin metadata and Picard 2 registration for Preferred Cover Art.

Importing this package inside Picard registers the cover-art provider and its
options page.  Importing it in a standalone Python process remains safe so the
pure scoring module can be tested without Picard or Qt installed.

Picard 2 discovers plugin ownership from the concrete class module.  The thin
classes below therefore live in the package root and delegate their behavior to
the implementation classes in ``provider.py``.
"""

PLUGIN_NAME = "Preferred Cover Art"
PLUGIN_AUTHOR = "Damien Renier"
PLUGIN_DESCRIPTION = (
    "Select front Cover Art Archive artwork from a preferred MusicBrainz "
    "release containing the current recording."
)
PLUGIN_VERSION = "0.5.3"
PLUGIN_API_VERSIONS = ["2.0", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7"]
PLUGIN_LICENSE = "MIT"
PLUGIN_LICENSE_URL = "https://opensource.org/licenses/MIT"

# Only the absence of Picard itself is optional.  An import failure from one of
# Picard's own dependencies must still surface rather than silently disabling
# registration and concealing a broken runtime installation.
try:
    from picard.coverart.providers import register_cover_art_provider
    from picard.ui.options import register_options_page
except ModuleNotFoundError as exc:
    if exc.name != "picard":
        raise
else:
    from picard.coverart.providers import CoverArtProvider
    from picard.ui.options import OptionsPage

    from .provider import (
        PreferredCoverArtOptionsPage as _PreferredCoverArtOptionsPage,
        PreferredCoverArtProvider as _PreferredCoverArtProvider,
    )
    from .ui_options import Ui_PreferredCoverArtOptionsPage

    # Picard 2 determines ownership from the module of the registered class.
    # Define the extension classes directly in the package root and inherit
    # directly from Picard's Qt classes. The implementation methods remain in
    # provider.py, but no intermediate QWidget-derived class is registered.
    class PreferredCoverArtProvider(CoverArtProvider):
        """Picard-owned facade delegating provider behavior to its implementation."""

        enabled = _PreferredCoverArtProvider.enabled
        _recording_id = _PreferredCoverArtProvider._recording_id
        _target_length_ms = _PreferredCoverArtProvider._target_length_ms
        queue_images = _PreferredCoverArtProvider.queue_images
        _releases_downloaded = _PreferredCoverArtProvider._releases_downloaded
        _http_status = staticmethod(_PreferredCoverArtProvider._http_status)
        _caa_candidate_downloaded = _PreferredCoverArtProvider._caa_candidate_downloaded
        _finish_caa_collection = _PreferredCoverArtProvider._finish_caa_collection
        _complete_provider = _PreferredCoverArtProvider._complete_provider

        NAME = _PreferredCoverArtProvider.NAME
        TITLE = _PreferredCoverArtProvider.TITLE


    class PreferredCoverArtOptionsPage(OptionsPage):
        """Picard-owned facade for the Preferred Cover Art configuration page."""

        def __init__(self, parent=None):
            """Build the UI while preserving direct ``OptionsPage`` inheritance."""
            super(PreferredCoverArtOptionsPage, self).__init__(parent)
            self.ui = Ui_PreferredCoverArtOptionsPage()
            self.ui.setupUi(self)
            self.ui.move_up.clicked.connect(self._move_up)
            self.ui.move_down.clicked.connect(self._move_down)

        _move_up = _PreferredCoverArtOptionsPage._move_up
        _move_down = _PreferredCoverArtOptionsPage._move_down
        load = _PreferredCoverArtOptionsPage.load
        save = _PreferredCoverArtOptionsPage.save

        NAME = _PreferredCoverArtOptionsPage.NAME
        TITLE = _PreferredCoverArtOptionsPage.TITLE
        PARENT = _PreferredCoverArtOptionsPage.PARENT
        options = _PreferredCoverArtOptionsPage.options

    register_cover_art_provider(PreferredCoverArtProvider)
    register_options_page(PreferredCoverArtOptionsPage)


# Picard 3 migration note (keep disabled until Picard 3 becomes the target):
#
# Picard 3 obtains the metadata above from MANIFEST.toml and replaces the
# module-level registration with this entry point:
#
# def enable(api) -> None:
#     from .provider_v3 import PreferredCoverArtProviderV3
#     api.register_cover_art_provider(PreferredCoverArtProviderV3)
