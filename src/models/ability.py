from dataclasses import dataclass, field


@dataclass
class Ability:
    name: str
    description: str
    effect: str           # shield_wall | sprint | artillery | cloak | overcharge
    uses_per_battle: int = 1

    # Runtime state
    uses_remaining: int = field(default=0, init=False)

    def __post_init__(self):
        self.uses_remaining = self.uses_per_battle

    def can_use(self) -> bool:
        return self.uses_remaining > 0

    def use(self):
        if self.uses_remaining > 0:
            self.uses_remaining -= 1

    def reset(self):
        self.uses_remaining = self.uses_per_battle

    @property
    def needs_target(self) -> bool:
        """Artillery needs a target tile; others are self-targeted."""
        return self.effect == "artillery"
