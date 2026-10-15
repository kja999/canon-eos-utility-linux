from canon_eos_utility.config import AppConfig
from canon_eos_utility.naming import DEFAULT_TEMPLATE


def test_defaults_when_missing(tmp_path):
    config = AppConfig.load(str(tmp_path / "missing.toml"))
    assert config.filename_template == DEFAULT_TEMPLATE
    assert config.auto_connect is True
    assert config.download_directory == ""


def test_roundtrip(tmp_path):
    path = str(tmp_path / "config.toml")
    config = AppConfig(
        filename_template="${original.name}",
        download_directory="/tmp/photos",
        auto_connect=False,
        use_video_template=True,
        video_download_directory="/tmp/videos",
        video_filename_template="V/${original.name}",
    )
    config.save(path)

    loaded = AppConfig.load(path)
    assert loaded == config
    assert loaded.use_video_template is True
    assert loaded.video_download_directory == "/tmp/videos"


def test_video_defaults():
    config = AppConfig()
    assert config.use_video_template is False
    assert config.video_filename_template.startswith("Devices/")
    # No video directory configured falls back to the photo directory.
    assert config.resolved_video_directory() == config.resolved_download_directory()


def test_set_file_times_roundtrip(tmp_path):
    path = str(tmp_path / "config.toml")
    config = AppConfig(set_file_times=False)
    config.save(path)
    assert AppConfig.load(path).set_file_times is False
    assert AppConfig().set_file_times is True


def test_overwrite_and_delete_roundtrip(tmp_path):
    path = str(tmp_path / "config.toml")
    config = AppConfig(always_overwrite=True, delete_after_download=True)
    config.save(path)
    loaded = AppConfig.load(path)
    assert loaded.always_overwrite is True
    assert loaded.delete_after_download is True
    defaults = AppConfig()
    assert defaults.always_overwrite is False
    assert defaults.delete_after_download is False


def test_toml_escaping():
    config = AppConfig(filename_template='a"b\\c\n')
    text = config.to_toml()
    assert '\\"' in text
    assert "\\\\" in text


def test_resolved_download_directory_default():
    config = AppConfig()
    resolved = config.resolved_download_directory()
    assert resolved.endswith("Pictures/Canon")


def test_accent_color_roundtrip(tmp_path):
    path = str(tmp_path / "config.toml")
    config = AppConfig(accent_color="#9141ac")
    config.save(path)
    assert AppConfig.load(path).accent_color == "#9141ac"
    assert AppConfig().accent_color == "auto"
