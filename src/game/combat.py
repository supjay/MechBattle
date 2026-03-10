"""Combat resolution and movement calculation."""
import random
from collections import deque
from typing import TYPE_CHECKING, Dict, Any, List, Optional, Set, Tuple

from src.models.mech import Mech
from src.models.weapon import Weapon

if TYPE_CHECKING:
    from src.game.game_state import GameState


class CombatResolver:
    """Stateless helper – all methods are static."""

    # ------------------------------------------------------------------
    # Distance helpers
    # ------------------------------------------------------------------

    @staticmethod
    def chebyshev(a: Tuple[int, int], b: Tuple[int, int]) -> int:
        """Max of |dx|, |dy| – allows 8-directional range checks."""
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    @staticmethod
    def get_valid_moves(mech: Mech, gs: "GameState") -> Set[Tuple[int, int]]:
        """BFS – returns all tiles reachable within mech.move_range."""
        if not mech.can_move():
            return set()

        start = mech.position
        visited: Set[Tuple[int, int]] = {start}
        reachable: Set[Tuple[int, int]] = set()
        queue: deque = deque([(start, 0)])

        while queue:
            (cx, cy), dist = queue.popleft()
            if dist > 0:
                reachable.add((cx, cy))
            if dist >= mech.move_range:
                continue

            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1),
                           (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in visited:
                    continue
                if not (0 <= nx < gs.map_width and 0 <= ny < gs.map_height):
                    continue
                tile = gs.map_data[ny][nx]
                if not tile.is_passable:
                    continue
                if tile.mech is not None:
                    continue      # Can't pass through any mech
                visited.add((nx, ny))
                queue.append(((nx, ny), dist + 1))

        return reachable

    # ------------------------------------------------------------------
    # Attack targeting
    # ------------------------------------------------------------------

    @staticmethod
    def get_valid_attack_tiles(mech: Mech, weapon: Weapon,
                               gs: "GameState") -> Set[Tuple[int, int]]:
        """Tiles that can be targeted with the given weapon."""
        if not weapon.has_ammo():
            return set()

        valid: Set[Tuple[int, int]] = set()
        mx, my = mech.position

        for y in range(gs.map_height):
            for x in range(gs.map_width):
                dist = CombatResolver.chebyshev((mx, my), (x, y))
                if not (1 <= dist <= weapon.range):
                    continue
                tile = gs.map_data[y][x]
                if weapon.splash > 0:
                    # Splash weapons target any passable tile (area effect)
                    if tile.is_passable or tile.mech is not None:
                        valid.add((x, y))
                else:
                    # Direct weapons need a visible enemy on that tile
                    if tile.mech is not None and tile.mech.is_alive:
                        if tile.mech.team != mech.team:
                            if not tile.mech.is_cloaked:
                                valid.add((x, y))
        return valid

    # ------------------------------------------------------------------
    # Attack resolution
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_attack(attacker: Mech, weapon: Weapon,
                       target_pos: Tuple[int, int],
                       gs: "GameState") -> List[Dict[str, Any]]:
        """Execute an attack. Returns a list of hit-results (one per mech hit)."""
        results: List[Dict[str, Any]] = []

        weapon.use_ammo()

        overcharge = attacker.is_overcharged
        if overcharge:
            attacker.is_overcharged = False

        ap_rounds = attacker.is_ap_rounds
        if ap_rounds:
            attacker.is_ap_rounds = False

        # Collect targets
        targets_to_hit: List[Tuple[Mech, Any]] = []
        tx, ty = target_pos

        if weapon.splash > 0:
            for y in range(gs.map_height):
                for x in range(gs.map_width):
                    if CombatResolver.chebyshev(target_pos, (x, y)) <= weapon.splash:
                        tile = gs.map_data[y][x]
                        if tile.mech is not None and tile.mech.is_alive:
                            targets_to_hit.append((tile.mech, tile))
        else:
            tile = gs.map_data[ty][tx]
            if tile.mech is not None and tile.mech.is_alive:
                targets_to_hit.append((tile.mech, tile))

        for target, tile in targets_to_hit:
            cover_penalty = 15 if tile.is_cover else 0
            hit_chance = max(10, weapon.accuracy - cover_penalty)
            if ap_rounds:
                hit_chance = min(99, hit_chance + 25)
            rolled = random.randint(1, 100)

            if rolled <= hit_chance:
                is_crit = random.randint(1, 100) <= 10
                raw = weapon.damage
                if overcharge:
                    raw = int(raw * 1.5)
                if is_crit:
                    raw = int(raw * 1.5)

                # AP Rounds pierce 5 armor
                ap_pierce = 5 if ap_rounds else 0
                target._cover_bonus = tile.cover_bonus - ap_pierce
                actual = target.take_damage(raw)
                target._cover_bonus = 0

                results.append({
                    "hit": True,
                    "target": target,
                    "damage": actual,
                    "critical": is_crit,
                    "overcharge": overcharge,
                    "ap_rounds": ap_rounds,
                })
            else:
                results.append({
                    "hit": False,
                    "target": target,
                    "damage": 0,
                    "critical": False,
                    "overcharge": overcharge,
                    "ap_rounds": ap_rounds,
                })

        return results

    # ------------------------------------------------------------------
    # Ability resolution
    # ------------------------------------------------------------------

    @staticmethod
    def apply_ability(mech: Mech, target_pos: Optional[Tuple[int, int]],
                      gs: "GameState") -> Dict[str, Any]:
        """Execute the mech's special ability. Returns a result dict."""
        ability = mech.ability
        if not ability.can_use():
            return {"success": False, "message": f"{ability.name} has no uses left!"}

        ability.use()

        if ability.effect == "shield_wall":
            mech.is_shielded = True
            return {
                "success": True,
                "message": f"{mech.name} raises Shield Wall! Incoming damage halved.",
            }

        elif ability.effect == "sprint":
            mech.has_moved = False          # Allow another move this turn
            mech.has_acted = True           # Sprint consumes the action
            return {
                "success": True,
                "message": f"{mech.name} sprints! Move again.",
                "extra_move": True,
            }

        elif ability.effect == "cloak":
            mech.is_cloaked = True
            return {
                "success": True,
                "message": f"{mech.name} activates Cloak! Cannot be targeted.",
            }

        elif ability.effect == "overcharge":
            mech.is_overcharged = True
            return {
                "success": True,
                "message": f"{mech.name} overcharges! Next attack deals +50% damage.",
            }

        elif ability.effect == "ap_rounds":
            mech.is_ap_rounds = True
            return {
                "success": True,
                "message": f"{mech.name} loads AP Rounds! Next attack: +25 accuracy, pierces 5 armor.",
            }

        elif ability.effect == "artillery":
            if target_pos is None:
                ability.uses_remaining += 1   # refund
                return {"success": False, "message": "Select a target tile first!"}

            hits = []
            for y in range(gs.map_height):
                for x in range(gs.map_width):
                    if CombatResolver.chebyshev(target_pos, (x, y)) <= 2:
                        tile = gs.map_data[y][x]
                        if (tile.mech is not None and tile.mech.is_alive
                                and tile.mech.team != mech.team):
                            dmg = tile.mech.take_damage(35)
                            hits.append(f"{tile.mech.name} -{dmg}hp")

            msg = (f"{mech.name} fires Artillery Barrage! " + ", ".join(hits)
                   if hits else f"{mech.name} fires Artillery Barrage! No targets hit.")
            return {"success": True, "message": msg, "artillery_hits": hits}

        return {"success": False, "message": "Unknown ability."}
