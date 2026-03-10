from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Weapon:
    name: str
    type: str        # melee | laser | missiles | autocannon
    damage: int
    range: int       # in tiles; melee = 1
    accuracy: int    # 0-100 base hit chance
    ammo: Optional[int] = None   # None = unlimited
    splash: int = 0              # splash radius in tiles (0 = no splash)

    # Runtime state – not loaded from JSON
    current_ammo: Optional[int] = field(default=None, init=False)

    def __post_init__(self):
        self.current_ammo = self.ammo

    def has_ammo(self) -> bool:
        return self.current_ammo is None or self.current_ammo > 0

    def use_ammo(self):
        if self.current_ammo is not None:
            self.current_ammo = max(0, self.current_ammo - 1)

    def reset(self):
        self.current_ammo = self.ammo

    @property
    def ammo_display(self) -> str:
        if self.current_ammo is None:
            return "∞"
        return f"{self.current_ammo}/{self.ammo}"

    @property
    def type_icon(self) -> str:
        icons = {"melee": "⚔", "laser": "⚡", "missiles": "🚀", "autocannon": "💥"}
        return icons.get(self.type, "•")
