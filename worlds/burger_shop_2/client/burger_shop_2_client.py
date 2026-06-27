"""Burger Shop 2 Archipelago client."""
from __future__ import annotations

import asyncio
import ctypes
import glob
import os
import struct
import sys

import Utils
from CommonClient import server_loop, gui_enabled, get_base_parser, logger
from NetUtils import ClientStatus

try:
    from worlds.tracker.TrackerClient import (
        TrackerGameContext, TrackerCommandProcessor as ClientCommandProcessor, UT_VERSION,
    )
    _tracker_loaded = True
except ImportError:
    from CommonClient import CommonContext as TrackerGameContext, ClientCommandProcessor
    _tracker_loaded = False
    UT_VERSION = "not installed"

from . import steam_utils
from .xml_patcher import apply_bs2_recipe_unlocks

# ── Game constants ────────────────────────────────────────────────────────────

POLL_INTERVAL: float = 1.0
_EXPERT_MODE_POLL_INTERVAL: float = 0.1  # how often to enforce the expert mode flag
_EXE_NAME: str = "BurgerShop2.exe"

MAX_LEVELS: int = 120
LEVEL_KEY_COUNT: int = 7
_GOAL_LEVELS: frozenset[int] = frozenset(range(MAX_LEVELS - 2, MAX_LEVELS + 1))  # {118, 119, 120}

# Confirmed pointer chains (via Cheat Engine).
# Expert story mode flag — write 1 every tick to force expert story.
_EXPERT_MODE_BASE: int = 0x377858
_EXPERT_MODE_OFFSETS: tuple[int, ...] = (0x90, 0x80C, 0x58, 0xDC)

# Level count for expert story mode.
_LEVEL_COUNT_BASE: int = 0x36AD00
_LEVEL_COUNT_OFFSETS: tuple[int, ...] = (0x6E8, 0x58, 0x270)

# Currently loaded profile name (the stem without "user_" prefix and ".dat" suffix).
_PROFILE_NAME_BASE: int = 0x372834
_PROFILE_NAME_OFFSETS: tuple[int, ...] = (0x80C, 0x58, 0x18)

# Coords.xml ox memory patches — hide special customer items until AP item is received.
# Each entry: AP item name → (base_offset, pointer_offsets, original_ox).
# Written every tick so the value is correct even when loading into a level.
# See COORDS_OX_ITEMS in recipe_data.py for the matching XML-side original values.
_COORDS_OX_HIDDEN: int = 2100000000
_COORDS_OX_CHAINS: dict[str, tuple[int, tuple[int, ...], int]] = {
    "Dog Biscuit": (0x3728C8, (0x80, 0xE3C), 21),
    "Shirt":       (0x3728C8, (0x80, 0xD9C), 38),
    "Menu":        (0x3728C8, (0x80, 0xCFC), 16),
}


# ── Sidecar helpers (.ap files alongside save files) ─────────────────────────

def _sidecar_path(save_file: str) -> str:
    return os.path.splitext(save_file)[0] + ".ap"


def _read_sidecar(save_file: str) -> tuple[str, frozenset[int]]:
    try:
        with open(_sidecar_path(save_file), "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        session_id = lines[0].strip() if lines else ""
        baseline: frozenset[int] = frozenset()
        if len(lines) > 1 and lines[1].strip():
            baseline = frozenset(
                int(n) for n in lines[1].split(",") if n.strip().isdigit()
            )
        return session_id, baseline
    except OSError:
        return "", frozenset()


def _is_session_save(save_file: str, session_id: str) -> bool:
    sid, _ = _read_sidecar(save_file)
    return bool(sid) and sid == session_id


def _mark_as_ap_save(save_file: str, session_id: str, baseline: frozenset[int]) -> None:
    with open(_sidecar_path(save_file), "w", encoding="utf-8") as f:
        f.write(session_id + "\n")
        f.write(",".join(str(n) for n in sorted(baseline)))


# ── Save file reading ─────────────────────────────────────────────────────────

def _find_story_section(data: bytes) -> tuple[int, int] | None:
    """
    Scan for the last valid (N, [optional TCEV], float32[N]) story block where
    1 ≤ N ≤ MAX_LEVELS, at least one float is in [0.5, 6.0], and every
    non-zero float is in [0.5, 6.0].  Zero entries represent levels not yet
    completed and are accepted; this matches the on-disk format where the game
    stores all N available level slots whether or not the player has beaten them.

    Returns (count_offset, tag_size) where tag_size is 0 or 4 (TCEV present).
    Returns None if no levels have been completed yet.
    """
    last_match: tuple[int, int] | None = None
    data_len = len(data)

    for pos in range(0, data_len - 8):
        n = struct.unpack_from("<I", data, pos)[0]
        if not (1 <= n <= MAX_LEVELS):
            continue
        for tag_size in (0, 4):
            if tag_size == 4:
                if data[pos + 4: pos + 8] != b"TCEV":
                    continue
            else:
                if data[pos + 4: pos + 8] == b"TCEV":
                    continue
            stars_start = pos + 4 + tag_size
            stars_end = stars_start + n * 4
            if stars_end > data_len:
                continue
            floats = [
                struct.unpack_from("<f", data, stars_start + i * 4)[0]
                for i in range(n)
            ]
            if (
                any(0.5 <= v <= 6.0 for v in floats)
                and all(v == 0.0 or 0.5 <= v <= 6.0 for v in floats)
            ):
                last_match = (pos, tag_size)
                break

    return last_match


def _find_save_file_bs2(save_dir: str, session_id: str) -> str | None:
    saves = [s for s in glob.glob(os.path.join(save_dir, "user*.dat"))
             if _is_session_save(s, session_id)]
    return max(saves, key=os.path.getmtime) if saves else None


def _read_completed_expert_levels(save_file: str, five_star: bool = True) -> set[int]:
    """
    Return 1-based level numbers for completed expert story levels.

    When five_star is True (default), only levels with exactly 5 stars (value >= 5.0)
    are counted.  When False, any non-zero star value counts as a completion.
    Returns an empty set if no levels have been played yet.
    """
    with open(save_file, "rb") as f:
        data = f.read()
    result = _find_story_section(data)
    if result is None:
        return set()
    count_off, tag_size = result
    n = struct.unpack_from("<I", data, count_off)[0]
    stars_base = count_off + 4 + tag_size
    completed: set[int] = set()
    for i in range(min(n, MAX_LEVELS)):
        stars_off = stars_base + i * 4
        if stars_off + 4 > len(data):
            break
        v = struct.unpack_from("<f", data, stars_off)[0]
        if (v >= 5.0) if five_star else (v > 0.0):
            completed.add(i + 1)
    return completed


# ── Process / memory helpers ──────────────────────────────────────────────────

def _find_game_pid() -> int | None:
    """Return the PID of the running BurgerShop2.exe process, or None."""
    try:
        import psutil
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"] and proc.info["name"].lower() == _EXE_NAME.lower():
                return proc.info["pid"]
    except Exception:
        pass
    return None


def _follow_pointer_chain(
    k32, handle, exe_base: int, base_offset: int, offsets: tuple[int, ...]
) -> int:
    """Follow a pointer chain rooted at (exe_base + base_offset); return final address or 0."""
    buf = ctypes.create_string_buffer(4)
    addr = exe_base + base_offset
    if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr), buf, 4, None):
        return 0
    addr = struct.unpack_from("<I", buf.raw)[0]
    if not addr:
        return 0
    for off in offsets[:-1]:
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr + off), buf, 4, None):
            return 0
        addr = struct.unpack_from("<I", buf.raw)[0]
        if not addr:
            return 0
    return addr + offsets[-1]


def _open_process_for_rw(k32, pid: int):
    """Open the process with read+write access; return handle or None."""
    handle = k32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400, False, pid)
    if not handle:
        logger.debug(f"[Burger Shop 2] OpenProcess failed for pid {pid}: {ctypes.get_last_error()}")
    return handle or None


def _get_exe_base(k32, pid: int) -> int:
    """Return the base address of _EXE_NAME in pid's module list, or 0."""
    TH32CS_SNAPMODULE = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010

    class ME32W(ctypes.Structure):
        _fields_ = [
            ("dwSize",        ctypes.c_uint32),
            ("th32ModuleID",  ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("GlblcntUsage",  ctypes.c_uint32),
            ("ProccntUsage",  ctypes.c_uint32),
            ("modBaseAddr",   ctypes.c_void_p),
            ("modBaseSize",   ctypes.c_uint32),
            ("hModule",       ctypes.c_void_p),
            ("szModule",      ctypes.c_wchar * 256),
            ("szExePath",     ctypes.c_wchar * 260),
        ]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    invalid = ctypes.c_void_p(-1).value
    if not snap or snap == invalid:
        return 0
    try:
        me = ME32W()
        me.dwSize = ctypes.sizeof(me)
        if k32.Module32FirstW(snap, ctypes.byref(me)):
            while True:
                if (me.szModule or "").lower() == _EXE_NAME.lower():
                    return me.modBaseAddr or 0
                if not k32.Module32NextW(snap, ctypes.byref(me)):
                    break
    finally:
        k32.CloseHandle(snap)
    logger.debug(f"[Burger Shop 2] {_EXE_NAME} module not found in pid {pid}.")
    return 0


def _read_int32(pid: int, base_offset: int, offsets: tuple[int, ...]) -> int | None:
    """Read a 32-bit integer via pointer chain; returns None on failure."""
    if sys.platform != "win32":
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    exe_base = _get_exe_base(k32, pid)
    if not exe_base:
        return None
    handle = _open_process_for_rw(k32, pid)
    if not handle:
        return None
    try:
        target = _follow_pointer_chain(k32, handle, exe_base, base_offset, offsets)
        if not target:
            return None
        buf = ctypes.create_string_buffer(4)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(target), buf, 4, None):
            return None
        return struct.unpack_from("<I", buf.raw)[0]
    finally:
        k32.CloseHandle(handle)


def _read_profile_name(pid: int) -> str | None:
    """Return the name of the currently loaded save profile (without 'user_' prefix), or None."""
    if sys.platform != "win32":
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    exe_base = _get_exe_base(k32, pid)
    if not exe_base:
        return None
    handle = _open_process_for_rw(k32, pid)
    if not handle:
        return None
    try:
        target = _follow_pointer_chain(k32, handle, exe_base, _PROFILE_NAME_BASE, _PROFILE_NAME_OFFSETS)
        if not target:
            return None
        buf = ctypes.create_string_buffer(64)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(target), buf, 64, None):
            return None
        raw = buf.raw
        null_pos = raw.find(b"\x00")
        text = raw[:null_pos if null_pos >= 0 else 64].decode("ascii", errors="replace")
        return text or None
    finally:
        k32.CloseHandle(handle)


def _write_int32(pid: int, base_offset: int, offsets: tuple[int, ...], value: int) -> bool:
    """Write a 32-bit integer via pointer chain; returns True on success."""
    if sys.platform != "win32":
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    exe_base = _get_exe_base(k32, pid)
    if not exe_base:
        return False
    handle = _open_process_for_rw(k32, pid)
    if not handle:
        return False
    try:
        target = _follow_pointer_chain(k32, handle, exe_base, base_offset, offsets)
        if not target:
            return False
        payload = struct.pack("<I", value)
        n_written = ctypes.c_size_t(0)
        return bool(k32.WriteProcessMemory(handle, ctypes.c_void_p(target), payload, 4,
                                           ctypes.byref(n_written)))
    finally:
        k32.CloseHandle(handle)


def _scan_replace_memory(k32, handle, old_bytes: bytes, new_bytes: bytes) -> int:
    """Scan all writable process regions for old_bytes; overwrite with new_bytes. Returns count."""
    class _MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress",       ctypes.c_size_t),
            ("AllocationBase",    ctypes.c_size_t),
            ("AllocationProtect", ctypes.c_ulong),
            ("RegionSize",        ctypes.c_size_t),
            ("State",             ctypes.c_ulong),
            ("Protect",           ctypes.c_ulong),
            ("Type",              ctypes.c_ulong),
        ]

    MEM_COMMIT = 0x1000
    PAGE_GUARD = 0x100
    WRITABLE = {0x04, 0x08, 0x40, 0x80}

    addr = 0
    count = 0
    mbi = _MBI()
    mbi_size = ctypes.sizeof(mbi)

    while k32.VirtualQueryEx(handle, ctypes.c_size_t(addr), ctypes.byref(mbi), mbi_size):
        base, size = mbi.BaseAddress, mbi.RegionSize
        protect = mbi.Protect & ~PAGE_GUARD
        if mbi.State == MEM_COMMIT and protect in WRITABLE and size > 0:
            buf = ctypes.create_string_buffer(size)
            n_read = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(handle, ctypes.c_size_t(base), buf, size,
                                     ctypes.byref(n_read)):
                data = buf.raw[: n_read.value]
                pos = 0
                while True:
                    idx = data.find(old_bytes, pos)
                    if idx < 0:
                        break
                    k32.WriteProcessMemory(handle, ctypes.c_size_t(base + idx),
                                           new_bytes, len(new_bytes), None)
                    count += 1
                    pos = idx + len(old_bytes)
        next_addr = base + max(size, 1)
        if next_addr <= addr:
            break
        addr = next_addr
    return count


def _patch_game_values_in_memory(pid: int, changes: list[tuple[str, str]]) -> None:
    """Scan game memory and replace each (old_value, new_value) numeric string pair."""
    if sys.platform != "win32" or not changes:
        return
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.OpenProcess(0x0010 | 0x0020 | 0x0400, False, pid)
    if not handle:
        return
    try:
        for old_str, new_str in changes:
            try:
                old_f, new_f = float(old_str), float(new_str)
            except ValueError:
                continue
            total = 0
            try:
                ob32, nb32 = struct.pack("<f", old_f), struct.pack("<f", new_f)
                if ob32 != nb32:
                    total += _scan_replace_memory(k32, handle, ob32, nb32)
            except (struct.error, OverflowError):
                pass
            try:
                old_i, new_i = int(old_f), int(new_f)
                if 0 <= old_i < 2**32 and 0 <= new_i < 2**32:
                    ob_u32 = struct.pack("<I", old_i)
                    nb_u32 = struct.pack("<I", new_i)
                    if ob_u32 != nb_u32:
                        total += _scan_replace_memory(k32, handle, ob_u32, nb_u32)
            except (struct.error, OverflowError):
                pass
            if total:
                logger.debug(
                    f"[Burger Shop 2] Memory-patched {old_str!r} -> {new_str!r} "
                    f"({total} location(s))"
                )
    finally:
        k32.CloseHandle(handle)


def _compute_level_target(key_count: int) -> int:
    """Return the 0-based level count to write to memory.

    With fewer than all 7 keys each key unlocks the next block of 15 levels.
    With all 7 keys levels 118, 119, and 120 all unlock at once.
    """
    if key_count < LEVEL_KEY_COUNT:
        return 15 * (1 + key_count) - 1  # 0 keys → 14, 6 keys → 104
    return MAX_LEVELS - 1             # all 7 keys → unlock 118, 119, and 120


# ── Command processor ─────────────────────────────────────────────────────────

class BurgerShop2CommandProcessor(ClientCommandProcessor):
    ctx: "BurgerShop2Context"

    def _cmd_launch(self) -> bool:
        """Launch Burger Shop 2 via Steam."""
        self.ctx.launch_game()
        return True

    def _cmd_gamepath(self) -> bool:
        """Print the detected Burger Shop 2 installation path."""
        self.output(f"Game path: {self.ctx.game_path or 'Not found'}")
        return True

    def _cmd_savepath(self) -> bool:
        """Print the detected save data directory."""
        self.output(f"Save path: {self.ctx.save_path or 'Not found'}")
        return True


# ── Context ───────────────────────────────────────────────────────────────────

class BurgerShop2Context(TrackerGameContext):
    game = "Burger Shop 2"
    items_handling = 0b111
    command_processor = BurgerShop2CommandProcessor
    tags = {"AP"}  # drop "Tracker" tag so the server allows LocationChecks from this client

    game_path: str | None = None
    save_path: str | None = None
    slot_data: dict = {}
    _last_recipe_items: tuple[str, ...] | None = None
    _generation_uid: str = ""
    _five_star_mode: bool = True
    _game_loop_started: bool = False
    _save_status_after_prints: int = 0
    _known_save_files: set[str]
    _pending_new_saves: set[str]

    def make_gui(self):
        ui = super().make_gui()
        if not _tracker_loaded:
            logger.info("[Burger Shop 2] Install Universal Tracker to enable the tracker page.")
        return ui

    def __init__(self, server_address: str | None, password: str | None) -> None:
        super().__init__(server_address, password)
        self._known_save_files = set()
        self._pending_new_saves = set()
        self._pending_starter_ids: list[int] = []
        self._locate_game()
        self._locate_save_dir()

    # ── Startup detection ────────────────────────────────────────────────────

    def _locate_game(self) -> None:
        """Resolve the game installation path via Steam auto-detection."""
        detected = steam_utils.find_game_install_path_bs2()
        if detected:
            self.game_path = detected
            logger.debug(f"[Burger Shop 2] Auto-detected game installation: {self.game_path}")
        else:
            logger.warning(
                "[Burger Shop 2] Game installation not found. "
                "Ensure Burger Shop 2 is installed in Steam."
            )

    def _locate_save_dir(self) -> None:
        """Resolve the save data directory (%APPDATA%\\GoBit Games\\BurgerShop2\\Steam\\users\\{id})."""
        detected = steam_utils.find_save_directory_bs2()
        if detected:
            self.save_path = detected
            logger.debug(f"[Burger Shop 2] Save directory: {self.save_path}")
            existing = set(glob.glob(os.path.join(detected, "user*.dat")))
            self._known_save_files = existing
            for ap_file in glob.glob(os.path.join(detected, "user*.ap")):
                dat_file = os.path.splitext(ap_file)[0] + ".dat"
                if dat_file not in existing:
                    try:
                        os.remove(ap_file)
                        logger.debug(
                            f"[Burger Shop 2] Removed orphaned sidecar: "
                            f"{os.path.basename(ap_file)}"
                        )
                    except OSError:
                        pass
        else:
            logger.warning(
                "[Burger Shop 2] Save directory not found under "
                "%APPDATA%\\GoBit Games\\BurgerShop2. "
                "Launch the game at least once so the save folder is created."
            )

    # ── Game launching ───────────────────────────────────────────────────────

    def launch_game(self) -> None:
        Utils.open_file(f"steam://rungameid/{steam_utils.BURGER_SHOP_2_STEAM_APP_ID}")
        logger.info("[Burger Shop 2] Launched via Steam.")

    # ── AP server hooks ──────────────────────────────────────────────────────

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    # ── Game loop ────────────────────────────────────────────────────────────

    @property
    def _session_id(self) -> str:
        return f"{self.seed_name}:{self.team}:{self.slot}:{self._generation_uid}"

    def _log_save_status(self) -> None:
        """Log which session save files are currently detected, or that none exist yet."""
        if not self.save_path:
            return
        saves = sorted(
            s for s in glob.glob(os.path.join(self.save_path, "user*.dat"))
            if _is_session_save(s, self._session_id)
        )
        if not saves:
            logger.info("[Burger Shop 2] Waiting for save file to be created.")
        elif len(saves) == 1:
            name = os.path.splitext(os.path.basename(saves[0]))[0].removeprefix("user_")
            logger.info(f"[Burger Shop 2] Save file found: {name}")
        else:
            names = ", ".join(
                os.path.splitext(os.path.basename(s))[0].removeprefix("user_") for s in saves
            )
            logger.info(f"[Burger Shop 2] Multiple save files found: {names}")

    def on_package(self, cmd: str, args: dict) -> None:
        super().on_package(cmd, args)
        if cmd == "PrintJSON" and self._save_status_after_prints > 0:
            self._save_status_after_prints -= 1
            if self._save_status_after_prints == 0:
                self._log_save_status()
        elif cmd == "Connected":
            slot_data = args.get("slot_data", {})
            self.slot_data = slot_data
            self._generation_uid = str(slot_data.get("generation_uid", ""))
            self._five_star_mode = bool(slot_data.get("five_star_mode", 1))
            if not self._game_loop_started:
                self._game_loop_started = True
                Utils.async_start(self.game_loop(), name="BurgerShop2_game_loop")
                Utils.async_start(self._expert_mode_loop(), name="BurgerShop2_expert_mode")
                self._save_status_after_prints = 2
            else:
                self._log_save_status()
            starter_assignments = slot_data.get("starter_assignments", {})
            if starter_assignments:
                from worlds.burger_shop_2.locations import LOCATION_NAME_TO_ID
                self._pending_starter_ids = [
                    LOCATION_NAME_TO_ID[name]
                    for name in starter_assignments
                    if name in LOCATION_NAME_TO_ID
                ]

    def _count_level_keys(self) -> int:
        """Return the number of Level Key items received, capped at LEVEL_KEY_COUNT."""
        from worlds.burger_shop_2.items import ITEM_NAME_TO_ID, LEVEL_KEY_ITEM
        key_id = ITEM_NAME_TO_ID[LEVEL_KEY_ITEM]
        return min(
            sum(1 for item in self.items_received if item.item == key_id),
            LEVEL_KEY_COUNT,
        )

    def _get_received_recipe_names(self) -> list[str]:
        """Return all received AP item names that affect XML recipes."""
        from worlds.burger_shop_2.items import ITEM_NAME_TO_ID
        id_to_name = {v: k for k, v in ITEM_NAME_TO_ID.items()}
        return [
            name
            for item in self.items_received
            if (name := id_to_name.get(item.item)) is not None
        ]

    def _watch_for_new_saves(self) -> None:
        """Create sidecars for new .dat files; delete sidecars for deleted .dat files."""
        if not self.save_path:
            return
        current = set(glob.glob(os.path.join(self.save_path, "user*.dat")))
        session_id = self._session_id

        for save_file in current - self._known_save_files:
            if not os.path.exists(_sidecar_path(save_file)):
                self._pending_new_saves.add(save_file)

        for save_file in list(self._pending_new_saves):
            if save_file not in current:
                self._pending_new_saves.discard(save_file)
                continue
            try:
                baseline = frozenset(_read_completed_expert_levels(save_file, self._five_star_mode))
            except Exception:
                continue  # file not readable yet — retry next tick
            try:
                _mark_as_ap_save(save_file, session_id, baseline)
                self._pending_new_saves.discard(save_file)
                if baseline:
                    logger.debug(
                        f"[Burger Shop 2] {os.path.basename(save_file)}: "
                        f"{len(baseline)} pre-existing expert level(s) excluded."
                    )
                self._log_save_status()
            except Exception:
                pass

        for save_file in self._known_save_files - current:
            sidecar = _sidecar_path(save_file)
            if os.path.exists(sidecar):
                try:
                    os.remove(sidecar)
                    logger.debug(
                        f"[Burger Shop 2] Removed sidecar for deleted save: "
                        f"{os.path.basename(save_file)}"
                    )
                except OSError:
                    pass
            self._pending_new_saves.discard(save_file)

        self._known_save_files = current

    async def _expert_mode_loop(self) -> None:
        """Write the expert story mode flag to 1 every 100 ms while the game is running.

        The game resets this flag to 0 when the player presses the Story Mode button,
        then reads it during the loading screen to decide which story mode to enter.
        Polling at 100 ms ensures the flag is corrected well within the load window.
        """
        while not self.exit_event.is_set():
            pid = _find_game_pid()
            if pid is not None and self.save_path:
                profile_name = _read_profile_name(pid)
                if profile_name is not None:
                    save_file = os.path.join(self.save_path, f"user_{profile_name}.dat")
                    if _is_session_save(save_file, self._session_id):
                        _write_int32(pid, _EXPERT_MODE_BASE, _EXPERT_MODE_OFFSETS, 1)
            await asyncio.sleep(_EXPERT_MODE_POLL_INTERVAL)

    async def game_loop(self) -> None:
        logger.debug("[Burger Shop 2] Game watcher started.")
        while not self.exit_event.is_set():
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"[Burger Shop 2] Error in game loop: {e}")
            await asyncio.sleep(POLL_INTERVAL)
        logger.debug("[Burger Shop 2] Game watcher stopped.")

    async def _tick(self) -> None:
        from worlds.burger_shop_2.locations import LOCATION_NAME_TO_ID

        recipe_items = self._get_received_recipe_names()
        recipe_key = tuple(sorted(recipe_items))
        pid = _find_game_pid()

        if recipe_key != self._last_recipe_items and self.game_path:
            _, game_changes = apply_bs2_recipe_unlocks(self.game_path, recipe_items)
            self._last_recipe_items = recipe_key
            if game_changes and pid is not None:
                _patch_game_values_in_memory(pid, game_changes)

        # Read save data to track completed levels for the goal condition.
        save_file: str | None = None
        baseline: frozenset[int] = frozenset()
        completed: set[int] = set()

        if self.save_path:
            self._watch_for_new_saves()
            save_file = _find_save_file_bs2(self.save_path, self._session_id)
            if save_file is not None:
                _, baseline = _read_sidecar(save_file)
                try:
                    completed = _read_completed_expert_levels(save_file, self._five_star_mode)
                except Exception as e:
                    logger.debug(f"[Burger Shop 2] Could not read expert levels: {e}")
                    save_file = None

        if pid is not None:
            profile_name = _read_profile_name(pid)
            ap_profile_loaded = (
                save_file is not None
                and profile_name is not None
                and os.path.basename(save_file) == f"user_{profile_name}.dat"
            )
            if ap_profile_loaded:
                key_count = self._count_level_keys()
                target = _compute_level_target(key_count)
                current = _read_int32(pid, _LEVEL_COUNT_BASE, _LEVEL_COUNT_OFFSETS)
                if current is not None and current != target:
                    logger.debug(f"[Burger Shop 2] Level count: {current} → {target}")
                _write_int32(pid, _LEVEL_COUNT_BASE, _LEVEL_COUNT_OFFSETS, target)

                received_set = frozenset(recipe_items)
                for item_name, (base, offsets, original_ox) in _COORDS_OX_CHAINS.items():
                    ox_val = original_ox if item_name in received_set else _COORDS_OX_HIDDEN
                    _write_int32(pid, base, offsets, ox_val)

        if save_file is None:
            return

        above_baseline = completed - baseline
        new_checks = [
            LOCATION_NAME_TO_ID[f"Story Level {n}"]
            for n in above_baseline
            if LOCATION_NAME_TO_ID.get(f"Story Level {n}") not in self.locations_checked
        ]

        if above_baseline and self._pending_starter_ids:
            new_checks.extend(
                loc_id for loc_id in self._pending_starter_ids
                if loc_id not in self.locations_checked
            )
            self._pending_starter_ids = []

        if new_checks:
            await self.send_msgs([{"cmd": "LocationChecks", "locations": new_checks}])

        if not self.finished_game and _GOAL_LEVELS.issubset(above_baseline):
            await self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
            self.finished_game = True


# ── Entry point ───────────────────────────────────────────────────────────────

def main(url: str | None = None) -> None:
    Utils.init_logging("BurgerShop2Client", exception_logger="Client")

    async def _main() -> None:
        ctx = BurgerShop2Context(url, None)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="BurgerShop2_server_loop")
        if _tracker_loaded:
            ctx.run_generator()
        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()
        await ctx.exit_event.wait()
        await ctx.shutdown()

    import colorama
    colorama.init()
    try:
        asyncio.run(_main())
    except asyncio.CancelledError:
        pass


def launch(*args: str) -> None:
    main(args[0] if args else None)


if __name__ == "__main__":
    parser = get_base_parser(description="Burger Shop 2 Archipelago Client")
    args = parser.parse_args()
    main(args.connect)
