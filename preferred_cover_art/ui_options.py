"""Programmatic PyQt5 form for the Preferred Cover Art options page.

The form contains presentation and widget-state logic only.  Picard setting
serialization is intentionally handled by ``PreferredCoverArtOptionsPage`` in
``provider.py`` so this UI remains a small, replaceable view layer.
"""

from PyQt5 import QtCore, QtWidgets


class Ui_PreferredCoverArtOptionsPage:
    """Construct and expose widgets used to configure candidate scoring."""

    def setupUi(self, page):
        """Build the options-page widget hierarchy on ``page``."""
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(12)

        various_group = QtWidgets.QGroupBox("Various Artists", page)
        various_layout = QtWidgets.QVBoxLayout(various_group)
        self.avoid_various_artists = QtWidgets.QCheckBox(
            "Avoid releases credited to Picard's configured Various Artists name",
            various_group,
        )
        various_layout.addWidget(self.avoid_various_artists)
        layout.addWidget(various_group)

        dimensions_group = QtWidgets.QGroupBox("Cover dimensions and ratio", page)
        dimensions_layout = QtWidgets.QFormLayout(dimensions_group)
        dimensions_layout.setHorizontalSpacing(24)
        dimensions_layout.setVerticalSpacing(12)
        dimensions_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)

        dimensions_fields = QtWidgets.QHBoxLayout()
        dimensions_fields.setSpacing(10)
        self.preferred_width = QtWidgets.QSpinBox(dimensions_group)
        self.preferred_width.setRange(1, 10000)
        self.preferred_width.setSuffix(" px")
        self.preferred_width.setMinimumWidth(110)
        dimensions_fields.addWidget(self.preferred_width)
        dimensions_fields.addWidget(QtWidgets.QLabel("×", dimensions_group))
        self.preferred_height = QtWidgets.QSpinBox(dimensions_group)
        self.preferred_height.setRange(1, 10000)
        self.preferred_height.setSuffix(" px")
        self.preferred_height.setMinimumWidth(110)
        dimensions_fields.addWidget(self.preferred_height)
        dimensions_fields.addStretch()
        dimensions_layout.addRow("Preferred dimensions:", dimensions_fields)

        self.square_tolerance = QtWidgets.QSpinBox(dimensions_group)
        self.square_tolerance.setRange(0, 50)
        self.square_tolerance.setSuffix(" %")
        self.square_tolerance.setMinimumWidth(110)
        dimensions_layout.addRow("Preferred ratio tolerance:", self.square_tolerance)

        self.number_of_covers = QtWidgets.QSpinBox(dimensions_group)
        self.number_of_covers.setRange(1, 10)
        self.number_of_covers.setMinimumWidth(110)
        dimensions_layout.addRow("Number of covers to return:", self.number_of_covers)
        layout.addWidget(dimensions_group)

        sources_group = QtWidgets.QGroupBox("Additional artwork sources", page)
        sources_layout = QtWidgets.QVBoxLayout(sources_group)
        sources_layout.setSpacing(10)

        discogs_group = QtWidgets.QGroupBox("Discogs", sources_group)
        discogs_layout = QtWidgets.QFormLayout(discogs_group)
        self.discogs_enabled = QtWidgets.QCheckBox("Enable Discogs", discogs_group)
        self.discogs_api_key = QtWidgets.QLineEdit(discogs_group)
        self.discogs_api_key.setPlaceholderText("Personal access token")
        self.discogs_api_key.setClearButtonEnabled(True)
        discogs_layout.addRow(self.discogs_enabled)
        discogs_layout.addRow("API key:", self.discogs_api_key)
        self.discogs_enabled.toggled.connect(self.discogs_api_key.setEnabled)
        self.discogs_api_key.setEnabled(False)
        sources_layout.addWidget(discogs_group)

        fanart_group = QtWidgets.QGroupBox("fanart.tv", sources_group)
        fanart_layout = QtWidgets.QFormLayout(fanart_group)
        self.fanart_enabled = QtWidgets.QCheckBox("Enable fanart.tv", fanart_group)
        self.fanart_api_key = QtWidgets.QLineEdit(fanart_group)
        self.fanart_api_key.setPlaceholderText("Project or personal API key")
        self.fanart_api_key.setClearButtonEnabled(True)
        fanart_layout.addRow(self.fanart_enabled)
        fanart_layout.addRow("API key:", self.fanart_api_key)
        self.fanart_enabled.toggled.connect(self.fanart_api_key.setEnabled)
        self.fanart_api_key.setEnabled(False)
        sources_layout.addWidget(fanart_group)

        layout.addWidget(sources_group)

        types_group = QtWidgets.QGroupBox("Preferred release types", page)
        types_layout = QtWidgets.QVBoxLayout(types_group)
        types_layout.setSpacing(8)

        note = QtWidgets.QLabel(
            "Checked types receive a score based on their order; unchecked types receive zero. "
            "Country and medium priorities come from Metadata > Preferred Releases.",
            types_group,
        )
        note.setWordWrap(True)
        types_layout.addWidget(note)

        list_row = QtWidgets.QHBoxLayout()
        self.release_types = QtWidgets.QListWidget(types_group)
        self.release_types.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.release_types.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.release_types.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.release_types.setMinimumHeight(300)
        list_row.addWidget(self.release_types)

        buttons = QtWidgets.QVBoxLayout()
        self.move_up = QtWidgets.QPushButton("Move up", types_group)
        self.move_down = QtWidgets.QPushButton("Move down", types_group)
        self.move_up.setFixedWidth(120)
        self.move_down.setFixedWidth(120)
        buttons.addWidget(self.move_up)
        buttons.addWidget(self.move_down)
        buttons.addStretch()
        list_row.addLayout(buttons)
        types_layout.addLayout(list_row)
        layout.addWidget(types_group)
        layout.addStretch()

    def set_release_types(self, ordered, enabled):
        """Populate the ordered, checkable release-type list.

        Args:
            ordered: Release-type names in descending preference order.
            enabled: Mapping from release-type name to checked state.
        """
        for value in ordered:
            item = QtWidgets.QListWidgetItem(value)
            item.setData(QtCore.Qt.UserRole, value)
            item.setFlags(
                item.flags()
                | QtCore.Qt.ItemIsUserCheckable
                | QtCore.Qt.ItemIsDragEnabled
            )
            item.setCheckState(
                QtCore.Qt.Checked if enabled.get(value, False) else QtCore.Qt.Unchecked
            )
            self.release_types.addItem(item)

    def release_type_settings(self):
        """Return visible release types as ordered ``(name, enabled)`` pairs."""
        return [
            (
                self.release_types.item(i).data(QtCore.Qt.UserRole),
                self.release_types.item(i).checkState() == QtCore.Qt.Checked,
            )
            for i in range(self.release_types.count())
        ]

    def move_selected(self, offset):
        """Move the selected release type by a signed row offset when valid."""
        row = self.release_types.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= self.release_types.count():
            return
        item = self.release_types.takeItem(row)
        self.release_types.insertItem(target, item)
        self.release_types.setCurrentRow(target)
