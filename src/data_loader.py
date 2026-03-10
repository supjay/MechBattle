"""Load mech and map data from JSON files."""
import copy
import json
from pathlib import Path
from typing import List, Dict, Any

from src.models.weapon import Weapon
from src.models.ability import Ability
from src.models.mech import Mech
from src.models.map_tile import MapTile

DATA_DIR = Path(__file__).parent.parent / "data"

_TILE_TYPE = {0: "open", 1: "cover", 2: "blocked"}


def load_mech_templates() -> List[Mech]:
    """Return the full roster of mech templates (unmodified)."""
    with open(DATA_DIR / "mechs.json", encoding="utf-8") as f:
        data = json.load(f)

    templates: List[Mech] = []
    for md in data["mechs"]:
        weapons = [Weapon(**w) for w in md["weapons"]]
        ability = Ability(**md["ability"])
        mech = Mech(
            id=md["id"],
            name=md["name"],
            description=md.get("description", ""),
            max_hp=md["hp"],
            armor=md["armor"],
            move_range=md["move_range"],
            initiative=md["initiative"],
            weapons=weapons,
            ability=ability,
            color=tuple(md["color"]),
        )
        templates.append(mech)
    return templates


def load_map_list() -> List[Dict[str, Any]]:
    """Return raw map data dicts (id, name, description, width, height, grid, spawns)."""
    with open(DATA_DIR / "maps.json", encoding="utf-8") as f:
        data = json.load(f)
    return data["maps"]


def build_map_tiles(map_data: Dict[str, Any]):
    """Convert a map dict into a 2-D list of MapTile objects.

    Returns (tiles, width, height).
    """
    grid = map_data["grid"]
    w = map_data["width"]
    h = map_data["height"]

    tiles: List[List[MapTile]] = []
    for y, row in enumerate(grid):
        tile_row = [MapTile(x=x, y=y, type=_TILE_TYPE[cell]) for x, cell in enumerate(row)]
        tiles.append(tile_row)

    return tiles, w, h
