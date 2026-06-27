from worlds.LauncherComponents import Component, Type, components, launch


def run_client(*args: str) -> None:
    from .client.burger_shop_2_client import main
    launch(main, name="Burger Shop 2 Client", args=args)


components.append(
    Component(
        "Burger Shop 2 Client",
        func=run_client,
        game_name="Burger Shop 2",
        component_type=Type.CLIENT,
        supports_uri=True,
    )
)
