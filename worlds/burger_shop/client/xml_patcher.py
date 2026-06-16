"""
Patch game Order_*.xml files to reflect which recipes have been received.

Pre-setup: the player copies the original game XML files to
``<game_path>/archipelago/levels/`` and adds
``<String id="LooseFilePath">archipelago</String>`` to
``properties/params_user.xml``.  The game then reads those loose files
instead of the packed ones in BurgerShop.pak, so the client can freely
rewrite them to control which recipes appear in customer orders.

On the first patch, each target file is backed up to ``<name>.xml.orig``.
All subsequent patches read from the backup, so the original is never lost
and newly received items can always be re-added cleanly.

XML format notes (from the actual game files):
  - Recipe choices are comma-separated weighted entries inside a single
    <Item> or <Flair> element: ``<Item id="X">Beef, Beef Cheese</Item>``
  - A weight prefix is an integer followed by a space: ``30 Beef Cheese``
  - Entries can span multiple lines; whitespace around commas is ignored
  - Some <Item> elements contain a single "compound" value with no comma,
    e.g. ``snacktray snacknugget`` (a snack recipe) or
    ``SaladBowl HippySaladIngredients`` (structural: salad + ingredient ref)
  - An empty <Item> list causes the game to skip that choice; elements that
    become entirely empty are also removed from any parent lists that
    reference them by ID (dead-item propagation)

Order_Alien.xml is intentionally excluded: alien recipes are permanently
required for chapter-8 levels and must never be filtered.
"""
from __future__ import annotations

import os
import re
import shutil

from .recipe_data import BASE_BURGER_STRINGS, BONUS_PAIRS, ITEM_TO_XML, SALAD_INGREDIENT_ORDER

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Subdirectory written by the player during pre-setup.
_LEVELS_SUBDIR: str = os.path.join("archipelago", "levels")

# All XML entry strings tied to AP recipe items (or always-available bases).
_ALL_RECIPE_STRINGS: frozenset[str] = frozenset(
    s
    for val in ITEM_TO_XML.values()
    for s in (val if isinstance(val, list) else [val])
) | BASE_BURGER_STRINGS | frozenset(SALAD_INGREDIENT_ORDER)

# Element IDs that are excluded from BONUS_PAIRS injection because they use a
# separate sibling element to present the bonus item in the correct quantity.
_BONUS_PAIRS_EXCLUDED_IDS: frozenset[str] = frozenset({
    "SchoolGirlMeal3",  # SmallVanillaColaFloat gets its own SchoolGirlMeal4 (3× instead of 1×)
})

# Item IDs defined in one order file but referenced by compound entries in other
# files.  Maps each ID to the set of XML strings it contains; when none of those
# strings are unlocked the ID's element will be empty in its home file, so it
# must be seeded as dead when patching every file that references it.
_CROSS_FILE_DEPS: dict[str, frozenset[str]] = {
    # RandomSnackSide (Order_Random.xml) is referenced in Order_Hippy.xml's snack entries.
    "RandomSnackSide": frozenset({"SmallFries", "SmallOnionRings", "SmallCurlyFries"}),
    # SchoolGirlMeal3 is defined in the original game XML (not our archipelago override)
    # so _build_dead_items never sees it.  Seed it dead when its content is locked.
    "SchoolGirlMeal3": frozenset({"LargeVanillaColaFloat"}),
}

# Files the patcher rewrites.  Order_Alien.xml is excluded by design.
_ORDER_FILES: tuple[str, ...] = (
    "Order_Random.xml",
    "Order_BizChick.xml",
    "Order_Cowboy.xml",
    "Order_Cowgirl.xml",
    "Order_BizDude.xml",
    "Order_Punk.xml",
    "Order_Clown.xml",
    "Order_SchoolGirls.xml",
    "Order_MomAndKid.xml",
    "Order_SportsFan.xml",
    "Order_SoftballPlayer.xml",
    "Order_Hippy.xml",
    "Order_Surfer.xml",
    "Order_Sumo.xml",
)

# Matches a complete <Item …>…</Item> or <Flair …>…</Flair> block, including
# multi-line content.
# Groups: (1) full open tag, (2) tag name "Item"/"Flair", (3) attributes text,
#         (4) element body, (5) close tag.
_BLOCK_RE = re.compile(
    r"(<(Item|Flair)\b([^>]*)>)(.*?)(</(?:Item|Flair)>)",
    re.IGNORECASE | re.DOTALL,
)
_ID_ATTR_RE = re.compile(r'\bid="([^"]+)"', re.IGNORECASE)
# Optional leading integer weight: "30 Beef Cheese" → weight=30, value="Beef Cheese"
_WEIGHT_PREFIX_RE = re.compile(r"^(\d+)\s+(.+)$")
# Matches an <Item> element whose body is empty after filtering, plus its line.
# These are removed entirely so the game never loads an item with no choices.
# Each character XML file is self-contained (no cross-file item references), so
# removing orphaned items is always safe.
_EMPTY_ITEM_RE = re.compile(r"[ \t]*<Item\b[^>]*></Item>[ \t]*\r?\n?", re.IGNORECASE)
# Extracts the root meal item ID from the <Customer> element (e.g. "SoftballPlayerMeal").
_CUSTOMER_RE = re.compile(r"<Customer\b[^>]*>([^<]+)</Customer>", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Game.xml attribute patching
# ---------------------------------------------------------------------------

_GAME_XML_FILE: str = "Game.xml"

# Disabled attribute values — applied when the controlling AP item has not been received.
# Intentionally unique large numbers so they can be found and replaced in game memory
# without false positives when the powerup is later unlocked.
_GAME_DISABLED: dict[str, str] = {
    "PowerupFreq_Cookie":   "600000002",
    "PowerupFreq_AllHappy": "700000003",
    "PowerupFreq_Money":    "800000004",
    "PowerupFreq_Speed":    "900000005",
}

# Which AP items enable each attribute.  An attribute keeps its original value
# from the .orig if ANY of its listed items has been received; otherwise the
# disabled value above is substituted.
_ATTR_ENABLED_BY: dict[str, frozenset[str]] = {
    "PowerupFreq_Cookie":   frozenset({"Cookie Powerup"}),
    "PowerupFreq_AllHappy": frozenset({"Happy Powerup"}),
    "PowerupFreq_Money":    frozenset({"Money Powerup"}),
    "PowerupFreq_Speed":    frozenset({"Speed Powerup"}),
}

# ---------------------------------------------------------------------------
# Layout.xml element patching
# ---------------------------------------------------------------------------

_LAYOUT_FILE: str = "Layout.xml"

# Maps each removable element tag to the AP item that enables it.
_LAYOUT_ELEMENT_ITEMS: dict[str, str] = {
    "TreatTray":   "Cookies",
    "WorkStation": "Workstation",
    "TipMeter":    "BurgerBot",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _levels_dir(game_path: str) -> str:
    return os.path.join(game_path, _LEVELS_SUBDIR)


def _compute_unlocked_strings(received_item_names: list[str]) -> frozenset[str]:
    """Build the set of XML entry text values that should remain in the files."""
    result: set[str] = set(BASE_BURGER_STRINGS)
    salad_count = 0
    for name in received_item_names:
        if name == "Progressive Salad":
            salad_count += 1
            continue
        val = ITEM_TO_XML.get(name)
        if val is None:
            continue
        if isinstance(val, list):
            result.update(val)
        else:
            result.add(val)
    result.update(SALAD_INGREDIENT_ORDER[:salad_count])
    return frozenset(result)


def _split_entries(content: str) -> list[str]:
    """Split comma-separated element content into stripped, non-empty entry strings."""
    return [e.strip() for e in content.split(",") if e.strip()]


def _entry_value(entry: str) -> str:
    """Return the value part of an entry, stripping an optional integer weight prefix."""
    m = _WEIGHT_PREFIX_RE.match(entry)
    return m.group(2) if m else entry


def _build_dead_items(text: str, unlocked: frozenset[str], initial_dead: frozenset[str] = frozenset()) -> frozenset[str]:
    """Return the set of item IDs that have no remaining entries after filtering.

    Iterates to a fixed point so that a dead sub-item cascades upward and
    makes its parent dead too (e.g. if all burger variants are filtered,
    the sub-list item referencing them becomes dead and is removed from the
    top-level burger list).

    Also handles compound entries of the form ``Keyword SubItemID`` (e.g.
    ``SaladBowl HippySaladIngredients``): if the last word of the compound
    is a dead item ID, that entry is treated as dead too.
    """
    # Collect id → [entries] for every named <Item> element in the file.
    # <Flair> elements are intentionally excluded: an empty flair list just
    # means "no condiment applied", which is harmless.  Including flair IDs
    # in the dead set would incorrectly remove Clown snack entries whose last
    # word is an inline flair reference (e.g. "snacktray toy … ClownSnackFlair").
    elem_entries: dict[str, list[str]] = {}
    for m in _BLOCK_RE.finditer(text):
        if m.group(2).lower() != "item":
            continue
        id_m = _ID_ATTR_RE.search(m.group(3))
        if id_m:
            elem_entries[id_m.group(1)] = _split_entries(m.group(4))

    dead: set[str] = set(initial_dead)
    changed = True
    while changed:
        changed = False
        for item_id, entries in elem_entries.items():
            if item_id in dead:
                continue
            remaining: list[str] = []
            for entry in entries:
                value = _entry_value(entry)
                # Remove if it's a known recipe string that hasn't been unlocked.
                if value in _ALL_RECIPE_STRINGS and value not in unlocked:
                    continue
                # Remove if it directly references a dead item ID.
                if value in dead:
                    continue
                # Remove compound entries (e.g. "SaladBowl X") when the
                # referenced sub-item (last word) is dead.
                words = value.split()
                if len(words) > 1 and words[-1] in dead:
                    continue
                # Remove compound entries with a locked inline ingredient as the
                # trailing word (e.g. "snacktray snackcarrot … ketchup").
                if len(words) > 1 and words[-1] in _ALL_RECIPE_STRINGS and words[-1] not in unlocked:
                    continue
                remaining.append(entry)
            if not remaining:
                # An item that would otherwise be empty stays alive when a bonus
                # recipe is eligible to be injected into it (keeping the parent
                # element's reference valid so the customer can still order it).
                original_values = {_entry_value(e) for e in entries}
                if not any(
                    base in original_values and bonus in unlocked
                    for bonus, base in BONUS_PAIRS.items()
                ):
                    dead.add(item_id)
                    changed = True

    return frozenset(dead)


def _filter_content(
    content: str,
    unlocked: frozenset[str],
    dead: frozenset[str],
    element_id: str | None = None,
) -> str:
    """Return the filtered comma-separated entry list for one element body."""
    # Collect all base entry values present in the original content so bonus
    # items can be injected even when their paired base was filtered out.
    original_values = {_entry_value(e) for e in _split_entries(content)}
    kept: list[str] = []
    for entry in _split_entries(content):
        value = _entry_value(entry)
        if value in _ALL_RECIPE_STRINGS and value not in unlocked:
            continue
        if value in dead:
            continue
        words = value.split()
        if len(words) > 1 and words[-1] in dead:
            continue
        if len(words) > 1 and words[-1] in _ALL_RECIPE_STRINGS and words[-1] not in unlocked:
            continue
        kept.append(entry)
    # Inject bonus items for any of their paired base entries that appeared in
    # the original content, regardless of whether the base survived filtering.
    # Excluded elements handle bonus items via their own sibling Item elements.
    if element_id not in _BONUS_PAIRS_EXCLUDED_IDS:
        for bonus_xml, base_xml in BONUS_PAIRS.items():
            if base_xml in original_values and bonus_xml in unlocked:
                kept.append(bonus_xml)
    return ", ".join(kept)


def _filter_xml(text: str, unlocked: frozenset[str]) -> str:
    """Rewrite all Item/Flair element bodies to contain only unlocked recipe entries."""
    # Seed the dead set with any cross-file item IDs whose home-file element will
    # be empty after patching, so compound entries referencing them are filtered here.
    cross_file_dead = frozenset(
        item_id for item_id, required in _CROSS_FILE_DEPS.items()
        if not (required & unlocked)
    )
    dead = _build_dead_items(text, unlocked, cross_file_dead)

    def _replace(m: re.Match) -> str:
        id_m = _ID_ATTR_RE.search(m.group(3))
        element_id = id_m.group(1) if id_m else None
        filtered = _filter_content(m.group(4), unlocked, dead, element_id)
        # A Flair element with type="pickmult" or condiment entries must never be
        # written empty — the game crashes trying to pick from an empty list.
        # Fall back to "noflair" (no condiment/topping applied) so the parent
        # food item can still be ordered.
        if m.group(2).lower() == "flair" and not filtered and m.group(4).strip():
            filtered = "noflair"
        return m.group(1) + filtered + m.group(5)

    result = _BLOCK_RE.sub(_replace, text)

    # Find the root meal item ID so we can protect it from removal.
    customer_m = _CUSTOMER_RE.search(result)
    meal_id = customer_m.group(1).strip() if customer_m else None

    def _remove_or_fallback(m: re.Match) -> str:
        if meal_id:
            id_m = _ID_ATTR_RE.search(m.group(0))
            if id_m and id_m.group(1) == meal_id:
                # The customer's root item has no choices — fall back to
                # EmptySandwich so the customer can still place an order.
                open_tag = re.search(r"<Item\b[^>]*>", m.group(0), re.IGNORECASE).group(0)
                return f"{open_tag}EmptySandwich</Item>\n"
        return ""

    return _EMPTY_ITEM_RE.sub(_remove_or_fallback, result)


def _patch_file(levels_dir: str, filename: str, unlocked: frozenset[str]) -> None:
    src = os.path.join(levels_dir, filename)
    orig = src + ".orig"

    if not os.path.isfile(src):
        return

    # Back up the original on first run; always restore from the backup.
    if not os.path.isfile(orig):
        shutil.copy2(src, orig)

    with open(orig, encoding="utf-8", errors="replace") as f:
        text = f.read()

    with open(src, "w", encoding="utf-8") as f:
        f.write(_filter_xml(text, unlocked))


def _patch_layout_xml(levels_dir: str, received: frozenset[str]) -> None:
    src = os.path.join(levels_dir, _LAYOUT_FILE)
    orig = src + ".orig"

    if not os.path.isfile(src):
        return

    if not os.path.isfile(orig):
        shutil.copy2(src, orig)

    with open(orig, encoding="utf-8", errors="replace") as f:
        text = f.read()

    for element, item in _LAYOUT_ELEMENT_ITEMS.items():
        if item not in received:
            text = re.sub(
                rf"[ \t]*<{re.escape(element)}\b[^>]*/?>[ \t]*\r?\n?",
                "",
                text,
                flags=re.IGNORECASE,
            )

    with open(src, "w", encoding="utf-8") as f:
        f.write(text)


_ATTR_RE = re.compile(r'\b(\w+)\s*=\s*"([^"]*)"')


def _set_attr(text: str, attr: str, value: str) -> str:
    """Replace every occurrence of attr="..." in text with attr="value"."""
    return re.sub(
        rf'\b({re.escape(attr)}\s*=\s*")[^"]*(")',
        rf'\g<1>{value}\g<2>',
        text,
    )


def _patch_game_xml(levels_dir: str, received: frozenset[str]) -> list[tuple[str, str]]:
    """Patch Game.xml and return (old_value, new_value) pairs for every attribute that changed.

    The caller can use these pairs to update the same values in game memory so that
    changes take effect without requiring a game restart.
    """
    src = os.path.join(levels_dir, _GAME_XML_FILE)
    orig = src + ".orig"

    if not os.path.isfile(src):
        return []

    if not os.path.isfile(orig):
        shutil.copy2(src, orig)

    # .orig is always the enabled/original state; read it as the clean base.
    with open(orig, encoding="utf-8", errors="replace") as f:
        text = f.read()

    # Read the current live file to detect what will change in memory.
    try:
        with open(src, encoding="utf-8", errors="replace") as f:
            prev_text = f.read()
    except OSError:
        prev_text = ""

    for attr, disabled_value in _GAME_DISABLED.items():
        if not (_ATTR_ENABLED_BY[attr] & received):
            text = _set_attr(text, attr, disabled_value)

    # Collect (old, new) string pairs for every attribute that differs from what
    # was previously written so the caller can patch game memory in-place.
    prev_vals = {m.group(1): m.group(2) for m in _ATTR_RE.finditer(prev_text)}
    new_vals  = {m.group(1): m.group(2) for m in _ATTR_RE.finditer(text)}
    changes: list[tuple[str, str]] = [
        (prev_vals[attr], new_vals[attr])
        for attr in _GAME_DISABLED
        if attr in prev_vals and attr in new_vals and prev_vals[attr] != new_vals[attr]
    ]

    with open(src, "w", encoding="utf-8") as f:
        f.write(text)

    return changes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def archipelago_levels_ready(game_path: str) -> bool:
    """Return True if the archipelago/levels directory contains Order XML files."""
    return os.path.isfile(
        os.path.join(_levels_dir(game_path), "Order_BizChick.xml")
    )


def apply_recipe_unlocks(
    game_path: str,
    received_item_names: list[str],
) -> tuple[bool, list[tuple[str, str]]]:
    """Rewrite Order_*.xml, Game.xml, and Layout.xml to reflect received items.

    Returns ``(success, game_xml_changes)`` where *success* is False when the
    archipelago/levels directory has not been set up and *game_xml_changes* is a
    list of ``(old_value, new_value)`` string pairs for every Game.xml attribute
    that changed.  The caller can use these pairs to patch the running game's
    memory so that powerup changes take effect without a restart.
    """
    from CommonClient import logger

    levels = _levels_dir(game_path)
    if not os.path.isdir(levels):
        logger.warning(
            "[Burger Shop] archipelago/levels not found — pre-setup required. "
            f"Copy the game's XML files to {levels} and add "
            "LooseFilePath=archipelago to properties/params_user.xml."
        )
        return False, []

    unlocked = _compute_unlocked_strings(received_item_names)
    received_set = frozenset(received_item_names)

    for filename in _ORDER_FILES:
        try:
            _patch_file(levels, filename, unlocked)
        except OSError as e:
            logger.warning(f"[Burger Shop] Failed to patch {filename}: {e}")

    game_xml_changes: list[tuple[str, str]] = []
    try:
        game_xml_changes = _patch_game_xml(levels, received_set)
    except OSError as e:
        logger.warning(f"[Burger Shop] Failed to patch Game.xml: {e}")

    try:
        _patch_layout_xml(levels, received_set)
    except OSError as e:
        logger.warning(f"[Burger Shop] Failed to patch Layout.xml: {e}")

    logger.debug(
        f"[Burger Shop] XML patched "
        f"({len(received_item_names)} item(s) unlocked)."
    )
    return True, game_xml_changes
