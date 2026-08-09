"""Burger Shop save file (``user_*.dat``) reading and editing.

Header layout (little-endian):

    0x00  uint32   block size (24)
    0x04  char[4]  "PROF" magic
    0x08  uint32   profile slot ID
    0x0C  uint16   profile name byte length (P)
    0x0E  char[P]  profile name
    ... 180 bytes of fixed-size game state ...

Story progress follows a variable-size block whose length is stored at
``_VAR_SIZE_BASE + P``.  It is a pair of parallel arrays, each preceded by its own copy
of the level count and by a "TCEV" vector tag that is present only for long vectors
(see ``_TAG_THRESHOLD``, so ``tag_size`` is 0 or 4 and is the same for both arrays):

    count_off     uint32     N — story level slots stored in this save
    +4            char[4]    "TCEV"     (present iff tag_size == 4)
    tips_base     uint32×N   best tips earned per level (0 = level never beaten)
    +N*4          uint32     second copy of N
    +4            char[4]    "TCEV"     (same tag)
    stars_base    float32×N  star rating per level (5.0 = five stars)

The game only ever writes the two together, so for a save it produced either field
identifies a beaten level.  A level completed through Archipelago collection is the
exception: it is given a star rating but left at $0, because the player never earned
those tips.  The star rating is therefore what decides whether a level counts as beaten.
The game keeps its running money total in a separate field further on, so a level's tips
entry is only the "best tips" record shown on the level select map.

The final 16 bytes of the file are an HMAC-MD5 over everything preceding them, keyed
with a 64-byte constant compiled into BurgerShop.exe.  A save whose digest does not
match is rejected and set aside as ``.dat.error``, so every edit has to be re-signed.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import struct
from collections.abc import Iterable
from dataclasses import dataclass

LEVEL_COUNT: int = 80

_NAME_LEN_OFFSET: int = 0x0C
_VAR_SIZE_BASE: int = 0xC2

# The engine tags a serialised vector with "TCEV" only when it holds more than this many
# elements — in BurgerShop.exe, `cmp esi, 0x32 / jle` right before the tag is written.
# The tag therefore has to be derived from the new length whenever a vector is resized:
# carrying the old one over produces a save the game refuses to load, because a vector
# that crosses the boundary either gains or loses its tag.
_TAG_THRESHOLD: int = 50
_VECTOR_TAG: bytes = b"TCEV"

FIVE_STARS: float = 5.0

# HMAC-MD5 key, read out of the key-material stub that BurgerShop.exe pushes onto the
# stack before signing a save (`hmac_md5(key, 64, body, len, digest)`).
_DIGEST_KEY: bytes = bytes.fromhex(
    "9f956a1051d15224d23fa9bbfad031422e3438008c95f7079517728fc7c022aa"
    "3cb630dd775ed0e2f4982891b79906b3192ac90973dc79ed873f839fab44ff9f"
)
_DIGEST_SIZE: int = 16

_BACKUP_SUFFIX: str = ".apbak"
_TEMP_SUFFIX: str = ".aptmp"


@dataclass(frozen=True)
class StoryLayout:
    """Where the story-progress arrays sit inside a save file."""

    count_off: int
    tag_size: int
    count: int

    @property
    def tips_base(self) -> int:
        return self.count_off + 4 + self.tag_size

    @property
    def second_count_off(self) -> int:
        return self.tips_base + self.count * 4

    @property
    def stars_base(self) -> int:
        return self.second_count_off + 4 + self.tag_size

    @property
    def end(self) -> int:
        return self.stars_base + self.count * 4


def vector_tag(count: int) -> bytes:
    """Return the section tag the game writes in front of a vector of ``count`` elements."""
    return _VECTOR_TAG if count > _TAG_THRESHOLD else b""


# ── Digest ────────────────────────────────────────────────────────────────────

def sign(body: bytes) -> bytes:
    """Return the 16-byte HMAC-MD5 the game expects at the end of ``body``."""
    return hmac.new(_DIGEST_KEY, body, hashlib.md5).digest()


def split_digest(data: bytes) -> tuple[bytes, bytes] | None:
    """Split a save file into (body, digest), or return None if the digest is wrong."""
    if len(data) <= _DIGEST_SIZE:
        return None
    body, digest = data[:-_DIGEST_SIZE], data[-_DIGEST_SIZE:]
    if not hmac.compare_digest(sign(body), digest):
        return None
    return body, digest


# ── Reading ───────────────────────────────────────────────────────────────────

def find_layout(data: bytes) -> StoryLayout | None:
    """Locate the story-progress arrays, or return None if the format is unrecognised."""
    if len(data) < _NAME_LEN_OFFSET + 2:
        return None
    name_len = struct.unpack_from("<H", data, _NAME_LEN_OFFSET)[0]
    var_size_off = _VAR_SIZE_BASE + name_len
    if var_size_off + 4 > len(data):
        return None
    var_size = struct.unpack_from("<I", data, var_size_off)[0]
    # The variable data block may be preceded by a "TCEV" section tag (appears in saves
    # written after the level span grows beyond the initial range).
    var_data_start = var_size_off + 4
    if data[var_data_start:var_data_start + 4] == b"TCEV":
        var_data_start += 4
    count_off = var_data_start + var_size
    if count_off + 4 > len(data):
        return None
    count = struct.unpack_from("<I", data, count_off)[0]
    if count > LEVEL_COUNT:
        return None
    # Try both layouts: without a section tag (tag_size=0) and with one (tag_size=4).
    # The duplicate count field at the end of the tips array must match exactly.
    for tag_size in (0, 4):
        second_count_off = count_off + 4 + tag_size + count * 4
        if second_count_off + 4 > len(data):
            continue
        if struct.unpack_from("<I", data, second_count_off)[0] == count:
            return StoryLayout(count_off, tag_size, count)
    return None


def read_completed_levels(save_file: str, require_five_stars: bool = False) -> set[int]:
    """
    Parse a Burger Shop save file and return the 1-based level numbers the player has
    completed (with 5 stars if require_five_stars is True).
    """
    with open(save_file, "rb") as f:
        data = f.read()

    layout = find_layout(data)
    if layout is None:
        raise ValueError(f"Unrecognised save format: {save_file}")
    if layout.count == 0:
        return set()

    completed: set[int] = set()
    for i in range(min(layout.count, LEVEL_COUNT)):
        tips_off = layout.tips_base + i * 4
        stars_off = layout.stars_base + i * 4
        if tips_off + 4 > len(data) or stars_off + 4 > len(data):
            break
        rating = struct.unpack_from("<f", data, stars_off)[0]
        if require_five_stars:
            if rating < FIVE_STARS:
                continue
        # A level marked complete through collection carries a rating and no tips, so
        # the rating alone settles it.  Tips are still consulted so that a save holding
        # some rating this does not expect cannot make a played level look unplayed.
        elif rating <= 0.0 and struct.unpack_from("<I", data, tips_off)[0] == 0:
            continue
        completed.add(i + 1)
    return completed


# ── Writing ───────────────────────────────────────────────────────────────────

def mark_levels_complete(save_file: str, levels: Iterable[int]) -> set[int]:
    """
    Force the given 1-based story levels to a beaten, five-star state on disk.

    Only the star rating is written.  The tips a level earned are left exactly as they
    are, which for a level that was never played means $0 — the player did not earn them,
    so the map screen should not claim otherwise.

    Levels beyond the count the save currently stores extend it; the levels in between
    are added as untouched slots, exactly as the game would have written them.  Returns
    the levels that were actually changed — an empty set means the save already had them
    and nothing was written.

    The rewritten file is re-signed, checked by re-parsing it, and swapped in atomically.
    The original is kept once as a ``.dat.apbak`` sidecar, and the write is abandoned if
    the game touches the save while it is being rebuilt.
    """
    wanted = {n for n in levels if 1 <= n <= LEVEL_COUNT}
    if not wanted:
        return set()

    stat_before = os.stat(save_file)
    with open(save_file, "rb") as f:
        data = f.read()

    split = split_digest(data)
    if split is None:
        raise ValueError(f"Save file is unsigned or its digest is stale: {save_file}")
    body, _ = split

    layout = find_layout(body)
    if layout is None:
        raise ValueError(f"Unrecognised save format: {save_file}")
    if layout.end > len(body):
        raise ValueError(f"Truncated story section: {save_file}")

    old_count = layout.count
    tips = list(struct.unpack_from(f"<{old_count}I", body, layout.tips_base))
    stars = list(struct.unpack_from(f"<{old_count}f", body, layout.stars_base))

    new_count = max(old_count, max(wanted))
    tips += [0] * (new_count - old_count)
    stars += [0.0] * (new_count - old_count)

    was_beaten = {i + 1 for i, value in enumerate(stars) if value > 0.0}

    changed: set[int] = set()
    for level in wanted:
        if stars[level - 1] < FIVE_STARS:
            stars[level - 1] = FIVE_STARS
            changed.add(level)
    if not changed:
        return set()

    rebuilt = _rebuild_story(body, layout, new_count, tips, stars)
    _verify(rebuilt, new_count, wanted, was_beaten | wanted, tips)
    _replace_atomically(save_file, rebuilt + sign(rebuilt), stat_before)
    return changed


def ensure_level_slots(save_file: str, count: int = LEVEL_COUNT) -> bool:
    """
    Widen the story arrays back out to ``count`` slots, keeping every rating.

    The game rewrites the story section to hold only as many levels as the player has
    reached, so a profile laid down with all eighty slots is back to a handful after the
    first save.  That matters beyond the file itself: the game sizes its in-memory level
    array from what it loaded, and the memory writer reads a fixed eighty entries, so a
    short array makes it read past the end, fail its sanity check, and stop patching
    entirely — level access included.

    Returns True if the file was rewritten.  Nothing is added but empty slots, so this
    never changes which levels count as played.
    """
    stat_before = os.stat(save_file)
    with open(save_file, "rb") as f:
        data = f.read()

    split = split_digest(data)
    if split is None:
        raise ValueError(f"Save file is unsigned or its digest is stale: {save_file}")
    body, _ = split

    layout = find_layout(body)
    if layout is None:
        raise ValueError(f"Unrecognised save format: {save_file}")
    if layout.end > len(body):
        raise ValueError(f"Truncated story section: {save_file}")
    if layout.count >= count:
        return False

    old_count = layout.count
    tips = list(struct.unpack_from(f"<{old_count}I", body, layout.tips_base))
    stars = list(struct.unpack_from(f"<{old_count}f", body, layout.stars_base))
    beaten = {i + 1 for i, value in enumerate(stars) if value > 0.0}
    tips += [0] * (count - old_count)
    stars += [0.0] * (count - old_count)

    rebuilt = _rebuild_story(body, layout, count, tips, stars)
    _verify(rebuilt, count, set(), beaten, tips)
    _replace_atomically(save_file, rebuilt + sign(rebuilt), stat_before)
    return True


def _rebuild_story(
    body: bytes, layout: StoryLayout, count: int, tips: list[int], stars: list[float]
) -> bytes:
    """Splice resized story arrays back into a save body, tagging them for their length."""
    tag = vector_tag(count)
    rebuilt = bytearray(body[:layout.count_off])
    rebuilt += struct.pack("<I", count) + tag
    rebuilt += struct.pack(f"<{count}I", *tips)
    rebuilt += struct.pack("<I", count) + tag
    rebuilt += struct.pack(f"<{count}f", *stars)
    rebuilt += body[layout.end:]
    return bytes(rebuilt)


def _verify(
    body: bytes, expected_count: int, levels: set[int], beaten: set[int], tips: list[int]
) -> None:
    """
    Re-parse a rebuilt save body and confirm it says what it was meant to say.

    ``beaten`` is every level that must read as played afterwards, so that a reassembly
    slip can never quietly drop the player's existing progress.  ``tips`` is the array as
    it went in: nothing here writes it, so reading anything else back means the arrays
    were spliced together wrongly.
    """
    layout = find_layout(body)
    if layout is None or layout.count != expected_count or layout.end > len(body):
        raise ValueError("rebuilt save file did not parse back")
    if layout.tag_size != len(vector_tag(layout.count)):
        raise ValueError("rebuilt save file tags its story vectors incorrectly")
    written_tips = struct.unpack_from(f"<{layout.count}I", body, layout.tips_base)
    stars = struct.unpack_from(f"<{layout.count}f", body, layout.stars_base)
    for level in levels:
        if stars[level - 1] < FIVE_STARS:
            raise ValueError(f"rebuilt save file is missing level {level}")
    if {i + 1 for i, value in enumerate(stars) if value > 0.0} != beaten:
        raise ValueError("rebuilt save file changed which levels count as played")
    if list(written_tips) != tips:
        raise ValueError("rebuilt save file changed the tips the player earned")


def _replace_atomically(save_file: str, data: bytes, stat_before: os.stat_result) -> None:
    """Swap in new save data, keeping one backup and refusing to clobber a newer file."""
    backup = save_file + _BACKUP_SUFFIX
    if not os.path.exists(backup):
        shutil.copy2(save_file, backup)

    temp = save_file + _TEMP_SUFFIX
    with open(temp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())

    stat_now = os.stat(save_file)
    if (stat_now.st_mtime_ns, stat_now.st_size) != (stat_before.st_mtime_ns, stat_before.st_size):
        os.remove(temp)
        raise RuntimeError(f"{os.path.basename(save_file)} was written by the game mid-update")
    os.replace(temp, save_file)
