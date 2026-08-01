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

import hashlib
import os
import random
import re
import shutil
from collections import Counter, defaultdict

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

# Element IDs holding "N+ Pool" required-distinct-pick entries (e.g.
# "3+ SchoolGirlDrink, 3+ SchoolGirlSide") whose Pool is relaxed to "N Pool"
# once fewer than N alternatives remain unlocked, so the customer still gets
# N items (via duplicates) instead of fewer than N.  See _relax_required_picks.
_SCHOOLGIRLS_RELAX_REQUIRED_PICKS: frozenset[str] = frozenset({
    "SchoolGirlMeal2",     # 3+ SchoolGirlDrink, 3+ SchoolGirlSide
    "SchoolGirlMealAlt3",  # 3+ SchoolGirlSandwich, SchoolGirlSideAlt
})

# Element IDs holding a literal combo list (type="list" with several bare,
# unweighted alternatives, e.g. "LargeVanillaSundae, LargeChocolateSundae,
# LargeStrawberrySundae") that should keep its original entry count even
# after locked flavors are pruned out.  See _pad_to_original_count.
_SCHOOLGIRLS_PAD_TO_ORIGINAL_COUNT: frozenset[str] = frozenset({
    "SchoolGirlMeal1",  # sundae course (Vanilla/Chocolate/Strawberry)
})

# When a customer's whole order collapses because everything in it is still locked,
# the root <Item> is stubbed rather than deleted so the <Customer> reference still
# resolves.  The stub is the Random customer's meal, which keeps the order plausible
# and varied instead of reducing every starved customer to a bare bun.
_RANDOM_ORDER_FILE: str = "Order_Random.xml"
_RANDOM_MEAL: str = "RandomMeal"
# A game-engine primitive (a bare bun, no XML definition), so it is always available
# even if the Random meal itself collapsed.
_LAST_RESORT_STUB: str = "EmptySandwich"

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
# "N+ PoolID": requires N distinct picks from PoolID (e.g. "3+ SchoolGirlDrink").
_N_PLUS_ENTRY_RE = re.compile(r"^(\d+)\+ (\S+)$")
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

    # Pad literal combo lists (e.g. the School Girls sundae course) back up to
    # their original entry count by cycling through the survivors, so pruning
    # locked flavors shrinks variety instead of shrinking the order size.
    # Repeats are collapsed into "N entry" weight form (the same idiom the
    # vanilla files already use for literal duplicates, e.g. "3 SmallVanillaColaFloat").
    original_entries = _split_entries(content)
    if element_id in _SCHOOLGIRLS_PAD_TO_ORIGINAL_COUNT and kept and len(kept) < len(original_entries):
        cycle = [kept[i % len(kept)] for i in range(len(original_entries))]
        counts: dict[str, int] = {}
        order: list[str] = []
        for e in cycle:
            if e not in counts:
                order.append(e)
            counts[e] = counts.get(e, 0) + 1
        kept = [e if counts[e] == 1 else f"{counts[e]} {e}" for e in order]

    return ", ".join(kept)


def _compute_kept_counts(text: str, unlocked: frozenset[str], dead: frozenset[str]) -> dict[str, int]:
    """Return item id -> number of entries that survive filtering (ignoring bonus injection).

    Used to look up how many live alternatives a referenced pool (e.g.
    SchoolGirlDrink) has, independent of the single left-to-right substitution
    pass over the file.
    """
    counts: dict[str, int] = {}
    for m in _BLOCK_RE.finditer(text):
        if m.group(2).lower() != "item":
            continue
        id_m = _ID_ATTR_RE.search(m.group(3))
        if not id_m:
            continue
        kept = 0
        for entry in _split_entries(m.group(4)):
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
            kept += 1
        counts[id_m.group(1)] = kept
    return counts


def _relax_required_picks(content: str, pool_kept_counts: dict[str, int]) -> str:
    """Rewrite 'N+ Pool' entries to 'N Pool' when Pool has fewer than N live
    alternatives (but at least one), so the customer still gets N items via
    duplicates instead of fewer than N."""
    rewritten = []
    for entry in _split_entries(content):
        m = _N_PLUS_ENTRY_RE.match(entry)
        if m:
            n, pool_id = int(m.group(1)), m.group(2)
            kept_count = pool_kept_counts.get(pool_id)
            if kept_count is not None and 0 < kept_count < n:
                entry = f"{n} {pool_id}"
        rewritten.append(entry)
    return ", ".join(rewritten)


def _filter_xml(text: str, unlocked: frozenset[str], stub_order: str = _LAST_RESORT_STUB) -> str:
    """Rewrite all Item/Flair element bodies to contain only unlocked recipe entries.

    *stub_order* is what a customer falls back to ordering when their whole order is
    still locked; see _RANDOM_MEAL.
    """
    # Seed the dead set with any cross-file item IDs whose home-file element will
    # be empty after patching, so compound entries referencing them are filtered here.
    cross_file_dead = frozenset(
        item_id for item_id, required in _CROSS_FILE_DEPS.items()
        if not (required & unlocked)
    )
    dead = _build_dead_items(text, unlocked, cross_file_dead)
    pool_kept_counts = _compute_kept_counts(text, unlocked, dead)

    def _replace(m: re.Match) -> str:
        id_m = _ID_ATTR_RE.search(m.group(3))
        element_id = id_m.group(1) if id_m else None
        content = m.group(4)
        if element_id in _SCHOOLGIRLS_RELAX_REQUIRED_PICKS:
            content = _relax_required_picks(content, pool_kept_counts)
        filtered = _filter_content(content, unlocked, dead, element_id)
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
                # The customer's root item has no choices — fall back to the Random
                # customer's meal so they can still place a plausible order.
                # Order_Random.xml's own root *is* RandomMeal, so stubbing it with the
                # same ID would make the item reference itself; use the bun there.
                body = _LAST_RESORT_STUB if meal_id == stub_order else stub_order
                open_tag = re.search(r"<Item\b[^>]*>", m.group(0), re.IGNORECASE).group(0)
                return f"{open_tag}{body}</Item>\n"
        return ""

    return _EMPTY_ITEM_RE.sub(_remove_or_fallback, result)


def _patch_file(
    levels_dir: str,
    filename: str,
    unlocked: frozenset[str],
    stub_order: str = _LAST_RESORT_STUB,
) -> None:
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
        f.write(_filter_xml(text, unlocked, stub_order))


def _item_is_live(levels_dir: str, filename: str, item_id: str) -> bool:
    """True if *item_id* still has a non-empty body in the already-patched *filename*."""
    try:
        with open(os.path.join(levels_dir, filename), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return False
    m = re.search(
        rf'<Item\b[^>]*\bid="{re.escape(item_id)}"[^>]*>(.*?)</Item>',
        text, re.IGNORECASE | re.DOTALL,
    )
    return bool(m and m.group(1).strip())


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


# ---------------------------------------------------------------------------
# DefLevel.xml character randomization
# ---------------------------------------------------------------------------
#
# Each <Customer> element lists the characters that can appear in the levels that
# reference it, as comma-separated "<count> <Character>" groups.  The count is
# optional and defaults to 1, so both of these are valid and appear in the vanilla
# data, sometimes within a single element:
#
#   <Customer id="customers7-2" type="shufflelist">4 Sumo, 4 Punk, 4 Cowgirl</Customer>
#   <Customer id="customers7-10" type="shufflelist">4 Sumo,Surfer,Hippy,Random</Customer>
#
# Randomization is driven by a seed chosen at generation time and shipped in slot
# data, so every client rebuilding this file from .orig produces the same result.

_DEFLEVEL_FILE: str = "DefLevel.xml"

# Never shuffled, and never used as a replacement.  Levels 71-80 are alien levels
# whose logic rule (rules.py) assumes the Alien customer appears there in exactly
# the numbers the vanilla data specifies.
_FROZEN_CHARACTERS: frozenset[str] = frozenset({"alien"})

RANDOMIZE_OFF: int = 0
RANDOMIZE_GROUPS: int = 1  # keep each group's size, swap which character it is
RANDOMIZE_COUNTS: int = 2  # keep only the level's total, re-roll groups and sizes

_CUSTOMER_ELEM_RE = re.compile(r"(<Customer\b[^>]*>)(.*?)(</Customer>)", re.IGNORECASE | re.DOTALL)
_GROUP_RE = re.compile(r"^(?:(\d+)\s+)?(\S+)$")


def _parse_groups(body: str) -> list[tuple[int, str, bool]]:
    """Split a <Customer> body into (count, character, had_explicit_count) triples."""
    groups: list[tuple[int, str, bool]] = []
    for entry in body.split(","):
        entry = entry.strip()
        if not entry:
            continue
        m = _GROUP_RE.match(entry)
        if not m:
            continue
        count, name = m.group(1), m.group(2)
        groups.append((int(count) if count else 1, name, count is not None))
    return groups


def _format_groups(groups: list[tuple[int, str, bool]]) -> str:
    # A bare name means 1, so keep that shorthand where the vanilla file used it.
    return ", ".join(
        name if count == 1 and not had_count else f"{count} {name}"
        for count, name, had_count in groups
    )


def _collect_characters(text: str) -> dict[str, str]:
    """Map lowercased character name -> its most common spelling in the file.

    The vanilla data is not consistently cased (Burger Shop 2 has a lone "CowGirl"
    against "Cowgirl" everywhere else), so characters are matched case-insensitively
    and re-emitted using whichever spelling the file uses most.
    """
    spellings: dict[str, Counter] = defaultdict(Counter)
    for m in _CUSTOMER_ELEM_RE.finditer(text):
        for _, name, _ in _parse_groups(m.group(2)):
            spellings[name.lower()][name] += 1
    return {low: c.most_common(1)[0][0] for low, c in spellings.items()}


def _randomize_customer_body(
    body: str,
    mode: int,
    pool: list[str],
    rng: random.Random,
) -> str:
    groups = _parse_groups(body)
    frozen = {i for i, (_, name, _) in enumerate(groups) if name.lower() in _FROZEN_CHARACTERS}
    live = [i for i in range(len(groups)) if i not in frozen]
    if not live:
        return body

    if mode == RANDOMIZE_GROUPS:
        # Sample without replacement so a level never loses variety by having two
        # groups collapse onto the same character.  Levels with more groups than the
        # pool can supply fall back to independent picks (does not occur in vanilla).
        if len(live) <= len(pool):
            names = rng.sample(pool, len(live))
        else:
            names = [rng.choice(pool) for _ in live]
        out = list(groups)
        for i, name in zip(live, names):
            out[i] = (groups[i][0], name, groups[i][2])
        return _format_groups(out)

    # RANDOMIZE_COUNTS: preserve only the number of non-frozen customers, then
    # re-roll both how many characters share them and how they are divided up.
    total = sum(groups[i][0] for i in live)
    if total < 1:
        return body
    count = rng.randint(1, min(len(pool), total))
    names = rng.sample(pool, count)
    # Random composition of `total` into `count` parts of at least 1 (stars and bars).
    cuts = sorted(rng.sample(range(1, total), count - 1)) if count > 1 else []
    sizes = [b - a for a, b in zip([0] + cuts, cuts + [total])]
    new_groups = [(size, name, True) for size, name in zip(sizes, names)]

    # Frozen groups keep their slots; the new groups take over the first live slot.
    out: list[tuple[int, str, bool]] = []
    placed = False
    for i, group in enumerate(groups):
        if i in frozen:
            out.append(group)
        elif not placed:
            out.extend(new_groups)
            placed = True
    return _format_groups(out)


def _patch_deflevel_xml(levels_dir: str, mode: int, seed: int) -> None:
    """Rewrite DefLevel.xml's <Customer> lists according to *mode*."""
    src = os.path.join(levels_dir, _DEFLEVEL_FILE)
    orig = src + ".orig"

    if not os.path.isfile(src):
        return

    if not os.path.isfile(orig):
        shutil.copy2(src, orig)

    with open(orig, encoding="utf-8", errors="replace") as f:
        text = f.read()

    if mode != RANDOMIZE_OFF:
        canonical = _collect_characters(text)
        # sorted() keeps the pool order independent of file iteration order, so the
        # same seed always draws the same characters.
        pool = sorted(
            spelling for low, spelling in canonical.items() if low not in _FROZEN_CHARACTERS
        )
        if pool:
            rng = random.Random(seed)
            text = _CUSTOMER_ELEM_RE.sub(
                lambda m: m.group(1) + _randomize_customer_body(m.group(2), mode, pool, rng)
                + m.group(3),
                text,
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


def _patch_game_xml(
    levels_dir: str,
    received: frozenset[str],
    customer_slots: int = 0,
) -> list[tuple[str, str]]:
    """Patch Game.xml and return (old_value, new_value) pairs for every attribute that changed.

    The caller can use these pairs to update the same values in game memory so that
    changes take effect without requiring a game restart.  *customer_slots* forces every
    level to that many customer slots; 0 keeps the vanilla per-level counts.
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

    # CustomerSlots appears in the leading DefVals block, in the per-section DefVals
    # resets that follow it, and as per-Level overrides.  Rewriting every occurrence
    # is what makes the count uniform — a single Level override would otherwise win
    # over the DefVals default for that level.  0 means "leave the vanilla counts".
    if customer_slots:
        text = _set_attr(text, "CustomerSlots", str(customer_slots))

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

def restart_sensitive_hash(game_path: str) -> str:
    """Hash the startup-only files so callers can tell when a game restart is needed.

    Game.xml is the only file the game parses once at process start; Order_*.xml and
    Layout.xml are re-read when a level loads.  The powerup frequency attributes are
    blanked before hashing — those are pushed into the running process by the client's
    memory patcher, so a change to them alone never requires a restart.
    """
    try:
        with open(os.path.join(_levels_dir(game_path), _GAME_XML_FILE),
                  encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    for attr in _GAME_DISABLED:
        text = _set_attr(text, attr, "")
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def archipelago_levels_ready(game_path: str) -> bool:
    """Return True if the archipelago/levels directory contains Order XML files."""
    return os.path.isfile(
        os.path.join(_levels_dir(game_path), "Order_BizChick.xml")
    )


def apply_recipe_unlocks(
    game_path: str,
    received_item_names: list[str],
    customer_slots: int = 0,
    character_randomization: int = RANDOMIZE_OFF,
    character_seed: int = 0,
) -> tuple[bool, list[tuple[str, str]]]:
    """Rewrite Order_*.xml, Game.xml, and Layout.xml to reflect received items.

    *customer_slots* forces every level to that many customer slots; 0 keeps the
    vanilla per-level counts.  *character_randomization* rewrites DefLevel.xml's
    customer lists using *character_seed*; see RANDOMIZE_* above.

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

    # Order_Random.xml goes first: every other customer falls back to its RandomMeal
    # when their own order collapses, so we need to know whether it survived filtering.
    ordered = (_RANDOM_ORDER_FILE, *(f for f in _ORDER_FILES if f != _RANDOM_ORDER_FILE))
    stub_order = _LAST_RESORT_STUB
    for filename in ordered:
        try:
            _patch_file(levels, filename, unlocked, stub_order)
        except OSError as e:
            logger.warning(f"[Burger Shop] Failed to patch {filename}: {e}")
            continue
        if filename == _RANDOM_ORDER_FILE and _item_is_live(levels, filename, _RANDOM_MEAL):
            stub_order = _RANDOM_MEAL

    game_xml_changes: list[tuple[str, str]] = []
    try:
        game_xml_changes = _patch_game_xml(levels, received_set, customer_slots)
    except OSError as e:
        logger.warning(f"[Burger Shop] Failed to patch Game.xml: {e}")

    try:
        _patch_layout_xml(levels, received_set)
    except OSError as e:
        logger.warning(f"[Burger Shop] Failed to patch Layout.xml: {e}")

    try:
        _patch_deflevel_xml(levels, character_randomization, character_seed)
    except OSError as e:
        logger.warning(f"[Burger Shop] Failed to patch {_DEFLEVEL_FILE}: {e}")

    logger.debug(
        f"[Burger Shop] XML patched "
        f"({len(received_item_names)} item(s) unlocked)."
    )
    return True, game_xml_changes
