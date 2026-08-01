import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

import settings
from worlds.AutoWorld import World

from . import character_shuffle, items, locations, regions, rules, web_world
from . import options as burger_shop2_options


class BurgerShop2Settings(settings.Group):
    class GameInstallPath(settings.UserFolderPath):
        """
        Path to the Burger Shop 2 installation directory.
        Leave empty to let the client auto-detect from a Steam installation.
        """
        description = "Burger Shop 2 root directory"

    game_install_path: GameInstallPath = GameInstallPath("")


class BurgerShop2World(World):
    """
    Burger Shop 2 is a time-management restaurant game serving breakfast, lunch,
    and dinner across 120 Story Mode levels in 8 stages.
    """

    game = "Burger Shop 2"
    settings_key = "burger_shop_2_settings"
    settings: ClassVar[BurgerShop2Settings]
    web = web_world.BurgerShop2WebWorld()

    options_dataclass = burger_shop2_options.BurgerShop2Options
    options: burger_shop2_options.BurgerShop2Options

    location_name_to_id = locations.LOCATION_NAME_TO_ID
    item_name_to_id = items.ITEM_NAME_TO_ID

    item_name_groups = items.ITEM_NAME_GROUPS
    location_name_groups = locations.LOCATION_NAME_GROUPS

    # UT yaml-less generation: skip the initial YAML-dependent generation and regenerate from slot data.
    ut_can_gen_without_yaml = True

    # Maps starter location name → item name when StarterRecipes is on.
    # Populated in generate_early; consumed by create_items (pool exclusion) and pre_fill (placement).
    _starter_assignments: dict[str, str] = {}
    # Items given directly to the player at start (not placed in any location).
    # Populated in generate_early; excluded from the item pool in create_items.
    _precollected_items: list[str] = []
    # Seed for the client's DefLevel_Test.xml character shuffle. Populated in generate_early.
    _character_seed: int = 0
    # Resolved <Customer> id -> character groups for this slot.  Populated in
    # generate_early because set_rules needs it: which levels are gated behind Menu,
    # Dog Biscuit, and Shirt depends on where OldChap, DogBag, and Annoying landed.
    character_map: dict[str, tuple[tuple[int, str], ...]] = {}

    @staticmethod
    def interpret_slot_data(slot_data: dict[str, Any]) -> dict[str, Any]:
        return slot_data

    def generate_early(self) -> None:
        self._precollected_items = []
        self._starter_assignments = {}

        # When UT regenerates from slot data, restore options and starter assignments
        # rather than re-rolling them, so the tracker reflects the actual generation.
        re_gen = getattr(self.multiworld, "re_gen_passthrough", {}).get(self.game, {})
        if re_gen:
            for key in ("five_star_mode", "starter_recipes", "bonus_recipes",
                        "start_with_lollipops", "start_with_burgerbot", "customer_slots",
                        "character_randomization"):
                opt = getattr(self.options, key, None)
                if opt is not None and key in re_gen:
                    opt.value = re_gen[key]
            self._starter_assignments = dict(re_gen.get("starter_assignments", {}))
            self._character_seed = int(re_gen.get("character_seed", 0))
        else:
            self._character_seed = self.random.getrandbits(31)

        # Resolved here, before set_rules, from the same pure function the client uses,
        # so generation, Universal Tracker, and the game all agree on where each
        # character ended up.
        self.character_map = character_shuffle.resolve(
            self.options.character_randomization.value, self._character_seed
        )

        if self.options.start_with_lollipops:
            self.multiworld.push_precollected(self.create_item("Lollipops"))
            self._precollected_items.append("Lollipops")
        if self.options.start_with_burgerbot:
            self.multiworld.push_precollected(self.create_item("BurgerBot"))
            self._precollected_items.append("BurgerBot")
        if not re_gen and self.options.starter_recipes:
            self._starter_assignments = {
                "Starter Side":            self.random.choice(items.STARTER_LARGE_SIDES),
                "Starter Soda":            self.random.choice(items.STARTER_LARGE_DRINKS),
                "Starter Ice Cream":       self.random.choice(items.STARTER_ICE_CREAMS),
                "Starter Breakfast Drink": self.random.choice(items.STARTER_BREAKFAST_DRINKS),
                "Starter Cereal":          self.random.choice(items.STARTER_CEREALS),
                "Starter Soup":            self.random.choice(items.STARTER_SOUPS),
                "Starter Toasted Item":    self.random.choice(items.STARTER_TOASTED_ITEMS),
                "Starter Dinner Meat":     self.random.choice(items.STARTER_DINNER_MEATS),
            }

    def pre_fill(self) -> None:
        for loc_name, item_name in self._starter_assignments.items():
            self.multiworld.get_location(loc_name, self.player).place_locked_item(
                self.create_item(item_name)
            )

    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)
        locations.create_all_locations(self)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def create_items(self) -> None:
        items.create_all_items(self)

    def create_item(self, name: str) -> items.BurgerShop2Item:
        return items.create_item_with_classification(self, name)

    def get_filler_item_name(self) -> str:
        return items.get_filler_item_name()

    def fill_slot_data(self) -> Mapping[str, Any]:
        data = dict(self.options.as_dict(
            "five_star_mode", "starter_recipes", "bonus_recipes",
            "start_with_lollipops", "start_with_burgerbot", "customer_slots",
            "character_randomization",
        ))
        data["generation_uid"] = uuid.uuid4().hex
        data["starter_assignments"] = self._starter_assignments
        data["character_seed"] = self._character_seed
        return data
