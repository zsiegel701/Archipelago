"""Burger Shop 2 Archipelago client."""
from __future__ import annotations

import asyncio
import ctypes

import os
import re
import struct
import sys
import uuid

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

from . import save_template, steam_utils
from .save_file import (
    MAX_LEVELS, ensure_level_slots, mark_levels_complete, read_completed_levels,
)
from .xml_patcher import apply_bs2_recipe_unlocks, restart_sensitive_hash

# ── Game constants ────────────────────────────────────────────────────────────

POLL_INTERVAL: float = 1.0
# The game clears the expert story flag when Story Mode is pressed and reads it back
# during the loading screen, and it applies a profile's level access the instant it loads
# it — both windows are far shorter than the save-file poll.  Everything written into the
# running game therefore runs on its own much shorter interval.
_MEMORY_POLL_INTERVAL: float = 0.1
_EXE_NAME: str = "BurgerShop2.exe"

LEVEL_KEY_COUNT: int = 7
# Beating the last three story levels is what sends the goal, so they are the levels
# that are never completed on the player's behalf when their checks are collected.
_GOAL_LEVELS: frozenset[int] = frozenset(range(MAX_LEVELS - 2, MAX_LEVELS + 1))  # {118, 119, 120}

# Data-storage key holding a UUID minted the first time any Burger Shop client connects to
# a room.  Both games share it: it identifies the room, not the slot.  The server keeps
# stored data in the room's save file, so deleting that file drops the key and the next
# connect mints a new ID — which is exactly the signal that the room was reset.
_ROOM_ID_KEY: str = "BurgerShop:room_id"

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

# The loaded profile's expert story level state — one float32 star rating per level, so
# level N is at index N-1 and 5.0 means a five-star clear.  It hangs off the same profile
# object as the name above, one dereference deeper.
# *(*(*(*(BurgerShop2.exe + 0x372834) + 0x80C) + 0x58) + 0x294) + 0 = float32[MAX_LEVELS]
_LEVEL_STATE_BASE: int = 0x372834
_LEVEL_STATE_OFFSETS: tuple[int, ...] = (0x80C, 0x58, 0x294, 0)

_FIVE_STARS: float = 5.0
# A resolved chain is only trusted when every entry already looks like a star rating.
# Star ratings are 0.0 for an unplayed level and otherwise sit in this range, so anything
# else means the chain landed somewhere it should not be written to.
_STAR_RANGE: tuple[float, float] = (0.5, 6.0)

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


# ── The Archipelago profile and its sidecar ──────────────────────────────────
#
# The client owns one save file, "user_Archipelago.dat", instead of asking the player to
# make their own and then guessing which of their profiles belongs to the session.  Next
# to it sits a one-line .ap sidecar naming the session the profile currently holds:
#
#   "{room_id}:{team}:{slot}"
#
# The room ID comes from the server's data storage, which lives in the room's own save
# file.  That makes it the one thing that changes when a room is wiped: the seed name and
# the generation UID survive deleting a room's save, so keying on them left the client
# unable to tell a reset room from an ordinary reconnect.
#
# Reconnecting to that same session keeps the profile and picks up its progress.  A
# different session means the profile belongs to a finished game, so it is laid down
# fresh from the pristine template and the sidecar is restamped.  Because a fresh profile
# has no progress of its own, there is no pre-existing story data to filter out — the
# whole "baseline" idea the old player-owned-save flow needed is gone.
#
# Reading and editing the .dat format itself lives in save_file.py.

def _sidecar_path(save_file: str) -> str:
    """Return the .ap sidecar path for a given .dat save file."""
    return os.path.splitext(save_file)[0] + ".ap"


def _read_sidecar(save_file: str) -> str:
    """Return the session ID recorded next to save_file, or "" if there is none."""
    try:
        with open(_sidecar_path(save_file), "r", encoding="utf-8") as f:
            return f.read().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def _write_sidecar(save_file: str, session_id: str) -> None:
    """Record which session the save file currently holds."""
    with open(_sidecar_path(save_file), "w", encoding="utf-8") as f:
        f.write(session_id + "\n")


def _remove_stale_sidecars(save_dir: str) -> None:
    """Delete .ap sidecars left beside profiles the client no longer owns.

    Earlier versions asked the player to make their own save file and stamped a sidecar
    next to whichever one they picked.  Only the Archipelago profile has one now, so the
    rest are never read again.  A sidecar holds nothing but a session ID, so removing one
    loses no progress — the .dat beside it is left alone.
    """
    keep = os.path.basename(_sidecar_path(save_template.SAVE_FILENAME))
    try:
        names = os.listdir(save_dir)
    except OSError:
        return
    for name in names:
        if name == keep or not name.startswith("user_") or not name.endswith(".ap"):
            continue
        try:
            os.remove(os.path.join(save_dir, name))
            logger.debug(f"[Burger Shop 2] Removed stale sidecar {name}.")
        except OSError as e:
            logger.debug(f"[Burger Shop 2] Could not remove stale sidecar {name}: {e}")


def _write_pristine_save(save_file: str) -> None:
    """Lay down a blank Archipelago profile, replacing whatever was there."""
    temp = save_file + ".aptmp"
    with open(temp, "wb") as f:
        f.write(save_template.PRISTINE_SAVE)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, save_file)
    # The backup save_file.py keeps of its first edit describes the session just replaced.
    try:
        os.remove(save_file + ".apbak")
    except OSError:
        pass


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


def _terminate_game(pid: int, timeout: float = 10.0) -> bool:
    """Ask the game process to close, escalating to a kill; True once it is gone."""
    try:
        import psutil
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=timeout)
        return True
    except Exception as e:
        logger.debug(f"[Burger Shop 2] Failed to terminate pid {pid}: {e}")
        return False


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
    return 0


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
        text = raw[:null_pos if null_pos >= 0 else 64].decode("latin-1")
        return text or None
    finally:
        k32.CloseHandle(handle)


def _write_int32_batch(pid: int, writes: list[tuple[int, tuple[int, ...], int]]) -> None:
    """Write several (base_offset, offsets, value) pointer-chain targets in one pass.

    Opening the process and snapshotting its module list once per value would be wasteful
    at the rate the memory loop runs, so the whole batch shares a single handle.
    """
    if sys.platform != "win32" or not writes:
        return
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    exe_base = _get_exe_base(k32, pid)
    if not exe_base:
        return
    handle = _open_process_for_rw(k32, pid)
    if not handle:
        return
    try:
        for base_offset, offsets, value in writes:
            target = _follow_pointer_chain(k32, handle, exe_base, base_offset, offsets)
            if target:
                k32.WriteProcessMemory(handle, ctypes.c_void_p(target),
                                       struct.pack("<I", value), 4, None)
    finally:
        k32.CloseHandle(handle)


def _sync_level_stars(pid: int, beaten: set[int]) -> tuple[float, ...] | None:
    """
    Mark the given 1-based expert story levels as five-star clears, and report every rating.

    Reading and writing share one pass because the caller wants both.  Returns None if the
    array could not be read or does not look like star ratings — a chain that resolved to
    the wrong object would otherwise be scribbled over, and this runs against a live
    process many times a second.
    """
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
        array = _follow_pointer_chain(k32, handle, exe_base, _LEVEL_STATE_BASE,
                                      _LEVEL_STATE_OFFSETS)
        if not array:
            return None

        buf = ctypes.create_string_buffer(MAX_LEVELS * 4)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(array), buf, MAX_LEVELS * 4, None):
            return None
        stars = list(struct.unpack(f"<{MAX_LEVELS}f", buf.raw))

        low, high = _STAR_RANGE
        if not all(v == 0.0 or low <= v <= high for v in stars):
            return None

        payload = struct.pack("<f", _FIVE_STARS)
        for level in sorted(beaten):
            if not 1 <= level <= MAX_LEVELS or stars[level - 1] >= _FIVE_STARS:
                continue
            if k32.WriteProcessMemory(handle, ctypes.c_void_p(array + (level - 1) * 4),
                                      payload, 4, None):
                stars[level - 1] = _FIVE_STARS
        return tuple(stars)
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

    def _cmd_restart(self) -> bool:
        """Close Burger Shop 2 if it is running, then relaunch it via Steam."""
        Utils.async_start(self.ctx.restart_game(), name="BurgerShop2_restart")
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
    _five_star_mode: bool = True
    _customer_slots: int = 0  # 0 = keep the vanilla per-level counts
    # Resolved <Customer> id -> character groups, rebuilt from slot data with the same
    # function generation used, so the game matches the logic the seed was built with.
    _character_map: dict | None = None
    _game_loop_started: bool = False
    _restart_required: bool = False
    _last_problem: str = ""
    _stale_profile_warned: bool = False
    _room_id: str = ""
    _session_save_ready: bool = False  # the profile on disk belongs to this session
    _cached_pid: int | None = None
    _coords_ids: dict[str, int] | None = None

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago Burger Shop 2 Client"
        if not _tracker_loaded:
            logger.info("[Burger Shop 2] Install Universal Tracker to enable the tracker page.")
        return ui

    def __init__(self, server_address: str | None, password: str | None) -> None:
        super().__init__(server_address, password)
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
            _remove_stale_sidecars(detected)
        else:
            logger.warning(
                "[Burger Shop 2] Save directory not found under "
                "%APPDATA%\\GoBit Games\\BurgerShop2. "
                "Launch the game at least once so the save folder is created."
            )

    @property
    def save_file(self) -> str | None:
        """Path to the Archipelago profile, or None until the save folder is known."""
        if not self.save_path:
            return None
        return os.path.join(self.save_path, save_template.SAVE_FILENAME)

    # ── Game launching ───────────────────────────────────────────────────────

    def launch_game(self) -> None:
        Utils.open_file(f"steam://rungameid/{steam_utils.BURGER_SHOP_2_STEAM_APP_ID}")
        logger.info("[Burger Shop 2] Launched via Steam.")

    async def restart_game(self) -> None:
        """Close the running game (if any) and launch it again."""
        pid = _find_game_pid()
        if pid is None:
            self.launch_game()
            return
        logger.info("[Burger Shop 2] Closing the game...")
        if not await asyncio.to_thread(_terminate_game, pid):
            logger.error(
                "[Burger Shop 2] Could not close the game. Please close and relaunch it manually."
            )
            return
        self.launch_game()

    # ── AP server hooks ──────────────────────────────────────────────────────

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    # ── Game loop ────────────────────────────────────────────────────────────

    @property
    def _session_id(self) -> str:
        """Identifies the room this profile belongs to, or "" until the room ID arrives.

        The room ID is minted into the server's data storage on connect, which lives in
        the room's own save file.  Deleting that file therefore produces a new ID and the
        profile is laid down fresh, while a reconnect or a server restart keeps it.  Team
        and slot are appended so that playing a different slot of the same room gets its
        own profile.
        """
        if not self._room_id:
            return ""
        return f"{self._room_id}:{self.team}:{self.slot}"

    async def _acquire_room_id(self) -> None:
        """Claim or read back this room's ID.

        The "default" operation leaves an existing value alone, so whichever client gets
        there first decides the ID and every later one reads the same answer back out of
        the reply — no race, one round trip.
        """
        await self.send_msgs([{
            "cmd": "Set",
            "key": _ROOM_ID_KEY,
            "default": uuid.uuid4().hex,
            "operations": [{"operation": "default", "value": None}],
            "want_reply": True,
        }])

    def on_package(self, cmd: str, args: dict) -> None:
        super().on_package(cmd, args)
        if cmd == "SetReply" and args.get("key") == _ROOM_ID_KEY:
            self._room_id = str(args.get("value") or "")
        elif cmd == "Connected":
            self._room_id = ""
            slot_data = args.get("slot_data", {})
            self.slot_data = slot_data
            self._five_star_mode = bool(slot_data.get("five_star_mode", 1))
            self._customer_slots = int(slot_data.get("customer_slots", 0))
            from worlds.burger_shop_2 import character_shuffle
            mode = int(slot_data.get("character_randomization", character_shuffle.VANILLA))
            self._character_map = (
                None if mode == character_shuffle.VANILLA
                else character_shuffle.resolve(mode, int(slot_data.get("character_seed", 0)))
            )
            if not self._game_loop_started:
                self._game_loop_started = True
                Utils.async_start(self.game_loop(), name="BurgerShop2_game_loop")
                Utils.async_start(self.memory_loop(), name="BurgerShop2_memory_loop")
            Utils.async_start(self._acquire_room_id(), name="BurgerShop2_room_id")
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

    def _collected_levels(self) -> set[int]:
        """Story levels the server already counts as checked.

        A level lands here once its check has been sent — by this client in an earlier
        session, or by ``!collect`` handing the item it held to a player who has finished.
        Either way the item is gone, so there is nothing left to earn by playing it.
        """
        from worlds.burger_shop_2.locations import LOCATION_NAME_TO_ID
        return {
            level
            for level in range(1, MAX_LEVELS + 1)
            if level not in _GOAL_LEVELS
            and LOCATION_NAME_TO_ID[f"Story Level {level}"] in self.checked_locations
        }

    def _log_problem(self, message: str) -> None:
        """Report a failure from the polling loops, without repeating it.

        These run one to ten times a second, so anything that keeps failing would other-
        wise fill the console.  Only a change in the message gets through, which still
        surfaces a new problem straight away and keeps a stuck one to a single line.
        """
        if message == self._last_problem:
            return
        self._last_problem = message
        logger.error(message)

    def _apply_collected_levels(self, save_file: str, completed: set[int]) -> set[int]:
        """Complete already-checked levels in the save file; return the levels marked."""
        pending = self._collected_levels() - completed
        if not pending:
            return set()
        try:
            return mark_levels_complete(save_file, pending)
        except Exception as e:
            self._log_problem(f"[Burger Shop 2] Could not update the "
                              f"{save_template.PROFILE_NAME} profile: {e}")
            return set()

    def _prepare_session_save(self) -> bool:
        """Make sure the Archipelago profile exists and belongs to the current session.

        A profile whose sidecar names a different session is left over from a game that is
        over, so it is replaced with a blank one.  A profile already stamped with this
        session is kept untouched, which is what lets a reconnect pick up whatever progress
        the player has made since.  Returns False if the profile is not usable yet.
        """
        save_file = self.save_file
        if save_file is None or not self._session_id:
            return False

        if os.path.exists(save_file) and _read_sidecar(save_file) == self._session_id:
            return True

        try:
            _write_pristine_save(save_file)
            _write_sidecar(save_file, self._session_id)
        except OSError as e:
            self._log_problem(f"[Burger Shop 2] Could not create the "
                              f"{save_template.PROFILE_NAME} profile: {e}")
            return False
        return True

    def _restore_level_slots(self, save_file: str) -> None:
        """Widen the profile back to the full set of level slots if the game trimmed it."""
        try:
            ensure_level_slots(save_file)
        except Exception as e:
            self._log_problem(f"[Burger Shop 2] Could not update the "
                              f"{save_template.PROFILE_NAME} profile: {e}")

    def _game_pid(self) -> int | None:
        """_find_game_pid, without walking the whole process list many times a second."""
        if self._cached_pid is not None:
            try:
                import psutil
                if psutil.pid_exists(self._cached_pid):
                    return self._cached_pid
            except Exception:
                pass
            self._cached_pid = None
        self._cached_pid = _find_game_pid()
        return self._cached_pid

    def _coords_ox_ids(self) -> dict[str, int]:
        """Item IDs for the Coords.xml entries, resolved once."""
        if self._coords_ids is None:
            from worlds.burger_shop_2.items import ITEM_NAME_TO_ID
            self._coords_ids = {
                name: ITEM_NAME_TO_ID[name]
                for name in _COORDS_OX_CHAINS
                if name in ITEM_NAME_TO_ID
            }
        return self._coords_ids

    def _patch_game_memory(self) -> None:
        """Hold the running game to what this session says it should be.

        Only ever touches a game sitting on this session's Archipelago profile: _tick has
        already decided whether the save file is usable, and the profile name is checked
        here because the player can switch profiles between passes.
        """
        if not self._session_save_ready or self._restart_required:
            return
        pid = self._game_pid()
        if pid is None:
            return
        profile_name = _read_profile_name(pid)
        if profile_name is None:
            self._cached_pid = None
            return
        if re.sub(r"[^A-Za-z0-9]", "_", profile_name) != save_template.PROFILE_NAME:
            return

        received = {item.item for item in self.items_received}
        writes = [
            # Forced back to 1 continuously: the game clears it when Story Mode is pressed
            # and reads it during the load screen to pick which story to enter.
            (_EXPERT_MODE_BASE, _EXPERT_MODE_OFFSETS, 1),
            (_LEVEL_COUNT_BASE, _LEVEL_COUNT_OFFSETS,
             _compute_level_target(self._count_level_keys())),
        ]
        for name, (base, offsets, original_ox) in _COORDS_OX_CHAINS.items():
            item_id = self._coords_ox_ids().get(name)
            unlocked = item_id is not None and item_id in received
            writes.append((base, offsets, original_ox if unlocked else _COORDS_OX_HIDDEN))
        _write_int32_batch(pid, writes)

        # Show collected levels as beaten straight away, rather than only once the game is
        # closed and the save file can be edited.
        _sync_level_stars(pid, self._collected_levels())

    async def memory_loop(self) -> None:
        logger.debug("[Burger Shop 2] Memory writer started.")
        while not self.exit_event.is_set():
            try:
                self._patch_game_memory()
            except Exception as e:
                self._log_problem(f"[Burger Shop 2] Error in memory loop: {e}")
            await asyncio.sleep(_MEMORY_POLL_INTERVAL)
        logger.debug("[Burger Shop 2] Memory writer stopped.")

    async def game_loop(self) -> None:
        logger.debug("[Burger Shop 2] Game watcher started.")
        while not self.exit_event.is_set():
            try:
                await self._tick()
            except Exception as e:
                self._log_problem(f"[Burger Shop 2] Error in game loop: {e}")
            await asyncio.sleep(POLL_INTERVAL)
        logger.debug("[Burger Shop 2] Game watcher stopped.")

    async def _tick(self) -> None:
        from worlds.burger_shop_2.locations import LOCATION_NAME_TO_ID

        recipe_items = self._get_received_recipe_names()
        recipe_key = tuple(sorted(recipe_items))
        pid = _find_game_pid()

        if recipe_key != self._last_recipe_items and self.game_path:
            # Game.xml and GameExp.xml are parsed once at process start, so a change to
            # them while the game is running is invisible until it is relaunched.  In
            # practice this only happens on the first tick, when the level data for this
            # seed is written for the first time.
            before = restart_sensitive_hash(self.game_path) if pid is not None else ""
            _, game_changes = apply_bs2_recipe_unlocks(
                self.game_path, recipe_items, self._customer_slots, self._character_map,
            )
            self._last_recipe_items = recipe_key
            if pid is not None:
                if game_changes:
                    _patch_game_values_in_memory(pid, game_changes)
                if before and restart_sensitive_hash(self.game_path) != before:
                    self._restart_required = True
                    logger.warning(
                        "[Burger Shop 2] Level data changed, but Burger Shop 2 is already "
                        "running. Close and relaunch the game (or use /restart) before "
                        "loading your save file. Progress made until then is not tracked."
                    )

        # The running game is working from the level data it read at launch, so nothing
        # it reports matches this seed.  Track nothing until the process is gone.
        if self._restart_required:
            if pid is not None:
                return
            self._restart_required = False
            logger.info("[Burger Shop 2] Game closed. Level data will load correctly on next launch.")

        profile_open = False
        if pid is not None:
            profile_name = _read_profile_name(pid)
            profile_open = (
                profile_name is not None
                and re.sub(r"[^A-Za-z0-9]", "_", profile_name) == save_template.PROFILE_NAME
            )

        # Lay down or reset the profile only while the game is not sitting on it; doing it
        # underneath a loaded profile would be undone by the game's next save.
        save_file = self.save_file
        if save_file is not None and not profile_open and not self._prepare_session_save():
            save_file = None

        # Never read a profile that still belongs to an earlier session.  That happens when
        # the game is left open on the previous seed's profile while the client connects to
        # a new one: its levels are another game's progress and must not be reported here.
        if save_file is not None and (
            not os.path.exists(save_file) or _read_sidecar(save_file) != self._session_id
        ):
            if profile_open and not self._stale_profile_warned:
                self._stale_profile_warned = True
                logger.warning(
                    f"[Burger Shop 2] The {save_template.PROFILE_NAME} profile belongs to a "
                    f"previous session. Close the game (or use /restart) so it can be reset "
                    f"for this one. Progress made until then is not tracked."
                )
            save_file = None
        else:
            self._stale_profile_warned = False

        # Nothing is written into the running game unless it has this session's Archipelago
        # profile open.  A profile of the player's own is none of our business, and one left
        # over from an earlier seed holds another game's progress.
        # The memory loop reads this rather than working it out itself, so that it stays
        # cheap enough to run many times a second.
        self._session_save_ready = save_file is not None

        completed: set[int] = set()
        if save_file is not None:
            try:
                completed = read_completed_levels(save_file, self._five_star_mode)
            except Exception as e:
                self._log_problem(f"[Burger Shop 2] Could not read the "
                                  f"{save_template.PROFILE_NAME} profile: {e}")
                save_file = None

        if save_file is None:
            return

        # Complete levels whose check has already been collected, so the player is never
        # asked to replay a level for an item that has already been handed out.  Skipped
        # while the game has this profile open: it would only save over the change, and
        # the write could race a save of its own.  Reflecting collection in a live game
        # is the memory writer's job.
        if not profile_open:
            self._restore_level_slots(save_file)
            completed |= self._apply_collected_levels(save_file, completed)

        new_checks = [
            LOCATION_NAME_TO_ID[f"Story Level {n}"]
            for n in completed
            if LOCATION_NAME_TO_ID[f"Story Level {n}"] in self.missing_locations
        ]

        if completed and self._pending_starter_ids:
            new_checks.extend(
                loc_id for loc_id in self._pending_starter_ids
                if loc_id in self.missing_locations
            )
            self._pending_starter_ids = []

        if new_checks:
            await self.send_msgs([{"cmd": "LocationChecks", "locations": new_checks}])

        if not self.finished_game and _GOAL_LEVELS.issubset(completed):
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
