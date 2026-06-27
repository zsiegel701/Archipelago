"""
Patch Burger Shop 2 customer order XML files to reflect which AP recipes have been received.

Pre-setup: copy the game's loose XML files to
``<game_path>/archipelago/levels/`` and add
``<String id="LooseFilePath">archipelago</String>`` to
``properties/params_user.xml``.

Patched file types:
  Breakfast_*.xml  — breakfast customer order pools
  Order_*.xml      — lunch customer order pools
  Dinner_*.xml     — dinner customer order pools

NOT patched (main filter pass):
  ComplexItems.xml   — patched selectively via _patch_complexitems_flairs instead
                       (salad flairs and Snack_Side only; sandwich bodies untouched)
  DefLevelExp.xml    — level structure (untouched)
  *_Alien.xml        — kept intact so alien levels always function
  Game.xml / Layout*.xml — patched separately for powerup/equipment attributes

Filtering rules:
  1. Elements with prunecat="breakfast" are never modified — always-available
     breakfast plate item/flair chains (Bacon/EggFried/SausagePatty plate ingredients).
  2. All other comma-separated alternatives: entries that reference a locked AP XML ID or a
     dead item are removed.  An empty <Item> element becomes dead and propagates upward.
  3. Dinner base items (SteakFries, Parsley, CornCob, MeatLoaf, Phouseroll) and lunch base
     items (San_Hamburger, San_Cheeseburger) are never filtered from any list.
  4. Sandwich context: <Item> elements whose body contains the "BreakfastSandwich" token are
     treated as sandwich orders.  In this context Bacon/EggFried/SausagePatty ALSO act as
     AP gates (they are excluded from _ALL_AP_XML_IDS so plate flairs always pass, but the
     matching AP item still needs to be received before the sandwich order is live).
  5. Cross-file dead items: the three *_Random.xml pool files are processed first and their
     dead-item sets seed the per-character-file filtering pass.
"""
from __future__ import annotations

import os
import re
import shutil

from .recipe_data import (
    ITEM_TO_XML_ID,
    SANDWICH_CONFIGID_MAP,
    SANDWICH_COMPOUND_VARIANTS,
    BREAKFAST_BASE_XML_IDS,
    DINNER_BASE_XML_IDS,
    BONUS_PAIRS,
    COORDS_OX_ITEMS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LEVELS_SUBDIR: str = os.path.join("archipelago", "levels")

_LUNCH_BASE_XML_IDS: frozenset[str] = frozenset({"San_Hamburger", "San_Cheeseburger"})
_ALWAYS_UNLOCKED: frozenset[str] = DINNER_BASE_XML_IDS | _LUNCH_BASE_XML_IDS

_ALL_AP_XML_IDS: frozenset[str] = (frozenset(
    xml_id
    for xml_ids in ITEM_TO_XML_ID.values()
    for xml_id in xml_ids
) | frozenset(
    # Order files reference full variant IDs (San_HamburgerLettuce, San_DoubleCheeseburger,
    # etc.) not the configid keys (San_Lettuce, San_Double).  Add every variant so that
    # _entry_is_blocked can gate them; _compute_unlocked already adds variants to the
    # unlocked set when the corresponding AP item is received.
    variant
    for variants in SANDWICH_CONFIGID_MAP.values()
    for variant in variants
) | frozenset(SANDWICH_COMPOUND_VARIANTS)
) - BREAKFAST_BASE_XML_IDS - DINNER_BASE_XML_IDS - _LUNCH_BASE_XML_IDS

# Breakfast plate base ingredients are excluded from _ALL_AP_XML_IDS so that
# plate flairs are never blocked.  But when the same ingredient appears inside a
# BreakfastSandwich item body (sandwich context) it DOES gate that sandwich —
# e.g. EggFried gates egg-sandwich orders but not breakfast-plate egg flairs.
_SANDWICH_GATE_XML_IDS: frozenset[str] = BREAKFAST_BASE_XML_IDS

_RANDOM_FILES: tuple[str, ...] = (
    "Breakfast_Random.xml",
    "Order_Random.xml",
    "Dinner_Random.xml",
)

# Flair IDs inside ComplexItems.xml whose entries can be safely patched.
# Tomato and Onions also appear in sandwich bodies in ComplexItems.xml, so the
# whole file is excluded from the main filter pass and only these IDs are touched.
_COMPLEXITEMS_FILTERED_FLAIR_IDS: frozenset[str] = frozenset({
    # Salad ingredient flairs
    "SaladIng1",          # Onions, Tomato, DinnerCheese
    "SaladType1",         # SaladIng1, Olives, Croutons
    "SaladType4",         # DinnerCheese, SaladType4a  ← must be patched so DinnerCheese is gated
    "SaladType4_Hippy",   # DinnerCheese, SaladType4a_Hippy  ← same for hippy salad
    "SaladType4a",        # GreenPeppers, Mushrooms, GreenOnions, BaconBits
    "SaladType4a_Hippy",  # GreenPeppers, Mushrooms, GreenOnions
    # Snack side flair — entries are individual small sides; gated so that
    # Snack_SuperFunMeal / Snack_VeggieFunMeal are only orderable once at least
    # one small side is unlocked (Snack_Side collapses to noflair otherwise).
    "Snack_Side",         # SmallFries, SmallOnionRings, SmallCurlyFries
})

_SKIP_FILES: frozenset[str] = frozenset({
    "complexitems.xml",
    "deflevelexp.xml",
    "deflevel.xml",
    "deflevel2.xml",
    "game.xml",
    "gameexp.xml",
    "layout.xml",
    "layout2.xml",
    "layout3.xml",
    "layout_breakfast.xml",
    "layout_dinner.xml",
})

# ---------------------------------------------------------------------------
# Layout*.xml element patching
# ---------------------------------------------------------------------------

_LAYOUT_FILES: tuple[str, ...] = (
    "Layout.xml",
    "Layout2.xml",
    "Layout3.xml",
    "Layout_Breakfast.xml",
    "Layout_Dinner.xml",
)

# Maps each removable element tag to the AP item that enables it.
# Lollipops is the BS2 equivalent of BS1's Cookies — same TreatTray XML element.
_LAYOUT_ELEMENT_ITEMS: dict[str, str] = {
    "TreatTray":   "Lollipops",
    "WorkStation": "Workstation",
    "TipMeter":    "BurgerBot",
}

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_ELEM_RE = re.compile(
    r"(<(Item|Flair)\b([^>]*)>)(.*?)(</(?:Item|Flair)>)",
    re.IGNORECASE | re.DOTALL,
)
_ID_ATTR_RE = re.compile(r'\bid\s*=\s*"([^"]+)"', re.IGNORECASE)
_PRUNECAT_RE = re.compile(r'\bprunecat\s*=\s*"([^"]+)"', re.IGNORECASE)
_WEIGHT_RE = re.compile(r"^(\d+\+?)\s+(.+)$")
# Matches the "N+ ID" required-weight format (distinct from the "ID+" required-suffix format).
_REQUIRED_WEIGHT_RE = re.compile(r"^\d+\+\s")
_PICKMULT_TYPE_RE = re.compile(r'\btype\s*=\s*"pickmult"', re.IGNORECASE)
_EMPTY_ITEM_RE = re.compile(r"[ \t]*<Item\b[^>]*></Item>[ \t]*\r?\n?", re.IGNORECASE)
_CUSTOMER_BODY_RE = re.compile(r"<Customer\b[^>]*>(.*?)</Customer>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'\b(\w+)\s*=\s*"([^"]*)"')

# ---------------------------------------------------------------------------
# Game.xml powerup patching
# ---------------------------------------------------------------------------

_GAME_DISABLED: dict[str, str] = {
    "PowerupFreq_Cookie":    "600000002",  # Lollipop Powerup
    "PowerupFreq_AllHappy":  "700000003",  # Happy Powerup
    "PowerupFreq_Money":     "800000004",  # Money Powerup
    "PowerupFreq_Speed":     "900000005",  # Speed Powerup
    "PowerupFreq_HappyGas":  "500000001",  # Freeze Powerup
    "PowerupFreq_CloseSlot": "400000000",  # Cone Powerup
}

_ATTR_ENABLED_BY: dict[str, frozenset[str]] = {
    "PowerupFreq_Cookie":    frozenset({"Lollipop Powerup"}),
    "PowerupFreq_AllHappy":  frozenset({"Happy Powerup"}),
    "PowerupFreq_Money":     frozenset({"Money Powerup"}),
    "PowerupFreq_Speed":     frozenset({"Speed Powerup"}),
    "PowerupFreq_HappyGas":  frozenset({"Freeze Powerup"}),
    "PowerupFreq_CloseSlot": frozenset({"Cone Powerup"}),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _levels_dir(game_path: str) -> str:
    return os.path.join(game_path, _LEVELS_SUBDIR)


def _entry_value(entry: str) -> str:
    """Return the value part of a weighted entry, stripping the optional integer weight prefix."""
    m = _WEIGHT_RE.match(entry)
    return m.group(2) if m else entry


def _split_entries(content: str) -> list[str]:
    """Split comma-separated element content into stripped, non-empty entry strings."""
    return [e.strip() for e in content.split(",") if e.strip()]


def _compute_unlocked(received_item_names: list[str]) -> frozenset[str]:
    unlocked_configids: set[str] = set()
    result: set[str] = set(_ALWAYS_UNLOCKED)
    for name in received_item_names:
        xml_ids = ITEM_TO_XML_ID.get(name)
        if not xml_ids:
            continue
        for xml_id in xml_ids:
            result.add(xml_id)
            unlocked_configids.add(xml_id)
            if xml_id in SANDWICH_CONFIGID_MAP:
                result.update(SANDWICH_CONFIGID_MAP[xml_id])
    # Compound variants require ALL listed configids to be unlocked simultaneously.
    for variant, required in SANDWICH_COMPOUND_VARIANTS.items():
        if all(cfg in unlocked_configids for cfg in required):
            result.add(variant)
    return frozenset(result)


def _compute_void_flairs(
    text: str,
    unlocked: frozenset[str],
    dead: frozenset[str],
) -> frozenset[str]:
    """Return Flair IDs whose original entries were all AP-blocked (so they always produce noflair).

    Only flairs that *originally* had non-noflair entries qualify — intentionally-noflair
    flairs (body already all-noflair in the source file) are excluded.  Void status
    propagates upward through flair reference chains.

    Void flair IDs are pruned from parent *flair* choice pools (to avoid empty plate
    slots) but are left alone inside *item* bodies (a plain donut is still a valid
    order even when its topping flair collapsed to noflair).

    Required-base rule — any flair type can have + (always-include) entries:
    if any + token is AP-blocked or void, the flair is void regardless of remaining
    optional entries.  Applies to both type="pickmult" (e.g. CowboyBakedPotato with
    ``100 PotatoBaked+``) and type="list" (e.g. RandomCake2 with ``RandomCake2a+``).

    Weight-100 rule — in a type="pickmult" flair, an entry with weight 100 is always
    selected (100 % probability), making it functionally required even without a +
    suffix (e.g. CowgirlCake1 with ``100 CheeseCake, 10 WhipCream``).  If every
    weight-100 entry is AP-blocked or void, the flair is void — the remaining
    low-weight entries would only rarely place anything on the plate, causing visually
    empty dessert/dinner plates.
    """
    flair_entries: dict[str, list[str]] = {}
    flair_is_pickmult: dict[str, bool] = {}
    for m in _ELEM_RE.finditer(text):
        if m.group(2).lower() != "flair":
            continue
        if _is_protected(m.group(3)):
            continue
        id_m = _ID_ATTR_RE.search(m.group(3))
        if not id_m:
            continue
        entries = _split_entries(m.group(4))
        # Only include flairs that HAD non-noflair content — skipping those whose body
        # was intentionally all-noflair in the source file.
        if any(_entry_value(e).strip().lower() != "noflair" for e in entries):
            flair_id = id_m.group(1)
            flair_entries[flair_id] = entries
            flair_is_pickmult[flair_id] = bool(_PICKMULT_TYPE_RE.search(m.group(3)))

    void: set[str] = set()
    changed = True
    while changed:
        changed = False
        for flair_id, entries in flair_entries.items():
            if flair_id in void:
                continue
            void_snap = frozenset(void)
            non_noflair = [e for e in entries if _entry_value(e).strip().lower() != "noflair"]

            # If any + (required-base) entry is AP-blocked or void, the flair is void
            # regardless of remaining optional entries.  Both pickmult and list flairs
            # use + to mark always-included required content.
            # Two formats: "ID+" (suffix) and "N+ ID" (weight carries the required marker).
            if any(
                (token[:-1] in _ALL_AP_XML_IDS and token[:-1] not in unlocked)
                or token[:-1] in dead
                or token[:-1] in void_snap
                for e in non_noflair
                for token in _entry_value(e).split()
                if token.endswith("+")
            ) or any(
                (_entry_value(e) in _ALL_AP_XML_IDS and _entry_value(e) not in unlocked)
                or _entry_value(e) in dead
                or _entry_value(e).rstrip("+") in void_snap
                for e in non_noflair
                if _REQUIRED_WEIGHT_RE.match(e)
            ):
                # A bonus injection can substitute for the blocked required entry — keep alive.
                original_stripped = {_entry_value(e).rstrip("+") for e in non_noflair}
                if any(
                    base in original_stripped and bonus in unlocked
                    for bonus, base in BONUS_PAIRS.items()
                ):
                    continue
                void.add(flair_id)
                changed = True
                continue

            # Weight-100 rule: in a pickmult flair, weight-100 entries are always
            # selected (100 % probability = functionally required without +).  If
            # every weight-100 entry is AP-blocked or void, the remaining low-weight
            # entries would produce empty plates most of the time — void the flair.
            if flair_is_pickmult.get(flair_id):
                w100 = [
                    e for e in non_noflair
                    if _WEIGHT_RE.match(e) and _WEIGHT_RE.match(e).group(1) == "100"
                ]
                if w100 and all(
                    _entry_value(e).strip().rstrip("+") in void_snap
                    or _entry_is_blocked(e, unlocked, dead)
                    for e in w100
                ):
                    void.add(flair_id)
                    changed = True
                    continue

            # Strip trailing + before checking void_snap: flair references can carry
            # a + modifier suffix (e.g. "RandomCake1a+") that is not part of the ID.
            if non_noflair and all(
                _entry_value(e).strip().rstrip("+") in void_snap or _entry_is_blocked(e, unlocked, dead)
                for e in non_noflair
            ):
                original_values = {_entry_value(e).rstrip("+") for e in non_noflair}
                if any(
                    base in original_values and bonus in unlocked
                    for bonus, base in BONUS_PAIRS.items()
                ):
                    continue
                void.add(flair_id)
                changed = True

    return frozenset(void)


def _customer_root_ids(text: str) -> frozenset[str]:
    """Return the set of item IDs directly referenced by <Customer> elements.

    These IDs must always remain defined (even as stubs) because the game parser
    validates Customer body references even when IgnoreCustomerXML suppresses the
    customer definition itself.
    """
    return frozenset(m.group(1).strip() for m in _CUSTOMER_BODY_RE.finditer(text))


def _is_protected(attrs: str) -> bool:
    m = _PRUNECAT_RE.search(attrs)
    if not m:
        return False
    return m.group(1) == "breakfast"


def _entry_is_blocked(
    entry: str,
    unlocked: frozenset[str],
    dead: frozenset[str],
    sandwich_context: bool = False,
    void_flairs: frozenset[str] = frozenset(),
) -> bool:
    value = _entry_value(entry)
    for token in value.split():
        # Strip trailing + — it is a game-engine modifier suffix (e.g. "ItemName+")
        # that must not prevent the base item name from matching the dead/unlocked sets.
        base = token.rstrip("+")
        if base in dead:
            return True
        if base in _ALL_AP_XML_IDS and base not in unlocked:
            return True
        # Breakfast sandwich items (those whose body contains the BreakfastSandwich
        # token) also gate via the base ingredients — so a sausage sandwich requires
        # SausagePatty unlocked even though SausagePatty is in BREAKFAST_BASE_XML_IDS
        # (and therefore absent from _ALL_AP_XML_IDS) so it never blocks plate flairs.
        if sandwich_context and base in _SANDWICH_GATE_XML_IDS and base not in unlocked:
            return True
        # A required (+) flair reference that is void means the assembled order would
        # be empty — treat it as blocked so the parent item/entry is pruned correctly.
        # (Non-required flair refs in item bodies are intentionally left alone; a dish
        # with a voided optional topping flair is still a valid order.)
        if token.endswith("+") and base in void_flairs:
            return True
    return False


def _build_dead_items(
    text: str,
    unlocked: frozenset[str],
    initial_dead: frozenset[str] = frozenset(),
    void_flairs: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Return the set of item IDs whose entries are all blocked or reference only dead items.

    Iterates to a fixed point so that a dead sub-item cascades upward and makes its
    parent dead too.  void_flairs is used in the second pass after _compute_void_flairs.
    """
    elem_entries: dict[str, list[str]] = {}
    elem_is_sandwich: dict[str, bool] = {}
    for m in _ELEM_RE.finditer(text):
        if m.group(2).lower() != "item":
            continue
        if _is_protected(m.group(3)):
            continue
        id_m = _ID_ATTR_RE.search(m.group(3))
        if id_m:
            item_id = id_m.group(1)
            entries = _split_entries(m.group(4))
            elem_entries[item_id] = entries
            # An item whose body directly contains BreakfastSandwich (the food-type
            # token, not to be confused with the plate type "Breakfast") is a breakfast
            # sandwich order.  These items apply sandwich_context gating so that plate
            # ingredients (EggFried, SausagePatty, Bacon) block the sandwich without
            # blocking the breakfast plate flair chains that also use them.
            body_tokens: set[str] = {
                tok.rstrip("+")
                for e in entries
                for tok in _entry_value(e).split()
            }
            elem_is_sandwich[item_id] = "BreakfastSandwich" in body_tokens

    dead: set[str] = set(initial_dead)
    changed = True
    while changed:
        changed = False
        for item_id, entries in elem_entries.items():
            if item_id in dead:
                continue
            dead_snap = frozenset(dead)
            sandwich = elem_is_sandwich.get(item_id, False)
            if not entries or all(
                _entry_is_blocked(e, unlocked, dead_snap, sandwich, void_flairs)
                for e in entries
            ):
                # Keep alive if a bonus injection is eligible: a bonus item is unlocked
                # and its paired base was present in this element's original body.
                original_values = {_entry_value(e).rstrip("+") for e in entries}
                if any(
                    base in original_values and bonus in unlocked
                    for bonus, base in BONUS_PAIRS.items()
                ):
                    continue
                dead.add(item_id)
                changed = True

    return frozenset(dead)


def _filter_xml(
    text: str,
    unlocked: frozenset[str],
    initial_dead: frozenset[str] = frozenset(),
    delete_empty: bool = True,
) -> str:
    dead = _build_dead_items(text, unlocked, initial_dead)
    void_flairs = _compute_void_flairs(text, unlocked, dead)
    # Second pass: items with required (+) void-flair references are now also dead
    # (e.g. RandomDessertCourse referencing a void RandomCake+ flair).
    dead = _build_dead_items(text, unlocked, initial_dead, void_flairs)

    def _replace(m: re.Match) -> str:
        tag_name = m.group(2).lower()
        attrs = m.group(3)
        body = m.group(4)

        if _is_protected(attrs):
            # Protected flairs (prunecat="breakfast") keep all ingredient entries
            # intact — but we still prune void child-flair references from choice
            # pools so that the PickNum never selects a slot that only yields noflair
            # (which would cause empty breakfast plate orders).
            if void_flairs and tag_name == "flair":
                entries = _split_entries(body)
                kept = [e for e in entries if _entry_value(e).strip().rstrip("+") not in void_flairs]
                if kept and len(kept) < len(entries):
                    return m.group(1) + ", ".join(kept) + m.group(5)
            return m.group(0)

        # A void flair must output noflair in full — entry-by-entry filtering would
        # otherwise leave optional topping/side entries intact while the required base
        # is gone (e.g. RandomLasagna keeping "60 RandomLasagnaSide" after Lasagna+ is
        # stripped, or RandomPastaPlate keeping "50 RandomPastaRoll" without pasta).
        if tag_name == "flair" and void_flairs:
            id_m = _ID_ATTR_RE.search(attrs)
            if id_m and id_m.group(1) in void_flairs:
                return m.group(1) + "noflair" + m.group(5)

        entries = _split_entries(body)
        sandwich_context = tag_name == "item" and any(
            "BreakfastSandwich" in _entry_value(e).split()
            for e in entries
        )
        # Collect original values before filtering so bonus injection can check
        # whether a base item was originally present even if it got filtered out.
        # Strip trailing + — it is a required-include modifier, not part of the ID.
        original_values = {_entry_value(e).rstrip("+") for e in entries}
        # For flair elements, also remove void-flair references from choice pools.
        # Void flair references inside item bodies are left alone (a donut with a
        # void topping flair is still a valid order; it just has no topping).
        # Strip trailing + before the void check — flair refs can carry a + modifier
        # suffix (e.g. "100 RandomCake1a+") that is not part of the flair ID.
        kept = [
            e for e in entries
            if not _entry_is_blocked(e, unlocked, dead, sandwich_context)
            and not (tag_name == "flair" and _entry_value(e).strip().rstrip("+") in void_flairs)
        ]

        # Inject bonus items: for each bonus/base pair, if the base was originally
        # present in this Item element and the bonus AP item is now unlocked, append
        # the bonus item ID.  The bonus IDs are never present in the source (.orig)
        # files — the patcher is the only thing that writes them.
        if tag_name in ("item", "flair"):
            for bonus_xml, base_xml in BONUS_PAIRS.items():
                if base_xml in original_values and bonus_xml in unlocked:
                    kept.append(bonus_xml)

        if kept and all(
            _WEIGHT_RE.match(e) and _WEIGHT_RE.match(e).group(1) == "0"
            for e in kept
        ):
            kept = [_entry_value(e) for e in kept]

        if tag_name == "flair" and not kept and entries:
            kept = ["noflair"]

        # noflair is valid for Flair elements but means "nothing" in an Item body —
        # treat a noflair-only Item as empty so it propagates dead and gets removed.
        if tag_name == "item" and kept and all(
            _entry_value(e).strip().lower() == "noflair" for e in kept
        ):
            kept = []

        return m.group(1) + ", ".join(kept) + m.group(5)

    result = _ELEM_RE.sub(_replace, text)

    # Items referenced by <Customer> elements must always remain defined — the game
    # parser validates Customer body references even when IgnoreCustomerXML suppresses
    # the customer definition.  Collect these from the original (pre-filter) text.
    customer_roots = _customer_root_ids(text)

    def _hamburger_stub(m: re.Match) -> str:
        open_tag = re.search(r"<Item\b[^>]*>", m.group(0), re.IGNORECASE).group(0)
        return f"{open_tag}San_Hamburger</Item>\n"

    if delete_empty:
        def _handle_empty(m: re.Match) -> str:
            open_tag = re.search(r"<Item\b[^>]*>", m.group(0), re.IGNORECASE).group(0)
            id_m = _ID_ATTR_RE.search(open_tag)
            if id_m and id_m.group(1) in customer_roots:
                # Root meal item — stub rather than delete so the Customer reference
                # remains resolvable. Surfer's SurferMealBR is the canonical example.
                return f"{open_tag}San_Hamburger</Item>\n"
            return ""
        result = _EMPTY_ITEM_RE.sub(_handle_empty, result)
    else:
        # All_*.xml: keep ALL empty items as stubs so aggregate IDs referenced by
        # DefLevelExp.xml and other unpatched files remain in the registry.
        result = _EMPTY_ITEM_RE.sub(_hamburger_stub, result)

    return result


def _set_attr(text: str, attr: str, value: str) -> str:
    return re.sub(
        rf'\b({re.escape(attr)}\s*=\s*")[^"]*(")',
        rf'\g<1>{value}\g<2>',
        text,
    )


def _patch_layout_file(levels_dir: str, filename: str, received: frozenset[str]) -> None:
    src = os.path.join(levels_dir, filename)
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


_COORDS_OX_HIDDEN: str = "2100000000"


def _patch_coords_xml(levels_dir: str, received: frozenset[str]) -> None:
    src = os.path.join(levels_dir, "Coords.xml")
    orig = src + ".orig"

    if not os.path.isfile(src):
        return

    if not os.path.isfile(orig):
        shutil.copy2(src, orig)

    with open(orig, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for item_name, (xml_type, original_ox) in COORDS_OX_ITEMS.items():
        ox_val = str(original_ox) if item_name in received else _COORDS_OX_HIDDEN
        for i, line in enumerate(lines):
            if f'type="{xml_type}"' in line:
                lines[i] = re.sub(r'\box="[^"]*"', f'ox="{ox_val}"', line)
                break

    with open(src, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _patch_game_xml(levels_dir: str, received: frozenset[str]) -> list[tuple[str, str]]:
    game_src = os.path.join(levels_dir, "Game.xml")
    game_orig = game_src + ".orig"
    gameexp_src = os.path.join(levels_dir, "GameExp.xml")
    gameexp_orig = gameexp_src + ".orig"

    if not os.path.isfile(game_src):
        return []

    if not os.path.isfile(game_orig):
        shutil.copy2(game_src, game_orig)

    # Preserve the original GameExp.xml as a backup, even though we no longer read from it.
    if os.path.isfile(gameexp_src) and not os.path.isfile(gameexp_orig):
        shutil.copy2(gameexp_src, gameexp_orig)

    with open(game_orig, encoding="utf-8", errors="replace") as f:
        text = f.read()

    try:
        with open(game_src, encoding="utf-8", errors="replace") as f:
            prev_text = f.read()
    except OSError:
        prev_text = ""

    for attr, disabled_value in _GAME_DISABLED.items():
        if not (_ATTR_ENABLED_BY[attr] & received):
            text = _set_attr(text, attr, disabled_value)

    prev_vals = {m.group(1): m.group(2) for m in _ATTR_RE.finditer(prev_text)}
    new_vals = {m.group(1): m.group(2) for m in _ATTR_RE.finditer(text)}
    all_changes = [
        (prev_vals[attr], new_vals[attr])
        for attr in _GAME_DISABLED
        if attr in prev_vals and attr in new_vals and prev_vals[attr] != new_vals[attr]
    ]

    with open(game_src, "w", encoding="utf-8") as f:
        f.write(text)

    # GameExp.xml is overwritten with the patched Game.xml so that expert story mode
    # uses the same level structure (CustomerFile, Stage visuals, CustomerSlots
    # progression) instead of DefLevelExp.xml with its harder EarningGoal targets.
    if os.path.isfile(gameexp_src):
        with open(gameexp_src, "w", encoding="utf-8") as f:
            f.write(text)

    return all_changes


# ---------------------------------------------------------------------------
# Per-file patching
# ---------------------------------------------------------------------------

def _patch_file(
    levels_dir: str,
    filename: str,
    unlocked: frozenset[str],
    initial_dead: frozenset[str] = frozenset(),
    delete_empty: bool = True,
) -> frozenset[str]:
    src = os.path.join(levels_dir, filename)
    orig = src + ".orig"

    if not os.path.isfile(src):
        return frozenset()

    if not os.path.isfile(orig):
        shutil.copy2(src, orig)

    with open(orig, encoding="utf-8", errors="replace") as f:
        text = f.read()

    dead = _build_dead_items(text, unlocked, initial_dead)
    void_flairs = _compute_void_flairs(text, unlocked, dead)
    dead = _build_dead_items(text, unlocked, initial_dead, void_flairs)

    with open(src, "w", encoding="utf-8") as f:
        f.write(_filter_xml(text, unlocked, initial_dead, delete_empty))

    return dead


# ---------------------------------------------------------------------------
# ComplexItems.xml selective patching
# ---------------------------------------------------------------------------

def _patch_complexitems_flairs(
    levels_dir: str,
    unlocked: frozenset[str],
    dead: frozenset[str],
) -> None:
    """Patch whitelisted flair IDs in ComplexItems.xml.

    ComplexItems.xml is excluded from the main filter pass because Tomato and
    Onions appear in both salad flairs and sandwich item bodies — applying the
    full filter would strip those tokens from the sandwich definitions.  This
    function patches only the flair IDs in _COMPLEXITEMS_FILTERED_FLAIR_IDS,
    leaving sandwiches, pasta flairs, and parent salad/snack wrappers untouched.
    """
    src = os.path.join(levels_dir, "ComplexItems.xml")
    orig = src + ".orig"

    if not os.path.isfile(src):
        return

    if not os.path.isfile(orig):
        shutil.copy2(src, orig)

    with open(orig, encoding="utf-8", errors="replace") as f:
        text = f.read()

    void_flairs = _compute_void_flairs(text, unlocked, dead)

    def _replace_salad(m: re.Match) -> str:
        if m.group(2).lower() != "flair":
            return m.group(0)
        id_m = _ID_ATTR_RE.search(m.group(3))
        if not id_m or id_m.group(1) not in _COMPLEXITEMS_FILTERED_FLAIR_IDS:
            return m.group(0)

        if id_m.group(1) in void_flairs:
            return m.group(1) + "noflair" + m.group(5)

        entries = _split_entries(m.group(4))
        kept = [
            e for e in entries
            if not _entry_is_blocked(e, unlocked, dead)
            and _entry_value(e).strip().rstrip("+") not in void_flairs
        ]
        if not kept and entries:
            kept = ["noflair"]
        return m.group(1) + ", ".join(kept) + m.group(5)

    with open(src, "w", encoding="utf-8") as f:
        f.write(_ELEM_RE.sub(_replace_salad, text))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_bs2_recipe_unlocks(
    game_path: str,
    received_item_names: list[str],
) -> tuple[bool, list[tuple[str, str]]]:
    """
    Rewrite Breakfast/Order/Dinner customer XML files to reflect received AP items.
    Also patches Game.xml powerup attributes if present.

    Returns ``(success, game_xml_changes)`` where *success* is False when the
    archipelago/levels directory has not been set up.
    """
    from CommonClient import logger

    levels = _levels_dir(game_path)
    if not os.path.isdir(levels):
        logger.warning(
            "[Burger Shop 2] archipelago/levels not found in the game's directory " \
            "— pre-setup required. "
        )
        return False, []

    unlocked = _compute_unlocked(received_item_names)
    received_set = frozenset(received_item_names)

    # Pass 1: Random pool files — seed the cross-file dead set.
    cross_file_dead: set[str] = set()
    for filename in _RANDOM_FILES:
        try:
            dead = _patch_file(levels, filename, unlocked)
            cross_file_dead.update(dead)
        except OSError as e:
            logger.warning(f"[Burger Shop 2] Failed to patch {filename}: {e}")
    cross_dead = frozenset(cross_file_dead)

    # Pass 2: Per-character Breakfast/Order/Dinner files.
    # Collect their dead sets so All_*.xml gets a complete picture in pass 3.
    char_dead_acc: set[str] = set()
    all_xml_names: list[str] = []
    patched = set(_RANDOM_FILES)
    for name in sorted(os.listdir(levels)):
        if not name.endswith(".xml") or name in patched:
            continue
        if name.lower() in _SKIP_FILES:
            continue
        if name.lower().endswith("_alien.xml"):
            continue
        if name.lower().startswith("all_"):
            all_xml_names.append(name)
            continue
        if (name.lower().startswith("breakfast_")
                or name.lower().startswith("order_")
                or name.lower().startswith("dinner_")):
            try:
                dead = _patch_file(levels, name, unlocked, cross_dead)
                char_dead_acc.update(dead)
            except OSError as e:
                logger.warning(f"[Burger Shop 2] Failed to patch {name}: {e}")

    # Pass 3: All_*.xml files — patch with the full accumulated dead set so that
    # entries referencing dead character-file items are removed from pick lists.
    # delete_empty=False: keep empty <Item> elements so their IDs remain in the game
    # registry — DefLevelExp.xml and other unpatched files reference these IDs and
    # crash with "Parent item not found" if the definition is completely absent.
    all_dead = cross_dead | frozenset(char_dead_acc)
    for name in all_xml_names:
        try:
            _patch_file(levels, name, unlocked, all_dead, delete_empty=False)
        except OSError as e:
            logger.warning(f"[Burger Shop 2] Failed to patch {name}: {e}")

    # ComplexItems.xml — whitelisted flairs only (sandwiches/pasta skipped).
    try:
        _patch_complexitems_flairs(levels, unlocked, all_dead)
    except OSError as e:
        logger.warning(f"[Burger Shop 2] Failed to patch ComplexItems.xml flairs: {e}")

    game_xml_changes: list[tuple[str, str]] = []
    try:
        game_xml_changes = _patch_game_xml(levels, received_set)
    except OSError as e:
        logger.warning(f"[Burger Shop 2] Failed to patch Game.xml: {e}")

    for layout_file in _LAYOUT_FILES:
        try:
            _patch_layout_file(levels, layout_file, received_set)
        except OSError as e:
            logger.warning(f"[Burger Shop 2] Failed to patch {layout_file}: {e}")

    try:
        _patch_coords_xml(levels, received_set)
    except OSError as e:
        logger.warning(f"[Burger Shop 2] Failed to patch Coords.xml: {e}")

    logger.debug(f"[Burger Shop 2] XML patched ({len(received_item_names)} item(s) unlocked).")
    return True, game_xml_changes
