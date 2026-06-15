# Burger Shop Multiworld Setup Guide

## Required Software

- [Burger Shop](https://store.steampowered.com/app/730840/) (Steam)
- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases) 0.5.0 or later
- `burger_shop.apworld` and the Burger Shop game data package (provided by your multiworld host)

## Installation

### 1. Install the Archipelago world

Place `burger_shop.apworld` in the `worlds/` folder inside your Archipelago installation directory and restart
the Archipelago launcher if it is already open.

### 2. Install the game data package

Extract the provided zip file and copy the `archipelago` folder and the `properties` folder directly into your
Burger Shop installation directory (the folder containing `BurgerShop.exe`). The result should look like:

```
Burger Shop/
├── archipelago/
│   └── levels/
│       ├── Game.xml
│       ├── Layout.xml
│       ├── Order_BizChick.xml
│       └── ... (remaining order files)
├── properties/
│   └── params_user.xml
└── BurgerShop.exe
```

The `properties/params_user.xml` file tells the game to load loose XML files from the `archipelago` folder,
which the Archipelago client patches in real-time as items are received.

## Joining a Multiworld Game

1. Open the **Archipelago Launcher** and click **Burger Shop Client**, or run `BurgerShopClient.exe` directly.
2. Connect to your server by typing in the client console:
   ```
   /connect <host>:<port>
   ```
3. Enter your slot name and password when prompted.
4. Launch the game using `/launch` in the client console, or start it manually.
5. **Create a new save file.** The client associates saves with your session at creation time — do not use a
   save that was created before connecting.

## Options

| Option | Default | Description |
|---|---|---|
| Five Star Mode | On | Level checks require all 5 stars; off means any completion counts |
| Starter Recipes | Off | Adds a random large side, drink, and ice cream to your starting inventory |
| Bonus Recipes | Off | Replaces filler items with bonus recipes not in the base game |
| Start with Cookies | Off | Cookies (sample tray) added to starting inventory |
| Start with BurgerBot | Off | BurgerBot (tip meter and powerups) added to starting inventory |

## Troubleshooting

**The client cannot find my Burger Shop installation.**
Add the following to `host.yaml` in your Archipelago directory:
```yaml
burger_shop_settings:
  game_install_path: "C:/Program Files (x86)/Steam/steamapps/common/Burger Shop"
```

**My save file is not being detected.**
Only saves created *after* connecting the client to the server are tracked. Create a fresh save once the
client shows you are connected.

**Recipe changes are not showing up mid-level.**
The game reads updated order files when a level starts. Finish the current level or return to the map screen
to see newly unlocked recipes take effect.
