"""Central game state for a battle."""
from typing import Any, Dict, List, Optional, Set, Tuple

from src.models.mech import Mech
from src.models.map_tile import MapTile
from src.models.weapon import Weapon
from src.game.combat import CombatResolver


class GameState:
    def __init__(
        self,
        team1: List[Mech],
        team2: List[Mech],
        map_data: List[List[MapTile]],
        map_width: int,
        map_height: int,
        spawn_team1: List[Tuple[int, int]],
        spawn_team2: List[Tuple[int, int]],
        team3: Optional[List[Mech]] = None,
        spawn_team3: Optional[List[Tuple[int, int]]] = None,
    ):
        self.team1 = team1
        self.team2 = team2
        self.team3 = team3 or []
        self.map_data = map_data
        self.map_width = map_width
        self.map_height = map_height

        # Assign teams and spawn positions
        for mech, pos in zip(team1, spawn_team1):
            mech.team = 1
            mech.position = pos
        for mech, pos in zip(team2, spawn_team2):
            mech.team = 2
            mech.position = pos
        if team3 and spawn_team3:
            for mech, pos in zip(team3, spawn_team3):
                mech.team = 3
                mech.position = pos

        all_mechs = team1 + team2 + self.team3
        # Sort by initiative descending; ties broken by team order
        self.turn_order: List[Mech] = sorted(
            all_mechs, key=lambda m: m.initiative, reverse=True
        )
        self.current_turn_idx: int = 0
        self.round_number: int = 1

        # Combat log (capped at 10 lines)
        self.combat_log: List[str] = []

        # UI selection state
        self.selected_mech: Optional[Mech] = None
        self.valid_move_tiles: Set[Tuple[int, int]] = set()
        self.valid_attack_tiles: Set[Tuple[int, int]] = set()
        self.active_weapon: Optional[Weapon] = None
        self.using_ability: bool = False

        # Place mechs on the tile grid
        self._place_mechs()

        # Kick off the first mech's turn
        curr = self.current_mech
        if curr:
            curr.start_turn()

    # ------------------------------------------------------------------
    # Current mech
    # ------------------------------------------------------------------

    @property
    def current_mech(self) -> Optional[Mech]:
        n = len(self.turn_order)
        if n == 0:
            return None
        for i in range(n):
            m = self.turn_order[(self.current_turn_idx + i) % n]
            if m.is_alive:
                return m
        return None

    @property
    def all_teams(self) -> List[List[Mech]]:
        teams = [self.team1, self.team2]
        if self.team3:
            teams.append(self.team3)
        return teams

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def end_turn(self):
        """Advance to the next living mech."""
        alive = [m for m in self.turn_order if m.is_alive]
        if not alive:
            return

        n = len(self.turn_order)
        # Walk forward until we find the next alive mech
        for _ in range(n):
            self.current_turn_idx = (self.current_turn_idx + 1) % n
            candidate = self.turn_order[self.current_turn_idx]
            if candidate.is_alive:
                # Check for new round (wrapped back to highest-initiative mech)
                if self.current_turn_idx == 0 or self._is_round_start():
                    self.round_number += 1
                candidate.start_turn()
                break

        self._clear_selection()

    def _is_round_start(self) -> bool:
        """True when we've wrapped around past all mechs in initiative order."""
        idx = self.current_turn_idx
        return all(
            not self.turn_order[i].is_alive or i >= idx
            for i in range(idx)
        )

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def select_mech(self, mech: Optional[Mech]):
        self._clear_selection()
        self.selected_mech = mech
        if mech:
            self.valid_move_tiles = CombatResolver.get_valid_moves(mech, self)

    def select_weapon(self, weapon: Optional[Weapon]):
        self.active_weapon = weapon
        self.using_ability = False
        self.valid_move_tiles = set()
        if self.selected_mech and weapon:
            self.valid_attack_tiles = CombatResolver.get_valid_attack_tiles(
                self.selected_mech, weapon, self
            )
        else:
            self.valid_attack_tiles = set()

    def select_ability(self):
        self.active_weapon = None
        self.using_ability = True
        self.valid_move_tiles = set()
        ability = self.selected_mech.ability if self.selected_mech else None
        if ability and ability.needs_target:
            # Artillery – allow targeting any tile in a wide radius
            mx, my = self.selected_mech.position
            self.valid_attack_tiles = {
                (x, y)
                for y in range(self.map_height)
                for x in range(self.map_width)
                if CombatResolver.chebyshev((mx, my), (x, y)) <= 8
                and self.map_data[y][x].is_passable
            }
        else:
            self.valid_attack_tiles = set()

    def cancel_action(self):
        """Return to 'mech selected, showing move tiles' state."""
        self.active_weapon = None
        self.using_ability = False
        self.valid_attack_tiles = set()
        if self.selected_mech:
            self.valid_move_tiles = CombatResolver.get_valid_moves(
                self.selected_mech, self
            )

    def _clear_selection(self):
        self.selected_mech = None
        self.valid_move_tiles = set()
        self.valid_attack_tiles = set()
        self.active_weapon = None
        self.using_ability = False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def move_mech(self, mech: Mech, new_pos: Tuple[int, int]) -> bool:
        if new_pos not in self.valid_move_tiles:
            return False

        ox, oy = mech.position
        self.map_data[oy][ox].mech = None

        mech.position = new_pos
        nx, ny = new_pos
        self.map_data[ny][nx].mech = mech
        mech.has_moved = True

        # Refresh move tiles (now empty; weapon/ability tiles unchanged)
        self.valid_move_tiles = set()
        return True

    def execute_attack(self, target_pos: Tuple[int, int]) -> List[Dict[str, Any]]:
        if not self.selected_mech or not self.active_weapon:
            return []

        results = CombatResolver.resolve_attack(
            self.selected_mech, self.active_weapon, target_pos, self
        )

        # Remove dead mechs from the map
        for r in results:
            tgt = r["target"]
            if not tgt.is_alive and tgt.position is not None:
                tx, ty = tgt.position
                self.map_data[ty][tx].mech = None
                tgt.position = None

        self.selected_mech.has_acted = True

        # Log
        for r in results:
            if r["hit"]:
                crit = " CRITICAL!" if r["critical"] else ""
                ap   = " [AP]" if r.get("ap_rounds") else ""
                oc   = " [OVERCHARGED]" if r["overcharge"] and r["critical"] is False else ""
                self._log(
                    f"{self.selected_mech.name} → {r['target'].name}: "
                    f"{r['damage']} dmg{crit}{ap}{oc}"
                )
            else:
                self._log(f"{self.selected_mech.name} → {r['target'].name}: MISS")

        self.active_weapon = None
        self.valid_attack_tiles = set()
        return results

    def execute_ability(self, target_pos: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
        if not self.selected_mech:
            return {"success": False, "message": "No mech selected."}

        result = CombatResolver.apply_ability(self.selected_mech, target_pos, self)

        if result.get("success"):
            if not result.get("extra_move"):
                self.selected_mech.has_acted = True

            # Clean up dead mechs from board
            for team in self.all_teams:
                for mech in team:
                    if not mech.is_alive and mech.position is not None:
                        tx, ty = mech.position
                        self.map_data[ty][tx].mech = None
                        mech.position = None

            self._log(result["message"])

        self.using_ability = False
        self.valid_attack_tiles = set()

        # If sprint, allow move again
        if result.get("extra_move") and self.selected_mech:
            self.valid_move_tiles = CombatResolver.get_valid_moves(self.selected_mech, self)

        return result

    # ------------------------------------------------------------------
    # Victory check
    # ------------------------------------------------------------------

    def check_victory(self) -> Optional[int]:
        """Returns winning team number (1, 2, or 3), or None if game continues."""
        teams_alive = []
        for i, team in enumerate([self.team1, self.team2, self.team3], start=1):
            if team and any(m.is_alive for m in team):
                teams_alive.append(i)

        if len(teams_alive) == 1:
            return teams_alive[0]
        if len(teams_alive) == 0:
            return 1  # fallback
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _place_mechs(self):
        for team in self.all_teams:
            for mech in team:
                if mech.position:
                    x, y = mech.position
                    self.map_data[y][x].mech = mech

    def _log(self, msg: str):
        self.combat_log.append(msg)
        if len(self.combat_log) > 10:
            self.combat_log.pop(0)
