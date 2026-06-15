import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

import settings
from worlds.AutoWorld import World

from . import items, locations, regions, rules, web_world
from . import options as burger_shop_options


class BurgerShopSettings(settings.Group):
    class GameInstallPath(settings.UserFolderPath):
        """
        Path to the Burger Shop installation directory.
        Leave empty to let the client auto-detect from a Steam installation.
        """
        description = "Burger Shop root directory"

    game_install_path: GameInstallPath = GameInstallPath("")


class BurgerShopWorld(World):
    """
    Burger Shop is a time-management restaurant game where you serve customers
    across 80 Story Mode levels. Unlock all 14 customer characters to reach the finale.
    """

    game = "Burger Shop"
    settings_key = "burger_shop_settings"
    settings: ClassVar[BurgerShopSettings]
    web = web_world.BurgerShopWebWorld()

    options_dataclass = burger_shop_options.BurgerShopOptions
    options: burger_shop_options.BurgerShopOptions

    location_name_to_id = locations.LOCATION_NAME_TO_ID
    item_name_to_id = items.ITEM_NAME_TO_ID

    item_name_groups = items.ITEM_NAME_GROUPS
    location_name_groups = locations.LOCATION_NAME_GROUPS

    # Maps starter location name → item name when StarterRecipes is on.
    # Populated in generate_early; consumed by create_items (pool exclusion) and pre_fill (placement).
    _starter_assignments: dict[str, str] = {}
    # Items given directly to the player at start (not placed in any location).
    # Populated in generate_early; excluded from the item pool in create_items.
    _precollected_items: list[str] = []

    def generate_early(self) -> None:
        self._precollected_items = []
        if self.options.start_with_cookies:
            self.multiworld.push_precollected(self.create_item("Cookies"))
            self._precollected_items.append("Cookies")
        if self.options.start_with_burgerbot:
            self.multiworld.push_precollected(self.create_item("BurgerBot"))
            self._precollected_items.append("BurgerBot")
        if self.options.starter_recipes:
            self._starter_assignments = {
                "Starter Side":    self.random.choice(items.STARTER_LARGE_SIDES),
                "Starter Soda":    self.random.choice(items.STARTER_LARGE_DRINKS),
                "Starter Dessert": self.random.choice(items.STARTER_ICE_CREAMS),
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

    def create_item(self, name: str) -> items.BurgerShopItem:
        return items.create_item_with_classification(self, name)

    def get_filler_item_name(self) -> str:
        return items.get_filler_item_name()

    def fill_slot_data(self) -> Mapping[str, Any]:
        data = dict(self.options.as_dict("five_star_mode", "starter_recipes", "start_with_cookies", "start_with_burgerbot"))
        data["generation_uid"] = uuid.uuid4().hex
        data["starter_assignments"] = self._starter_assignments
        return data
