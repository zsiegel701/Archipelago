"""Burger Shop 2 save file (``user_*.dat``) reading and editing.

Story progress is stored as three parallel per-level records, each preceded by its own
copy of the level count and by a "TCEV" vector tag that is present only for long vectors
(see ``_TAG_THRESHOLD``, so ``tag_size`` is 0 or 4 and, because all three records are the
same length, is the same for every one of them in a given save):

    count_off      uint32     N — story level slots stored in this save
    +4             char[4]    "TCEV"    (present iff tag_size == 4)
    tips_base      uint32×N   best tips earned per level (0 = level never beaten)
    +N*4           uint32     second copy of N
    +4             char[4]    "TCEV"
    stars_base     float32×N  star rating per level (5.0 = five stars)
    +N*4           byte       unrelated single-byte field
    +1             uint32     third copy of N
    +4             char[4]    "TCEV"
    beaten_base    byte[⌈N/8⌉]  one bit per level, LSB first, 1 = beaten

The game only ever writes all three together.  A level completed through Archipelago
collection is the exception: it is given a star rating and its bit, but left at $0,
because the player never earned those tips.  The star rating is therefore what decides
whether a level counts as beaten.  The running money total lives in its own field after
the bitmap, which is why a level's tips entry is purely the "best tips" figure shown on
the level select map.

The final 16 bytes of the file are an HMAC-MD5 over everything preceding them, keyed
with a 64-byte constant compiled into BurgerShop2.exe.  A save whose digest does not
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

MAX_LEVELS: int = 120

# The engine tags a serialised vector with "TCEV" only when it holds more than this many
# elements — in BurgerShop2.exe, `cmp esi, 0x32 / jle` right before the tag is written.
# The tag therefore has to be derived from the new length whenever a vector is resized:
# carrying the old one over produces a save the game refuses to load, because a vector
# that crosses the boundary either gains or loses its tag.  The bitmap counts levels, not
# bytes, so all three story vectors cross the boundary together.
_TAG_THRESHOLD: int = 50
_VECTOR_TAG: bytes = b"TCEV"

FIVE_STARS: float = 5.0

# HMAC-MD5 key, read out of the key-material stub that BurgerShop2.exe pushes onto the
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
    """Where the story-progress records sit inside a save file."""

    count_off: int          # count field in front of the tips array
    tag_size: int
    count: int
    beaten_count_off: int   # count field in front of the beaten bitmap
    beaten_tag_size: int

    @property
    def tips_base(self) -> int:
        return self.count_off + 4 + self.tag_size

    @property
    def stars_count_off(self) -> int:
        return self.tips_base + self.count * 4

    @property
    def stars_base(self) -> int:
        return self.stars_count_off + 4 + self.tag_size

    @property
    def stars_end(self) -> int:
        return self.stars_base + self.count * 4

    @property
    def beaten_base(self) -> int:
        return self.beaten_count_off + 4 + self.beaten_tag_size

    @property
    def end(self) -> int:
        return self.beaten_base + bitmap_size(self.count)


def bitmap_size(count: int) -> int:
    """Bytes the game uses to hold ``count`` beaten-level bits."""
    return (count + 7) // 8


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

def find_story_section(data: bytes) -> tuple[int, int] | None:
    """
    Scan for the last valid (N, [optional TCEV], float32[N]) story block where
    1 ≤ N ≤ MAX_LEVELS, at least one float is in [0.5, 6.0], and every non-zero float is
    in [0.5, 6.0].  Zero entries represent levels not yet completed and are accepted;
    this matches the on-disk format where the game stores all N available level slots
    whether or not the player has beaten them.

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


def read_completed_levels(save_file: str, five_star: bool = True) -> set[int]:
    """
    Return 1-based level numbers for completed expert story levels.

    When five_star is True (default), only levels with exactly 5 stars (value >= 5.0)
    are counted.  When False, any non-zero star value counts as a completion.
    Returns an empty set if no levels have been played yet.
    """
    with open(save_file, "rb") as f:
        data = f.read()
    result = find_story_section(data)
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
        if (v >= FIVE_STARS) if five_star else (v > 0.0):
            completed.add(i + 1)
    return completed


def find_layout(data: bytes) -> StoryLayout | None:
    """
    Locate every story-progress record, or return None if they cannot all be found.

    Stricter than :func:`find_story_section`, which only needs the stars array: editing a
    save means resizing the tips array, the stars array and the beaten bitmap in step, so
    each one has to be found and each has to be preceded by a matching copy of the level
    count.  A partial match is not good enough.

    The stars array found by :func:`find_story_section` is the anchor, because a save
    holds other count-prefixed arrays that satisfy the structural test on their own — a
    bare structural scan happily locks onto one of those and rewrites the wrong record.
    The scan is only used as a fallback for a brand-new save whose star ratings are still
    all zero, which the star-value heuristic cannot see; there the first match wins, since
    story progress is the earliest such array in the file.
    """
    found = find_story_section(data)
    if found is not None:
        return _complete_layout(data, *found)
    return _scan_for_layout(data)


def _complete_layout(data: bytes, stars_count_off: int, tag_size: int) -> StoryLayout | None:
    """Grow a located stars array into a full layout, or return None if it does not fit."""
    count = struct.unpack_from("<I", data, stars_count_off)[0]
    count_off = stars_count_off - count * 4 - 4 - tag_size
    if count_off < 0:
        return None
    if struct.unpack_from("<I", data, count_off)[0] != count:
        return None
    if (data[count_off + 4:count_off + 8] == b"TCEV") != (tag_size == 4):
        return None

    stars_end = stars_count_off + 4 + tag_size + count * 4
    # A single byte of unrelated state sits between the stars array and the bitmap's
    # count field; tolerate its absence rather than assume it is always there.
    for gap in (1, 0):
        beaten_count_off = stars_end + gap
        if beaten_count_off + 4 > len(data):
            continue
        if struct.unpack_from("<I", data, beaten_count_off)[0] != count:
            continue
        beaten_tag_size = 4 if data[beaten_count_off + 4:beaten_count_off + 8] == b"TCEV" else 0
        layout = StoryLayout(count_off, tag_size, count, beaten_count_off, beaten_tag_size)
        if layout.end <= len(data):
            return layout
    return None


def _scan_for_layout(data: bytes) -> StoryLayout | None:
    """Return the first complete layout in the file, ignoring the star ratings."""
    for stars_count_off in range(0, len(data) - 8):
        count = struct.unpack_from("<I", data, stars_count_off)[0]
        if not (1 <= count <= MAX_LEVELS):
            continue
        tag_size = 4 if data[stars_count_off + 4:stars_count_off + 8] == b"TCEV" else 0
        stars_end = stars_count_off + 4 + tag_size + count * 4
        if stars_end > len(data):
            continue
        stars = struct.unpack_from(f"<{count}f", data, stars_count_off + 4 + tag_size)
        if not all(v == 0.0 or 0.5 <= v <= 6.0 for v in stars):
            continue
        layout = _complete_layout(data, stars_count_off, tag_size)
        if layout is not None:
            return layout
    return None


# ── Writing ───────────────────────────────────────────────────────────────────

def mark_levels_complete(save_file: str, levels: Iterable[int]) -> set[int]:
    """
    Force the given 1-based story levels to a beaten, five-star state on disk.

    Only the star rating and the beaten bit are written.  The tips a level earned are
    left exactly as they are, which for a level that was never played means $0 — the
    player did not earn them, so the map screen should not claim otherwise.

    Levels beyond the count the save currently stores extend it; the levels in between
    are added as untouched slots, exactly as the game would have written them.  Returns
    the levels that were actually changed — an empty set means the save already had them
    and nothing was written.

    The rewritten file is re-signed, checked by re-parsing it, and swapped in atomically.
    The original is kept once as a ``.dat.apbak`` sidecar, and the write is abandoned if
    the game touches the save while it is being rebuilt.
    """
    wanted = {n for n in levels if 1 <= n <= MAX_LEVELS}
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

    old_count = layout.count
    tips = list(struct.unpack_from(f"<{old_count}I", body, layout.tips_base))
    stars = list(struct.unpack_from(f"<{old_count}f", body, layout.stars_base))
    beaten = bytearray(body[layout.beaten_base:layout.beaten_base + bitmap_size(old_count)])

    new_count = max(old_count, max(wanted))
    tips += [0] * (new_count - old_count)
    stars += [0.0] * (new_count - old_count)
    beaten += bytes(bitmap_size(new_count) - len(beaten))

    was_beaten = {i + 1 for i, value in enumerate(stars) if value > 0.0}

    changed: set[int] = set()
    for level in wanted:
        i = level - 1
        if stars[i] < FIVE_STARS:
            stars[i] = FIVE_STARS
            changed.add(level)
        if not beaten[i // 8] >> (i % 8) & 1:
            beaten[i // 8] |= 1 << (i % 8)
            changed.add(level)
    if not changed:
        return set()

    rebuilt = _rebuild_story(body, layout, new_count, tips, stars, beaten)
    _verify(rebuilt, new_count, wanted, was_beaten | wanted, tips)
    _replace_atomically(save_file, rebuilt + sign(rebuilt), stat_before)
    return changed


def ensure_level_slots(save_file: str, count: int = MAX_LEVELS) -> bool:
    """
    Widen the story records back out to ``count`` slots, keeping every rating.

    The game rewrites them to hold only as many levels as the player has reached, so a
    profile laid down with all 120 slots is back to a handful after the first save.  That
    matters beyond the file itself: the game sizes its in-memory level array from what it
    loaded, and the memory writer reads a fixed 120 entries, so a short array makes it read
    past the end, fail its sanity check, and stop patching entirely.

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
    if layout.count >= count:
        return False

    old_count = layout.count
    tips = list(struct.unpack_from(f"<{old_count}I", body, layout.tips_base))
    stars = list(struct.unpack_from(f"<{old_count}f", body, layout.stars_base))
    beaten = bytearray(body[layout.beaten_base:layout.beaten_base + bitmap_size(old_count)])
    was_beaten = {i + 1 for i, value in enumerate(stars) if value > 0.0}

    tips += [0] * (count - old_count)
    stars += [0.0] * (count - old_count)
    beaten += bytes(bitmap_size(count) - len(beaten))

    rebuilt = _rebuild_story(body, layout, count, tips, stars, beaten)
    _verify(rebuilt, count, set(), was_beaten, tips)
    _replace_atomically(save_file, rebuilt + sign(rebuilt), stat_before)
    return True


def _rebuild_story(
    body: bytes, layout: StoryLayout, count: int,
    tips: list[int], stars: list[float], beaten: bytearray,
) -> bytes:
    """Splice resized story records back into a save body, tagging them for their length."""
    tag = vector_tag(count)
    rebuilt = bytearray(body[:layout.count_off])
    rebuilt += struct.pack("<I", count) + tag
    rebuilt += struct.pack(f"<{count}I", *tips)
    rebuilt += struct.pack("<I", count) + tag
    rebuilt += struct.pack(f"<{count}f", *stars)
    rebuilt += body[layout.stars_end:layout.beaten_count_off]
    rebuilt += struct.pack("<I", count) + tag
    rebuilt += beaten
    rebuilt += body[layout.end:]
    return bytes(rebuilt)


def _verify(
    body: bytes, expected_count: int, levels: set[int], beaten: set[int], tips: list[int]
) -> None:
    """
    Re-parse a rebuilt save body and confirm it says what it was meant to say.

    ``beaten`` is every level that must read as played afterwards.  Checking it through
    :func:`find_story_section`, which locates the stars array on its own terms, is what
    catches the dangerous failure: a layout anchored on the wrong count-prefixed array
    rebuilds a perfectly well-formed file that has quietly eaten the player's progress.

    ``tips`` is the array as it went in: nothing here writes it, so reading anything else
    back means the records were spliced together wrongly.
    """
    layout = find_layout(body)
    if layout is None or layout.count != expected_count:
        raise ValueError("rebuilt save file did not parse back")
    expected_tag = len(vector_tag(layout.count))
    if layout.tag_size != expected_tag or layout.beaten_tag_size != expected_tag:
        raise ValueError("rebuilt save file tags its story vectors incorrectly")
    written_tips = struct.unpack_from(f"<{layout.count}I", body, layout.tips_base)
    stars = struct.unpack_from(f"<{layout.count}f", body, layout.stars_base)
    bits = body[layout.beaten_base:layout.beaten_base + bitmap_size(layout.count)]
    for level in levels:
        i = level - 1
        if stars[i] < FIVE_STARS or not bits[i // 8] >> (i % 8) & 1:
            raise ValueError(f"rebuilt save file is missing level {level}")
    if list(written_tips) != tips:
        raise ValueError("rebuilt save file changed the tips the player earned")

    found = find_story_section(body)
    if found is None:
        raise ValueError("rebuilt save file has no readable story section")
    count_off, tag_size = found
    count = struct.unpack_from("<I", body, count_off)[0]
    ratings = struct.unpack_from(f"<{count}f", body, count_off + 4 + tag_size)
    if {i + 1 for i, value in enumerate(ratings) if value > 0.0} != beaten:
        raise ValueError("rebuilt save file changed which levels count as played")


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
