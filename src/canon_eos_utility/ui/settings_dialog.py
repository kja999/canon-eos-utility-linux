"""Settings dialog: file-naming templates (photo + optional video), download
folders, and auto-connect."""

from __future__ import annotations

import datetime
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, config_path
from ..constants import ObjectFormat
from ..metadata import MediaMetadata
from ..models import CameraObject
from ..naming import (
    AVAILABLE_VARIABLES,
    DEFAULT_TEMPLATE,
    DEFAULT_VIDEO_TEMPLATE,
    build_context,
    render_target_path,
)


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(680, 720)
        self._config = config

        layout = QVBoxLayout(self)

        # -- photos --------------------------------------------------------
        photo_group = QGroupBox("Photos")
        photo_layout = QVBoxLayout(photo_group)

        photo_layout.addWidget(QLabel("Photo folder:"))
        photo_layout.addWidget(
            self._directory_row(config.download_directory, "Photo folder", "directory_edit")
        )

        photo_layout.addWidget(QLabel("Naming template:"))
        self.template_edit = QLineEdit(config.filename_template)
        self.template_edit.textChanged.connect(self._update_preview)
        photo_layout.addWidget(self.template_edit)
        photo_reset = QPushButton("Reset to default")
        photo_reset.clicked.connect(lambda: self.template_edit.setText(DEFAULT_TEMPLATE))
        photo_layout.addWidget(photo_reset, alignment=Qt.AlignRight)

        photo_layout.addWidget(QLabel("Preview:"))
        self.photo_preview_label = _preview_label()
        photo_layout.addWidget(self.photo_preview_label)
        layout.addWidget(photo_group)

        # -- videos --------------------------------------------------------
        video_group = QGroupBox("Videos")
        video_layout = QVBoxLayout(video_group)

        self.video_check = QCheckBox("Use a different directory & template for video files")
        self.video_check.setChecked(config.use_video_template)
        self.video_check.toggled.connect(self._update_preview)
        video_layout.addWidget(self.video_check)

        video_layout.addWidget(QLabel("Video folder:"))
        video_layout.addWidget(
            self._directory_row(
                config.video_download_directory,
                "Video folder",
                "video_directory_edit",
                placeholder="Leave empty to use the photo folder",
            )
        )

        video_layout.addWidget(QLabel("Naming template:"))
        self.video_template_edit = QLineEdit(config.video_filename_template)
        self.video_template_edit.textChanged.connect(self._update_preview)
        video_layout.addWidget(self.video_template_edit)
        video_reset = QPushButton("Reset to default")
        video_reset.clicked.connect(
            lambda: self.video_template_edit.setText(DEFAULT_VIDEO_TEMPLATE)
        )
        video_layout.addWidget(video_reset, alignment=Qt.AlignRight)

        video_layout.addWidget(QLabel("Preview:"))
        self.video_preview_label = _preview_label()
        video_layout.addWidget(self.video_preview_label)
        layout.addWidget(video_group)

        # -- variables reference ------------------------------------------
        variables_group = QGroupBox("Available variables")
        variables_layout = QVBoxLayout(variables_group)
        variable_list = QListWidget()
        variable_list.setMaximumHeight(140)
        for name, description in AVAILABLE_VARIABLES:
            QListWidgetItem(f"${{{name}}}  —  {description}", variable_list)
        variables_layout.addWidget(variable_list)
        layout.addWidget(variables_group)

        # -- options -------------------------------------------------------
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        self.auto_connect_check = QCheckBox("Connect automatically when the camera is discovered")
        self.auto_connect_check.setChecked(config.auto_connect)
        options_layout.addWidget(self.auto_connect_check)

        self.set_times_check = QCheckBox("Set downloaded files' dates to the capture time")
        self.set_times_check.setChecked(config.set_file_times)
        options_layout.addWidget(self.set_times_check)

        self.always_overwrite_check = QCheckBox("Always overwrite existing files")
        self.always_overwrite_check.setChecked(config.always_overwrite)
        self.always_overwrite_check.setToolTip(
            "Skip the 'File exists. Overwrite?' prompt and replace files automatically"
        )
        options_layout.addWidget(self.always_overwrite_check)

        self.delete_after_check = QCheckBox("Always delete files after download")
        self.delete_after_check.setChecked(config.delete_after_download)
        self.delete_after_check.setToolTip(
            "Delete each file from the camera once it is downloaded and verified"
        )
        options_layout.addWidget(self.delete_after_check)

        accent_form = QFormLayout()
        self.accent_edit = QLineEdit(config.accent_color)
        self.accent_edit.setPlaceholderText("auto, or a colour like #9141ac")
        self.accent_edit.setToolTip("Accent colour. 'auto' follows the system/GTK theme highlight.")
        accent_form.addRow("Accent colour:", self.accent_edit)
        options_layout.addLayout(accent_form)
        layout.addWidget(options_group)

        layout.addWidget(
            QLabel(f"Configuration file: <code>{config_path()}</code> (editable by hand too)")
        )

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setProperty("class", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    def _directory_row(
        self,
        value: str,
        title: str,
        attr: str,
        placeholder: str = "",
    ) -> QWidget:
        """A folder edit + Browse button; stores the edit on ``self.<attr>``."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(self._update_preview)
        row.addWidget(edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse(edit, title))
        row.addWidget(browse)
        widget = QWidget()
        widget.setLayout(row)
        setattr(self, attr, edit)
        return widget

    # -- helpers -----------------------------------------------------------

    def result_config(self) -> AppConfig:
        return AppConfig(
            filename_template=self.template_edit.text().strip() or DEFAULT_TEMPLATE,
            download_directory=self.directory_edit.text().strip(),
            auto_connect=self.auto_connect_check.isChecked(),
            client_name=self._config.client_name,
            client_guid=self._config.client_guid,
            daemon_poll_interval=self._config.daemon_poll_interval,
            use_video_template=self.video_check.isChecked(),
            video_download_directory=self.video_directory_edit.text().strip(),
            video_filename_template=(
                self.video_template_edit.text().strip() or DEFAULT_VIDEO_TEMPLATE
            ),
            set_file_times=self.set_times_check.isChecked(),
            always_overwrite=self.always_overwrite_check.isChecked(),
            delete_after_download=self.delete_after_check.isChecked(),
            accent_color=self.accent_edit.text().strip() or "auto",
        )

    def _browse(self, target: QLineEdit, title: str) -> None:
        directory = QFileDialog.getExistingDirectory(self, title, target.text())
        if directory:
            target.setText(directory)

    def _update_preview(self) -> None:
        photo_base = self.directory_edit.text().strip() or os.path.expanduser("~/Pictures/Canon")
        self.photo_preview_label.setText(
            _preview(self.template_edit.text(), photo_base, is_video=False)
        )

        enabled = self.video_check.isChecked()
        for widget in (
            self.video_directory_edit,
            self.video_template_edit,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self.video_preview_label.setText("(videos use the photo directory and template)")
            return
        video_base = self.video_directory_edit.text().strip() or photo_base
        self.video_preview_label.setText(
            _preview(self.video_template_edit.text(), video_base, is_video=True)
        )


def _preview_label() -> QLabel:
    label = QLabel()
    label.setObjectName("previewBox")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _preview(template: str, base: str, is_video: bool) -> str:
    try:
        target = render_target_path(
            template,
            _sample_context(is_video),
            base,
            original_extension="MP4" if is_video else "CR3",
        )
        return os.path.relpath(target, base)
    except Exception as exc:  # pragma: no cover - defensive
        return f"<invalid template: {exc}>"


def _sample_context(is_video: bool = False) -> dict:
    camera = {
        "model": "Canon EOS R5",
        "manufacturer": "Canon",
        "serial": "0859408",
        "firmware": "3-2.2.1",
        "name": "EOSR5_859408",
    }
    obj = CameraObject(
        handle=1,
        storage_id=1,
        format=int(ObjectFormat.MP4) if is_video else int(ObjectFormat.CR3),
        size=237_004_944 if is_video else 46_312_534,
        filename="246A8462.MP4" if is_video else "246A8454.CR3",
        capture_date="20260912T150605.0",
        width=3840 if is_video else 8192,
        height=2160 if is_video else 5464,
    )
    metadata = MediaMetadata(
        width=obj.width,
        height=obj.height,
        taken=datetime.datetime(2026, 9, 12, 15, 6, 5),
        make="Canon",
        model="Canon EOS R5",
        lens_model="RF24-70mm F2.8 L IS USM",
        iso=100,
        f_number=2.8,
        exposure_time=0.05,
        focal_length=56.0,
        source="cr3",
    )
    return build_context(camera, obj, metadata)
