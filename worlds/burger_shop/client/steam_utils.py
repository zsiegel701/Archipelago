"""Utilities for locating Burger Shop's Steam installation."""
from __future__ import annotations

import os
import re
import sys

BURGER_SHOP_STEAM_APP_ID: str = "730840"
BURGER_SHOP_STEAM_FOLDER: str = "Burger Shop"
BURGER_SHOP_EXE: str = "BurgerShop.exe"

# Save data lives at: %APPDATA%\GoBit Games\BurgerShop\Steam\users\{steam_user_id}\
# The numeric user ID folder is Steam account-specific, so we scan for it at runtime.
_SAVE_APPDATA_SUBPATH: str = os.path.join("GoBit Games", "BurgerShop")


def find_steam_path() -> str | None:
    """Return the Steam installation directory, or None if it cannot be found."""
    if sys.platform == "win32":
        import winreg
        for hive, subkey, value in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        ]:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    path, _ = winreg.QueryValueEx(key, value)
                    if os.path.isdir(path):
                        return path
            except OSError:
                continue
        # Fallback default path
        default = r"C:\Program Files (x86)\Steam"
        if os.path.isdir(default):
            return default

    elif sys.platform.startswith("linux"):
        home = os.path.expanduser("~")
        for candidate in [
            os.path.join(home, ".steam", "steam"),
            os.path.join(home, ".local", "share", "Steam"),
        ]:
            if os.path.isdir(candidate):
                return candidate

    elif sys.platform == "darwin":
        candidate = os.path.expanduser("~/Library/Application Support/Steam")
        if os.path.isdir(candidate):
            return candidate

    return None


def find_steam_library_folders(steam_path: str) -> list[str]:
    """Return all Steam library folder paths (including the default one)."""
    folders: list[str] = [steam_path]
    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if not os.path.isfile(vdf_path):
        return folders
    with open(vdf_path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    for match in re.finditer(r'"path"\s+"([^"]+)"', content):
        path = match.group(1).replace("\\\\", "\\")
        if os.path.isdir(path) and path not in folders:
            folders.append(path)
    return folders


def find_game_install_path() -> str | None:
    """Search all Steam library folders for the Burger Shop installation directory."""
    steam_path = find_steam_path()
    if steam_path is None:
        return None
    for library in find_steam_library_folders(steam_path):
        candidate = os.path.join(library, "steamapps", "common", BURGER_SHOP_STEAM_FOLDER)
        if os.path.isdir(candidate):
            return candidate
    return None


def find_save_directory() -> str | None:
    """
    Return the Burger Shop save directory for the current Steam user.

    Save data lives at:
        %APPDATA%\\GoBit Games\\BurgerShop\\Steam\\users\\{steam_user_id}\\

    The numeric steam_user_id folder is account-specific, so we scan for it.
    If multiple user folders exist, the most recently modified one is used.
    """
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return None

    base = os.path.join(appdata, _SAVE_APPDATA_SUBPATH)
    if not os.path.isdir(base):
        return None

    users_dir = os.path.join(base, "Steam", "users")
    if not os.path.isdir(users_dir):
        # Fallback: game not launched via Steam, or older non-Steam version.
        return base

    # Find all numeric user ID subdirectories and pick the most recently modified.
    user_dirs = [
        os.path.join(users_dir, entry)
        for entry in os.listdir(users_dir)
        if entry.isdigit() and os.path.isdir(os.path.join(users_dir, entry))
    ]
    if not user_dirs:
        return users_dir  # return parent if no user folders found yet

    return max(user_dirs, key=os.path.getmtime)
