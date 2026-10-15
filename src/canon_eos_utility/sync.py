"""Headless download / sync primitives (no Qt dependency).

Shared by the GUI worker and the headless daemon so file naming, resumable
transfers and metadata extraction live in exactly one place.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from .exceptions import CameraError
from .metadata import parse_ptp_datetime, read_metadata
from .naming import build_context, render_target_path

PART_SUFFIX = ".part"
PARTIAL_DIRNAME = ".canon-eos-partial"
DEFAULT_CHUNK = 1 << 20

#: What to do when the destination file already exists.
POLICY_ASK = "ask"
POLICY_OVERWRITE = "overwrite"
POLICY_SKIP = "skip"
POLICY_RENAME = "rename"  # keep both, append " (n)"


def partial_path(directory: str, filename: str) -> str:
    """Path of the resumable staging file for ``filename``."""
    staging = os.path.join(directory, PARTIAL_DIRNAME)
    os.makedirs(staging, exist_ok=True)
    return os.path.join(staging, filename + PART_SUFFIX)


def unique_target(path: str) -> str:
    """Return ``path``, or ``name (n).ext`` if it already exists."""
    if not os.path.exists(path):
        return path
    directory, filename = os.path.split(path)
    base, extension = os.path.splitext(filename)
    counter = 1
    candidate = path
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base} ({counter}){extension}")
        counter += 1
    return candidate


def resolve_target(target: str, policy: str, ask=None) -> str | None:
    """Resolve an existing destination according to ``policy``.

    Returns the path to write, or ``None`` to skip the file.  ``ask`` is a
    callable invoked for :data:`POLICY_ASK` that must return a policy string.
    """
    if not os.path.exists(target):
        return target
    decision = policy
    if decision == POLICY_ASK:
        decision = ask(target) if ask is not None else POLICY_SKIP
    if decision == POLICY_OVERWRITE:
        return target
    if decision == POLICY_RENAME:
        return unique_target(target)
    return None


def finalize_download(
    obj,
    directory: str,
    part: str,
    template: str,
    camera_context: dict,
    set_times: bool = True,
    policy: str = POLICY_RENAME,
    ask=None,
) -> str | None:
    """Read metadata, render the target name and move ``part`` into place.

    Returns the final path, or ``None`` if the file was skipped because the
    destination already existed (see :func:`resolve_target`).
    """
    metadata = read_metadata(
        part,
        fallback_datetime=parse_ptp_datetime(obj.capture_date or ""),
        fallback_size=(obj.width, obj.height),
    )
    context = build_context(camera_context, obj, metadata)
    extension = os.path.splitext(obj.filename or "")[1]
    target = render_target_path(template, context, directory, original_extension=extension)

    resolved = resolve_target(target, policy, ask)
    if resolved is None:
        try:
            os.remove(part)
        except OSError:
            pass
        return None
    target = resolved

    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(part, target)

    if set_times:
        taken = metadata.taken or parse_ptp_datetime(obj.capture_date or "")
        apply_file_time(target, taken)

    return target


def apply_file_time(path: str, when) -> None:
    """Set a file's access + modification time to ``when`` (best effort).

    Linux has no portable way to set the birth/creation time, so this sets the
    times that file managers and tools display (atime and mtime).
    """
    if when is None:
        return
    try:
        stamp = when.timestamp()
    except (AttributeError, ValueError, OSError):
        return
    try:
        os.utime(path, (stamp, stamp))
    except (OSError, OverflowError):
        pass


def output_for(obj, config) -> tuple[str, str]:
    """Return ``(base_directory, template)`` for an object.

    Videos use their own directory/template when that option is enabled; the
    check is based on the object's detected type (``obj.is_movie``).
    """
    if getattr(obj, "is_movie", False) and getattr(config, "use_video_template", False):
        return (
            config.resolved_video_directory(),
            config.video_filename_template or config.filename_template,
        )
    return config.resolved_download_directory(), config.filename_template


class SyncState:
    """Remembers which objects were already downloaded to avoid re-fetching."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._entries: dict[str, str] = {}
        self._load()

    @staticmethod
    def key(obj) -> str:
        return f"{obj.filename}|{obj.size}"

    def seen(self, obj) -> bool:
        target = self._entries.get(self.key(obj))
        return bool(target) and os.path.exists(target)

    def mark(self, obj, target: str) -> None:
        self._entries[self.key(obj)] = target

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                self._entries = {str(k): str(v) for k, v in data.items()}
        except (OSError, ValueError):
            self._entries = {}

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._entries, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:  # pragma: no cover - best effort
            pass


ProgressCallback = Callable[[object, int, int], None]
LogCallback = Callable[[str], None]


class CameraSync:
    """Download objects from one connected :class:`CameraClient` session.

    Raises :class:`~canon_eos_utility.exceptions.CameraError` (or a transport
    error) if the connection drops; the caller is expected to reconnect and call
    again — the ``.part`` files mean it resumes where it left off.
    """

    def __init__(
        self,
        client,
        config,
        camera_context: dict,
        chunk_size: int = DEFAULT_CHUNK,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
        stop=None,
        policy: str = POLICY_ASK,
        ask=None,
        on_downloaded=None,
    ) -> None:
        self.client = client
        self.config = config
        self.camera_context = camera_context
        self.chunk_size = chunk_size
        self.progress = progress
        self.log = log or (lambda _message: None)
        self.stop = stop
        self.policy = policy
        self.ask = ask
        self.on_downloaded = on_downloaded

    def media_objects(self) -> list:
        return [obj for obj in self.client.list_objects() if obj.is_image or obj.is_movie]

    def output_for(self, obj) -> tuple[str, str]:
        """Directory and naming template to use for ``obj``."""
        return output_for(obj, self.config)

    def download(
        self,
        obj,
        directory: str | None = None,
        template: str | None = None,
    ) -> str | None:
        """Download one object (resuming); returns its path or ``None`` if skipped."""
        if directory is None:
            directory, resolved = self.output_for(obj)
            template = template or resolved
        template = template or self.config.filename_template

        filename = obj.filename or f"IMG_{obj.handle}"
        part = partial_path(directory, filename)
        offset = os.path.getsize(part) if os.path.exists(part) else 0

        if not obj.size or offset < obj.size:
            self._copy(obj, part, offset)

        return finalize_download(
            obj,
            directory,
            part,
            template,
            self.camera_context,
            set_times=getattr(self.config, "set_file_times", True),
            policy=self.policy,
            ask=self.ask,
        )

    def _copy(self, obj, part: str, offset: int) -> None:
        if not obj.size:
            data = self.client.get_object(obj.handle)
            with open(part, "wb") as handle:
                handle.write(data)
            if self.progress:
                self.progress(obj, len(data), len(data))
            return

        filename = obj.filename or f"IMG_{obj.handle}"
        with open(part, "ab") as handle:
            while offset < obj.size:
                if self.stop is not None and self.stop.is_set():
                    raise InterruptedError("sync stopped")
                chunk = self.client.get_partial_object(obj.handle, offset, self.chunk_size)
                if not chunk:
                    raise CameraError(f"{filename}: camera returned no data at offset {offset}")
                handle.write(chunk)
                handle.flush()
                offset += len(chunk)
                if self.progress:
                    self.progress(obj, offset, obj.size)

    def sync_all(
        self,
        directory: str | None = None,
        state: SyncState | None = None,
    ) -> tuple[int, int, int]:
        """Download every new object. Returns ``(downloaded, skipped, failed)``.

        When ``directory`` is ``None`` the destination for each object is
        resolved from the config (so videos can go somewhere else).
        """
        downloaded = skipped = failed = 0
        for obj in self.media_objects():
            if self.stop is not None and self.stop.is_set():
                break
            if state is not None and state.seen(obj):
                skipped += 1
                continue
            try:
                target = self.download(obj, directory)
            except InterruptedError:
                break
            except (CameraError, OSError) as exc:
                failed += 1
                self.log(f"Failed to download {obj.filename}: {exc}")
                continue

            if target is None:
                skipped += 1
                self.log(f"Skipped {obj.filename} (already exists)")
                continue

            downloaded += 1
            if state is not None:
                state.mark(obj, target)
                state.save()
            if self.on_downloaded is not None:
                self.on_downloaded(obj)
            self.log(f"Saved {target}")
        return downloaded, skipped, failed
