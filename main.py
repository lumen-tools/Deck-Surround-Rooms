import argparse
import asyncio
import asyncio.subprocess
import contextlib
import datetime
from collections.abc import Awaitable, Callable
import json
import logging
import os
import random
import re
import shutil
import subprocess
import threading
import time
import sys

script_directory = os.path.dirname(os.path.abspath(__file__))
plugin_dir_basename = os.path.basename(script_directory)
tmp_log_dir = os.path.join(script_directory, "tmp", "logs")
tmp_settings_dir = os.path.join(script_directory, "tmp", "config")


def ensure_directory_exists(path: str) -> bool:
    """Create directory if possible, returning True on success."""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def detect_plugin_dir(kind: str, fallback: str) -> str:
    candidate = os.path.abspath(os.path.join(script_directory, os.pardir, os.pardir, kind, plugin_dir_basename))
    return candidate if os.path.isdir(candidate) else fallback


# Set our logs and settings directory
log_dir = detect_plugin_dir("logs", tmp_log_dir)
settings_dir = detect_plugin_dir("settings", tmp_settings_dir)

# If the DECKY_ env vars are set, then use those as the priority
log_dir = os.environ.get("DECKY_PLUGIN_LOG_DIR", log_dir)
settings_dir = os.environ.get("DECKY_PLUGIN_SETTINGS_DIR", settings_dir)

# Create the directories
ensure_directory_exists(log_dir)
ensure_directory_exists(settings_dir)

# Export the directories to env
decy_plugin_dirs = {
    "DECKY_PLUGIN_LOG_DIR": log_dir,
    "DECKY_PLUGIN_SETTINGS_DIR": settings_dir,
}
for env_key, resolved_path in decy_plugin_dirs.items():
    os.environ.setdefault(env_key, resolved_path)

# The decky plugin module is located at decky-loader/plugin
# For easy intellisense checkout the decky-loader code repo
# and add the `decky-loader/plugin/imports` path to `python.analysis.extraPaths` in `.vscode/settings.json`
try:
    import decky
except ModuleNotFoundError:
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s][%(levelname)s]: %(message)s',
        stream=sys.stderr,
    )

    class _DummyLogger:
        """Lightweight logger so CLI runs do not crash when decky is missing."""

        def __init__(self):
            self._logger = logging.getLogger("decky-cli")
            self._logger.setLevel(logging.INFO)
            self._logger.propagate = True

        def info(self, msg, *args):
            self._logger.info(msg, *args)

        def warning(self, msg, *args):
            self._logger.warning(msg, *args)

        def error(self, msg, *args):
            self._logger.error(msg, *args)

        def debug(self, msg, *args):
            self._logger.debug(msg, *args)

    class _DummyDecky:
        """Fallback decky shim for running the script outside Decky."""

        def __init__(self):
            self.logger = _DummyLogger()
            self.DECKY_USER_HOME = os.path.expanduser("~")
            self.DECKY_HOME = os.path.join(self.DECKY_USER_HOME, ".decky")

        def migrate_logs(self, *_args, **_kwargs):
            self.logger.debug("Skipping decky.migrate_logs in CLI mode")

        def migrate_settings(self, *_args, **_kwargs):
            self.logger.debug("Skipping decky.migrate_settings in CLI mode")

        def migrate_runtime(self, *_args, **_kwargs):
            self.logger.debug("Skipping decky.migrate_runtime in CLI mode")

    decky = _DummyDecky()

try:
    from settings import SettingsManager  # type: ignore
except ModuleNotFoundError:

    class SettingsManager:
        """Simple JSON-backed settings manager for CLI mode."""

        def __init__(self, name: str, settings_directory: str | None = None):
            self.name = name
            self.settings_directory = settings_directory
            self.settings_path = os.path.join(self.settings_directory, ".plugin-config.json")
            self._settings: dict[str, object] = {}

        def read(self):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as infile:
                    self._settings = json.load(infile)
            except FileNotFoundError:
                self._settings = {}
            except json.JSONDecodeError:
                self._settings = {}

        def _write(self):
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, "w", encoding="utf-8") as outfile:
                json.dump(self._settings, outfile, indent=2)

        def getSetting(self, key, default=None):
            return self._settings.get(key, default)

        def setSetting(self, key, value):
            self._settings[key] = value
            self._write()

# Read settings
settings = SettingsManager(name="settings", settings_directory=settings_dir)
settings.read()

# Configure other plugin files and directories
hrir_directory = os.path.join(script_directory, "hrir-audio")
default_hrir_file = "Studio Small - WDR Control Room 1.wav"
pipewire_config_path = os.path.join(os.path.expanduser("~"), ".config", "pipewire")
hrir_dest_path = os.path.join(pipewire_config_path, "hrir.wav")
eq_settings_path = os.path.join(pipewire_config_path, "vss-eq.txt")
# Real output device the surround/EQ chain plays to (read by service.sh).
output_target_path = os.path.join(pipewire_config_path, "vss-output.txt")
autoeq_index_cache_path = os.path.join(settings_dir, "autoeq-index.json")
AUTOEQ_RESULTS_URL = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results"
# Preferred measurement sources when a headphone was measured by several (best first).
AUTOEQ_SOURCE_PRIORITY = ["oratory1990", "crinacle", "Rtings", "Innerfidelity", "Headphone.com Legacy"]
# Filter slots of the EQ chain in service.sh (per ear).
EQ_SLOTS = {"LSC": ["ls1", "ls2"], "PK": [f"pk{i}" for i in range(1, 11)], "HSC": ["hs1", "hs2"]}
sofa_directory = os.path.join(script_directory, "hrtf-sofa")
sofa_dest_path = os.path.join(pipewire_config_path, "hrir.sofa")
hrir_original_backup_path = os.path.join(pipewire_config_path, "hrir-original.wav")

# Bump this whenever the filter graph in service.sh changes so that an already running
# systemd service gets restarted after a plugin update (otherwise the old graph keeps running).
SERVICE_GRAPH_VERSION = 8
# Bump this whenever the HRIR preparation (normalisation) changes.
HRIR_PREPARE_VERSION = 1

# HeSuVi 14 channel layout used by the convolver graph in service.sh.
# Each virtual speaker is rendered by two impulse responses (one per ear).
HRIR_SPEAKER_CHANNELS = {
    "FL": (0, 1),
    "SL": (2, 3),
    "RL": (4, 5),
    "FC": (6, 13),
    "FR": (7, 8),
    "SR": (9, 10),
    "RR": (11, 12),
}


# Display names for the bundled presets, in the order they are listed (file names are kept unchanged on disk).
# The presets are binaural room impulse responses of real rooms taken from the ASH IR Dataset.
# See defaults/hrir-audio/LICENSE.txt and the README for sources and licences.
HRIR_DISPLAY_NAMES = {
    "Studio Small - WDR Control Room 1": "Small Studio",
    "Studio Medium - WDR Control Room 7": "Medium Studio",
    "Studio Large - WDR Small Broadcast Studio": "Large Studio",
    "Studio TV - TU Ilmenau TV Studio": "TV Studio",
    "Room Listening - University of Salford Listening Room": "Listening Room",
    "Room Audio Lab - University of Rostock Audio Lab": "Audio Lab",
    "Room Conference - TU Ilmenau Conference Room": "Conference Room",
    "Room Lecture Hall - TU Berlin Auditorium 3": "Lecture Hall",
}


def _hrir_name_key(name: str) -> str:
    # Compare by letters and digits only: special characters such as the degree sign in
    # "EAC Default HRTF (35°-100°-150°)" can get mangled when the plugin zip is extracted.
    return re.sub(r"[^a-z0-9]", "", name.lower())


_HRIR_DISPLAY_NAMES_BY_KEY = {_hrir_name_key(k): v for k, v in HRIR_DISPLAY_NAMES.items()}
_HRIR_SORT_ORDER = {v: i for i, v in enumerate(HRIR_DISPLAY_NAMES.values())}


def hrir_display_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    known = _HRIR_DISPLAY_NAMES_BY_KEY.get(_hrir_name_key(stem))
    if known:
        return known
    # Custom files: keep printable characters only and make the file name readable.
    readable = "".join(c for c in stem if c.isprintable() and c != "\ufffd")
    readable = re.sub(r"[_\s]+", " ", readable).strip()
    return readable or "Custom HRIR"



def parse_autoeq_index(text: str) -> list[dict]:
    """Parses AutoEq's results/INDEX.md into entries {name, path, source, rig}."""
    import urllib.parse
    entries = []
    pattern = re.compile(r"^- \[(?P<name>.+?)\]\(\./(?P<path>.+)\) by (?P<rest>.+)$")
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        rest = m.group("rest")
        source, _, rig = rest.partition(" on ")
        entries.append({
            "name": m.group("name"),
            "path": urllib.parse.unquote(m.group("path")),
            "source": source.strip(),
            "rig": rig.strip(),
        })
    return entries


def parse_autoeq_recommended(text: str) -> set[str]:
    """Paths of AutoEq's recommended results (results/README.md): the best measurement per headphone."""
    import urllib.parse
    return {urllib.parse.unquote(m.group(1)) for m in
            (re.match(r"^- \[.+?\]\(\./(.+)\)\s*$", line.strip()) for line in text.splitlines()) if m}


def parse_autoeq_parametric(text: str) -> dict:
    """Parses an AutoEq ParametricEQ.txt (Equalizer APO format)."""
    preamp = 0.0
    filters = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^Preamp:\s*(-?[0-9.]+)\s*dB", line, re.IGNORECASE)
        if m:
            preamp = float(m.group(1))
            continue
        m = re.match(r"^Filter\s*\d*:\s*ON\s+(LSC|LS|PK|PEQ|HSC|HS)\s+Fc\s+([0-9.]+)\s*Hz\s+Gain\s+(-?[0-9.]+)\s*dB\s+Q\s+([0-9.]+)",
                     line, re.IGNORECASE)
        if m:
            kind = m.group(1).upper()
            kind = {"LS": "LSC", "PEQ": "PK", "HS": "HSC"}.get(kind, kind)
            filters.append({"type": kind, "fc": float(m.group(2)), "gain": float(m.group(3)), "q": float(m.group(4))})
    if not filters:
        raise ValueError("No filters found in the EQ profile")
    return {"preamp": preamp, "filters": filters}


def eq_slot_values(profile: dict | None) -> tuple[float, dict[str, tuple[float, float, float]]]:
    """Maps a profile onto the fixed EQ slots. Returns (linear preamp, {slot: (freq, q, gain)})."""
    values = {slot: (1000.0, 0.707, 0.0) for slots in EQ_SLOTS.values() for slot in slots}
    if not profile:
        return 1.0, values
    free = {kind: list(slots) for kind, slots in EQ_SLOTS.items()}
    # Strongest filters first, so if a profile ever has more filters than slots only the weakest are dropped.
    for f in sorted(profile.get("filters", []), key=lambda f: -abs(f["gain"])):
        slots = free.get(f["type"])
        if not slots:
            continue
        values[slots.pop(0)] = (f["fc"], max(f["q"], 0.05), f["gain"])
    return 10 ** (profile.get("preamp", 0.0) / 20), values

class UnsupportedHrirError(Exception):
    pass


def _wav_read_header(data: bytes) -> tuple[dict, int, int]:
    """Returns (fmt, data_offset, data_size) for a RIFF/WAVE byte string."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise UnsupportedHrirError("Not a RIFF/WAVE file")
    import struct
    pos = 12
    fmt = None
    data_offset = data_size = None
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        chunk_size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body_start = pos + 8
        if chunk_id == b"fmt ":
            tag, channels, rate, _, block_align, bits = struct.unpack("<HHIIHH", data[body_start:body_start + 16])
            if tag == 0xFFFE and chunk_size >= 40:
                # WAVE_FORMAT_EXTENSIBLE: real format tag is the first 2 bytes of the sub-format GUID
                tag = struct.unpack("<H", data[body_start + 24:body_start + 26])[0]
            fmt = {"tag": tag, "channels": channels, "rate": rate, "block_align": block_align, "bits": bits}
        elif chunk_id == b"data":
            data_offset = body_start
            data_size = min(chunk_size, len(data) - body_start)
        pos = body_start + chunk_size + (chunk_size & 1)
    if fmt is None or data_offset is None:
        raise UnsupportedHrirError("Missing fmt or data chunk")
    return fmt, data_offset, data_size


def wav_channel_count(path: str) -> int | None:
    try:
        with open(path, "rb") as f:
            fmt, _, _ = _wav_read_header(f.read())
        return int(fmt["channels"])
    except Exception:
        return None


def read_wav(path: str) -> tuple[int, list[list[float]]]:
    """Reads a PCM or IEEE float WAV file into per-channel float lists (pure Python, no numpy)."""
    import struct
    with open(path, "rb") as f:
        data = f.read()
    fmt, offset, size = _wav_read_header(data)
    tag, n_ch, bits = fmt["tag"], fmt["channels"], fmt["bits"]
    if n_ch < 1:
        raise UnsupportedHrirError("Invalid channel count")
    raw = data[offset:offset + size]
    if tag == 3 and bits == 32:
        n = len(raw) // 4
        samples = list(struct.unpack("<%df" % n, raw[:n * 4]))
    elif tag == 3 and bits == 64:
        n = len(raw) // 8
        samples = list(struct.unpack("<%dd" % n, raw[:n * 8]))
    elif tag == 1 and bits == 16:
        n = len(raw) // 2
        samples = [v / 32768.0 for v in struct.unpack("<%dh" % n, raw[:n * 2])]
    elif tag == 1 and bits == 32:
        n = len(raw) // 4
        samples = [v / 2147483648.0 for v in struct.unpack("<%di" % n, raw[:n * 4])]
    elif tag == 1 and bits == 24:
        n = len(raw) // 3
        samples = [int.from_bytes(raw[i:i + 3], "little", signed=True) / 8388608.0 for i in range(0, n * 3, 3)]
    elif tag == 1 and bits == 8:
        samples = [(v - 128) / 128.0 for v in raw]
    else:
        raise UnsupportedHrirError(f"Unsupported WAV sample format (tag={tag}, bits={bits})")
    frames = len(samples) // n_ch
    return fmt["rate"], [samples[c:frames * n_ch:n_ch] for c in range(n_ch)]


def write_wav_float32(path: str, rate: int, channels: list[list[float]]) -> None:
    import struct
    n_ch = len(channels)
    frames = len(channels[0])
    interleaved = [channels[c][i] for i in range(frames) for c in range(n_ch)]
    payload = struct.pack("<%df" % len(interleaved), *interleaved)
    header = b"RIFF" + struct.pack("<I", 4 + 8 + 16 + 8 + len(payload)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 3, n_ch, rate, rate * n_ch * 4, n_ch * 4, 32)
    header += b"data" + struct.pack("<I", len(payload))
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(header + payload)
    os.replace(tmp_path, path)


def prepare_hrir(source_path: str, dest_path: str) -> dict:
    """
    Converts a HeSuVi style HRIR WAV into the 14 channel float WAV that the convolver graph expects
    and normalises its level.

    - 7 channel (symmetric) HeSuVi files are expanded to 14 channels by mirroring the left side.
    - Every virtual speaker is normalised individually to the same energy. This makes all presets play
      back at the same loudness (the bundled presets differ by more than 10 dB otherwise), makes all
      channels equally loud and left/right symmetric. The interaural level difference of each speaker
      (which carries the direction information) is preserved. Personal preferences are handled by the
      per-channel mixer.
    """
    rate, channels = read_wav(source_path)
    n_ch = len(channels)
    if n_ch == 7:
        channels = channels + [list(c) for c in channels]
    elif n_ch != 14:
        raise UnsupportedHrirError(f"Expected a 7 or 14 channel HeSuVi HRIR, got {n_ch} channels")

    energies = {}
    for speaker, (a, b) in HRIR_SPEAKER_CHANNELS.items():
        energies[speaker] = sum(x * x for x in channels[a]) + sum(x * x for x in channels[b])
    if any(e <= 1e-12 for e in energies.values()):
        raise UnsupportedHrirError("HRIR contains silent channels")

    import math
    gains = {speaker: 1.0 / math.sqrt(energy) for speaker, energy in energies.items()}

    out = [list(c) for c in channels]
    for speaker, (a, b) in HRIR_SPEAKER_CHANNELS.items():
        g = gains[speaker]
        out[a] = [x * g for x in channels[a]]
        out[b] = [x * g for x in channels[b]]
    write_wav_float32(dest_path, rate, out)
    return {
        "source_channels": n_ch,
        "rate": rate,
        "levels_db": {k: round(10 * math.log10(v), 1) for k, v in energies.items()},
        "gains_db": {k: round(20 * math.log10(v), 1) for k, v in gains.items()},
    }


def subprocess_exec_env():
    uid = os.getuid()
    if uid not in (1000, 1001):
        decky.logger.warning("Attempting to run subprocess as uid %s. Looks like something is going wrong here.", uid)
    allowed_keys = [
        "DBUS_SESSION_BUS_ADDRESS", "HOME", "LANG", "PATH", "SHELL", "USER",
        "XDG_DATA_DIRS", "XDG_RUNTIME_DIR", "XDG_SESSION_CLASS", "XDG_SESSION_ID", "XDG_SESSION_TYPE",
    ]
    env = {key: os.environ[key] for key in allowed_keys if key in os.environ}
    env['XDG_RUNTIME_DIR'] = f"/run/user/{uid}"
    env['DBUS_SESSION_BUS_ADDRESS'] = f"unix:path=/run/user/{uid}/bus"
    return env


async def service_script_exec(command, args=None):
    if args is None:
        args = []
    service_script = os.path.join(script_directory, "service.sh")
    try:
        process = await asyncio.create_subprocess_exec(
            service_script, command, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_exec_env()
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            decky.logger.error(f"Service script exec failed: {stderr.decode()}")
        else:
            decky.logger.info("Service script exec output:")
            for line in stdout.decode().splitlines():
                decky.logger.info(line)
    except Exception as e:
        decky.logger.error(f"Error executing service script: {e}")


async def _fetch_virtual_surround_sink_info() -> dict[str, str]:
    service_script = os.path.join(script_directory, "service.sh")
    try:
        process = await asyncio.create_subprocess_exec(
            service_script, "print-vss-info",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_exec_env()
        )
    except FileNotFoundError:
        decky.logger.error("service.sh not found at %s", service_script)
        return {}
    except Exception as exc:
        decky.logger.error("Error executing service script: %s", exc)
        return {}

    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        decky.logger.error("service.sh print-vss-info failed: %s", stderr.decode().strip())
        return {}

    info: dict[str, str] = {}
    for line in stdout.decode().splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        info[key.strip()] = value.strip()
    return info


_virtual_surround_sink_names: tuple[str, str] | None = None


async def get_virtual_surround_sink_names() -> tuple[str | None, str | None]:
    # The names are fixed in service.sh. Ask once instead of starting the script on every check.
    global _virtual_surround_sink_names
    if _virtual_surround_sink_names is not None:
        return _virtual_surround_sink_names
    info = await _fetch_virtual_surround_sink_info()
    filter_name = info.get("VSS Filter Capture Name")
    device_name = info.get("VSS Device Capture Name")
    if not filter_name or not device_name:
        decky.logger.error("service.sh missing virtual surround sink names: %s", info)
        return None, None
    _virtual_surround_sink_names = (filter_name, device_name)
    return _virtual_surround_sink_names


_headphone_eq_sink_name: str | None = None


async def get_headphone_eq_sink_name() -> str | None:
    """Name of the stereo sink with only the headphone EQ (used when surround is off)."""
    global _headphone_eq_sink_name
    if _headphone_eq_sink_name is None:
        _headphone_eq_sink_name = (await _fetch_virtual_surround_sink_info()).get("VSS EQ Capture Name") or None
    return _headphone_eq_sink_name


async def async_wait(evt: asyncio.Event, timeout: float) -> bool:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(evt.wait(), timeout)
    return evt.is_set()


class Plugin:
    IGNORED_APP_BINARIES = {"steamwebhelper"}

    def __init__(self):
        self._background_task = None
        self._sound_test_process = None
        self._last_mixer_profile = None
        self._volume_sync_task = None
        self._volume_sync_state: dict = {}
        self._neutralized_vss_state = None
        self._state_lock = asyncio.Lock()
        self._vss_guard_task = None
        self._vss_object_id = None
        self._vss_channels = None
        self._vss_guard_fast_until = 0.0
        self.stop_event = asyncio.Event()

    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def _main(self):
        self.loop = asyncio.get_event_loop()

        # Install initial files
        await self.init_config()

        self.stop_event.clear()
        # Start the background task.
        self._background_task = self.loop.create_task(self.background_tasks())
        self._volume_sync_task = self.loop.create_task(self.volume_sync_task())
        self._vss_guard_task = self.loop.create_task(self.vss_volume_guard_task())
        self._vss_monitor_task = self.loop.create_task(self.vss_volume_monitor_task())
        decky.logger.info("Plugin main started")

    # Function called first during the unload process, utilize this to handle your plugin being stopped, but not
    # completely removed
    async def _unload(self):
        decky.logger.info("Unloading plugin: stopping background tasks...")
        # Signal the background task to exit.
        self.stop_event.set()
        with contextlib.suppress(Exception):
            await self._stop_channel_meter()
        monitor = getattr(self, "_vss_monitor_task", None)
        if monitor:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await monitor
        await self._stop_pw_cli()
        if self._vss_guard_task:
            self._vss_guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._vss_guard_task
        if self._volume_sync_task:
            self._volume_sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._volume_sync_task
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                decky.logger.info("Background task cancelled successfully")
        decky.logger.info("Plugin unloaded")

    # Function called after `_unload` during uninstall, utilize this to clean up processes and other remnants of your
    # plugin that may remain on the system
    async def _uninstall(self):
        decky.logger.info("Uninstalling service as background task")
        service_script = os.path.join(script_directory, "service.sh")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
        uninstall_log_path = os.path.join(log_dir, f"uninstall_{timestamp}.log")
        cmd = f"{service_script} uninstall &> {uninstall_log_path}"
        os.spawnle(os.P_NOWAIT, "/bin/sh", "sh", "-c", cmd, subprocess_exec_env())
        # Clean up the HRIR file if it exists.
        decky.logger.info("Removing '%s' if it exists", hrir_dest_path)
        if os.path.exists(hrir_dest_path):
            os.remove(hrir_dest_path)
        if os.path.exists(hrir_original_backup_path):
            os.remove(hrir_original_backup_path)
        decky.logger.info("Plugin uninstalled")

    # Migrations that should be performed before entering `_main()`.
    async def _migration(self):
        decky.logger.info("Migrating")
        # Here's a migration example for logs:
        # - `~/.config/decky-template/template.log` will be migrated to `decky.decky_LOG_DIR/template.log`
        decky.migrate_logs(os.path.join(decky.DECKY_USER_HOME,
                                        ".config", "decky-template", "template.log"))
        # Here's a migration example for settings:
        # - `~/homebrew/settings/template.json` is migrated to `decky.decky_SETTINGS_DIR/template.json`
        # - `~/.config/decky-template/` all files and directories under this root are migrated to `decky.decky_SETTINGS_DIR/`
        decky.migrate_settings(
            os.path.join(decky.DECKY_HOME, "settings", "template.json"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "decky-template"))
        # Here's a migration example for runtime data:
        # - `~/homebrew/template/` all files and directories under this root are migrated to `decky.decky_RUNTIME_DIR/`
        # - `~/.local/share/decky-template/` all files and directories under this root are migrated to `decky.decky_RUNTIME_DIR/`
        decky.migrate_runtime(
            os.path.join(decky.DECKY_HOME, "template"),
            os.path.join(decky.DECKY_USER_HOME, ".local", "share", "decky-template"))

    # ---- Volume sync ---------------------------------------------------------------------------
    #
    # The volume of the "Virtual Surround Sound" sink is mirrored onto the real output device and
    # vice versa. The VSS sink itself keeps showing its volume but does not apply it: its internal
    # software volume ("softVolumes") is set back to 1.0 after every change. This is the same thing
    # PipeWire's filter-chain does internally for capture.volumes, but without touching the graph.
    #   - Steam volume slider on "Virtual Surround Sound"  -> real device gets the same volume
    #   - real device volume changes (e.g. headphones plugged in and their saved volume restored)
    #                                                       -> "Virtual Surround Sound" shows it
    # The effective volume is therefore always the real device volume, whichever output is selected.
    # Nothing is ever raised artificially, so switching outputs can't cause a sudden volume jump.

    @staticmethod
    def _sink_volume(sink: dict) -> tuple[int | None, bool]:
        volume = sink.get("volume")
        values = []
        if isinstance(volume, dict):
            for details in volume.values():
                if isinstance(details, dict) and isinstance(details.get("value"), int):
                    values.append(details["value"])
        level = round(sum(values) / len(values)) if values else None
        return level, bool(sink.get("mute"))

    async def _pactl(self, *args) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                "pactl", *args,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.warning("pactl %s failed: %s", " ".join(args), stderr.decode().strip())
                return False
            return True
        except Exception as e:
            decky.logger.warning("pactl %s failed: %s", " ".join(args), e)
            return False

    async def sync_volumes(self):
        state = self._volume_sync_state
        if "names" not in state:
            filter_name, device_name = await get_virtual_surround_sink_names()
            if not filter_name or not device_name:
                return
            state["names"] = (filter_name, device_name)
        filter_name, _ = state["names"]
        # The virtual sink the apps play to: the surround device, or the headphone EQ sink.
        device_name = await self._active_input_sink_name()
        virtual_names = await self._virtual_sink_names()

        sinks = await self.list_sinks() or []
        vss = next((sink for sink in sinks if sink.get("name") == device_name), None) if device_name else None
        if vss is None:
            state.pop("vss_index", None)
            # Object ids get reused by PipeWire; never touch a stale one.
            self._vss_object_id = None
            return
        # The real output device: the default sink, or the highest priority sink when one of the
        # virtual surround sinks is the default (same rule the service uses for linking).
        output = None
        default_name = await self.get_default_sink_name()
        if default_name and default_name not in virtual_names:
            output = next((sink for sink in sinks if sink.get("name") == default_name), None)
        if output is None:
            output_id = await self.get_highest_priority_sink_id()
            output = next((sink for sink in sinks if self._object_id_from_sink(sink) == output_id), None)
        if output is None or output.get("name") in virtual_names:
            return

        vss_index = self._sink_index_from_entry(vss)
        output_name = output.get("name")
        vss_level, vss_mute = self._sink_volume(vss)
        out_level, out_mute = self._sink_volume(output)
        if vss_level is None or out_level is None:
            return

        tolerance = 655  # ~1%
        vss_changed = (
            state.get("vss_level") is not None
            and (abs(vss_level - state["vss_level"]) > tolerance or vss_mute != state.get("vss_mute"))
        )
        new_pairing = state.get("vss_index") != vss_index or state.get("output_name") != output_name

        if new_pairing or not vss_changed:
            # The real device is the reference (startup, new/plugged output device, re-created sink,
            # or its volume was changed directly).
            if abs(vss_level - out_level) > tolerance:
                await self._pactl("set-sink-volume", device_name, str(out_level))
                vss_level = out_level
            if vss_mute != out_mute:
                await self._pactl("set-sink-mute", device_name, "1" if out_mute else "0")
                vss_mute = out_mute
        else:
            # The user changed the "Virtual Surround Sound" volume (e.g. the Steam volume slider).
            if abs(vss_level - out_level) > tolerance:
                await self._pactl("set-sink-volume", output_name, str(vss_level))
                out_level = vss_level
            if vss_mute != out_mute:
                await self._pactl("set-sink-mute", output_name, "1" if vss_mute else "0")
                out_mute = vss_mute

        state.update({
            "vss_index": vss_index,
            "output_name": output_name,
            "vss_level": vss_level,
            "vss_mute": vss_mute,
        })
        # Every volume change on the VSS sink (by Steam or by us) resets its software volume, so it
        # has to be neutralised again. Our own pw-cli call triggers another change event, which is
        # ignored because the state did not change.
        current = (vss_index, vss_level, vss_mute)
        if self._neutralized_vss_state != current:
            await self._neutralize_vss_volume(vss)
            self._neutralized_vss_state = current

    async def neutralize_vss_volume_now(self):
        device_name = await self._active_input_sink_name()
        if not device_name:
            return
        vss = next((sink for sink in await self.list_sinks() or [] if sink.get("name") == device_name), None)
        if vss is not None:
            await self._neutralize_vss_volume(vss)

    async def vss_volume_guard_task(self):
        """
        Steam (and possibly other clients) set the VSS volume directly in PipeWire. Even when the value does
        not change, that re-enables the VSS attenuation, and it produces no event that the volume sync could
        react to. Re-neutralise periodically: every 0.5 s right after a switch, every 2 s otherwise.
        Neutralising emits no events, so this cannot cause a feedback loop.
        """
        while not self.stop_event.is_set():
            fast = time.monotonic() < self._vss_guard_fast_until
            try:
                object_id = self._vss_object_id
                if object_id is not None and await self._routing_mode() != "off":
                    await self._set_soft_volumes(object_id, self._vss_channels or 8)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                decky.logger.debug("VSS volume guard: %s", e)
            with contextlib.suppress(asyncio.TimeoutError):
                # While the event monitor works it reacts immediately; the guard is only a safety net then.
                idle = 10.0 if getattr(self, "_vss_monitor_ok", False) else 2.0
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.5 if fast else idle)

    async def _neutralize_vss_volume(self, vss_sink: dict):
        object_id = self._object_id_from_sink(vss_sink)
        if object_id is None:
            return
        self._vss_object_id = object_id
        self._vss_channels = len(self._channel_map_from_sink(vss_sink)) or 8
        await self._set_soft_volumes(object_id, self._vss_channels)

    async def _set_soft_volumes(self, object_id: int, n_channels: int):
        self._vss_own_change_at = time.monotonic()  # the volume monitor ignores the echo of this change
        volumes = ", ".join(["1.0"] * n_channels)
        try:
            process = await asyncio.create_subprocess_exec(
                "pw-cli", "set-param", str(object_id), "Props", f'{{ "softVolumes": [ {volumes} ] }}',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.warning("pw-cli set-param softVolumes failed: %s", stderr.decode().strip())
                self._vss_object_id = None
        except Exception as e:
            decky.logger.warning("pw-cli set-param softVolumes failed: %s", e)
            self._vss_object_id = None

    # ---- Immediate reaction to volume changes on the virtual sink ------------------------------------
    #
    # Steam sets the volume of the virtual sink directly in PipeWire. That turns the sink's own (software)
    # attenuation back on, so the volume would apply twice (dip while changing the volume; silence until
    # the volume is changed again if it happens while switching). PulseAudio events don't report it, so
    # the guard above used to catch it only every 2 s. PipeWire's own monitor (pw-dump -m, JSON) reports
    # every change of the sink's channel volumes / mute right away; the attenuation is then neutralised
    # through a pw-cli connection that stays open. Our own neutralising doesn't change the reported
    # channel volumes, so it can't trigger itself.

    async def _pw_cli_send(self, line: str) -> bool:
        proc = getattr(self, "_pw_cli", None)
        if proc is None or proc.returncode is not None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pw-cli", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, env=subprocess_exec_env())
            except Exception as e:
                decky.logger.warning("Unable to start pw-cli: %s", e)
                self._pw_cli = None
                return False
            self._pw_cli = proc
            fresh = True
        else:
            fresh = False
        try:
            proc.stdin.write((line + "\n").encode())
            await proc.stdin.drain()
            # A pw-cli that was just started may not be connected yet and can drop the first command:
            # report it as not sent, so the caller also uses the one-shot command this time.
            return not fresh
        except Exception:
            await self._stop_pw_cli()
            return False

    async def _stop_pw_cli(self):
        proc = getattr(self, "_pw_cli", None)
        self._pw_cli = None
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=2)

    async def _neutralize_fast(self, object_id: int):
        # Our own change is reported by the monitor as well; remember when we sent it to ignore the echo.
        self._vss_own_change_at = time.monotonic()
        n_channels = self._vss_channels or 8
        volumes = ", ".join(["1.0"] * n_channels)
        if not await self._pw_cli_send(f'set-param {object_id} Props {{ "softVolumes": [ {volumes} ] }}'):
            await self._set_soft_volumes(object_id, n_channels)

    async def _on_vss_volume_event(self, object_id: int, changed: bool):
        # Neutralise first (ends the double attenuation right away), then mirror the volume to the device.
        await self._neutralize_fast(object_id)
        if changed:
            with contextlib.suppress(Exception):
                await self.sync_volumes()

        # PipeWire can report the change slightly before it applies the attenuation: check again shortly after.
        async def follow_up():
            for delay in (0.06, 0.24):
                await asyncio.sleep(delay)
                if self._vss_object_id == object_id:
                    await self._neutralize_fast(object_id)
        previous = getattr(self, "_vss_follow_up", None)
        if previous is not None and not previous.done():
            previous.cancel()
        self._vss_follow_up = asyncio.get_event_loop().create_task(follow_up())

    @staticmethod
    def _volume_key(params: dict) -> tuple | None:
        volumes = params.get("channelVolumes")
        if not isinstance(volumes, list):
            return None
        return tuple(round(float(v), 4) for v in volumes), bool(params.get("mute"))

    async def vss_volume_monitor_task(self):
        decky.logger.info("Volume monitor started")
        decoder = json.JSONDecoder()
        while not self.stop_event.is_set():
            object_id = self._vss_object_id
            if object_id is None or await self._routing_mode() == "off":
                self._vss_monitor_ok = False
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
                continue
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    "pw-dump", "-m", str(object_id), stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=subprocess_exec_env())
                buffer, last, last_action = "", None, 0.0
                while not self.stop_event.is_set() and self._vss_object_id == object_id:
                    try:
                        chunk = await asyncio.wait_for(process.stdout.read(65536), timeout=1.0)
                    except asyncio.TimeoutError:
                        if await self._routing_mode() == "off":
                            break
                        continue
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    while True:
                        text = buffer.lstrip()
                        if not text:
                            buffer = ""
                            break
                        try:
                            update, end = decoder.raw_decode(text)
                        except ValueError:
                            buffer = text  # incomplete, wait for more
                            break
                        buffer = text[end:]
                        for obj in update if isinstance(update, list) else [update]:
                            if not isinstance(obj, dict) or obj.get("id") != object_id:
                                continue
                            props = ((obj.get("info") or {}).get("params") or {}).get("Props") or []
                            for params in props:
                                key = self._volume_key(params) if isinstance(params, dict) else None
                                if key is None:
                                    continue
                                self._vss_monitor_ok = True
                                # Also react when the same value is set again (that re-enables the attenuation
                                # too), but at most every 150 ms so nothing can ever loop.
                                now = time.monotonic()
                                if key == last and now - getattr(self, "_vss_own_change_at", 0.0) < 0.05:
                                    continue  # echo of our own neutralising
                                if key != last or now - last_action > 0.15:
                                    changed, last, last_action = key != last, key, now
                                    await self._on_vss_volume_event(object_id, changed)
                    if len(buffer) > 4 * 1024 * 1024:
                        buffer = ""  # never grow without bounds on unexpected output
            except asyncio.CancelledError:
                raise
            except Exception as e:
                decky.logger.warning("Volume monitor error: %s", e)
            finally:
                self._vss_monitor_ok = False
                if process is not None and process.returncode is None:
                    with contextlib.suppress(Exception):
                        process.kill()
                        await process.wait()
            # pw-dump ended (sink re-created, pipewire restarted, ...): retry shortly.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
        decky.logger.info("Volume monitor stopped")

    async def volume_sync_task(self):
        """Runs sync_volumes whenever PulseAudio/PipeWire reports a sink or server change."""
        decky.logger.info("Volume sync started")
        while not self.stop_event.is_set():
            process = None
            try:
                await self.sync_volumes()
                process = await asyncio.create_subprocess_exec(
                    "pactl", "subscribe",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    env=subprocess_exec_env()
                )
                while not self.stop_event.is_set():
                    line = await process.stdout.readline()
                    if not line:
                        break
                    text = line.decode(errors="ignore")
                    if " on sink " not in text and " on server" not in text:
                        continue
                    # Collapse bursts of events (e.g. while dragging the volume slider) into one sync.
                    while True:
                        try:
                            more = await asyncio.wait_for(process.stdout.readline(), timeout=0.05)
                        except asyncio.TimeoutError:
                            break
                        if not more:
                            break
                    await self.sync_volumes()
                    # Headphones plugged/unplugged, output chosen in Steam, ...
                    with contextlib.suppress(Exception):
                        await self.check_state()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                decky.logger.error("Volume sync error: %s", e)
            finally:
                if process is not None and process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
            # pactl subscribe ended (e.g. pipewire-pulse restarted); retry shortly.
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=2)
        decky.logger.info("Volume sync stopped")

    async def background_tasks(self):
        decky.logger.info("Background tasks started")
        fast_retries = 0
        while not self.stop_event.is_set():
            try:
                # decky.logger.info("Running task to ensure applications are assigned to their configured sinks")
                await self.check_state()
                # Normally re-check every 10 s. While the service is still starting or not every app is
                # on the right output yet, re-check every second so it is fixed right away.
                interval = 10
                with contextlib.suppress(Exception):
                    if await self._routing_is_applied():
                        fast_retries = 0
                    elif fast_retries < 20:
                        # Limited, so an app that can't be moved doesn't cause a check every second forever.
                        fast_retries += 1
                        interval = 1
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    # Timeout occurred: continue loop.
                    pass
            except asyncio.CancelledError:
                decky.logger.info("Background task cancelled")
                break
            except Exception as e:
                decky.logger.error(f"[background_tasks error]: {e}")
        decky.logger.info("Background tasks stopped")

    async def init_config(self):
        source_path = settings.getSetting("hrir_source_path", None)
        if not os.path.exists(hrir_dest_path):
            decky.logger.info("Installing default HRIR .wav file '%s'", default_hrir_file)
            self._install_hrir(os.path.join(hrir_directory, default_hrir_file))
        elif source_path and not os.path.exists(source_path):
            # The selected preset is no longer shipped with the plugin (older versions bundled presets
            # that were removed). Switch to the default preset.
            decky.logger.info("Selected HRIR '%s' no longer exists. Installing default '%s'", source_path, default_hrir_file)
            self._install_hrir(os.path.join(hrir_directory, default_hrir_file))
        elif settings.getSetting("hrir_prepared_version", 0) != HRIR_PREPARE_VERSION:
            # Installed by an older plugin version as a raw copy. Find out which preset it was and
            # re-install it with level normalisation.
            source_path = self._find_hrir_source_for_installed_file()
            decky.logger.info("Migrating installed HRIR file (source: %s)", source_path)
            self._install_hrir(source_path)
        with contextlib.suppress(Exception):
            self._write_eq_file()
        restart = settings.getSetting("service_graph_version", 0) != SERVICE_GRAPH_VERSION
        decky.logger.info("Installing service (restart=%s)", restart)
        await service_script_exec("install", ["--restart-after-install"] if restart else [])
        settings.setSetting("service_graph_version", SERVICE_GRAPH_VERSION)

    @staticmethod
    def _find_hrir_source_for_installed_file() -> str:
        """Older versions copied the preset 1:1 to hrir.wav. Find the matching preset file."""
        import filecmp
        try:
            for filename in os.listdir(hrir_directory):
                candidate = os.path.join(hrir_directory, filename)
                if filename.endswith(".wav") and filecmp.cmp(candidate, hrir_dest_path, shallow=False):
                    return candidate
        except OSError:
            pass
        # Not one of the bundled presets (e.g. a preset that older versions shipped): use the default.
        return os.path.join(hrir_directory, default_hrir_file)

    @staticmethod
    def _install_hrir(source_path: str) -> bool:
        """Prepares (normalises) the HRIR and writes it to ~/.config/pipewire/hrir.wav."""
        os.makedirs(os.path.dirname(hrir_dest_path), exist_ok=True)
        try:
            info = prepare_hrir(source_path, hrir_dest_path)
            decky.logger.info("Installed HRIR %s -> %s: %s", source_path, hrir_dest_path, info)
        except UnsupportedHrirError as e:
            # Unknown layout. Install unchanged so the user can still use it.
            decky.logger.warning("Unable to normalise HRIR '%s' (%s). Installing unchanged.", source_path, e)
            shutil.copy2(source_path, hrir_dest_path)
        os.chmod(hrir_dest_path, 0o644)
        settings.setSetting("hrir_source_path", source_path)
        settings.setSetting("hrir_prepared_version", HRIR_PREPARE_VERSION)
        return True

    # ---- Master switch -------------------------------------------------------------------------
    #
    # One switch controls everything:
    #   ON  -> "Virtual Surround Sound" is the default output and every app (that does not pin its own
    #          output device) is moved onto it.
    #   OFF -> the real output device is the default and every app is moved back onto it.
    # Older versions had a separate "use as default sink" option plus a per-app "Enable" switch, which
    # left already running apps on the real device even though surround was the default.

    INTERNAL_STREAM_BINARIES = {"pw-cli", "speaker-test"}

    @staticmethod
    def _surround_wanted() -> bool:
        return bool(settings.getSetting("surround_enabled", settings.getSetting("surround_sink_default", True)))

    def _external_connected(self) -> bool:
        # Unknown until the first check: assume yes.
        return getattr(self, "_external_output", "?") is not None

    async def get_output_available(self) -> bool:
        """False while only the internal speakers are available: surround and EQ can't be switched on then."""
        output = await self._output_target(await self.list_sinks() or [])
        self._external_output = output.get("name") if output else None
        return output is not None

    async def get_surround_enabled(self) -> bool:
        """What the switch shows: on only while an external output (headphones etc.) is connected."""
        return self._surround_wanted() and self._external_connected()

    async def _routing_mode(self) -> str:
        """
        Where the apps play to:
          "surround" -> "Virtual Surround Sound" device (room simulation + headphone EQ)
          "eq"       -> "Headphone EQ" sink (headphone EQ only, surround switched off)
          "off"      -> the real output device
        """
        # Without headphones (or another external output) everything pauses and the speakers play directly.
        if not self._external_connected():
            return "off"
        if self._surround_wanted():
            return "surround"
        if self._active_eq_profile() is not None:
            return "eq"
        return "off"

    async def _active_input_sink_name(self) -> str | None:
        """The virtual sink the apps play to in the current mode (None when they play to the device)."""
        mode = await self._routing_mode()
        if mode == "surround":
            return (await get_virtual_surround_sink_names())[1]
        if mode == "eq":
            return await get_headphone_eq_sink_name()
        return None

    @staticmethod
    def _is_internal_speaker(sink: dict) -> bool:
        """The Steam Deck's built-in speakers (never offered as output for surround/EQ)."""
        props = sink.get("properties") or {}
        if str(props.get("device.bus", "")).lower() in ("usb", "bluetooth"):
            return False
        text = " ".join(str(v).lower() for v in (
            sink.get("active_port"), sink.get("name"), sink.get("description"), props.get("device.profile.name")))
        return "speaker" in text

    @staticmethod
    def _is_connected(sink: dict) -> bool:
        ports = sink.get("ports") or []
        if not ports:
            return True
        active = sink.get("active_port")
        port = next((p for p in ports if p.get("name") == active), None)
        return str((port or {}).get("availability", "")).lower() != "not available"

    async def _external_outputs(self, sinks: list[dict]) -> list[dict]:
        """Connected real output devices except the internal speakers, highest priority first."""
        virtual = await self._virtual_sink_names()
        outputs = [s for s in sinks if s.get("name") not in virtual and not self._is_internal_speaker(s)
                   and self._is_connected(s)]
        outputs.sort(key=lambda s: -self._parse_int((s.get("properties") or {}).get("priority.session"), 0))
        return outputs

    async def _output_target(self, sinks: list[dict]) -> dict | None:
        outputs = await self._external_outputs(sinks)
        preferred = settings.getSetting("output_device", None)
        return next((s for s in outputs if s.get("name") == preferred), outputs[0] if outputs else None)

    async def get_outputs(self) -> dict:
        sinks = await self.list_sinks() or []
        target = await self._output_target(sinks)
        return {
            "selected": target.get("name") if target else None,
            "outputs": [{"name": s.get("name"), "label": s.get("description") or s.get("name")}
                        for s in await self._external_outputs(sinks)],
        }

    async def set_output(self, name: str) -> dict:
        settings.setSetting("output_device", name)
        await self.check_state()
        return await self.get_outputs()

    def _write_output_target(self, name: str | None):
        if getattr(self, "_written_output_target", "?") == name:
            return
        self._written_output_target = name
        with contextlib.suppress(Exception):
            os.makedirs(pipewire_config_path, exist_ok=True)
            with open(output_target_path, "w", encoding="utf-8") as f:
                f.write((name or "") + "\n")
        # Let the service re-link right away instead of on its next check.
        with contextlib.suppress(Exception):
            subprocess.Popen([os.path.join(script_directory, "service.sh"), "relink"], env=subprocess_exec_env(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def _virtual_sink_names(self) -> set[str]:
        filter_name, device_name = await get_virtual_surround_sink_names()
        return {n for n in (filter_name, device_name, await get_headphone_eq_sink_name()) if n}

    async def _apply_routing(self) -> bool:
        """Moves the apps for the current mode and only returns once they are actually there."""
        if not await self._wait_for_surround_sinks(timeout=20.0):
            decky.logger.warning("Routing: virtual sinks are not available")
            return False
        self._vss_guard_fast_until = time.monotonic() + 5.0
        for attempt in range(10):
            await self.check_state()
            if await self._routing_is_applied():
                if await self._routing_mode() != "off":
                    # Steam re-applies the volume of the new default output shortly after the switch, which
                    # turns the attenuation of the virtual sink back on (silence at low volumes). Neutralise
                    # it a few times before reporting the switch as done.
                    for _ in range(3):
                        await self.neutralize_vss_volume_now()
                        await asyncio.sleep(0.4)
                return True
            await asyncio.sleep(0.3)
        decky.logger.warning("Routing: not all apps could be moved")
        return False

    async def set_surround_enabled(self, enabled: bool) -> bool:
        """Switches surround on/off and only returns once all apps are actually on the new output."""
        decky.logger.info("Virtual surround %s", "enabled" if enabled else "disabled")
        settings.setSetting("surround_enabled", bool(enabled))
        self._applied_mode = None
        # Right after installing/updating the plugin the surround service is still starting; the routing
        # waits for it instead of giving up, otherwise the switch is "on" but nothing is routed yet.
        return await self._apply_routing()

    async def _surround_sinks_ready(self) -> bool:
        filter_name, device_name = await get_virtual_surround_sink_names()
        eq_name = await get_headphone_eq_sink_name()
        if not filter_name or not device_name or not eq_name:
            return False
        names = {sink.get("name") for sink in await self.list_sinks() or []}
        return filter_name in names and device_name in names and eq_name in names

    async def _wait_for_surround_sinks(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if await self._surround_sinks_ready():
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.5)

    async def _target_indices(self, sinks: list[dict], mode: str) -> tuple[set[int], set[int]]:
        """(indices of the sinks apps should be on in this mode, indices of all virtual sinks)."""
        filter_name, device_name = await get_virtual_surround_sink_names()
        eq_name = await get_headphone_eq_sink_name()
        index = {sink.get("name"): self._sink_index_from_entry(sink) for sink in sinks}
        virtual = {index.get(n) for n in (filter_name, device_name, eq_name) if index.get(n) is not None}
        if mode == "surround":
            target = {index.get(n) for n in (filter_name, device_name) if index.get(n) is not None}
        elif mode == "eq":
            target = {index[eq_name]} if index.get(eq_name) is not None else set()
        else:
            target = set()
        return target, virtual

    async def _routing_is_applied(self, enabled: bool | None = None) -> bool:
        mode = await self._routing_mode()
        filter_name, device_name = await get_virtual_surround_sink_names()
        sinks = await self.list_sinks() or []
        managed_targets = await self._managed_targets(sinks, filter_name, device_name)
        target, virtual = await self._target_indices(sinks, mode)
        if mode != "off" and not target:
            return False
        for sink_input in await self.list_sink_inputs() or []:
            if self._is_internal_stream(sink_input) or self._is_pinned_elsewhere(sink_input, managed_targets):
                continue
            current = self._parse_int(sink_input.get("sink"), -1)
            if (current in target) if mode != "off" else (current not in virtual):
                continue
            return False
        return True

    # Kept for the CLI
    async def get_surround_sink_default(self):
        return await self.get_surround_enabled()

    async def enable_surround_sink_default(self):
        return await self.set_surround_enabled(True)

    async def disable_surround_sink_default(self):
        return await self.set_surround_enabled(False)

    def _is_internal_stream(self, sink_input: dict) -> bool:
        """Streams of the plugin itself (filter outputs, sound test) must never be re-routed."""
        props = self._sink_input_properties(sink_input)
        if str(props.get("node.autoconnect", "")).lower() == "false":
            return True
        node_name = str(props.get("node.name", ""))
        if node_name.startswith(("output.vss-filter", "output.virtual-surround-sound", "output.vss-headphone-eq")):
            return True
        return props.get("application.process.binary") in self.INTERNAL_STREAM_BINARIES

    @staticmethod
    def _sink_identifiers(sink: dict | None) -> set[str]:
        """All values a stream's target.object may use to refer to this sink."""
        if not sink:
            return set()
        props = sink.get("properties") or {}
        values = {sink.get("name"), props.get("node.name"), props.get("object.id"), props.get("object.serial")}
        return {str(v) for v in values if v not in (None, "")}

    async def _managed_targets(self, sinks: list[dict], filter_name: str, device_name: str) -> set[str]:
        """
        Targets the plugin switches between: the virtual surround sinks, the real output device and the
        current default sink. Proton/Wine games open their stream on the default device *by name*,
        which pins them to it; such streams must still be switched. Only streams pinned to some other
        device (e.g. HDMI chosen in the game) are left alone.
        """
        managed: set[str] = set()
        eq_name = await get_headphone_eq_sink_name()
        for sink in sinks:
            if sink.get("name") in (filter_name, device_name, eq_name):
                managed |= self._sink_identifiers(sink)
        output_id = await self.get_highest_priority_sink_id()
        managed |= self._sink_identifiers(
            next((sink for sink in sinks if self._object_id_from_sink(sink) == output_id), None))
        default_name = await self.get_default_sink_name()
        managed |= self._sink_identifiers(next((sink for sink in sinks if sink.get("name") == default_name), None))
        return managed

    def _is_pinned_elsewhere(self, sink_input: dict, managed_targets: set[str]) -> bool:
        """True for streams the plugin must not (or cannot) move."""
        props = self._sink_input_properties(sink_input)
        # Streams created with "don't move" cannot be moved by anyone but the app itself.
        if str(props.get("node.dont-reconnect", "")).lower() == "true":
            return True
        target = self._sink_input_target_object(sink_input).strip()
        return bool(target) and target not in managed_targets

    async def check_state(self):
        # Serialised: a background run that started before the switch was flipped must not move apps
        # back after the switch has been applied.
        async with self._state_lock:
            await self._check_state()

    async def _check_state(self):
        settings.read()
        sinks = await self.list_sinks() or []
        sink_inputs = await self.list_sink_inputs()
        if not isinstance(sink_inputs, list):
            sink_inputs = []

        filter_name, device_name = await get_virtual_surround_sink_names()
        if not filter_name or not device_name:
            decky.logger.error("Unable to resolve virtual surround sink names")
            return

        # Find the sinks for the Virtual Surround Sound nodes
        virtual_surround_filter_sink = next((sink for sink in sinks if sink.get("name")
                                             == filter_name), None)
        virtual_surround_device_sink = next((sink for sink in sinks if sink.get("name")
                                             == device_name), None)
        if not virtual_surround_filter_sink:
            decky.logger.error("Required sink not found. Virtual Surround Sound is missing.")
            return

        virtual_surround_object_id = self._object_id_from_sink(virtual_surround_filter_sink)
        virtual_surround_index = self._sink_index_from_entry(virtual_surround_filter_sink)
        if virtual_surround_object_id is None or virtual_surround_index is None:
            decky.logger.error("Virtual Surround Sound sink is missing required metadata.")
            return
        virtual_surround_device_object_id = self._object_id_from_sink(virtual_surround_device_sink)
        virtual_surround_device_index = self._sink_index_from_entry(virtual_surround_device_sink)
        # Apps are only ever routed to the "Virtual Surround Sound" device sink, never directly into the
        # filter. While the service is starting the device sink may not exist yet; routing then waits.
        virtual_surround_target_index = virtual_surround_device_index

        # Determine the default_sink_id and default_sink_index
        default_sink_id: int | None = None
        default_sink_index: int | None = None
        fallback_sink_id = await self.get_highest_priority_sink_id()
        if fallback_sink_id is not None:
            fallback_sink = next(
                (sink for sink in sinks if self._object_id_from_sink(sink) == fallback_sink_id),
                None
            )
            if fallback_sink:
                default_sink_id = self._object_id_from_sink(fallback_sink)
                default_sink_index = self._sink_index_from_entry(fallback_sink)
                decky.logger.debug(
                    "Using highest priority sink (object %s, index %s).",
                    default_sink_id, default_sink_index
                )
            else:
                decky.logger.warning(
                    "Fallback sink object id %s not found; cannot determine sink index.",
                    fallback_sink_id
                )
        if default_sink_id is None or default_sink_index is None:
            decky.logger.warning("Unable to determine fallback default sink; leaving default unchanged.")

        # The real device behind surround/EQ: the output chosen in the plugin, or the first external one.
        # Without any external output (only the speakers) everything pauses.
        output = await self._output_target(sinks)
        self._external_output = output.get("name") if output else None
        self._write_output_target(self._external_output)

        virtual_names = await self._virtual_sink_names()
        current_default = await self.get_default_sink_name()
        mode = await self._routing_mode()
        applied_mode = getattr(self, "_applied_mode", None)
        # Another output was chosen in Steam while surround/EQ was on: Steam wins, turn everything off and
        # don't fight it (no jumping back).
        if (mode != "off" and applied_mode == mode and current_default
                and current_default != getattr(self, "_applied_default", None)
                and current_default not in virtual_names):
            decky.logger.info("Output '%s' was chosen outside the plugin; turning surround and EQ off", current_default)
            settings.setSetting("surround_enabled", False)
            settings.setSetting("eq_enabled", False)
            mode = "off"
            self._applied_mode = "off"
            self._applied_default = current_default

        eq_name = await get_headphone_eq_sink_name()
        eq_sink = next((sink for sink in sinks if sink.get("name") == eq_name), None)
        real_default = next((sink for sink in sinks if sink.get("name") == current_default
                             and current_default not in virtual_names), None)
        if mode == "surround":
            target_object_id, target_index, target_label = (
                virtual_surround_device_object_id, virtual_surround_target_index, "Virtual Surround Sound")
        elif mode == "eq":
            target_object_id, target_index, target_label = (
                self._object_id_from_sink(eq_sink), self._sink_index_from_entry(eq_sink), "Headphone EQ")
        elif real_default is not None:
            # Off: keep whatever real output is the default (the user's choice).
            target_object_id, target_index, target_label = (
                self._object_id_from_sink(real_default), self._sink_index_from_entry(real_default), current_default)
        else:
            target_object_id, target_index, target_label = default_sink_id, default_sink_index, "the output device"
        # Only change the default when the mode changes, or (when off) if it is stuck on a virtual sink.
        target_name = next((sink.get("name") for sink in sinks if self._object_id_from_sink(sink) == target_object_id), None)
        stuck_on_virtual = mode == "off" and (current_default in virtual_names or not current_default)
        if (mode != applied_mode or stuck_on_virtual) and target_object_id is not None:
            if current_default != target_name:
                await self.set_default_sink(target_object_id)
            self._applied_mode = mode
            self._applied_default = target_name if mode == "off" else target_name
        elif target_object_id is None:
            decky.logger.warning("Sink for mode '%s' not resolved; cannot update default sink.", mode)

        target_indices, virtual_indices = await self._target_indices(sinks, mode)
        managed_targets = await self._managed_targets(sinks, filter_name, device_name)
        for sink_input in sink_inputs:
            if self._is_internal_stream(sink_input):
                continue
            # Apps that picked another output device themselves are left alone.
            if self._is_pinned_elsewhere(sink_input, managed_targets):
                continue
            app_name = self._sink_input_app_name(sink_input) or f"sink input {sink_input.get('index')}"
            current_sink_index = self._parse_int(sink_input.get('sink'), -1)
            if mode == "off":
                if current_sink_index not in virtual_indices or target_index is None:
                    continue
            elif target_index is None or current_sink_index in target_indices:
                continue
            decky.logger.info("Moving %s (sink input %s) to %s (sink %s)",
                              app_name, sink_input['index'], target_label, target_index)
            await self.set_sink_for_application(sink_input['index'], target_index)

    async def get_hrir_file_list(self) -> list[dict[str, str | None | int]] | None:
        """Lists available HRIR files with channel count."""
        hrir_files = []
        for filename in os.listdir(hrir_directory):
            filepath = os.path.join(hrir_directory, filename)
            if filename.endswith(".wav") and os.path.isfile(filepath):
                hrir_files.append({
                    "label": hrir_display_name(filepath),
                    "path": filepath,
                    "channel_count": wav_channel_count(filepath),
                })
        active_path = settings.getSetting("hrir_source_path", os.path.join(hrir_directory, default_hrir_file))
        for entry in hrir_files:
            entry["active"] = entry["path"] == active_path
        hrir_files.sort(key=lambda x: (_HRIR_SORT_ORDER.get(x["label"], len(_HRIR_SORT_ORDER)), x["label"].lower()))
        return hrir_files

    async def set_hrir_file(self, selected_hrir_path: str) -> bool:
        """Installs the specified HRIR file."""
        decky.logger.info("Installing %s", selected_hrir_path)
        try:
            self._install_hrir(selected_hrir_path)
            await self._reload_filter()
            return True
        except Exception as e:
            decky.logger.error("Error: Failed to install HRIR WAV file: %s", e)
        return False

    async def _reload_filter(self):
        """
        Reloads only the filter module (new HRIR/SOFA file). The "Virtual Surround Sound" sink that
        the apps are connected to stays in place, so apps keep their output. Restarting the whole
        service used to remove that sink, which moved apps to another output or muted them.
        """
        await service_script_exec("reload-filter")
        # The new filter sink starts at 100% on every channel; re-apply the mixer right away
        # instead of waiting for the frontend's next 5s poll.
        if self._last_mixer_profile:
            await self.set_mixer_profile(self._last_mixer_profile)
        # The filter sink disappearing and reappearing makes Steam re-apply the output volume, which
        # re-enables the VSS attenuation (silence until the volume is changed). Same handling as after
        # switching surround on.
        self._vss_guard_fast_until = time.monotonic() + 5.0
        for _ in range(3):
            await self.neutralize_vss_volume_now()
            await asyncio.sleep(0.4)

    async def reset_plugin(self) -> bool:
        """
        Resets the whole plugin to a fresh install state:
        - all backend settings back to their defaults (default sink option, per-app routing)
        - default HRIR preset re-installed, custom HRIR backup removed
        - surround service re-installed and restarted
        - apps that were routed to the virtual surround sink are moved back
        The frontend clears its own settings (mixer and per-game profiles) and re-applies the
        default mixer profile afterwards.
        """
        decky.logger.info("Resetting plugin to defaults")
        ok = True
        await self._stop_running_sound_test()
        settings.setSetting("surround_enabled", True)
        settings.setSetting("eq_enabled", False)
        settings.setSetting("eq_profiles", [])
        settings.setSetting("eq_active_profile", None)
        with contextlib.suppress(Exception):
            self._write_eq_file()
        try:
            if os.path.exists(hrir_original_backup_path):
                os.remove(hrir_original_backup_path)
            self._install_hrir(os.path.join(hrir_directory, default_hrir_file))
        except Exception as e:
            decky.logger.error("Reset: failed to install default HRIR: %s", e)
            ok = False
        await service_script_exec("install", ["--restart-after-install"])
        settings.setSetting("service_graph_version", SERVICE_GRAPH_VERSION)
        # Give the service a moment to re-create the sinks, then re-apply the app routing.
        filter_name, _ = await get_virtual_surround_sink_names()
        for _ in range(20):
            sinks = await self.list_sinks() or []
            if any(sink.get("name") == filter_name for sink in sinks):
                break
            await asyncio.sleep(0.5)
        try:
            await self.check_state()
        except Exception as e:
            decky.logger.error("Reset: failed to re-apply audio routing: %s", e)
            ok = False
        decky.logger.info("Plugin reset finished (ok=%s)", ok)
        return ok

    async def get_sofa_file_list(self) -> list[dict[str, str | None | int]] | None:
        """Lists available SOFA files."""
        sofa_files: list[dict[str, str | None | int]] = []
        try:
            os.makedirs(sofa_directory, exist_ok=True)
        except OSError:
            pass
        for filename in os.listdir(sofa_directory):
            if filename.endswith(".sofa") and os.path.isfile(os.path.join(sofa_directory, filename)):
                filepath = os.path.join(sofa_directory, filename)
                file_size: int | None
                try:
                    file_size = os.path.getsize(filepath)
                except OSError:
                    file_size = None
                sofa_files.append({
                    "label": os.path.splitext(os.path.basename(filepath))[0],
                    "path": filepath,
                    "size": file_size
                })
        if sofa_files:
            sofa_files.sort(key=lambda x: x.get("label") or "")
        return sofa_files

    async def set_sofa_file(self, selected_sofa_path: str) -> bool:
        """Installs the specified SOFA file."""
        decky.logger.info("Installing %s", selected_sofa_path)
        try:
            os.makedirs(os.path.dirname(sofa_dest_path), exist_ok=True)
            shutil.copy2(selected_sofa_path, sofa_dest_path)
            os.chmod(sofa_dest_path, 0o644)
            decky.logger.info("Copied %s to %s", selected_sofa_path, sofa_dest_path)
            await self._reload_filter()
            return True
        except Exception as e:
            decky.logger.error("Error: Failed to copy SOFA file: %s", e)
        return False

    async def _stop_running_sound_test(self):
        process = getattr(self, "_sound_test_process", None)
        if process is not None and process.returncode is None:
            decky.logger.info("Stopping running sound test (pid %s)", process.pid)
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, 15)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=3)
        self._sound_test_process = None

    async def stop_sound_test(self) -> bool:
        await self._stop_running_sound_test()
        return True

    # ---- Headphone EQ (AutoEq) ------------------------------------------------------------------
    #
    # Profiles come from the AutoEq database (github.com/jaakkopasanen/AutoEq, Harman target). Nothing
    # is bundled: the user searches the index, the chosen profile is downloaded once and kept offline in
    # the plugin settings. The EQ runs in the filter chain behind the binaural mix (see service.sh);
    # switching profiles or turning it on/off only changes filter values, without reloading.

    async def _download(self, url: str, timeout: int = 30) -> bytes | None:
        try:
            process = await asyncio.create_subprocess_exec(
                "curl", "-fsSL", "--max-time", str(timeout), url,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=subprocess_exec_env())
            out, err = await process.communicate()
            if process.returncode != 0:
                decky.logger.warning("Download failed (%s): %s", url, err.decode(errors="replace").strip())
                return None
            return out
        except Exception as e:
            decky.logger.error("Download error (%s): %s", url, e)
            return None

    async def _autoeq_index(self) -> list[dict]:
        cached = getattr(self, "_autoeq_index_cache", None)
        if cached is not None:
            return cached
        entries: list[dict] = []
        stored = None
        with contextlib.suppress(Exception):
            with open(autoeq_index_cache_path, "r", encoding="utf-8") as f:
                stored = json.load(f)
        # Refresh the index once a week; fall back to the stored copy when offline.
        if stored and stored.get("version") == 2 and time.time() - stored.get("fetched", 0) < 7 * 24 * 3600:
            entries = stored.get("entries", [])
        else:
            data = await self._download(f"{AUTOEQ_RESULTS_URL}/INDEX.md", timeout=60)
            if data:
                entries = parse_autoeq_index(data.decode("utf-8", errors="replace"))
                recommended_data = await self._download(f"{AUTOEQ_RESULTS_URL}/README.md", timeout=60)
                recommended = parse_autoeq_recommended(recommended_data.decode("utf-8", errors="replace")) \
                    if recommended_data else set()
                for e in entries:
                    e["recommended"] = e["path"] in recommended
                with contextlib.suppress(Exception):
                    with open(autoeq_index_cache_path, "w", encoding="utf-8") as f:
                        json.dump({"version": 2, "fetched": time.time(), "entries": entries}, f)
            elif stored:
                entries = stored.get("entries", [])
        if entries:
            self._autoeq_index_cache = entries
        return entries

    @staticmethod
    def _headphone_form(path: str) -> str:
        lower = path.lower()
        if "in-ear" in lower:
            return "In-ear"
        if "earbud" in lower:
            return "Earbud"
        return "Over-ear"

    async def search_headphones(self, query: str) -> dict:
        """Searches the AutoEq index. Returns {ok, results: [{id, name, source, form}], error?}."""
        query = (query or "").strip()
        if len(query) < 2:
            return {"ok": True, "results": []}
        entries = await self._autoeq_index()
        if not entries:
            return {"ok": False, "results": [], "error": "No internet connection"}
        compact = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())
        tokens = [compact(t) for t in query.split() if compact(t)]
        matches = []
        query_compact = compact(query)

        def match_rank(original: str, name: str) -> int:
            # 0: the query starts at a word start ("hd 600" -> "Sennheiser HD 600"), 1: anywhere in the
            # name ("Denon AH-D600"), 2: only the single words match.
            pos, starts = 0, []
            for word in re.findall(r"[a-z0-9]+", original.lower()):
                starts.append(pos)
                pos += len(word)
            if any(name.startswith(query_compact, start) for start in starts):
                return 0
            return 1 if query_compact in name else 2

        for e in entries:
            name = compact(e["name"])
            if all(t in name for t in tokens):
                priority = AUTOEQ_SOURCE_PRIORITY.index(e["source"]) if e["source"] in AUTOEQ_SOURCE_PRIORITY \
                    else len(AUTOEQ_SOURCE_PRIORITY)
                matches.append((match_rank(e["name"], name), len(e["name"]), e["name"].lower(),
                                0 if e.get("recommended") else 1, priority, e))
        matches.sort(key=lambda m: m[:5])
        results = [{
            "id": e["path"],
            "name": e["name"],
            "source": e["source"] + (f" ({e['rig']})" if e["rig"] else ""),
            "form": self._headphone_form(e["path"]),
            "recommended": bool(e.get("recommended")),
        } for *_, e in matches[:40]]
        return {"ok": True, "results": results}

    @staticmethod
    def _eq_profiles() -> list[dict]:
        return list(settings.getSetting("eq_profiles", []) or [])

    async def get_eq_state(self) -> dict:
        profiles = self._eq_profiles()
        active = settings.getSetting("eq_active_profile", None)
        if active not in [p["id"] for p in profiles]:
            active = profiles[0]["id"] if profiles else None
        active_profile = next((p for p in profiles if p["id"] == active), None)
        return {
            "enabled": bool(settings.getSetting("eq_enabled", False)) and active is not None and self._external_connected(),
            "available": self._external_connected(),
            "active": active,
            "profiles": [{"id": p["id"], "label": f"{p['name']} · {p['source']}"} for p in profiles],
            # For the curve display.
            "curve": {"preamp": active_profile["preamp"], "filters": active_profile["filters"]} if active_profile else None,
        }

    async def add_headphone_profile(self, profile_id: str) -> dict:
        """Downloads an AutoEq profile, stores it offline, selects it and turns the EQ on."""
        mode_before = await self._routing_mode()
        entry = next((e for e in await self._autoeq_index() if e["path"] == profile_id), None)
        if entry is None:
            return {"ok": False, "error": "Headphones not found"}
        import urllib.parse
        folder = entry["path"].rsplit("/", 1)[-1]
        url = f"{AUTOEQ_RESULTS_URL}/{urllib.parse.quote(entry['path'])}/{urllib.parse.quote(folder)}%20ParametricEQ.txt"
        data = await self._download(url)
        if not data:
            return {"ok": False, "error": "Download failed"}
        try:
            parsed = parse_autoeq_parametric(data.decode("utf-8", errors="replace"))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        profile = {
            "id": entry["path"],
            "name": entry["name"],
            "source": entry["source"],
            "form": self._headphone_form(entry["path"]),
            "preamp": parsed["preamp"],
            "filters": parsed["filters"],
        }
        profiles = [p for p in self._eq_profiles() if p["id"] != profile["id"]] + [profile]
        settings.setSetting("eq_profiles", profiles)
        settings.setSetting("eq_active_profile", profile["id"])
        settings.setSetting("eq_enabled", True)
        await self._eq_changed(mode_before)
        decky.logger.info("Added headphone EQ '%s' (%s): %s filters, preamp %s dB",
                          profile["name"], profile["source"], len(profile["filters"]), profile["preamp"])
        return {"ok": True, "state": await self.get_eq_state()}

    async def get_eq_import_start_path(self) -> str:
        homes = [getattr(decky, "DECKY_USER_HOME", None), os.path.expanduser("~")]
        for home in [h for h in homes if h]:
            if os.path.isdir(os.path.join(home, "Downloads")):
                return os.path.join(home, "Downloads")
        return next((h for h in homes if h and os.path.isdir(h)), "/")

    async def import_headphone_profile(self, path: str) -> dict:
        """
        Imports an AutoEq profile from a file, for use without internet. Expected format: the
        "<headphones> ParametricEQ.txt" files of the AutoEq repository, or an "Equalizer APO" /
        parametric export from autoeq.app (Preamp line plus LSC/PK/HSC filter lines).
        """
        mode_before = await self._routing_mode()
        try:
            if not os.path.isfile(path) or os.path.getsize(path) > 64 * 1024:
                return {"ok": False, "error": "Not an AutoEq ParametricEQ file"}
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            if text.lstrip().startswith("GraphicEQ:"):
                return {"ok": False, "error": "This is a GraphicEQ file. Use the ParametricEQ.txt file instead"}
            parsed = parse_autoeq_parametric(text)
        except ValueError:
            return {"ok": False, "error": "Not an AutoEq ParametricEQ file"}
        except OSError as e:
            return {"ok": False, "error": f"Unable to read the file ({e.strerror})"}
        name = os.path.splitext(os.path.basename(path))[0]
        name = re.sub(r"\s*ParametricEQ$", "", name, flags=re.IGNORECASE).strip() or "Imported headphones"
        dropped = sum(max(0, sum(1 for f in parsed["filters"] if f["type"] == kind) - len(slots))
                      for kind, slots in EQ_SLOTS.items())
        profile = {
            "id": f"file:{name}",
            "name": name,
            "source": "imported",
            "form": "",
            "preamp": parsed["preamp"],
            "filters": parsed["filters"],
        }
        profiles = [p for p in self._eq_profiles() if p["id"] != profile["id"]] + [profile]
        settings.setSetting("eq_profiles", profiles)
        settings.setSetting("eq_active_profile", profile["id"])
        settings.setSetting("eq_enabled", True)
        await self._eq_changed(mode_before)
        decky.logger.info("Imported headphone EQ '%s' from %s: %s filters (%s dropped), preamp %s dB",
                          name, path, len(parsed["filters"]), dropped, parsed["preamp"])
        result = {"ok": True, "state": await self.get_eq_state()}
        if dropped:
            result["warning"] = f"{dropped} weak filter(s) were left out (the EQ has 2 low shelf, 10 peak and 2 high shelf filters)"
        return result

    async def remove_headphone_profile(self, profile_id: str) -> dict:
        mode_before = await self._routing_mode()
        profiles = [p for p in self._eq_profiles() if p["id"] != profile_id]
        settings.setSetting("eq_profiles", profiles)
        if settings.getSetting("eq_active_profile", None) == profile_id:
            settings.setSetting("eq_active_profile", profiles[0]["id"] if profiles else None)
        await self._eq_changed(mode_before)
        return await self.get_eq_state()

    async def set_eq_enabled(self, enabled: bool) -> dict:
        mode_before = await self._routing_mode()
        settings.setSetting("eq_enabled", bool(enabled))
        await self._eq_changed(mode_before)
        return await self.get_eq_state()

    async def set_eq_profile(self, profile_id: str) -> dict:
        mode_before = await self._routing_mode()
        if profile_id in [p["id"] for p in self._eq_profiles()]:
            settings.setSetting("eq_active_profile", profile_id)
            await self._eq_changed(mode_before)
        return await self.get_eq_state()

    async def _eq_changed(self, mode_before: str):
        self._applied_mode = None
        await self._apply_eq()
        if await self._routing_mode() != mode_before:
            await self._apply_routing()

    def _active_eq_profile(self) -> dict | None:
        if not settings.getSetting("eq_enabled", False):
            return None
        active = settings.getSetting("eq_active_profile", None)
        return next((p for p in self._eq_profiles() if p["id"] == active), None)

    def _write_eq_file(self) -> tuple[float, dict]:
        preamp, values = eq_slot_values(self._active_eq_profile())
        lines = [f"pre {preamp:.6f}"] + [f"{slot} {f:.2f} {q:.4f} {g:.2f}" for slot, (f, q, g) in values.items()]
        os.makedirs(pipewire_config_path, exist_ok=True)
        with open(eq_settings_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return preamp, values

    async def _apply_eq(self) -> bool:
        """Writes the EQ values for the next filter load and applies them to the running filter."""
        preamp, values = self._write_eq_file()
        filter_name, _ = await get_virtual_surround_sink_names()
        eq_name = await get_headphone_eq_sink_name()
        # Both the surround filter and the headphone EQ sink have the EQ chain.
        object_ids = [self._object_id_from_sink(s) for s in await self.list_sinks() or []
                      if s.get("name") in (filter_name, eq_name)]
        object_ids = [o for o in object_ids if o is not None]
        if not object_ids:
            return False  # Not running; the file is read when the filters are loaded.
        pairs = []
        for side in ("L", "R"):
            pairs.append((f'"eq{side}_pre:Gain 1"', f"{preamp:.6f}"))
            for slot, (freq, q, gain) in values.items():
                pairs += [(f'"eq{side}_{slot}:Freq"', f"{freq:.2f}"), (f'"eq{side}_{slot}:Q"', f"{q:.4f}"),
                          (f'"eq{side}_{slot}:Gain"', f"{gain:.2f}")]
        # pw-cli silently drops a set-param with more than ~20 values (fixed size buffer), so send small batches.
        batch_size = 15
        ok = True
        for object_id, start in [(o, st) for o in object_ids for st in range(0, len(pairs), batch_size)]:
            params = " ".join(f"{k} {v}" for k, v in pairs[start:start + batch_size])
            try:
                process = await asyncio.create_subprocess_exec(
                    "pw-cli", "set-param", str(object_id), "Props", "{ params = [ " + params + " ] }",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=subprocess_exec_env())
                _, err = await process.communicate()
                if process.returncode != 0:
                    decky.logger.warning("Applying EQ failed: %s", err.decode(errors="replace").strip())
                    ok = False
            except Exception as e:
                decky.logger.error("Applying EQ failed: %s", e)
                return False
        return ok

    # ---- Channel activity meter ----------------------------------------------------------------
    #
    # Shows which of the 8 input channels of the "Virtual Surround Sound" device currently carry
    # audio. PipeWire computes the peaks itself (resample.peaks, the same mechanism pavucontrol uses
    # for its level meters) and delivers only METER_RATE values per second and channel, so the plugin
    # never touches the audio samples. The recorder only runs while the frontend polls the levels
    # (plugin panel open) and stops on its own METER_IDLE_TIMEOUT seconds after the last poll.

    METER_CHANNELS = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]
    METER_RATE = 25
    METER_IDLE_TIMEOUT = 3.0

    async def get_channel_levels(self) -> list[float]:
        """
        Returns the peak level (0..1, linear) of each channel since the previous call, in the order of
        METER_CHANNELS. Starts the meter if it is not running.
        """
        self._meter_last_poll = time.monotonic()
        process = getattr(self, "_meter_process", None)
        if process is None or process.returncode is not None:
            await self._start_channel_meter()
        peaks = getattr(self, "_meter_peaks", None) or [0.0] * len(self.METER_CHANNELS)
        self._meter_peaks = [0.0] * len(self.METER_CHANNELS)
        return [round(min(max(p, 0.0), 1.0), 4) for p in peaks]

    async def stop_channel_meter(self) -> bool:
        await self._stop_channel_meter()
        return True

    async def _start_channel_meter(self):
        # Do not restart a failing recorder on every poll.
        if time.monotonic() < getattr(self, "_meter_retry_after", 0.0):
            return
        self._meter_retry_after = time.monotonic() + 2.0
        _, device_name = await get_virtual_surround_sink_names()
        if not device_name:
            return
        self._meter_peaks = [0.0] * len(self.METER_CHANNELS)
        # pw-record writes through a buffered stream: in a pipe the few bytes per second would only
        # arrive every few seconds. stdbuf makes the output unbuffered.
        prefix = ["stdbuf", "-o0"] if shutil.which("stdbuf") else []
        # Newer pw-record versions write an AU file (header, big endian) to stdout unless --raw is given.
        raw_args = ["--raw"] if await self._pw_record_supports_raw() else []
        try:
            process = await asyncio.create_subprocess_exec(
                *prefix, "pw-record", *raw_args,
                # Not linked by the session manager: on SteamOS it connected the channels in a different
                # order (stereo showed up as SL/SR). The ports are linked by name below instead.
                "--target", "0",
                "-P", "{ stream.capture.sink = true resample.peaks = true node.name = vss-channel-meter "
                      "node.description = \"Channel meter\" node.autoconnect = false media.role = Monitor }",
                "--rate", str(self.METER_RATE),
                "--channels", str(len(self.METER_CHANNELS)),
                "--channel-map", ",".join(self.METER_CHANNELS),
                "--format", "f32",
                "--latency", "40ms",
                "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=subprocess_exec_env(),
            )
        except Exception as e:
            decky.logger.error("Channel meter: unable to start pw-record: %s", e)
            return
        self._meter_process = process
        if not await self._link_channel_meter(device_name):
            decky.logger.error("Channel meter: unable to link the meter to '%s'", device_name)
            await self._stop_channel_meter(cancel_reader=False)
            return
        decky.logger.info("Channel meter started (pid %s) on '%s'", process.pid, device_name)
        self._meter_task = asyncio.get_event_loop().create_task(self._channel_meter_reader(process, device_name))

    async def _pw_record_supports_raw(self) -> bool:
        cached = getattr(self, "_pw_record_raw", None)
        if cached is not None:
            return cached
        supported = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "pw-record", "--help", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                env=subprocess_exec_env())
            out, _ = await proc.communicate()
            supported = b"--raw" in out
        except Exception:
            pass
        self._pw_record_raw = supported
        return supported

    async def _link_channel_meter(self, device_name: str) -> bool:
        """Links every monitor port of the surround device to the meter input of the same channel."""
        env = subprocess_exec_env()
        wanted = [f"vss-channel-meter:input_{ch}" for ch in self.METER_CHANNELS]
        for _ in range(20):
            proc = await asyncio.create_subprocess_exec(
                "pw-link", "-i", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env)
            out, _ = await proc.communicate()
            ports = {line.strip() for line in out.decode(errors="replace").splitlines()}
            if all(port in ports for port in wanted):
                break
            await asyncio.sleep(0.1)
        else:
            return False
        ok = True
        for ch in self.METER_CHANNELS:
            proc = await asyncio.create_subprocess_exec(
                "pw-link", f"{device_name}:monitor_{ch}", f"vss-channel-meter:input_{ch}",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, env=env)
            _, err = await proc.communicate()
            if proc.returncode != 0 and b"exists" not in err.lower():
                decky.logger.warning("Channel meter: linking %s failed: %s", ch, err.decode(errors="replace").strip())
                ok = False
        return ok

    @staticmethod
    def _meter_stream_header(head: bytes) -> tuple[int, str] | None:
        """
        pw-record writes through libsndfile. Depending on the PipeWire version, "-" (stdout) is raw
        float data or a sound file with a header (AU, big endian, or WAV). Returns (header size,
        byte order) or None if more bytes are needed to decide.
        """
        import struct
        if len(head) < 4:
            return None
        magic = head[:4]
        if magic in (b".snd", b"dns."):  # AU, big or little endian
            if len(head) < 8:
                return None
            order = ">" if magic == b".snd" else "<"
            return struct.unpack(order + "I", head[4:8])[0], order
        if magic in (b"RIFF", b"RF64"):
            pos = 12
            while pos + 8 <= len(head):
                chunk_id = head[pos:pos + 4]
                size = struct.unpack("<I", head[pos + 4:pos + 8])[0]
                if chunk_id == b"data":
                    return pos + 8, "<"
                if size == 0xFFFFFFFF:
                    size = 0
                pos += 8 + size + (size & 1)
            return None if len(head) < 4096 else (len(head), "<")
        if magic == b"FORM":
            idx = head.find(b"SSND")
            if idx < 0:
                return None if len(head) < 4096 else (len(head), ">")
            if len(head) < idx + 16:
                return None
            offset = struct.unpack(">I", head[idx + 8:idx + 12])[0]
            return idx + 16 + offset, ">"
        return 0, "<"

    async def _channel_meter_reader(self, process, device_name: str):
        import struct
        n_ch = len(self.METER_CHANNELS)
        frame_size = 4 * n_ch
        fmt = None
        buffer = b""
        silent_reads = 0
        try:
            while time.monotonic() - getattr(self, "_meter_last_poll", 0.0) <= self.METER_IDLE_TIMEOUT:
                try:
                    chunk = await asyncio.wait_for(process.stdout.read(frame_size * 8), timeout=1.0)
                except asyncio.TimeoutError:
                    # No data: nothing is playing and the sink is suspended, or the surround device was
                    # re-created (service restart) and the links are gone. Re-link every few seconds.
                    silent_reads += 1
                    if silent_reads % 3 == 0:
                        await self._link_channel_meter(device_name)
                    continue
                if not chunk:
                    break  # pw-record exited
                silent_reads = 0
                buffer += chunk
                if fmt is None:
                    header = self._meter_stream_header(buffer)
                    if header is None:
                        continue
                    skip, order = header
                    if skip:
                        decky.logger.info("Channel meter: stream has a %s byte header (%s endian)",
                                          skip, "big" if order == ">" else "little")
                    if len(buffer) < skip:
                        continue
                    buffer = buffer[skip:]
                    fmt = order + "f" * n_ch
                usable = len(buffer) - len(buffer) % frame_size
                peaks = self._meter_peaks
                for offset in range(0, usable, frame_size):
                    for i, value in enumerate(struct.unpack_from(fmt, buffer, offset)):
                        value = abs(value)
                        if value > peaks[i] and value == value:  # ignore NaN
                            peaks[i] = value
                buffer = buffer[usable:]
        except asyncio.CancelledError:
            return
        except Exception as e:
            decky.logger.error("Channel meter reader error: %s", e)
        await self._stop_channel_meter(cancel_reader=False)

    async def _stop_channel_meter(self, cancel_reader: bool = True):
        process = getattr(self, "_meter_process", None)
        task = getattr(self, "_meter_task", None)
        self._meter_process = None
        self._meter_task = None
        if cancel_reader and task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=2)
            decky.logger.info("Channel meter stopped")
        self._meter_peaks = [0.0] * len(self.METER_CHANNELS)

    async def run_sound_test(self, sink: str, channel: str | None = None) -> bool:
        """
        Run a surround sound test.

        sink:    "virtual-surround" (through the surround filter) or "default" (the real output device
                 without the filter). Any other value is used as a literal sink name.
        channel: optional single channel code (FL, FR, FC, LFE, RL, RR, SL, SR). Plays the full sequence if empty.
        """
        sink_name = None
        if sink in ("virtual-surround", "virtual-surround-sound-filter"):
            # Play into the "Virtual Surround Sound" device (the same input the apps use), so the test
            # takes the same path as game audio and shows up in the channel meter.
            _, device_name = await get_virtual_surround_sink_names()
            sink_name = device_name
        elif sink == "default":
            fallback_sink_id = await self.get_highest_priority_sink_id()
            if fallback_sink_id is not None:
                sinks = await self.list_sinks() or []
                fallback_sink = next(
                    (entry for entry in sinks if self._object_id_from_sink(entry) == fallback_sink_id),
                    None
                )
                if fallback_sink:
                    sink_name = fallback_sink.get("name")
        else:
            sink_name = sink
        if not sink_name:
            decky.logger.error("Sound test: unable to resolve sink '%s'", sink)
            return False

        # Only ever run one test at a time. Overlapping runs play two channels at once.
        await self._stop_running_sound_test()

        args = ["--sink", sink_name]
        if channel:
            args += ["--channel", str(channel)]
        decky.logger.info("Sound test on sink '%s' channel '%s'", sink_name, channel or "all")
        try:
            process = await asyncio.create_subprocess_exec(
                os.path.join(script_directory, "service.sh"), "speaker-test", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env(),
                start_new_session=True,
            )
        except Exception as e:
            decky.logger.error("Error starting sound test: %s", e)
            return False
        self._sound_test_process = process
        stdout, stderr = await process.communicate()
        if self._sound_test_process is process:
            self._sound_test_process = None
        if process.returncode is not None and process.returncode < 0:
            decky.logger.info("Sound test was stopped")
            return False
        if process.returncode != 0:
            decky.logger.error("Sound test failed (%s): %s", process.returncode, stderr.decode().strip())
            return False
        return True

    @staticmethod
    def _sink_input_properties(sink_input: dict | None) -> dict:
        if not sink_input:
            return {}
        props = sink_input.get("properties")
        if isinstance(props, dict):
            return props
        return {}

    @staticmethod
    def _clean_application_name(name_value) -> str | None:
        if isinstance(name_value, str):
            cleaned = name_value.strip()
            if cleaned and cleaned.lower() != "(null)":
                return cleaned
        return None

    def _normalize_sink_input(self, sink_input: dict | None) -> dict | None:
        if not isinstance(sink_input, dict):
            return None
        props = self._sink_input_properties(sink_input)
        if self._sink_input_binary_is_ignored(props):
            return None
        normalized = dict(sink_input)
        normalized["properties"] = props
        normalized["target_object"] = props.get("target.object", "")
        app_name = self._clean_application_name(props.get("application.name"))
        if app_name:
            normalized["name"] = app_name
        normalized["format"] = self._parse_format_description(sink_input)
        normalized["volume"] = self._sink_input_volume_description(sink_input)
        return normalized

    def _sink_input_binary_is_ignored(self, props: dict) -> bool:
        binary = props.get("application.process.binary")
        if not isinstance(binary, str) or not binary.strip():
            return True
        return binary in self.IGNORED_APP_BINARIES

    def _parse_format_description(self, sink_input: dict | None) -> dict:
        format_string = ""
        sample_spec = ""
        channel_map_value = None
        if isinstance(sink_input, dict):
            if isinstance(sink_input.get("format"), str):
                format_string = sink_input.get("format", "")
            if isinstance(sink_input.get("sample_specification"), str):
                sample_spec = sink_input.get("sample_specification", "")
            channel_map_value = sink_input.get("channel_map")
        base_format = format_string.split(",", 1)[0].strip() if format_string else ""
        sample_format = self._extract_format_field(format_string, r'format\.sample_format\s*=\s*"((?:\\.|[^"])*)"')
        rate = self._extract_format_field(format_string, r'format\.rate\s*=\s*"((?:\\.|[^"])*)"')
        channels = self._extract_format_field(format_string, r'format\.channels\s*=\s*"((?:\\.|[^"])*)"')
        extracted_map = self._extract_format_field(format_string, r'format\.channel_map\s*=\s*"((?:\\.|[^"])*)"')
        channel_map = self._parse_channel_map(
            extracted_map) if extracted_map else self._parse_channel_map(channel_map_value)

        if sample_spec:
            if not sample_format:
                sample_format = sample_spec.split()[0].strip()
            if not rate:
                rate_match = re.search(r'(\d+)\s*Hz', sample_spec, re.IGNORECASE)
                rate = rate_match.group(1) if rate_match else rate
            if not channels:
                channels_match = re.search(r'(\d+)ch', sample_spec, re.IGNORECASE)
                channels = channels_match.group(1) if channels_match else channels

        return {
            "format": base_format or sample_format or "",
            "sample_format": sample_format or "",
            "rate": rate or "",
            "channels": channels or "",
            "channel_map": channel_map or [],
        }

    @staticmethod
    def _extract_format_field(format_string: str, pattern: str) -> str:
        if not format_string:
            return ""
        match = re.search(pattern, format_string)
        if not match:
            return ""
        return Plugin._clean_format_token(match.group(1))

    @staticmethod
    def _clean_format_token(value: str | None) -> str:
        if not value:
            return ""
        try:
            decoded = bytes(value, "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            decoded = value
        cleaned = decoded.strip()
        if cleaned.startswith('"') and cleaned.endswith('"'):
            cleaned = cleaned[1:-1].strip()
        return cleaned

    @staticmethod
    def _parse_channel_map(value) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            cleaned = Plugin._clean_format_token(value)
            return [part.strip() for part in cleaned.split(",") if part.strip()]
        return []

    def _sink_input_app_name(self, sink_input: dict | None) -> str | None:
        props = self._sink_input_properties(sink_input)
        if not props:
            return None
        if props.get("application.process.binary") == "steamwebhelper":
            return None
        name = self._clean_application_name(props.get("application.name"))
        if name:
            return name
        media_name = props.get("media.name")
        if isinstance(media_name, str) and media_name.strip():
            return media_name
        return None

    @staticmethod
    def _sink_input_target_object(sink_input: dict | None) -> str:
        props = Plugin._sink_input_properties(sink_input)
        target_object = props.get("target.object", "")
        if isinstance(target_object, str):
            return target_object
        return ""

    @staticmethod
    def _sink_input_volume_description(sink_input: dict | None) -> str:
        volume = sink_input.get("volume") if sink_input else None
        if not isinstance(volume, dict):
            return ""
        entries = []
        for channel, details in volume.items():
            if not isinstance(details, dict):
                continue
            percent = details.get("value_percent")
            if isinstance(percent, str) and percent:
                entries.append(f"{channel}: {percent}")
        return ", ".join(entries)

    def _parse_plain_sink_input_names(self, output: str) -> dict[int, str]:
        names: dict[int, str] = {}
        current_index: int | None = None
        for raw_line in output.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            index_match = re.match(r"Sink Input #(\d+)", stripped)
            if index_match:
                try:
                    current_index = int(index_match.group(1))
                except ValueError:
                    current_index = None
                continue
            if current_index is None:
                continue
            app_match = re.match(r'application\.name\s*=\s*"([^"]*)"', stripped)
            if app_match:
                cleaned = self._clean_application_name(app_match.group(1))
                if cleaned:
                    names[current_index] = cleaned
                continue
            node_match = re.match(r'node\.name\s*=\s*"([^"]*)"', stripped)
            if node_match and current_index not in names:
                cleaned = self._clean_application_name(node_match.group(1))
                if cleaned:
                    names[current_index] = cleaned
        return names

    @staticmethod
    def _parse_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _object_id_from_sink(sink_entry: dict | None) -> int | None:
        if not sink_entry:
            return None
        props = sink_entry.get("properties") or {}
        try:
            object_id = int(props.get("object.id"))
            return object_id if object_id >= 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sink_index_from_entry(sink_entry: dict | None) -> int | None:
        if not sink_entry:
            return None
        try:
            index = int(sink_entry.get("index"))
            return index if index >= 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _channel_map_from_sink(sink_entry: dict | None) -> list[str]:
        if not sink_entry:
            return []
        channel_map = sink_entry.get("channel_map")
        if isinstance(channel_map, list):
            return [str(item).strip() for item in channel_map if str(item).strip()]
        if isinstance(channel_map, str):
            return [part.strip() for part in channel_map.split(",") if part.strip()]
        return []

    @staticmethod
    def _sink_display_name(sink_entry: dict | None) -> str:
        if not sink_entry:
            return "unknown sink"
        props = sink_entry.get("properties") or {}
        return props.get("node.description") or sink_entry.get("description") or sink_entry.get("name") or "unknown sink"

    async def get_highest_priority_sink_id(self) -> int | None:
        """
        Returns the object ID of the sink with the highest priority.session value.
        Ports marked as "not available" for every entry are treated as priority 0.
        """
        sinks = await self.list_sinks()
        if not sinks:
            decky.logger.warning("Unable to determine priority sink: no sinks reported.")
            return None

        best_sink_id: int | None = None
        best_priority = -1
        best_index = -1
        virtual_names = await self._virtual_sink_names()

        for sink in sinks:
            if sink.get("name") in virtual_names:
                continue
            obj_id = self._object_id_from_sink(sink)
            if obj_id is None:
                continue

            # Get the sink index
            sink_index = self._parse_int(sink.get("index"), -1)

            # Get sink properties
            properties = sink.get("properties") or {}

            # Skip virtual sinks
            if properties.get("node.virtual") == "true":
                continue

            # Get session priority
            session_priority = self._parse_int(properties.get("priority.session"), -1)

            # Ensure sink has eligible port (Note: WirePlumber will consider ports that are marked as "unknown" as eligible for selection)
            # Anything with an availablility "not available" on all ports should be considered of a low priority
            ports = sink.get("ports") or []
            effective_priority = session_priority
            if ports:
                availabilities = [
                    str(port.get("availability") or "").strip().lower()
                    for port in ports
                ]
                if availabilities and all(value == "not available" for value in availabilities):
                    effective_priority = 0

            # Determine the priority
            if effective_priority > best_priority or (
                effective_priority == best_priority and sink_index > best_index
            ):
                best_priority = effective_priority
                best_index = sink_index
                best_sink_id = obj_id

        if best_sink_id is None:
            decky.logger.warning("No suitable sinks with priority.session found.")
            return None

        return best_sink_id

    async def get_default_sink_id(self) -> int | None:
        """
        Returns the object ID of the current default sink as reported by pactl.
        """
        default_sink_name = await self.get_default_sink_name()
        sinks = await self.list_sinks()
        if not sinks:
            return None
        if not default_sink_name:
            return None

        default_sink = next((s for s in sinks if s.get("name") == default_sink_name), None)
        if not default_sink:
            decky.logger.warning("Default sink '%s' not found in pactl list.", default_sink_name)
            return None

        object_id = self._object_id_from_sink(default_sink)
        if object_id is None:
            decky.logger.warning("Default sink '%s' is missing a valid object.id.", default_sink_name)
            return None

        decky.logger.debug(
            "Using default sink '%s' (object_id=%s index=%s)",
            default_sink_name,
            object_id,
            default_sink.get("index"),
        )
        return object_id

    async def get_default_sink_name(self) -> str | None:
        """
        Returns the sink name reported by `pactl get-default-sink`.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                'pactl', 'get-default-sink',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error("pactl get-default-sink failed: %s", stderr.decode().strip())
                return None
            output = stdout.decode().strip()
            if not output:
                return None
            first_line = output.splitlines()[0].strip()
            match = re.search(r'(?:default(?:\s+sink)?)\s*[:=]\s*(\S+)', first_line, re.IGNORECASE)
            if match:
                return match.group(1)
            return first_line
        except FileNotFoundError:
            decky.logger.error("pactl not found when requesting default sink.")
            return None
        except Exception as e:
            decky.logger.error("Error retrieving default sink: %s", e)
            return None

    async def list_sinks(self):
        """
        Retrieve a mapping of sink index to its name and description.
        """
        sinks = []
        try:
            process = await asyncio.create_subprocess_exec(
                'pactl', '-f', 'json', 'list', 'sinks',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error(f"pactl list sinks failed: {stderr.decode()}")
                return []

            try:
                return json.loads(stdout.decode())
            except json.JSONDecodeError as exc:
                decky.logger.error(f"Failed to decode pactl sinks JSON: {exc}")
                return []
        except FileNotFoundError:
            decky.logger.error("pactl not found.")
            return []
        except Exception as e:
            decky.logger.error(f"Error getting sinks: {e}")
            return []
        return sinks

    async def list_sink_inputs(self):
        """
        Retrieve sink inputs (running application audio streams) using pactl's JSON output.
        Returns a normalized list that includes parsed format details and friendly metadata.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                'pactl', '-f', 'json', 'list', 'sink-inputs',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error("pactl list sink-inputs failed: %s", stderr.decode().strip())
                return []
            try:
                raw_inputs = json.loads(stdout.decode())
            except json.JSONDecodeError as exc:
                decky.logger.error("Failed to decode pactl sink inputs JSON: %s", exc)
                return []
            normalized_inputs = []
            for entry in raw_inputs:
                normalized = self._normalize_sink_input(entry)
                if normalized:
                    normalized_inputs.append(normalized)
            if normalized_inputs:
                # NOTE: For some reason the JSON formatted output of pactl had decode errors for some app names.
                #   I could not figure out how to fix that, so I am going to run it twice, the second time without JSON formatting.
                #   Not ideal, but whatever.
                process = await asyncio.create_subprocess_exec(
                    'pactl', 'list', 'sink-inputs',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=subprocess_exec_env()
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    decky.logger.error("pactl list sink-inputs (text) failed: %s", stderr.decode().strip())
                    name_map = {}
                else:
                    name_map = self._parse_plain_sink_input_names(stdout.decode())
                    if name_map:
                        for entry in normalized_inputs:
                            sink_index = self._parse_int(entry.get("index"), -1)
                            if sink_index < 0:
                                continue
                            new_name = self._clean_application_name(name_map.get(sink_index))
                            if not new_name:
                                continue
                            existing = self._clean_application_name(entry.get("name"))
                            if existing:
                                continue
                            entry["name"] = new_name
            return normalized_inputs
        except FileNotFoundError:
            decky.logger.error("pactl not found.")
            return []
        except Exception as e:
            decky.logger.error(f"Error getting sink inputs: {e}")
            return []

    async def set_default_sink(self, sink_input_index: str):
        """Moves the sink output for the given app"""
        try:
            process = await asyncio.create_subprocess_exec(
                "wpctl", 'set-default', str(sink_input_index),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error(
                    "Failed to set default sink to %s: %s",
                    sink_input_index,
                    stderr.decode().strip(),
                )
                return False
            decky.logger.debug(
                "Default sink set via wpctl to %s. %s",
                sink_input_index,
                stdout.decode().strip(),
            )
            return True
        except FileNotFoundError:
            decky.logger.warning("wpctl not found.")
            return False
        except Exception as e:
            decky.logger.error(f"Error setting default input sink: {e}")
            return False

    async def set_sink_for_application(self, sink_input_index: str, target_sink_index: str):
        """Moves the sink output for the given app"""
        #  > pactl list sink-inputs
        # Plex - Sink Input #649
        # Plex -         Sink: 50
        #
        #  > pactl list sinks
        # Virtual Sink: 50
        # Virtual Surround Sound Sink: 57
        #
        #  > pactl move-sink-input 649 50
        #  > pactl move-sink-input 1790 49
        #  > pactl move-sink-input 1868 433
        #  > pactl move-sink-input 1868 49
        try:
            process = await asyncio.create_subprocess_exec(
                "pactl", 'move-sink-input', str(sink_input_index), str(target_sink_index),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            await process.communicate()
            return process.returncode == 0
        except FileNotFoundError:
            decky.logger.warning("pactl not found.")
            return False
        except Exception as e:
            decky.logger.error(f"Error moving sink input: {e}")
            return False

    async def set_mixer_profile(self, mixer_profile):
        """
        Sets per-channel volumes on the sink named "virtual-surround-sound"
        using the provided mixer_profile dict.

        The mixer_profile is expected to be a dict like:
          {
            "name": "default",
            "usePerAppProfile": false,
            "volumes": {
              "FL": 100,
              "FR": 100,
              "FC": 100,
              "LFE": 100,
              "RL": 100,
              "RR": 100,
              "SL": 100,
              "SR": 100
            }
          }
        """
        self._last_mixer_profile = mixer_profile
        filter_name, _ = await get_virtual_surround_sink_names()
        if not filter_name:
            decky.logger.error("Unable to resolve virtual surround filter sink name")
            return False
        sinks = await self.list_sinks()
        target_sink = None
        for sink in sinks:
            # Look for the sink named "input.virtual-surround-sound"
            if sink.get("name") == filter_name:
                target_sink = sink
                break
        if target_sink is None:
            decky.logger.error("Sink 'virtual-surround-sound' not found")
            return False

        sink_index = self._sink_index_from_entry(target_sink)
        if sink_index is None:
            decky.logger.error("Sink 'virtual-surround-sound' missing sink index")
            return False

        channel_map = self._channel_map_from_sink(target_sink)
        if not channel_map:
            decky.logger.error("Channel Map not found for sink 'virtual-surround-sound'")
            return False

        # Map full channel names to short codes used in mixer_profile.
        # The pactl command will return the channels as "front-left" and "front-right".
        channel_name_map = {
            "front-left": "FL",
            "front-right": "FR",
            "front-center": "FC",
            "lfe": "LFE",
            "rear-left": "RL",
            "rear-right": "RR",
            "side-left": "SL",
            "side-right": "SR"
        }
        # Since we need to map the volume args in the correct order, we will map them based on the sink channel_map,
        # then read each channel volume provided in the mixer_profile in the correct order.
        volume_args = []
        for ch in channel_map:
            short_code = channel_name_map.get(ch)
            if short_code and short_code in mixer_profile.get("volumes", {}):
                volume_value = mixer_profile["volumes"][short_code]
                # Build a per-channel volume argument (e.g. "100%")
                volume_args.append(f"{volume_value}%")
            else:
                volume_args.append(f"100%")

        if not volume_args:
            decky.logger.error("No matching channels found in mixer profile for sink channel map")
            return False

        # Execute pactl to set the per-channel volume.
        command = ["pactl", "set-sink-volume", str(sink_index)] + volume_args
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error("Failed to set mixer profile: " + stderr.decode())
                return False
            decky.logger.debug(f"Mixer profile applied on sink {sink_index} with volumes: {volume_args}")
            return True
        except Exception as e:
            decky.logger.error(f"Error setting mixer profile: {e}")
            return False

    async def test_stuff(self):
        # await self._main()
        # await self._uninstall()
        # hrir_file_list = await self.get_hrir_file_list()
        # await self.set_hrir_file(hrir_file_list[0].get("path"))
        sinks = await self.list_sinks()
        print(json.dumps(sinks, indent=2))
        sink_inputs = await self.list_sink_inputs()
        print(json.dumps(sink_inputs, indent=2))

        # For testing set_mixer_profile, define a mixer_profile dict:
        mixer_profile = {
            "name": "default",
            "usePerAppProfile": False,
            "volumes": {
                "FL": 50,
                "FR": 50,
                "FC": 50,
                "LFE": 20,
                "RL": 100,
                "RR": 100,
                "SL": 80,
                "SR": 80
            }
        }
        # Uncomment to test setting the mixer profile:
        await plugin.set_mixer_profile(mixer_profile)


class CLIHelper:
    """Convenience bridge for running async plugin methods from the curses UI."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._lock = threading.Lock()

    def run(self, coro):
        with self._lock:
            return self.loop.run_until_complete(coro)

    def run_delayed(self, coro_factory: Callable[[], Awaitable[object]], delay: float):
        """Run coroutine returned by coro_factory after delay in seconds on a background thread."""

        def _worker():
            time.sleep(delay)
            try:
                self.run(coro_factory())
            except Exception as exc:
                logging.getLogger("cli-menu").error("Delayed task failed: %s", exc)

        threading.Thread(target=_worker, daemon=True).start()

    def close(self):
        self.loop.close()

    def lines_for_sinks(self, plugin: Plugin) -> list[str]:
        sinks = self.run(plugin.list_sinks()) or []
        lines: list[str] = []
        if not sinks:
            lines.append("No sinks found.")
            return lines
        for idx, sink in enumerate(sinks, start=1):
            sink_index = plugin._sink_index_from_entry(sink)
            object_id = plugin._object_id_from_sink(sink)
            description = sink.get("description") or "No description"
            lines.append(f"{idx}. {sink.get('name')} (index={sink_index if sink_index is not None else 'unknown'})")
            lines.append(f"    object_id: {object_id if object_id is not None else 'unknown'}")
            lines.append(f"    description: {description}")
            props = sink.get("properties") or {}
            priority = props.get("priority.session")
            if priority is not None:
                lines.append(f"    priority.session: {priority}")
            channels = plugin._channel_map_from_sink(sink)
            if channels:
                lines.append(f"    channels: {', '.join(channels)}")
        return lines

    def lines_for_running_apps(self, plugin: Plugin) -> list[str]:
        sink_inputs = self.run(plugin.list_sink_inputs()) or []
        lines: list[str] = []
        if not sink_inputs:
            lines.append("No running apps detected.")
            return lines
        for idx, entry in enumerate(sink_inputs, start=1):
            name = entry.get("name") or plugin._sink_input_app_name(entry) or f"Sink Input {entry.get('index')}"
            lines.append(f"{idx}. {name}")
            lines.append(f"    index: {entry.get('index')} -> sink {entry.get('sink')}")
            target = entry.get("target_object") or plugin._sink_input_target_object(entry)
            if target:
                lines.append(f"    target: {target}")
            volume_desc = entry.get("volume") or plugin._sink_input_volume_description(entry)
            if volume_desc:
                lines.append(f"    volume: {volume_desc}")
            format_value = entry.get("format")
            if isinstance(format_value, dict):
                fmt_parts = []
                if format_value.get("format"):
                    fmt_parts.append(f"type={format_value['format']}")
                if format_value.get("sample_format"):
                    fmt_parts.append(f"sample={format_value['sample_format']}")
                if format_value.get("rate"):
                    fmt_parts.append(f"rate={format_value['rate']}")
                if format_value.get("channels"):
                    fmt_parts.append(f"channels={format_value['channels']}")
                if fmt_parts:
                    lines.append(f"    format: {', '.join(fmt_parts)}")
                channel_map = format_value.get("channel_map") or []
                if channel_map:
                    lines.append(f"    channel_map: {', '.join(channel_map)}")
        return lines

    def lines_for_highest_priority_sink(self, plugin: Plugin) -> list[str]:
        sink_id = self.run(plugin.get_highest_priority_sink_id())
        if sink_id is None:
            return ["Unable to determine a highest priority sink."]
        sinks = self.run(plugin.list_sinks()) or []
        entry = next((s for s in sinks if plugin._object_id_from_sink(s) == sink_id), None)
        lines = [f"Object ID: {sink_id}"]
        if entry:
            lines.append(f"Name: {entry.get('name')}")
            lines.append(f"Index: {plugin._sink_index_from_entry(entry)}")
            lines.append(f"Description: {entry.get('description')}")
            props = entry.get("properties") or {}
            priority = props.get("priority.session")
            if priority is not None:
                lines.append(f"priority.session: {priority}")
        return lines

    def lines_for_default_sink(self, plugin: Plugin) -> list[str]:
        sink_id = self.run(plugin.get_default_sink_id())
        if sink_id is None:
            return ["Unable to determine default sink."]
        sinks = self.run(plugin.list_sinks()) or []
        entry = next((s for s in sinks if plugin._object_id_from_sink(s) == sink_id), None)
        lines = [f"Object ID: {sink_id}"]
        if entry:
            lines.append(f"Name: {entry.get('name')}")
            lines.append(f"Index: {plugin._sink_index_from_entry(entry)}")
            lines.append(f"Description: {entry.get('description')}")
            props = entry.get("properties") or {}
            priority = props.get("priority.session")
        if priority is not None:
            lines.append(f"priority.session: {priority}")
        return lines

    @staticmethod
    def print_lines(lines: list[str]) -> None:
        for line in lines:
            print(line)


class CLIMenu:
    """Curses-driven CLI for interacting with Plugin helpers."""

    _curses_module = None

    @classmethod
    def _ensure_curses(cls):
        if cls._curses_module is None:
            import curses as curses_module
            cls._curses_module = curses_module
        return cls._curses_module

    def __init__(self, plugin: Plugin):
        self.plugin = plugin
        self.helper = CLIHelper()
        self.menu_items: list[tuple[str, Callable[[object], None]]] = [
            ("List sinks", self.list_sinks_action),
            ("List running apps (sink inputs)", self.list_sink_inputs_action),
            ("Get highest priority sink", self.highest_priority_sink_action),
            ("Get default sink", self.default_sink_action),
            ("Toggle Virtual Surround + Rooms on/off", self.toggle_default_surround_action),
            ("List HRIR files", self.list_hrir_files_action),
            ("Set HRIR file", self.set_hrir_file_action),
            ("List SOFA files", self.list_sofa_files_action),
            ("Set SOFA file", self.set_sofa_file_action),
            ("Run sound test", self.run_sound_test_action),
            ("Test random mixer profile", self.random_mixer_profile_action),
        ]

    @classmethod
    def _safe_curs_set(cls, mode: int):
        curses = cls._ensure_curses()
        try:
            curses.curs_set(mode)
        except curses.error:
            pass

    def _navigate_menu(self, stdscr, title: str, labels: list[str], footer: str) -> int | None:
        curses = self._ensure_curses()
        if not labels:
            return None
        index = 0
        offset = 0
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            self._safe_curs_set(0)
            visible_rows = max(1, height - 4)
            offset = max(0, min(offset, len(labels) - visible_rows))
            if index < offset:
                offset = index
            elif index >= offset + visible_rows:
                offset = index - visible_rows + 1
            stdscr.addnstr(0, 2, title, width - 4, curses.A_BOLD)
            for row in range(visible_rows):
                label_idx = offset + row
                if label_idx >= len(labels):
                    break
                prefix = f"{label_idx + 1}. {labels[label_idx]}"
                attr = curses.A_REVERSE if label_idx == index else curses.A_NORMAL
                stdscr.addnstr(2 + row, 2, prefix, width - 4, attr)
            stdscr.addnstr(height - 2, 2, footer, width - 4)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('k')):
                index = (index - 1) % len(labels)
            elif key in (curses.KEY_DOWN, ord('j')):
                index = (index + 1) % len(labels)
            elif key == curses.KEY_NPAGE:
                index = min(index + visible_rows, len(labels) - 1)
            elif key == curses.KEY_PPAGE:
                index = max(index - visible_rows, 0)
            elif key in (curses.KEY_ENTER, 10, 13):
                return index
            elif key in (27, ord('q'), ord('Q')):
                return None
            elif ord('0') <= key <= ord('9'):
                digit = key - ord('0')
                target = 9 if digit == 0 else digit - 1
                if target < len(labels):
                    index = target
                    return index

    def _show_scrollable_text(self, stdscr, title: str, lines: list[str], footer: str = "Press Enter to return"):
        curses = self._ensure_curses()
        content = lines or ["No data to display."]
        top = 0
        while True:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            self._safe_curs_set(0)
            visible_rows = max(1, height - 4)
            top = max(0, min(top, max(0, len(content) - visible_rows)))
            stdscr.addnstr(0, 2, title, width - 4, curses.A_BOLD)
            for row in range(visible_rows):
                line_idx = top + row
                if line_idx >= len(content):
                    break
                stdscr.addnstr(2 + row, 2, content[line_idx], width - 4)
            stdscr.addnstr(height - 2, 2, footer, width - 4)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('k')):
                top = max(0, top - 1)
            elif key in (curses.KEY_DOWN, ord('j')):
                if top + visible_rows < len(content):
                    top += 1
            elif key == curses.KEY_NPAGE:
                top = min(top + visible_rows, max(0, len(content) - visible_rows))
            elif key == curses.KEY_PPAGE:
                top = max(0, top - visible_rows)
            elif key in (curses.KEY_ENTER, 10, 13, 27, ord('q'), ord('Q')):
                return

    def _show_message(self, stdscr, title: str, message: str):
        self._show_scrollable_text(stdscr, title, [message])

    def list_sinks_action(self, stdscr):
        lines = self.helper.lines_for_sinks(self.plugin)
        self._show_scrollable_text(stdscr, "Available Sinks", lines)

    def list_sink_inputs_action(self, stdscr):
        lines = self.helper.lines_for_running_apps(self.plugin)
        self._show_scrollable_text(stdscr, "Running Apps (Sink Inputs)", lines)

    def highest_priority_sink_action(self, stdscr):
        lines = self.helper.lines_for_highest_priority_sink(self.plugin)
        self._show_scrollable_text(stdscr, "Highest Priority Sink", lines)

    def default_sink_action(self, stdscr):
        lines = self.helper.lines_for_default_sink(self.plugin)
        self._show_scrollable_text(stdscr, "Default Sink", lines)

    def toggle_default_surround_action(self, stdscr):
        current = bool(self.helper.run(self.plugin.get_surround_sink_default()))
        if current:
            self.helper.run(self.plugin.disable_surround_sink_default())
            self._show_message(stdscr, "Virtual Surround", "Virtual Surround + Rooms is now off.")
        else:
            self.helper.run(self.plugin.enable_surround_sink_default())
            self._show_message(stdscr, "Virtual Surround", "Virtual Surround + Rooms is now on.")

    def list_hrir_files_action(self, stdscr):
        files = self.helper.run(self.plugin.get_hrir_file_list()) or []
        lines: list[str] = []
        if not files:
            lines.append("No HRIR files found.")
        else:
            for idx, entry in enumerate(files, start=1):
                channel_info = f"{entry.get('channel_count')} ch" if entry.get("channel_count") else "Unknown channels"
                lines.append(f"{idx}. {entry.get('label')} ({channel_info})")
                lines.append(f"    {entry.get('path')}")
        self._show_scrollable_text(stdscr, "HRIR Files", lines)

    def set_hrir_file_action(self, stdscr):
        files = self.helper.run(self.plugin.get_hrir_file_list()) or []
        if not files:
            self._show_message(stdscr, "Set HRIR File", "No HRIR files available.")
            return
        labels = []
        for entry in files:
            channel_info = f"{entry.get('channel_count')} ch" if entry.get("channel_count") else "?"
            labels.append(f"{entry.get('label')} ({channel_info})")
        selection = self._navigate_menu(
            stdscr,
            "Select HRIR File",
            labels,
            "↑/↓ navigate • Enter install • q cancel"
        )
        if selection is None:
            return
        selected = files[selection]
        path = selected.get("path")
        if not isinstance(path, str):
            self._show_message(stdscr, "Set HRIR File", "Invalid HRIR file entry.")
            return
        success = self.helper.run(self.plugin.set_hrir_file(path))
        if success:
            self.helper.run_delayed(lambda: self.plugin.check_state(), 5.0)
            self._show_message(
                stdscr,
                "Set HRIR File",
                f"Installed '{selected.get('label')}'.\nRechecking sink assignments shortly."
            )
        else:
            self._show_message(stdscr, "Set HRIR File", "Failed to install selected HRIR file.")

    def list_sofa_files_action(self, stdscr):
        files = self.helper.run(self.plugin.get_sofa_file_list()) or []
        lines: list[str] = []
        if not files:
            lines.append("No SOFA files found.")
        else:
            for idx, entry in enumerate(files, start=1):
                label = entry.get("label") or entry.get("path") or f"SOFA File {idx}"
                lines.append(f"{idx}. {label}")
                file_path = entry.get("path")
                if file_path:
                    lines.append(f"    {file_path}")
                size = entry.get("size")
                if isinstance(size, int):
                    lines.append(f"    size: {size} bytes")
        self._show_scrollable_text(stdscr, "SOFA Files", lines)

    def set_sofa_file_action(self, stdscr):
        files = self.helper.run(self.plugin.get_sofa_file_list()) or []
        if not files:
            self._show_message(stdscr, "Set SOFA File", "No SOFA files available.")
            return
        labels = []
        for entry in files:
            label = entry.get("label") or entry.get("path")
            labels.append(label or "SOFA file")
        selection = self._navigate_menu(
            stdscr,
            "Select SOFA File",
            labels,
            "↑/↓ navigate • Enter install • q cancel"
        )
        if selection is None:
            return
        selected = files[selection]
        path = selected.get("path")
        if not isinstance(path, str):
            self._show_message(stdscr, "Set SOFA File", "Invalid SOFA file entry.")
            return
        label_text = selected.get("label") or os.path.basename(path)
        success = self.helper.run(self.plugin.set_sofa_file(path))
        if success:
            self.helper.run_delayed(lambda: self.plugin.check_state(), 5.0)
            self._show_message(
                stdscr,
                "Set SOFA File",
                f"Installed '{label_text}'.\nRechecking sink assignments shortly."
            )
        else:
            self._show_message(stdscr, "Set SOFA File", "Failed to install selected SOFA file.")

    def run_sound_test_action(self, stdscr):
        sinks = self.helper.run(self.plugin.list_sinks())
        candidates = [s for s in sinks if isinstance(s.get("name"), str)]
        if not candidates:
            self._show_message(stdscr, "Sound Test", "No sinks available for testing.")
            return
        labels = []
        for sink in candidates:
            sink_index = self.plugin._sink_index_from_entry(sink)
            labels.append(f"{sink.get('name')} (index={sink_index if sink_index is not None else 'unknown'})")
        selection = self._navigate_menu(
            stdscr,
            "Select Sink for Sound Test",
            labels,
            "↑/↓ navigate • Enter run test • q cancel"
        )
        if selection is None:
            return
        sink_name = candidates[selection].get("name")
        if not isinstance(sink_name, str):
            self._show_message(stdscr, "Sound Test", "Invalid sink selection.")
            return
        self.helper.run(self.plugin.run_sound_test(sink_name))
        self._show_message(stdscr, "Sound Test", f"Started speaker-test on '{sink_name}'.")

    def random_mixer_profile_action(self, stdscr):
        channel_codes = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]
        volumes = {code: random.randint(45, 120) for code in channel_codes}
        profile = {
            "name": "random",
            "usePerAppProfile": False,
            "volumes": volumes
        }
        success = self.helper.run(self.plugin.set_mixer_profile(profile))
        lines = [f"{code}: {value}%" for code, value in volumes.items()]
        if success:
            self._show_scrollable_text(stdscr, "Random Mixer Profile Applied", lines)
        else:
            self._show_scrollable_text(stdscr, "Random Mixer Profile Failed", lines + ["Operation failed."])

    def _main_menu(self, stdscr):
        self._safe_curs_set(0)
        labels = [label for label, _handler in self.menu_items]
        while True:
            selection = self._navigate_menu(
                stdscr,
                "Virtual Surround + Rooms",
                labels + ["Exit"],
                "↑/↓ navigate • Enter select • q exit"
            )
            if selection is None or selection == len(labels):
                break
            _label, handler = self.menu_items[selection]
            handler(stdscr)

    def run(self):
        curses = self._ensure_curses()
        try:
            curses.wrapper(self._main_menu)
        finally:
            self.helper.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Virtual Surround + Rooms CLI")
    parser.add_argument("--menu", action="store_true", help="Launch the curses menu UI")
    parser.add_argument("--list-sinks", action="store_true", help="List available sinks")
    parser.add_argument("--list-running-apps", action="store_true", help="List sink inputs (running apps)")
    parser.add_argument("--print-highest-priority-sink", action="store_true",
                        help="Print highest priority physical sink")
    parser.add_argument("--print-default-sink", action="store_true", help="Print current default sink")
    args = parser.parse_args()

    actions_requested = any([
        args.list_sinks,
        args.list_running_apps,
        args.print_highest_priority_sink,
        args.print_default_sink,
    ])

    if args.menu and actions_requested:
        parser.error("--menu cannot be combined with other options")

    if args.menu or not actions_requested:
        plugin = Plugin()
        menu = CLIMenu(plugin)
        menu.run()
        sys.exit(0)

    plugin = Plugin()
    helper = CLIHelper()
    exit_code = 0
    try:
        if args.list_sinks:
            lines = helper.lines_for_sinks(plugin)
            helper.print_lines(lines)
            if lines[:1] == ["No sinks found."]:
                exit_code |= 1
        if args.list_running_apps:
            lines = helper.lines_for_running_apps(plugin)
            helper.print_lines(lines)
            if lines[:1] == ["No running apps detected."]:
                exit_code |= 1
        if args.print_highest_priority_sink:
            lines = helper.lines_for_highest_priority_sink(plugin)
            helper.print_lines(lines)
            if lines[:1] == ["Unable to determine a highest priority sink."]:
                exit_code |= 1
        if args.print_default_sink:
            lines = helper.lines_for_default_sink(plugin)
            helper.print_lines(lines)
            if lines[:1] == ["Unable to determine default sink."]:
                exit_code |= 1
    finally:
        helper.close()
    sys.exit(exit_code)
