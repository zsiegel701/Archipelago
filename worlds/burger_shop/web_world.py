from BaseClasses import Tutorial
from worlds.AutoWorld import WebWorld


class BurgerShopWebWorld(WebWorld):
    game = "Burger Shop"

    # Available themes: dirt, grass, grassFlowers, ice, jungle, ocean, partyTime, stone
    theme = "dirt"

    setup_en = Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up Burger Shop for MultiWorld.",
        "English",
        "setup_en.md",
        "setup/en",
        ["TODO: your name here"],
    )

    tutorials = [setup_en]
