"""Burger Shop Archipelago client."""
from __future__ import annotations

import asyncio
import ctypes
import glob
import os
import struct
import subprocess
import sys

import Utils
from CommonClient import CommonContext, ClientCommandProcessor, server_loop, gui_enabled, get_base_parser, logger
from NetUtils import ClientStatus

from ..locations import LOCATION_NAME_TO_ID, STARTER_LOCATION_NAMES
from ..items import ALIEN_FOOD_ITEMS, ITEM_NAME_TO_ID, LEVEL_KEY_ITEM, LEVEL_KEY_COUNT
from . import steam_utils


LOCATION_ID_TO_NAME: dict[int, str] = {v: k for k, v in LOCATION_NAME_TO_ID.items()}
ITEM_ID_TO_NAME: dict[int, str] = {v: k for k, v in ITEM_NAME_TO_ID.items()}

POLL_INTERVAL: float = 1.0
LEVEL_COUNT: int = 80
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

# Static flag: 0x00 while the level-select map is displayed, non-zero otherwise.
# When the player is on the map screen we write level_count + 1 so the level they
# are about to click is never the last available one, preventing the "Choose New
# Item" popup.  The count is restored to its true value when they leave the map.
_LEVEL_SELECT_FLAG_OFFSET: int = 0x31907F

# Save file parsing constants.
#
#   Header layout (little-endian):
#     0x00  uint32   block size (24)
#     0x04  char[4]  "PROF" magic
#     0x08  uint32   profile slot ID
#     0x0C  uint16   profile name byte length (P)
#     0x0E  char[P]  profile name
#     ... 180 bytes of fixed-size game state ...
#
#   Story level data — two layouts detected at parse time.
#
#   The var-size block itself may or may not be preceded by a "TCEV" tag
#   (appears once the level span grows past the initial range):
#     0xC2+P    uint32   V = variable data size
#     0xC2+P+4  char[4]  "TCEV" section tag (optional; detected at runtime)
#     0xC2+P+4[+4]  byte[V]  variable data
#
#   The tips / stars arrays then follow the count field in one of two forms:
#
#   Layout A (linear saves, tag_size=0):
#     …+V      uint32   N = story levels beaten
#     …+V+4    uint32×N best tips per level
#     …+V+4+N×4   uint32   second copy of N
#     …+V+4+N×4+4 float32×N star ratings (5.0 = 5 stars)
#
#   Layout B (non-linear / extended saves, tag_size=4):
#     …+V      uint32   N = story levels beaten
#     …+V+4    char[4]  "TCEV"
#     …+V+8    uint32×N best tips per level
#     …+V+8+N×4   uint32   second copy of N
#     …+V+8+N×4+4 char[4]  "TCEV"
#     …+V+8+N×4+8 float32×N star ratings (5.0 = 5 stars)
#
#   Level L (1-based) is beaten iff L ≤ N and tips[L-1] > 0.
_NAME_LEN_OFFSET: int = 0x0C
_VAR_SIZE_BASE: int = 0xC2


# ── Sidecar helpers (.ap files, read-only identification) ────────────────────
#
# Sidecar format (two lines):
#   Line 1: session ID  →  "{seed_name}:{team}:{slot}"
#   Line 2: comma-separated baseline level numbers that were already completed
#            when the save file was first associated with this AP session.
#
# The baseline is subtracted in _tick so that story progress predating the AP
# session is never sent as location checks for the current game.

def _sidecar_path(save_file: str) -> str:
    """Return the .ap sidecar path for a given .dat save file."""
    return os.path.splitext(save_file)[0] + ".ap"


def _read_sidecar(save_file: str) -> tuple[str, frozenset[int]]:
    """Return (session_id, baseline_levels) from the .ap sidecar, or ("", frozenset()) on error."""
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
    """Return True if the .ap sidecar for this save file matches session_id."""
    sid, _ = _read_sidecar(save_file)
    return bool(sid) and sid == session_id


def _mark_as_ap_save(save_file: str, session_id: str, baseline: frozenset[int]) -> None:
    """Write session_id and baseline to the .ap sidecar next to save_file."""
    with open(_sidecar_path(save_file), "w", encoding="utf-8") as f:
        f.write(session_id + "\n")
        f.write(",".join(str(n) for n in sorted(baseline)))


# ── Save file reading (read-only; never written to) ───────────────────────────

def _find_count_offset(data: bytes | bytearray) -> tuple[int, int] | None:
    """
    Return (count_off, tag_size) where tag_size is 0 (Layout A) or 4 (Layout B),
    or None if the format is unrecognised.  See the header comment for the two layouts.
    """
    if len(data) < _NAME_LEN_OFFSET + 2:
        return None
    name_len = struct.unpack_from("<H", data, _NAME_LEN_OFFSET)[0]
    var_size_off = _VAR_SIZE_BASE + name_len
    if var_size_off + 4 > len(data):
        return None
    var_size = struct.unpack_from("<I", data, var_size_off)[0]
    # The variable data block may be preceded by a "TCEV" section tag (appears in
    # saves written after the level span grows beyond the initial range).
    var_data_start = var_size_off + 4
    if data[var_data_start:var_data_start + 4] == b"TCEV":
        var_data_start += 4
    count_off = var_data_start + var_size
    if count_off + 4 > len(data):
        return None
    count = struct.unpack_from("<I", data, count_off)[0]
    if count > LEVEL_COUNT:
        return None
    # Try both layouts: without section tag (tag_size=0) and with "TCEV" tag (tag_size=4).
    # The duplicate count field at the end of the tips array must equal count exactly.
    for tag_size in (0, 4):
        second_count_off = count_off + 4 + tag_size + count * 4
        if second_count_off + 4 > len(data):
            continue
        if struct.unpack_from("<I", data, second_count_off)[0] == count:
            return count_off, tag_size
    return None


def _find_save_file(save_dir: str, session_id: str) -> str | None:
    """Return the most recently modified user*.dat that has a matching .ap sidecar, or None."""

    saves = [s for s in glob.glob(os.path.join(save_dir, "user*.dat"))
             if _is_session_save(s, session_id)]
    return max(saves, key=os.path.getmtime) if saves else None


def _read_completed_levels(save_file: str, require_five_stars: bool = False) -> set[int]:
    """
    Parse a Burger Shop save file and return the 1-based level numbers the player
    has completed (with 5 stars if require_five_stars is True).
    """

    with open(save_file, "rb") as f:
        data = f.read()

    result = _find_count_offset(data)
    if result is None:
        raise ValueError(f"Unrecognised save format: {save_file}")
    count_off, tag_size = result
    count = struct.unpack_from("<I", data, count_off)[0]
    if count == 0:
        return set()

    money_base = count_off + 4 + tag_size
    stars_base = money_base + count * 4 + 4 + tag_size  # skip second count uint32 + optional tag

    completed: set[int] = set()
    for i in range(min(count, LEVEL_COUNT)):
        money_off = money_base + i * 4
        stars_off = stars_base + i * 4
        if money_off + 4 > len(data) or stars_off + 4 > len(data):
            break
        money = struct.unpack_from("<I", data, money_off)[0]
        if money == 0:
            continue
        if require_five_stars:
            stars = struct.unpack_from("<f", data, stars_off)[0]
            if stars < 5.0:
                continue
        completed.add(i + 1)
    return completed


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


# ── Memory manipulation ───────────────────────────────────────────────────────

def _read_profile_name(pid: int) -> str | None:
    """Return the name of the currently loaded save profile (without 'user_' prefix), or None."""
    if sys.platform != "win32":
        return None

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

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    exe_base = 0
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    invalid = ctypes.c_void_p(-1).value
    if snap and snap != invalid:
        try:
            me = ME32W()
            me.dwSize = ctypes.sizeof(me)
            if k32.Module32FirstW(snap, ctypes.byref(me)):
                while True:
                    if (me.szModule or "").lower() == _CHAIN_EXE_NAME.lower():
                        exe_base = me.modBaseAddr or 0
                        break
                    if not k32.Module32NextW(snap, ctypes.byref(me)):
                        break
        finally:
            k32.CloseHandle(snap)

    if not exe_base:
        return None

    handle = k32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400, False, pid)
    if not handle:
        return None

    try:
        buf = ctypes.create_string_buffer(4)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(exe_base + _PROFILE_NAME_BASE), buf, 4, None):
            return None
        addr = struct.unpack_from("<I", buf.raw)[0]
        if not addr:
            return None
        for off in _PROFILE_NAME_OFFSETS[:-1]:
            if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr + off), buf, 4, None):
                return None
            addr = struct.unpack_from("<I", buf.raw)[0]
            if not addr:
                return None
        str_buf = ctypes.create_string_buffer(64)
        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr + _PROFILE_NAME_OFFSETS[-1]), str_buf, 64, None):
            return None
        raw = str_buf.raw
        null_pos = raw.find(b"\x00")
        text = raw[:null_pos if null_pos >= 0 else 64].decode("ascii", errors="replace")
        return text or None
    finally:
        k32.CloseHandle(handle)


def _write_level_count(pid: int, target_count: int) -> bool:
    """
    Follow the pointer chain rooted in BurgerShop.exe and write target_count to the
    level-availability field, making exactly target_count story levels selectable on
    the map without requiring a game restart.
    """
    if sys.platform != "win32":
        return False



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

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    exe_base = 0
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    invalid = ctypes.c_void_p(-1).value
    if snap and snap != invalid:
        try:
            me = ME32W()
            me.dwSize = ctypes.sizeof(me)
            if k32.Module32FirstW(snap, ctypes.byref(me)):
                while True:
                    if (me.szModule or "").lower() == _CHAIN_EXE_NAME.lower():
                        exe_base = me.modBaseAddr or 0
                        break
                    if not k32.Module32NextW(snap, ctypes.byref(me)):
                        break
        finally:
            k32.CloseHandle(snap)

    if not exe_base:
        logger.debug(f"[Burger Shop] {_CHAIN_EXE_NAME} module not found in pid {pid}.")
        return False

    handle = k32.OpenProcess(0x0010 | 0x0020 | 0x0008 | 0x0400, False, pid)
    if not handle:
        logger.debug(f"[Burger Shop] OpenProcess failed: {ctypes.get_last_error()}")
        return False

    try:
        buf = ctypes.create_string_buffer(4)

        # On the level-select map screen, inflate the count by 1 so the level the
        # player is about to click is never the last available one, which prevents
        # the "Choose New Item" popup from firing.
        flag_buf = ctypes.create_string_buffer(1)
        if (k32.ReadProcessMemory(handle, ctypes.c_void_p(exe_base + _LEVEL_SELECT_FLAG_OFFSET),
                                   flag_buf, 1, None)
                and flag_buf.raw[0] == 0
                and target_count < LEVEL_COUNT):
            target_count += 1

        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(exe_base + _CHAIN_BASE_OFFSET),
                                      buf, 4, None):
            return False
        addr = struct.unpack_from("<I", buf.raw)[0]
        if not addr:
            return False

        for off in _CHAIN_OFFSETS[:-1]:
            if not k32.ReadProcessMemory(handle, ctypes.c_void_p(addr + off), buf, 4, None):
                return False
            addr = struct.unpack_from("<I", buf.raw)[0]
            if not addr:
                return False

        target = addr + _CHAIN_OFFSETS[-1]

        if not k32.ReadProcessMemory(handle, ctypes.c_void_p(target), buf, 4, None):
            return False
        current = struct.unpack_from("<I", buf.raw)[0]

        if not (1 <= current <= LEVEL_COUNT):
            return False  # game not yet initialised, or pointer chain led to garbage
        if current == target_count:
            return True   # already correct, nothing to do

        payload = struct.pack("<I", target_count)
        n_written = ctypes.c_size_t(0)
        if k32.WriteProcessMemory(handle, ctypes.c_void_p(target), payload, 4,
                                   ctypes.byref(n_written)):
            logger.debug(f"[Burger Shop] Level count updated ({current} → {target_count})")
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
    _generation_uid: str = ""
    _game_watcher_started: bool = False
    _save_status_after_prints: int = 0
    _known_save_files: set[str]
    _pending_new_saves: set[str]  # new .dat files whose sidecars haven't been written yet
    _last_recipe_items: tuple[str, ...] | None  # None = never patched; sorted tuple for count-aware equality

    def __init__(self, server_address: str | None, password: str | None) -> None:
        super().__init__(server_address, password)
        self._known_save_files = set()
        self._pending_new_saves = set()
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
        
            existing = set(glob.glob(os.path.join(detected, "user*.dat")))
            self._known_save_files = existing
            for ap_file in glob.glob(os.path.join(detected, "user*.ap")):
                dat_file = os.path.splitext(ap_file)[0] + ".dat"
                if dat_file not in existing:
                    try:
                        os.remove(ap_file)
                        logger.debug(f"[Burger Shop] Removed orphaned sidecar: {os.path.basename(ap_file)}")
                    except OSError:
                        pass
        else:
            logger.warning(
                "[Burger Shop] Save directory not found under "
                "%APPDATA%\\GoBit Games\\BurgerShop. "
                "Launch the game at least once so the save folder is created."
            )

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

    # ── AP server hooks ──────────────────────────────────────────────────────

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict) -> None:
        super().on_package(cmd, args)
        if cmd == "PrintJSON" and self._save_status_after_prints > 0:
            self._save_status_after_prints -= 1
            if self._save_status_after_prints == 0:
                self._log_save_status()
        elif cmd == "Connected":
            slot_data = args.get("slot_data", {})
            self.five_star_mode = bool(slot_data.get("five_star_mode", True))
            self._generation_uid = str(slot_data.get("generation_uid", ""))
            if not self._game_watcher_started:
                self._game_watcher_started = True
                Utils.async_start(self.game_loop(), name="BurgerShop_game_loop")
                self._save_status_after_prints = 2
            else:
                self._log_save_status()

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
            logger.info("[Burger Shop] Waiting for save file to be created.")
        elif len(saves) == 1:
            name = os.path.splitext(os.path.basename(saves[0]))[0].removeprefix("user_")
            logger.info(f"[Burger Shop] Save file found: {name}")
        else:
            names = ", ".join(os.path.splitext(os.path.basename(s))[0].removeprefix("user_") for s in saves)
            logger.info(f"[Burger Shop] Multiple save files found: {names}")

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

    def _watch_for_new_saves(self) -> None:
        """Create sidecars for new .dat files; delete sidecars for deleted .dat files."""
        if not self.save_path:
            return
    
        current = set(glob.glob(os.path.join(self.save_path, "user*.dat")))
        session_id = self._session_id

        # Queue newly-appeared save files for sidecar creation.
        for save_file in current - self._known_save_files:
            if not os.path.exists(_sidecar_path(save_file)):
                self._pending_new_saves.add(save_file)

        # Attempt sidecar creation for queued files.  The game may still be
        # writing the file when we first see it, so we retry until the parse
        # succeeds and we can capture an accurate baseline.
        for save_file in list(self._pending_new_saves):
            if save_file not in current:
                self._pending_new_saves.discard(save_file)
                continue
            try:
                baseline = frozenset(_read_completed_levels(save_file))
                _mark_as_ap_save(save_file, session_id, baseline)
                self._pending_new_saves.discard(save_file)
                if baseline:
                    logger.debug(
                        f"[Burger Shop] {os.path.basename(save_file)}: "
                        f"{len(baseline)} pre-existing level(s) excluded from checks."
                    )
                self._log_save_status()
            except Exception:
                pass  # file not yet fully written; retry next tick

        # Clean up sidecars for deleted save files.
        for save_file in self._known_save_files - current:
            sidecar = _sidecar_path(save_file)
            if os.path.exists(sidecar):
                try:
                    os.remove(sidecar)
                    logger.debug(f"[Burger Shop] Removed sidecar for deleted save: {os.path.basename(save_file)}")
                except OSError:
                    pass
            self._pending_new_saves.discard(save_file)

        self._known_save_files = current

    async def game_loop(self) -> None:
        logger.debug("[Burger Shop] Game watcher started.")
        while not self.exit_event.is_set():
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"[Burger Shop] Error in game loop: {e}")
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
            from .xml_patcher import apply_recipe_unlocks
            _, game_changes = apply_recipe_unlocks(self.game_path, recipe_items)
            self._last_recipe_items = recipe_key
            # Push any Game.xml attribute changes into live game memory so powerup
            # unlocks take effect immediately without requiring a restart.
            if game_changes and pid is not None:
                _patch_game_values_in_memory(pid, game_changes)

        # Determine the session save file first — needed to gate memory writes.
        save_file: str | None = None
        if self.save_path:
            self._watch_for_new_saves()
            save_file = _find_save_file(self.save_path, self._session_id)

        # Keep the in-memory level count correct based on received Level Keys,
        # but only while the player has an AP save file loaded.
        # The count field is the last accessible level number (0-indexed from "next"),
        # so write (target_levels - 1): 0 keys → 9, 7 keys → 79.
        # The final key (unlocking alien levels 71-80) only takes effect once all
        # three alien food items have also been received.
        if pid is not None:
            profile_name = _read_profile_name(pid)
            ap_profile_loaded = (
                save_file is not None
                and profile_name is not None
                and os.path.basename(save_file) == f"user_{profile_name}.dat"
            )
            if ap_profile_loaded:
                key_count = self._count_level_keys()
                has_alien_food = _ALIEN_FOOD_IDS.issubset(item.item for item in self.items_received)
                if key_count >= LEVEL_KEY_COUNT and not has_alien_food:
                    key_count = LEVEL_KEY_COUNT - 1
                target_count = 9 + key_count * 10
                _write_level_count(pid, target_count)

        if save_file is None:
            return

        # Detect completed story levels from this session's save file.

        _, baseline = _read_sidecar(save_file)

        try:
            completed = _read_completed_levels(save_file, require_five_stars=self.five_star_mode)
        except Exception as e:
            logger.debug(f"[Burger Shop] Could not read completed levels: {e}")
            return

        # Only report levels completed AFTER this AP session started (above baseline).
        above_baseline = completed - baseline
        new_checks = [
            LOCATION_NAME_TO_ID[f"Story Level {n}"]
            for n in above_baseline
            if LOCATION_NAME_TO_ID.get(f"Story Level {n}") not in self.locations_checked
        ]

        # When Level 1 is done, auto-check any starter locations that still exist in
        # missing_locations (present only when StarterRecipes is on; already absent if
        # the option is off or the checks were sent in a previous session).
        if 1 in above_baseline:
            new_checks += [
                loc_id for loc_id in _STARTER_LOCATION_IDS
                if loc_id in self.missing_locations
            ]

        if new_checks:
            await self.send_msgs([{"cmd": "LocationChecks", "locations": new_checks}])

        if not self.finished_game and LEVEL_COUNT in above_baseline:
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
