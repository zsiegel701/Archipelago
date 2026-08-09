"""Burger Shop Archipelago client."""
from __future__ import annotations

import asyncio
import ctypes
import os
import re
import struct
import subprocess
import sys
import uuid

import Utils
from CommonClient import CommonContext, ClientCommandProcessor, server_loop, gui_enabled, get_base_parser, logger
from NetUtils import ClientStatus

from ..locations import LOCATION_NAME_TO_ID, STARTER_LOCATION_NAMES
from ..items import ALIEN_FOOD_ITEMS, ITEM_NAME_TO_ID, LEVEL_KEY_ITEM, LEVEL_KEY_COUNT
from . import save_template, steam_utils
from .save_file import (
    LEVEL_COUNT, ensure_level_slots, mark_levels_complete, read_completed_levels,
)


ITEM_ID_TO_NAME: dict[int, str] = {v: k for k, v in ITEM_NAME_TO_ID.items()}

POLL_INTERVAL: float = 1.0
# The game applies a profile's level access the instant it loads it, so the save-file poll
# is far too slow to correct it: the map appears with every level unlocked and stays that
# way until the next tick.  The memory writes run on their own much shorter interval so
# that window shuts before the player can click anything.
_MEMORY_POLL_INTERVAL: float = 0.1
_LEVEL_KEY_ID: int = ITEM_NAME_TO_ID[LEVEL_KEY_ITEM]
_ALIEN_FOOD_IDS: frozenset[int] = frozenset(ITEM_NAME_TO_ID[name] for name in ALIEN_FOOD_ITEMS)
# Location IDs for the three starter locations (present only when StarterRecipes is on).
_STARTER_LOCATION_IDS: tuple[int, ...] = tuple(
    LOCATION_NAME_TO_ID[name] for name in STARTER_LOCATION_NAMES
)

# Pointer chain to the level-availability field, rooted in BurgerShop.exe's data section.
# *(*(*(BurgerShop.exe + 0x32251C) + 0x7C8) + 0x58) + 0x2C8 = target
_CHAIN_EXE_NAME: str = "BurgerShop.exe"
_CHAIN_BASE_OFFSET: int = 0x32251C
_CHAIN_OFFSETS: tuple[int, ...] = (0x7C8, 0x58, 0x2C8)

# Pointer chain to the currently selected save profile name (without "user_" prefix).
# *(*(*(BurgerShop.exe + 0x3192B8) + 0x6A4) + 0x58) + 0x18 = char[64] profile name
_PROFILE_NAME_BASE: int = 0x3192B8
_PROFILE_NAME_OFFSETS: tuple[int, ...] = (0x6A4, 0x58, 0x18)

# Pointer chain to the loaded profile's story level state — one float32 star rating per
# level, so level N is at index N-1 and 5.0 means a five-star clear.  It hangs off the
# same profile object as the name above, one dereference deeper.
# *(*(*(*(BurgerShop.exe + 0x3192B8) + 0x6A4) + 0x58) + 0x2E8) + 0 = float32[LEVEL_COUNT]
_LEVEL_STATE_BASE: int = 0x3192B8
_LEVEL_STATE_OFFSETS: tuple[int, ...] = (0x6A4, 0x58, 0x2E8, 0)

_FIVE_STARS: float = 5.0
# A resolved chain is only trusted when every entry already looks like a star rating.
# Star ratings are 0.0 for an unplayed level and otherwise sit in this range, so anything
# else means the chain landed somewhere it should not be written to.
_STAR_RANGE: tuple[float, float] = (0.5, 6.0)

# Static flag: 0x00 while the level-select map is displayed, non-zero otherwise.
# When the player is on the map screen we write level_count + 1 so the level they
# are about to click is never the last available one, preventing the "Choose New
# Item" popup.  The count is restored to its true value when they leave the map.
_LEVEL_SELECT_FLAG_OFFSET: int = 0x31907F

# Beating the last story level is what sends the goal, so it is the one level that is
# never completed on the player's behalf when its check is collected.
_GOAL_LEVELS: frozenset[int] = frozenset({LEVEL_COUNT})

# Data-storage key holding a UUID minted the first time any Burger Shop client connects to
# a room.  Both games share it: it identifies the room, not the slot.  The server keeps
# stored data in the room's save file, so deleting that file drops the key and the next
# connect mints a new ID — which is exactly the signal that the room was reset.
_ROOM_ID_KEY: str = "BurgerShop:room_id"


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
            logger.debug(f"[Burger Shop] Removed stale sidecar {name}.")
        except OSError as e:
            logger.debug(f"[Burger Shop] Could not remove stale sidecar {name}: {e}")


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


# ── Process detection ─────────────────────────────────────────────────────────

def _find_game_pid() -> int | None:
    """Return the PID of the running Burger Shop process, or None."""
    try:
        import psutil
        exe = steam_utils.BURGER_SHOP_EXE.lower()
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"] and proc.info["name"].lower() == exe:
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
        logger.debug(f"[Burger Shop] Failed to terminate pid {pid}: {e}")
        return False


# ── Memory manipulation ───────────────────────────────────────────────────────

def _get_exe_base(k32, pid: int) -> int:
    """Return the base address of BurgerShop.exe in pid's module list, or 0."""
    TH32CS_SNAPMODULE   = 0x00000008
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
                if (me.szModule or "").lower() == _CHAIN_EXE_NAME.lower():
                    return me.modBaseAddr or 0
                if not k32.Module32NextW(snap, ctypes.byref(me)):
                    break
    finally:
        k32.CloseHandle(snap)
    return 0


def _open_process_for_rw(k32, pid: int):
    """Open the process with read+write access; return handle or None."""
    handle = k32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400, False, pid)
    return handle or None


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
        target = _follow_pointer_chain(k32, handle, exe_base, _PROFILE_NAME_BASE,
                                       _PROFILE_NAME_OFFSETS)
        if not target:
            return None
        str_buf = ctypes.create_string_buffer(64)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(target), str_buf, 64, None):
            return None
        raw = str_buf.raw
        null_pos = raw.find(b"\x00")
        text = raw[:null_pos if null_pos >= 0 else 64].decode("latin-1")
        return text or None
    finally:
        k32.CloseHandle(handle)


def _sync_level_stars(pid: int, beaten: set[int]) -> tuple[float, ...] | None:
    """
    Mark the given 1-based story levels as five-star clears, and report every rating.

    Reading and writing share one pass because the caller needs the ratings anyway: which
    levels are already beaten decides how many levels the map is allowed to offer.
    Returns None if the array could not be read or does not look like star ratings — a
    chain that resolved to the wrong object would otherwise be scribbled over, and this
    runs against a live process many times a second.
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

        buf = ctypes.create_string_buffer(LEVEL_COUNT * 4)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(array), buf, LEVEL_COUNT * 4, None):
            return None
        stars = list(struct.unpack(f"<{LEVEL_COUNT}f", buf.raw))

        low, high = _STAR_RANGE
        if not all(v == 0.0 or low <= v <= high for v in stars):
            return None

        payload = struct.pack("<f", _FIVE_STARS)
        for level in sorted(beaten):
            if not 1 <= level <= LEVEL_COUNT or stars[level - 1] >= _FIVE_STARS:
                continue
            if k32.WriteProcessMemory(handle, ctypes.c_void_p(array + (level - 1) * 4),
                                      payload, 4, None):
                stars[level - 1] = _FIVE_STARS
        return tuple(stars)
    finally:
        k32.CloseHandle(handle)


def _write_level_count(pid: int, target_count: int) -> bool:
    """
    Write target_count to the level-availability field, making exactly that many story
    levels selectable on the map without requiring a game restart.

    The field is the last accessible level number counting from zero, so 0 leaves only
    the tutorial reachable and 79 opens all eighty.
    """
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
        # On the level-select map screen, inflate the count by 1 so the level the player is
        # about to click is never the last available one, which prevents the "Choose New
        # Item" popup from firing.  Skipped while the count is being held at zero: there the
        # single reachable level is the whole point, and inflating it would offer a second.
        flag_buf = ctypes.create_string_buffer(1)
        if (
            target_count > 0
            and target_count < LEVEL_COUNT
            and k32.ReadProcessMemory(handle, ctypes.c_void_p(exe_base + _LEVEL_SELECT_FLAG_OFFSET),
                                      flag_buf, 1, None)
            and flag_buf.raw[0] == 0
        ):
            target_count += 1

        target = _follow_pointer_chain(k32, handle, exe_base, _CHAIN_BASE_OFFSET, _CHAIN_OFFSETS)
        if not target:
            return False

        buf = ctypes.create_string_buffer(4)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(target), buf, 4, None):
            return False
        current = struct.unpack_from("<I", buf.raw)[0]

        # Zero is a value this client writes deliberately, so it has to be accepted as a
        # starting point; anything above the level count means the game is not initialised
        # yet or the chain led somewhere it should not be written to.
        if current > LEVEL_COUNT:
            return False
        if current == target_count:
            return True   # already correct, nothing to do

        payload = struct.pack("<I", target_count)
        n_written = ctypes.c_size_t(0)
        if k32.WriteProcessMemory(handle, ctypes.c_void_p(target), payload, 4,
                                  ctypes.byref(n_written)):
            return True
        return False
    finally:
        k32.CloseHandle(handle)


# ── Game-attribute memory patching ───────────────────────────────────────────

def _scan_replace_memory(k32, handle, old_bytes: bytes, new_bytes: bytes) -> int:
    """Scan all writable regions of the process for old_bytes and overwrite with new_bytes.

    Returns the number of replacement sites written.
    """


    # MEMORY_BASIC_INFORMATION — uses c_size_t so the layout is correct on both
    # 32-bit (SIZE_T=4) and 64-bit (SIZE_T=8) Python.  ctypes inserts the natural
    # 4-byte alignment gap between AllocationProtect and RegionSize automatically.
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
    PAGE_GUARD  = 0x100
    # Pages that are writable (and therefore can hold live attribute values).
    WRITABLE = {0x04, 0x08, 0x40, 0x80}  # READWRITE, WRITECOPY, EXEC_RW, EXEC_WC

    addr = 0
    count = 0
    mbi = _MBI()
    mbi_size = ctypes.sizeof(mbi)

    while k32.VirtualQueryEx(handle, ctypes.c_size_t(addr), ctypes.byref(mbi), mbi_size):
        base = mbi.BaseAddress
        size = mbi.RegionSize
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
    """For each (old_value, new_value) string pair, scan the game process memory
    and replace every occurrence of the old bytes with the new bytes.

    Both float32 and uint32 representations are tried so the scan succeeds
    regardless of how the game engine stores numeric XML attributes internally.
    """
    if sys.platform != "win32" or not changes:
        return



    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION
    handle = k32.OpenProcess(0x0010 | 0x0020 | 0x0400, False, pid)
    if not handle:
        logger.debug(f"[Burger Shop] Could not open PID {pid} for memory patching.")
        return

    try:
        for old_str, new_str in changes:
            try:
                old_f, new_f = float(old_str), float(new_str)
            except ValueError:
                continue

            total = 0

            # Try float32 representation.
            try:
                ob32 = struct.pack("<f", old_f)
                nb32 = struct.pack("<f", new_f)
                if ob32 != nb32:
                    total += _scan_replace_memory(k32, handle, ob32, nb32)
            except (struct.error, OverflowError):
                pass

            # Try uint32 representation (exact integer — distinct bytes from float32
            # for the large unique sentinel values like 600000002).
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
                    f"[Burger Shop] Memory-patched {old_str!r} -> {new_str!r} "
                    f"({total} location(s))"
                )
    finally:
        k32.CloseHandle(handle)


# ── Client ────────────────────────────────────────────────────────────────────

class BurgerShopCommandProcessor(ClientCommandProcessor):
    ctx: "BurgerShopContext"

    def _cmd_launch(self) -> bool:
        """Launch Burger Shop."""
        self.ctx.launch_game()
        return True

    def _cmd_restart(self) -> bool:
        """Close Burger Shop if it is running, then launch it again."""
        Utils.async_start(self.ctx.restart_game(), name="BurgerShop_restart")
        return True

    def _cmd_gamepath(self) -> bool:
        """Print the detected Burger Shop installation path."""
        self.output(f"Game path: {self.ctx.game_path or 'Not found'}")
        return True

    def _cmd_savepath(self) -> bool:
        """Print the detected save data directory."""
        self.output(f"Save path: {self.ctx.save_path or 'Not found'}")
        return True


class BurgerShopContext(CommonContext):
    game = "Burger Shop"
    items_handling = 0b111  # receive all items (local + remote)
    command_processor = BurgerShopCommandProcessor

    game_path: str | None = None
    save_path: str | None = None
    five_star_mode: bool = True
    _customer_slots: int = 0  # 0 = keep the vanilla per-level counts
    _character_randomization: int = 0
    _character_seed: int = 0
    _game_watcher_started: bool = False
    _restart_required: bool = False
    _stale_profile_warned: bool = False
    _room_id: str = ""
    _last_problem: str = ""
    _session_save_ready: bool = False  # the profile on disk belongs to this session
    _cached_pid: int | None = None
    _last_recipe_items: tuple[str, ...] | None  # None = never patched; sorted tuple for count-aware equality

    def make_gui(self):
        ui = super().make_gui()
        ui.base_title = "Archipelago Burger Shop Client"
        return ui

    def __init__(self, server_address: str | None, password: str | None) -> None:
        super().__init__(server_address, password)
        self._last_recipe_items = None
        self._locate_game()
        self._locate_save_dir()

    # ── Startup detection ────────────────────────────────────────────────────

    def _locate_game(self) -> None:
        """Resolve the game installation path: configured path first, then Steam auto-detect."""
        try:
            from worlds.burger_shop.world import BurgerShopWorld
            configured = str(BurgerShopWorld.settings.game_install_path)
        except Exception:
            configured = ""

        if configured and os.path.isfile(os.path.join(configured, steam_utils.BURGER_SHOP_EXE)):
            self.game_path = configured
            logger.debug(f"[Burger Shop] Using configured game path: {self.game_path}")
            return

        detected = steam_utils.find_game_install_path()
        if detected:
            self.game_path = detected
            logger.debug(f"[Burger Shop] Auto-detected game installation: {self.game_path}")
        else:
            logger.warning(
                "[Burger Shop] Game installation not found. "
                "Set game_install_path in host.yaml or use /launch after finding the folder manually."
            )

    def _locate_save_dir(self) -> None:
        """Resolve the save data directory (%APPDATA%\\GoBit Games\\BurgerShop\\Steam\\users\\{id})."""
        detected = steam_utils.find_save_directory()
        if detected:
            self.save_path = detected
            logger.debug(f"[Burger Shop] Save directory: {self.save_path}")
            _remove_stale_sidecars(detected)
        else:
            logger.warning(
                "[Burger Shop] Save directory not found under "
                "%APPDATA%\\GoBit Games\\BurgerShop. "
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
        """Launch Burger Shop via Steam URI when the App ID is known; otherwise run the .exe directly."""
        app_id = steam_utils.BURGER_SHOP_STEAM_APP_ID
        if app_id != "TODO":
            Utils.open_file(f"steam://rungameid/{app_id}")
            logger.info(f"[Burger Shop] Launched via Steam (App ID {app_id}).")
            return

        if self.game_path:
            exe = os.path.join(self.game_path, steam_utils.BURGER_SHOP_EXE)
            if os.path.isfile(exe):
                subprocess.Popen([exe], cwd=self.game_path)
                logger.info(f"[Burger Shop] Launched: {exe}")
                return
            logger.error(
                f"[Burger Shop] Executable not found at {exe}. "
                f"Update BURGER_SHOP_EXE in steam_utils.py if the filename differs."
            )
        else:
            logger.error(
                "[Burger Shop] Cannot launch: game path unknown and Steam App ID not set. "
                "Set game_install_path in host.yaml."
            )

    async def restart_game(self) -> None:
        """Close the running game (if any) and launch it again."""
        pid = _find_game_pid()
        if pid is None:
            self.launch_game()
            return
        logger.info("[Burger Shop] Closing the game...")
        if not await asyncio.to_thread(_terminate_game, pid):
            logger.error(
                "[Burger Shop] Could not close the game. Please close and relaunch it manually."
            )
            return
        self.launch_game()

    # ── AP server hooks ──────────────────────────────────────────────────────

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict) -> None:
        super().on_package(cmd, args)
        if cmd == "SetReply" and args.get("key") == _ROOM_ID_KEY:
            self._room_id = str(args.get("value") or "")
        elif cmd == "Connected":
            self._room_id = ""
            slot_data = args.get("slot_data", {})
            self.five_star_mode = bool(slot_data.get("five_star_mode", True))
            self._customer_slots = int(slot_data.get("customer_slots", 0))
            self._character_randomization = int(slot_data.get("character_randomization", 0))
            self._character_seed = int(slot_data.get("character_seed", 0))
            if not self._game_watcher_started:
                self._game_watcher_started = True
                Utils.async_start(self.game_loop(), name="BurgerShop_game_loop")
                Utils.async_start(self.memory_loop(), name="BurgerShop_memory_loop")
            Utils.async_start(self._acquire_room_id(), name="BurgerShop_room_id")

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

    def _get_unlocked_recipe_items(self) -> list[str]:
        """Return all received AP item names that affect XML recipes, preserving duplicates for progressive items."""
        return [
            name
            for item in self.items_received
            if (name := ITEM_ID_TO_NAME.get(item.item)) is not None
        ]

    def _count_level_keys(self) -> int:
        """Return the number of Level Key items received, capped at LEVEL_KEY_COUNT."""
        return min(
            sum(1 for item in self.items_received if item.item == _LEVEL_KEY_ID),
            LEVEL_KEY_COUNT,
        )

    def _collected_levels(self) -> set[int]:
        """Story levels the server already counts as checked.

        A level lands here once its check has been sent — by this client in an earlier
        session, or by ``!collect`` handing the item it held to a player who has finished.
        Either way the item is gone, so there is nothing left to earn by playing it.
        """
        return {
            level
            for level in range(1, LEVEL_COUNT + 1)
            if level not in _GOAL_LEVELS
            and LOCATION_NAME_TO_ID[f"Story Level {level}"] in self.checked_locations
        }

    def _restore_level_slots(self, save_file: str) -> None:
        """Widen the profile back to the full set of level slots if the game trimmed it."""
        try:
            ensure_level_slots(save_file)
        except Exception as e:
            self._log_problem(f"[Burger Shop] Could not update the "
                              f"{save_template.PROFILE_NAME} profile: {e}")

    def _apply_collected_levels(self, save_file: str, completed: set[int]) -> set[int]:
        """Complete already-checked levels in the save file; return the levels marked."""
        pending = self._collected_levels() - completed
        if not pending:
            return set()
        try:
            return mark_levels_complete(save_file, pending)
        except Exception as e:
            self._log_problem(f"[Burger Shop] Could not update the "
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

        exists = os.path.exists(save_file)
        if exists and _read_sidecar(save_file) == self._session_id:
            return True

        try:
            _write_pristine_save(save_file)
            _write_sidecar(save_file, self._session_id)
        except OSError as e:
            self._log_problem(f"[Burger Shop] Could not create the "
                              f"{save_template.PROFILE_NAME} profile: {e}")
            return False

        return True

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

    def _patch_game_memory(self) -> None:
        """Hold the running game's level state to what this session says it should be.

        Only ever touches a game sitting on this session's Archipelago profile: _tick has
        already decided whether the save file is usable, and the profile name is checked
        here because the player can switch profiles between ticks.
        """
        if not self._session_save_ready:
            return
        pid = self._game_pid()
        if pid is None:
            return
        profile_name = _read_profile_name(pid)
        if (
            profile_name is None
            or re.sub(r"[^A-Za-z0-9]", "_", profile_name) != save_template.PROFILE_NAME
        ):
            self._cached_pid = None if profile_name is None else self._cached_pid
            return

        # Show collected levels as beaten straight away, rather than only once the game is
        # closed and the save file can be edited.  Rewritten continuously so the state
        # survives the game reloading the profile.
        stars = _sync_level_stars(pid, self._collected_levels())
        if stars is None:
            return
        _write_level_count(pid, self._level_count_target(stars))

    def _level_count_target(self, stars: tuple[float, ...]) -> int:
        """How many levels the map may offer, as a last-accessible index counting from zero.

        Until level 1 has been played the count is pinned to zero, leaving it the only
        reachable level so the game drops straight into the tutorial.  After that the count
        follows the Progressive Burger Shop keys: 0 keys → 9, 7 keys → 79.  The final key
        (unlocking alien levels 71-80) only takes effect once all three alien food items
        have also been received.

        Any rating counts as played, not just a five-star one — the tutorial is done with
        once it has been cleared, whatever the option says a location check requires.
        """
        if stars[0] <= 0.0:
            return 0
        key_count = self._count_level_keys()
        has_alien_food = _ALIEN_FOOD_IDS.issubset(item.item for item in self.items_received)
        if key_count >= LEVEL_KEY_COUNT and not has_alien_food:
            key_count = LEVEL_KEY_COUNT - 1
        return 9 + key_count * 10

    async def memory_loop(self) -> None:
        logger.debug("[Burger Shop] Memory writer started.")
        while not self.exit_event.is_set():
            try:
                self._patch_game_memory()
            except Exception as e:
                self._log_problem(f"[Burger Shop] Error in memory loop: {e}")
            await asyncio.sleep(_MEMORY_POLL_INTERVAL)
        logger.debug("[Burger Shop] Memory writer stopped.")

    async def game_loop(self) -> None:
        logger.debug("[Burger Shop] Game watcher started.")
        while not self.exit_event.is_set():
            try:
                await self._tick()
            except Exception as e:
                self._log_problem(f"[Burger Shop] Error in game loop: {e}")
            await asyncio.sleep(POLL_INTERVAL)
        logger.debug("[Burger Shop] Game watcher stopped.")

    async def _tick(self) -> None:
        # Patch Order_*.xml recipe files whenever the unlocked recipe set changes.
        # Uses None as sentinel so the first tick always writes even if no items received.
        # Sorted tuple preserves duplicate counts (e.g. multiple Progressive Salad) for equality checks.
        recipe_items = self._get_unlocked_recipe_items()
        recipe_key = tuple(sorted(recipe_items))

        # Get PID once; used for both level-count write and Game.xml memory patching.
        pid = _find_game_pid()

        if recipe_key != self._last_recipe_items and self.game_path:
            from .xml_patcher import apply_recipe_unlocks, restart_sensitive_hash
            # Game.xml is parsed once at process start, so a change to it while the game
            # is running is invisible until it is relaunched.  In practice this only
            # happens on the first tick, when this seed's level data is first written.
            before = restart_sensitive_hash(self.game_path) if pid is not None else ""
            _, game_changes = apply_recipe_unlocks(
                self.game_path, recipe_items, self._customer_slots,
                self._character_randomization, self._character_seed,
            )
            self._last_recipe_items = recipe_key
            if pid is not None:
                # Push any Game.xml attribute changes into live game memory so powerup
                # unlocks take effect immediately without requiring a restart.
                if game_changes:
                    _patch_game_values_in_memory(pid, game_changes)
                if before and restart_sensitive_hash(self.game_path) != before:
                    self._restart_required = True
                    logger.warning(
                        "[Burger Shop] Level data changed, but Burger Shop is already "
                        "running. Close and relaunch the game (or use /restart) before "
                        "loading your save file. Progress made until then is not tracked."
                    )

        # The running game is working from the level data it read at launch, so nothing
        # it reports matches this seed.  Track nothing until the process is gone.
        if self._restart_required:
            if pid is not None:
                return
            self._restart_required = False
            logger.info("[Burger Shop] Game closed. Level data will load correctly on next launch.")

        # Whether the game currently has the Archipelago profile open decides both the
        # memory writes below and whether the save file may be touched at all.
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
                    f"[Burger Shop] The {save_template.PROFILE_NAME} profile belongs to a "
                    f"previous session. Close the game (or use /restart) so it can be reset "
                    f"for this one. Progress made until then is not tracked."
                )
            save_file = None
        else:
            self._stale_profile_warned = False

        # Nothing is written into the running game unless it has this session's Archipelago
        # profile open.  A profile of the player's own is none of our business, and one left
        # over from an earlier seed holds another game's progress — save_file is already None
        # in both cases, which is what makes this the same condition as reading the save.
        # The memory loop reads this rather than working it out itself, so that it stays
        # cheap enough to run many times a second.
        self._session_save_ready = save_file is not None

        if save_file is None:
            return

        # Read the profile first, so a reconnect picks up whatever the player has beaten
        # since.  A fresh profile starts blank, so everything read here belongs to this
        # session and there is no earlier progress to filter out.
        try:
            completed = read_completed_levels(save_file, require_five_stars=self.five_star_mode)
        except Exception as e:
            self._log_problem(f"[Burger Shop] Could not read the "
                              f"{save_template.PROFILE_NAME} profile: {e}")
            return

        # Both of these edit the file, so they are skipped while the game has the profile
        # open: it would only save over the change, and the write could race a save of its
        # own.  Reflecting either in a live game is the memory writer's job.
        if not profile_open:
            # Put back any level slots the game dropped when it last saved, before anything
            # reads the profile expecting all eighty to be there.
            self._restore_level_slots(save_file)

            # Complete levels whose check has already been collected, so the player is
            # never asked to replay a level for an item that has already been handed out.
            completed |= self._apply_collected_levels(save_file, completed)

        new_checks = [
            LOCATION_NAME_TO_ID[f"Story Level {n}"]
            for n in completed
            if LOCATION_NAME_TO_ID[f"Story Level {n}"] in self.missing_locations
        ]

        # Once any level is done, auto-check the starter locations that still exist in
        # missing_locations (present only when StarterRecipes is on; already absent if the
        # option is off or the checks were sent in a previous session).  Any level rather
        # than level 1 specifically: the map opens a whole chapter at a time, so the player
        # is free to clear level 4 first and never touch level 1.
        if completed:
            new_checks += [
                loc_id for loc_id in _STARTER_LOCATION_IDS
                if loc_id in self.missing_locations
            ]

        if new_checks:
            await self.send_msgs([{"cmd": "LocationChecks", "locations": new_checks}])

        if not self.finished_game and LEVEL_COUNT in completed:
            await self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
            self.finished_game = True


# ── Entry point ───────────────────────────────────────────────────────────────

def main(url: str | None = None) -> None:
    Utils.init_logging("BurgerShopClient", exception_logger="Client")

    async def _main() -> None:
        ctx = BurgerShopContext(url, None)
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="BurgerShop_server_loop")
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


if __name__ == "__main__":
    parser = get_base_parser(description="Burger Shop Archipelago Client")
    args = parser.parse_args()
    main(args.connect)
