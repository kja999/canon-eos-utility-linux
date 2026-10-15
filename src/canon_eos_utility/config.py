"""User-facing configuration persisted to a TOML file.

Stored at ``$XDG_CONFIG_HOME/canon-eos-utility-linux/config.toml`` (falling back
to ``~/.config/...``) so it can be edited by hand as well as from the settings
dialog.  Deliberately Qt-free so the headless daemon can use it too.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import tomllib

from .naming import DEFAULT_TEMPLATE, DEFAULT_VIDEO_TEMPLATE


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "canon-eos-utility-linux")


def config_path() -> str:
    return os.path.join(config_dir(), "config.toml")


@dataclass
class AppConfig:
    filename_template: str = DEFAULT_TEMPLATE
    download_directory: str = ""
    auto_connect: bool = True
    client_name: str = "EOS Utility for Linux"
    #: Hex-encoded 16-byte client GUID; the pairing identity shared by the GUI
    #: and the daemon.  Empty until first use.
    client_guid: str = ""
    daemon_poll_interval: float = 5.0
    #: When enabled, videos use their own directory and naming template.
    use_video_template: bool = False
    video_download_directory: str = ""
    video_filename_template: str = DEFAULT_VIDEO_TEMPLATE
    #: When enabled, set downloaded files' timestamps to the capture time.
    set_file_times: bool = True
    #: When enabled, overwrite existing files without asking.
    always_overwrite: bool = False
    #: When enabled, delete files from the camera after they are downloaded.
    delete_after_download: bool = False
    #: Accent colour: "auto" (follow the system theme) or a hex colour.
    accent_color: str = "auto"

    @classmethod
    def load(cls, path: str | None = None) -> AppConfig:
        path = path or config_path()
        config = cls()
        if not os.path.exists(path):
            return config
        try:
            with open(path, "rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return config

        if isinstance(data.get("filename_template"), str):
            config.filename_template = data["filename_template"]
        if isinstance(data.get("download_directory"), str):
            config.download_directory = data["download_directory"]
        if isinstance(data.get("auto_connect"), bool):
            config.auto_connect = data["auto_connect"]
        if isinstance(data.get("client_name"), str):
            config.client_name = data["client_name"]
        if isinstance(data.get("client_guid"), str):
            config.client_guid = data["client_guid"]
        if isinstance(data.get("daemon_poll_interval"), (int, float)):
            config.daemon_poll_interval = float(data["daemon_poll_interval"])
        if isinstance(data.get("use_video_template"), bool):
            config.use_video_template = data["use_video_template"]
        if isinstance(data.get("video_download_directory"), str):
            config.video_download_directory = data["video_download_directory"]
        if isinstance(data.get("video_filename_template"), str):
            config.video_filename_template = data["video_filename_template"]
        if isinstance(data.get("set_file_times"), bool):
            config.set_file_times = data["set_file_times"]
        if isinstance(data.get("always_overwrite"), bool):
            config.always_overwrite = data["always_overwrite"]
        if isinstance(data.get("delete_after_download"), bool):
            config.delete_after_download = data["delete_after_download"]
        if isinstance(data.get("accent_color"), str):
            config.accent_color = data["accent_color"]
        return config

    def save(self, path: str | None = None) -> str:
        path = path or config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_toml())
        return path

    def to_toml(self) -> str:
        return (
            "# canon-eos-utility configuration\n"
            f"filename_template = {_toml_string(self.filename_template)}\n"
            f"download_directory = {_toml_string(self.download_directory)}\n"
            f"auto_connect = {'true' if self.auto_connect else 'false'}\n"
            f"client_name = {_toml_string(self.client_name)}\n"
            f"client_guid = {_toml_string(self.client_guid)}\n"
            f"daemon_poll_interval = {self.daemon_poll_interval!r}\n"
            f"use_video_template = {'true' if self.use_video_template else 'false'}\n"
            f"video_download_directory = {_toml_string(self.video_download_directory)}\n"
            f"video_filename_template = {_toml_string(self.video_filename_template)}\n"
            f"set_file_times = {'true' if self.set_file_times else 'false'}\n"
            f"always_overwrite = {'true' if self.always_overwrite else 'false'}\n"
            f"delete_after_download = {'true' if self.delete_after_download else 'false'}\n"
            f"accent_color = {_toml_string(self.accent_color)}\n"
        )

    def resolved_download_directory(self) -> str:
        directory = self.download_directory.strip()
        if directory:
            return os.path.abspath(os.path.expanduser(directory))
        return os.path.join(os.path.expanduser("~"), "Pictures", "Canon")

    def resolved_video_directory(self) -> str:
        directory = self.video_download_directory.strip()
        if directory:
            return os.path.abspath(os.path.expanduser(directory))
        return self.resolved_download_directory()


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
