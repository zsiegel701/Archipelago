from BaseClasses import Tutorial
from worlds.AutoWorld import WebWorld


class BurgerShop2WebWorld(WebWorld):
    game = "Burger Shop 2"

    # Available themes: dirt, grass, grassFlowers, ice, jungle, ocean, partyTime, stone
    theme = "dirt"

    setup_en = Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up Burger Shop 2 for MultiWorld.",
        "English",
        "setup_en.md",
        "setup/en",
        ["TODO: your name here"],
    )

    tutorials = [setup_en]
