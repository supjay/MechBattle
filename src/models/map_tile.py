from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MapTile:
    x: int
    y: int
    type: str   # open | cover | blocked

    # Set at runtime – not in JSON
    mech: Optional[object] = field(default=None, repr=False)

    @property
    def is_passable(self) -> bool:
        return self.type != "blocked"

    @property
    def is_cover(self) -> bool:
        return self.type == "cover"

    @property
    def cover_bonus(self) -> int:
        """Effective extra armor when standing in cover."""
        return 4 if self.is_cover else 0
