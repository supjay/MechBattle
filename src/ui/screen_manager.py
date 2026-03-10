"""ScreenManager – owns all screens and shared cross-screen state."""
import copy
from typing import Any, Dict, List, Optional

import pygame

from src.data_loader import load_mech_templates, load_map_list, build_map_tiles
from src.game.game_state import GameState
from src.models.mech import Mech

from src.ui.screens.main_menu        import MainMenuScreen
from src.ui.screens.name_entry_screen import NameEntryScreen
from src.ui.screens.roster_screen    import RosterScreen
from src.ui.screens.map_select       import MapSelectScreen
from src.ui.screens.battle_screen    import BattleScreen
from src.ui.screens.result_screen    import ResultScreen
from src.ui.screens.wiki_screen      import WikiScreen


class ScreenManager:
    def __init__(self, surface: pygame.Surface):
        self.surface = surface

        # ---- Shared data loaded once ----
        self.mech_templates: List[Mech] = load_mech_templates()
        self.map_list: List[Dict[str, Any]] = load_map_list()

        # ---- Cross-screen state ----
        self.player_count: int = 2
        self.team1_templates: List[Mech] = []
        self.team2_templates: List[Mech] = []
        self.team3_templates: List[Mech] = []
        self.selected_map_idx: int = 0
        self.game_state: Optional[GameState] = None
        self.winner: Optional[int] = None
        self.player1_name: str = "Player 1"
        self.player2_name: str = "Player 2"
        self.player3_name: str = "Player 3"

        # ---- Screens ----
        self._screens: Dict[str, Any] = {
            "main_menu":   MainMenuScreen(self),
            "name_entry":  NameEntryScreen(self),
            "roster":      RosterScreen(self),
            "map_select":  MapSelectScreen(self),
            "battle":      BattleScreen(self),
            "result":      ResultScreen(self),
            "wiki":        WikiScreen(self),
        }
        self._current_key: str = "main_menu"
        self._current = self._screens["main_menu"]
        if hasattr(self._current, "on_enter"):
            self._current.on_enter()

    # ------------------------------------------------------------------
    def switch_to(self, key: str, **kwargs):
        if key not in self._screens:
            raise ValueError(f"Unknown screen: {key!r}")

        # Build game state when entering battle
        if key == "battle":
            self._build_game_state()

        self._current_key = key
        self._current = self._screens[key]
        if hasattr(self._current, "on_enter"):
            self._current.on_enter(**kwargs)

    # ------------------------------------------------------------------
    def _build_game_state(self):
        """Create fresh Mech instances and GameState from current selections."""
        map_data_raw = self.map_list[self.selected_map_idx]
        tiles, w, h = build_map_tiles(map_data_raw)

        spawn1 = [tuple(p) for p in map_data_raw["spawn_team1"]]
        spawn2 = [tuple(p) for p in map_data_raw["spawn_team2"]]

        team1 = [copy.deepcopy(t) for t in self.team1_templates]
        team2 = [copy.deepcopy(t) for t in self.team2_templates]
        team1 = team1[: len(spawn1)]
        team2 = team2[: len(spawn2)]

        # 3-player support
        team3 = None
        spawn3 = None
        if self.player_count == 3 and self.team3_templates:
            raw_spawn3 = map_data_raw.get("spawn_team3")
            if raw_spawn3:
                spawn3 = [tuple(p) for p in raw_spawn3]
                team3 = [copy.deepcopy(t) for t in self.team3_templates]
                team3 = team3[: len(spawn3)]
            # If the map has no spawn_team3, silently drop to 2-player

        self.game_state = GameState(
            team1=team1,
            team2=team2,
            map_data=tiles,
            map_width=w,
            map_height=h,
            spawn_team1=spawn1[: len(team1)],
            spawn_team2=spawn2[: len(team2)],
            team3=team3,
            spawn_team3=spawn3,
        )

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event):
        self._current.handle_event(event)

    def update(self, dt: float):
        self._current.update(dt)

    def draw(self):
        self._current.draw(self.surface)
