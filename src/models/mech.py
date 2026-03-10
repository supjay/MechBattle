import copy
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from src.models.weapon import Weapon
from src.models.ability import Ability


@dataclass
class Mech:
    id: str
    name: str
    max_hp: int
    armor: int
    move_range: int
    initiative: int
    weapons: List[Weapon]
    ability: Ability
    color: Tuple[int, int, int]
    description: str = ""

    # Set during game setup
    team: int = 0
    position: Optional[Tuple[int, int]] = None

    # Current HP – initialised in __post_init__
    hp: int = field(default=0, init=False)
    is_alive: bool = field(default=True, init=False)

    # Status effects (cleared at start of this mech's next turn)
    is_shielded: bool = field(default=False, init=False)
    is_cloaked: bool = field(default=False, init=False)
    is_overcharged: bool = field(default=False, init=False)
    is_ap_rounds: bool = field(default=False, init=False)    # consumed on next attack

    # Per-turn flags
    has_moved: bool = field(default=False, init=False)
    has_acted: bool = field(default=False, init=False)

    def __post_init__(self):
        self.hp = self.max_hp

    # ------------------------------------------------------------------
    # Combat helpers
    # ------------------------------------------------------------------

    def take_damage(self, raw_damage: int) -> int:
        """Apply damage after armor/shield reduction. Returns actual damage taken."""
        effective_armor = self.armor
        tile_bonus = getattr(self, "_cover_bonus", 0)
        effective_armor += tile_bonus

        if self.is_shielded:
            actual = max(1, raw_damage // 2 - effective_armor)
        else:
            actual = max(1, raw_damage - effective_armor)

        self.hp = max(0, self.hp - actual)
        if self.hp <= 0:
            self.is_alive = False
        return actual

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def start_turn(self):
        """Clear per-turn flags and single-turn status effects."""
        self.has_moved = False
        self.has_acted = False
        self.is_shielded = False
        self.is_cloaked = False
        # is_overcharged is intentionally NOT cleared here;
        # it's consumed when the mech attacks during this same turn.

    def can_move(self) -> bool:
        return self.is_alive and not self.has_moved

    def can_act(self) -> bool:
        return self.is_alive and not self.has_acted

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def hp_percent(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0.0

    def create_instance(self) -> "Mech":
        """Deep-copy this mech template for use in an actual battle."""
        m = copy.deepcopy(self)
        m.hp = m.max_hp
        m.is_alive = True
        m.is_shielded = False
        m.is_cloaked = False
        m.is_overcharged = False
        m.is_ap_rounds = False
        m.has_moved = False
        m.has_acted = False
        m.position = None
        return m

    def status_string(self) -> str:
        parts = []
        if self.is_shielded:
            parts.append("SHIELDED")
        if self.is_cloaked:
            parts.append("CLOAKED")
        if self.is_overcharged:
            parts.append("OVERCHARGED")
        if self.is_ap_rounds:
            parts.append("AP ROUNDS")
        return " | ".join(parts)
