"""Wiki / Codex screen – in-game reference for mechs, weapons, abilities, and rules."""
import pygame
from typing import List

from src.ui.constants import *
from src.ui.components import Button, draw_text
from src.ui.mech_renderer import draw_mech_portrait


# ---------------------------------------------------------------------------
# Static reference data (mirrors mechs.json to avoid loading it twice)
# ---------------------------------------------------------------------------

_MECH_ENTRIES = [
    {
        "id": "titan",
        "name": "Titan",
        "color": (200, 80, 80),
        "tagline": "Walking fortress — slow, unstoppable.",
        "stats": "HP 120 | ARM 8 | MOV 3 | INIT 2",
        "weapons": [
            ("Power Fist",  "Melee",      "30 dmg | Rng 1 | Acc 90% | ∞"),
            ("Missile Pod", "Missiles",   "22 dmg | Rng 6 | Acc 70% | ×3 | Splash 1"),
        ],
        "ability": ("Shield Wall", "Halves ALL incoming damage until your next turn. Use before "
                    "closing into melee or tanking a barrage."),
    },
    {
        "id": "raptor",
        "name": "Raptor",
        "color": (80, 200, 80),
        "tagline": "Speed and agility — hit fast, reposition faster.",
        "stats": "HP 75 | ARM 3 | MOV 6 | INIT 8",
        "weapons": [
            ("Laser Cannon", "Laser",      "18 dmg | Rng 7 | Acc 80% | ∞"),
            ("Autocannon",   "Autocannon", "14 dmg | Rng 4 | Acc 85% | ∞"),
        ],
        "ability": ("Sprint", "Resets movement — move a second time this turn. Counts as your "
                    "action. Great for repositioning after an opening attack."),
    },
    {
        "id": "colossus",
        "name": "Colossus",
        "color": (220, 170, 50),
        "tagline": "Siege mech — devastating area denial.",
        "stats": "HP 150 | ARM 10 | MOV 2 | INIT 1",
        "weapons": [
            ("Heavy Autocannon", "Autocannon", "20 dmg | Rng 5 | Acc 80% | ∞"),
            ("Siege Missiles",   "Missiles",   "28 dmg | Rng 7 | Acc 65% | ×3 | Splash 1"),
        ],
        "ability": ("Artillery Barrage", "Target any tile within range 8. Deals 35 damage (ignores "
                    "cover) to ALL enemies within radius 2 of the impact point."),
    },
    {
        "id": "phantom",
        "name": "Phantom",
        "color": (100, 100, 220),
        "tagline": "Stealth assassin — strike from shadows.",
        "stats": "HP 70 | ARM 2 | MOV 5 | INIT 9",
        "weapons": [
            ("Stealth Laser", "Laser", "20 dmg | Rng 6 | Acc 85% | ∞"),
            ("Vibro Blade",   "Melee", "35 dmg | Rng 1 | Acc 95% | ∞"),
        ],
        "ability": ("Cloak", "Becomes completely untargetable until the start of your next turn. "
                    "Cannot be hit by direct weapons or splash. Best used defensively when surrounded."),
    },
    {
        "id": "vanguard",
        "name": "Vanguard",
        "color": (180, 80, 200),
        "tagline": "Balanced frontliner — reliable in any role.",
        "stats": "HP 95 | ARM 5 | MOV 4 | INIT 5",
        "weapons": [
            ("Plasma Laser",    "Laser",      "20 dmg | Rng 6 | Acc 82% | ∞"),
            ("Rapid Autocannon","Autocannon", "16 dmg | Rng 4 | Acc 88% | ∞"),
        ],
        "ability": ("Overcharge", "Next attack this turn deals ×1.5 damage. Stack with a critical "
                    "hit for ×2.25 total damage. Use before your hardest shot."),
    },
    {
        "id": "sniper",
        "name": "Sniper",
        "color": (80, 200, 200),
        "tagline": "Extreme-range hunter — precision over power.",
        "stats": "HP 80 | ARM 3 | MOV 2 | INIT 7",
        "weapons": [
            ("Longshot Rifle", "Laser", "28 dmg | Rng 10 | Acc 88% | ∞"),
            ("Combat Blade",   "Melee", "18 dmg | Rng 1  | Acc 82% | ∞"),
        ],
        "ability": ("AP Rounds (×2)", "Load armor-piercing ammunition. Next attack: +25 accuracy "
                    "(capped at 99%), ignores 5 armor. Two uses per battle — plan them carefully."),
    },
]

_TABS = ["Mechs", "Combat Rules", "Weapons", "Turn Order"]


class WikiScreen:
    _SCROLL_SPEED = 280.0   # pixels per second

    def __init__(self, manager):
        self.manager = manager
        self._tab = 0
        self._scroll_y = 0.0
        self._max_scroll = 0
        self._content_surf: pygame.Surface = None
        self._tab_rects: List[pygame.Rect] = []

        cx = SCREEN_W // 2
        self._btn_back = Button((14, SCREEN_H - 58, 120, 44), "← Back",
                                font_size=FONT_MEDIUM)

    # ------------------------------------------------------------------
    def on_enter(self, **_):
        self._tab = 0
        self._scroll_y = 0.0
        self._rebuild_tabs()
        self._rebuild_content()

    def _rebuild_tabs(self):
        tab_w = 160
        tab_h = 36
        total_w = len(_TABS) * tab_w + (len(_TABS) - 1) * 6
        start_x = (SCREEN_W - total_w) // 2
        self._tab_rects = [
            pygame.Rect(start_x + i * (tab_w + 6), 54, tab_w, tab_h)
            for i in range(len(_TABS))
        ]

    def _rebuild_content(self):
        """Render the selected tab's content onto an off-screen surface."""
        if self._tab == 0:
            self._content_surf = self._build_mechs_surf()
        elif self._tab == 1:
            self._content_surf = self._build_combat_surf()
        elif self._tab == 2:
            self._content_surf = self._build_weapons_surf()
        else:
            self._content_surf = self._build_turn_surf()

        self._max_scroll = max(0, self._content_surf.get_height() - (SCREEN_H - 160))
        self._scroll_y = 0.0

    # ------------------------------------------------------------------
    # Event / update
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event):
        if self._btn_back.handle_event(event):
            self.manager.switch_to("main_menu")

        if event.type == pygame.MOUSEBUTTONDOWN:
            for i, rect in enumerate(self._tab_rects):
                if rect.collidepoint(event.pos):
                    self._tab = i
                    self._rebuild_content()
                    return
            if event.button == 4:   # scroll wheel up
                self._scroll_y = max(0, self._scroll_y - 40)
            elif event.button == 5: # scroll wheel down
                self._scroll_y = min(self._max_scroll, self._scroll_y + 40)

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self._scroll_y = max(0, self._scroll_y - 40)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._scroll_y = min(self._max_scroll, self._scroll_y + 40)

    def update(self, dt: float):
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            self._scroll_y = max(0, self._scroll_y - self._SCROLL_SPEED * dt)
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            self._scroll_y = min(self._max_scroll, self._scroll_y + self._SCROLL_SPEED * dt)

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------
    def draw(self, surface: pygame.Surface):
        surface.fill(DARK_GRAY)
        pygame.draw.rect(surface, (22, 28, 38), (0, 0, SCREEN_W, 100))

        draw_text(surface, "CODEX", (SCREEN_W // 2, 24),
                  color=HUD_ACCENT, font_size=FONT_TITLE, anchor="center")

        # Tabs
        for i, (rect, label) in enumerate(zip(self._tab_rects, _TABS)):
            active = (i == self._tab)
            bg  = HUD_PANEL if active else (28, 32, 42)
            brd = HUD_ACCENT if active else HUD_BORDER
            pygame.draw.rect(surface, bg,  rect, border_radius=5)
            pygame.draw.rect(surface, brd, rect, 1 if not active else 2, border_radius=5)
            draw_text(surface, label, rect.center,
                      color=WHITE if active else HUD_DIM,
                      font_size=FONT_MEDIUM, anchor="center")

        # Content viewport
        viewport_y = 100
        viewport_h = SCREEN_H - 160
        viewport_rect = pygame.Rect(0, viewport_y, SCREEN_W, viewport_h)
        pygame.draw.rect(surface, (20, 24, 32), viewport_rect)

        if self._content_surf:
            surface.blit(self._content_surf, (0, viewport_y),
                         pygame.Rect(0, int(self._scroll_y), SCREEN_W, viewport_h))

        # Scroll hint
        if self._max_scroll > 0:
            bar_h = max(20, int(viewport_h * viewport_h / (self._content_surf.get_height() + 1)))
            bar_y = viewport_y + int((self._scroll_y / self._max_scroll)
                                     * (viewport_h - bar_h))
            pygame.draw.rect(surface, HUD_BORDER, (SCREEN_W - 8, bar_y, 5, bar_h), border_radius=3)

        self._btn_back.draw(surface)
        draw_text(surface, "↑↓ / Scroll to navigate",
                  (SCREEN_W // 2, SCREEN_H - 34),
                  color=HUD_DIM, font_size=FONT_SMALL, anchor="center")

    # ------------------------------------------------------------------
    # Content surface builders
    # ------------------------------------------------------------------

    @staticmethod
    def _make_surf(height: int) -> pygame.Surface:
        s = pygame.Surface((SCREEN_W, height))
        s.fill((20, 24, 32))
        return s

    def _build_mechs_surf(self) -> pygame.Surface:
        PAD    = 30
        ROW_H  = 240
        surf   = self._make_surf(PAD + len(_MECH_ENTRIES) * (ROW_H + 20) + PAD)
        y      = PAD

        for entry in _MECH_ENTRIES:
            # Background card
            card = pygame.Rect(PAD, y, SCREEN_W - PAD * 2, ROW_H)
            pygame.draw.rect(surf, (28, 34, 46), card, border_radius=8)
            pygame.draw.rect(surf, HUD_BORDER,   card, 1, border_radius=8)

            # Portrait
            port_rect = pygame.Rect(card.x + 10, card.y + 10, 100, 120)
            pygame.draw.rect(surf, (18, 20, 28), port_rect, border_radius=4)
            draw_mech_portrait(surf, entry["id"], entry["color"], port_rect)
            pygame.draw.rect(surf, HUD_BORDER, port_rect, 1, border_radius=4)

            # Name + tagline
            tx = card.x + 124
            draw_text(surf, entry["name"], (tx, card.y + 14),
                      color=tuple(entry["color"]), font_size=FONT_LARGE + 4)
            draw_text(surf, entry["tagline"], (tx, card.y + 44),
                      color=HUD_DIM, font_size=FONT_SMALL)
            draw_text(surf, entry["stats"], (tx, card.y + 62),
                      color=HUD_TEXT, font_size=FONT_SMALL)

            # Weapons
            wy = card.y + 88
            draw_text(surf, "WEAPONS", (tx, wy), color=HUD_ACCENT, font_size=FONT_TINY)
            wy += 16
            for wname, wtype, wstats in entry["weapons"]:
                draw_text(surf, f"  {wname}  [{wtype}]", (tx, wy),
                          color=HUD_TEXT, font_size=FONT_SMALL)
                draw_text(surf, wstats, (tx + 220, wy), color=HUD_DIM, font_size=FONT_TINY)
                wy += 18

            # Ability
            ab_name, ab_desc = entry["ability"]
            wy += 4
            draw_text(surf, f"✦ ABILITY: {ab_name}", (tx, wy),
                      color=(220, 175, 50), font_size=FONT_SMALL)
            wy += 18
            # Word-wrap description
            self._wrap_text(surf, ab_desc, tx, wy, SCREEN_W - tx - PAD - 10,
                            FONT_TINY, HUD_DIM)

            y += ROW_H + 20

        return surf

    def _build_combat_surf(self) -> pygame.Surface:
        sections = [
            ("HOW DAMAGE WORKS",
             [
                 "When a weapon fires, the game rolls 1–100. If the roll ≤ the weapon's Accuracy,",
                 "the shot hits. Cover tiles subtract 15 from accuracy.",
                 "",
                 "  Damage dealt = Weapon Damage - Target Armor",
                 "  Minimum 1 damage is always dealt.",
                 "",
                 "  Critical Hit (10% chance on a hit): ×1.5 damage",
                 "  Overcharge + Critical: ×1.5 × ×1.5 = ×2.25 total",
                 "  Shield Wall: halves all incoming damage (after armor reduction)",
                 "  AP Rounds: +25 accuracy, pierces 5 armor on the next shot",
             ]),
            ("COVER",
             [
                 "Tiles marked with an X pattern are Cover tiles.",
                 "  • Attacking a mech in cover: −15 accuracy penalty",
                 "  • Cover also grants +4 effective armor against all incoming fire",
                 "  • Splash weapons (missiles) ignore cover bonuses",
             ]),
            ("ABILITIES",
             [
                 "Each mech has one unique ability with limited uses per battle.",
                 "Using an ability costs your action for the turn (you cannot also attack).",
                 "",
                 "  Shield Wall   — Defensive buff. Use before taking hits.",
                 "  Sprint        — Extra movement, consumes action.",
                 "  Artillery     — Targeted AOE barrage. Ignores cover.",
                 "  Cloak         — Immunity to targeting for one round.",
                 "  Overcharge    — +50% damage on next attack this turn.",
                 "  AP Rounds     — +25 accuracy, +5 armor pierce. 2 uses.",
             ]),
            ("WEAPON TYPES",
             [
                 "  Laser      — Instant beam. Fast animation. Standard accuracy.",
                 "  Autocannon — Burst fire. 3 shells, rapid impacts. High accuracy.",
                 "  Missiles   — Arcing projectile. Slow travel, splash radius 1.",
                 "               Splash hits all mechs within 1 tile of the target.",
                 "  Melee      — Rush attack. Short range (1 tile). Very high accuracy.",
                 "               Phantom's Vibro Blade is the hardest single hit in the game.",
             ]),
            ("AMMO",
             [
                 "Weapons marked ∞ have unlimited ammunition.",
                 "Weapons with ×N use limited ammo (e.g. ×3 = 3 shots per battle).",
                 "Once ammo is depleted, that weapon cannot be selected.",
             ]),
        ]

        line_h = FONT_SMALL + 4
        total_h = 40
        for title, lines in sections:
            total_h += 36 + len(lines) * line_h + 20

        surf = self._make_surf(total_h + 40)
        y = 20
        PAD = 48

        for title, lines in sections:
            pygame.draw.line(surf, HUD_ACCENT,
                             (PAD, y + 20), (SCREEN_W - PAD, y + 20), 1)
            draw_text(surf, title, (PAD, y), color=HUD_ACCENT, font_size=FONT_MEDIUM)
            y += 30
            for line in lines:
                col = HUD_DIM if line.startswith("  ") else HUD_TEXT
                if line == "":
                    y += line_h // 2
                    continue
                draw_text(surf, line, (PAD + 8, y), color=col, font_size=FONT_SMALL)
                y += line_h
            y += 20

        return surf

    def _build_weapons_surf(self) -> pygame.Surface:
        rows = [
            ("Laser",      "Instant beam — good accuracy, very fast visual",
             "No ammo limit. Reduced by cover. Hits single target."),
            ("Autocannon", "Burst fire — excellent accuracy",
             "No ammo limit. 3 sequential impacts. Direct fire only."),
            ("Missiles",   "Arcing projectile — splash damage",
             "Limited ammo. Splash radius 1. Hits through cover bonus."),
            ("Melee",      "Rush attack — extreme close range",
             "No ammo limit. Range 1 only. Highest base accuracy."),
        ]

        surf = self._make_surf(60 + len(rows) * 110 + 60)
        y = 24
        PAD = 48

        draw_text(surf, "WEAPON TYPE REFERENCE", (SCREEN_W // 2, y),
                  color=HUD_ACCENT, font_size=FONT_LARGE, anchor="center")
        y += 40

        type_cols = {
            "Laser": GLOW_BLUE if False else (80, 200, 255),
            "Autocannon": (200, 200, 80),
            "Missiles": (255, 120, 40),
            "Melee": (220, 60, 60),
        }

        for wtype, summary, detail in rows:
            card = pygame.Rect(PAD, y, SCREEN_W - PAD * 2, 90)
            pygame.draw.rect(surf, (28, 34, 46), card, border_radius=6)
            pygame.draw.rect(surf, type_cols.get(wtype, HUD_BORDER), card, 1, border_radius=6)
            draw_text(surf, wtype, (card.x + 16, card.y + 12),
                      color=type_cols.get(wtype, WHITE), font_size=FONT_LARGE)
            draw_text(surf, summary, (card.x + 16, card.y + 42),
                      color=HUD_TEXT, font_size=FONT_SMALL)
            draw_text(surf, detail, (card.x + 16, card.y + 62),
                      color=HUD_DIM, font_size=FONT_SMALL)
            y += 110

        return surf

    def _build_turn_surf(self) -> pygame.Surface:
        sections = [
            ("INITIATIVE & TURN ORDER",
             [
                 "At the start of battle, all mechs are sorted by Initiative (descending).",
                 "Higher initiative = acts first. Ties are broken by team order.",
                 "",
                 "  Phantom:  INIT 9  (acts first almost always)",
                 "  Raptor:   INIT 8",
                 "  Sniper:   INIT 7",
                 "  Vanguard: INIT 5",
                 "  Titan:    INIT 2",
                 "  Colossus: INIT 1  (acts last)",
                 "",
                 "This order repeats every round. Dead mechs are skipped.",
             ]),
            ("EACH MECH'S TURN",
             [
                 "On your mech's turn you may do BOTH of these (in any order):",
                 "",
                 "  1. MOVE  — Move to any reachable tile (shown in blue).",
                 "             Range = mech's MOV stat, 8-directional BFS.",
                 "             Cannot move through other mechs or blocked tiles.",
                 "",
                 "  2. ACTION — Choose one:",
                 "     • Fire a weapon (click a highlighted red tile)",
                 "     • Use your ability (some target a tile; some are instant)",
                 "",
                 "Once both are used (or you click End Turn), the next mech goes.",
                 "If a mech has nothing left to do, the turn advances automatically.",
             ]),
            ("ROUNDS",
             [
                 "A Round ends when every surviving mech has taken one turn.",
                 "The Round counter is shown in the top-left of the HUD.",
                 "There is no round limit — battle continues until one team remains.",
             ]),
            ("3-PLAYER MODE",
             [
                 "Three teams play in initiative order just like 2-player.",
                 "Victory: the last team with any surviving mechs wins.",
                 "Choosing the Triangle Protocol map gives each team a distinct",
                 "starting corner for a balanced 3-way engagement.",
                 "",
                 "Tip: In 3-player, sometimes it's worth letting two enemies weaken",
                 "each other before committing your own forces.",
             ]),
            ("COVER & POSITIONING",
             [
                 "Cover tiles (X-marked) provide:",
                 "  • −15 accuracy to attacks targeting that tile",
                 "  • +4 effective armor for the occupying mech",
                 "",
                 "Blocked tiles (wall tiles) cannot be moved through or onto.",
                 "A mech in cover is still vulnerable to Splash weapons — missiles",
                 "affect all mechs within radius 1 of the impact point regardless.",
             ]),
        ]

        line_h = FONT_SMALL + 4
        total_h = 40
        for title, lines in sections:
            total_h += 36 + len(lines) * line_h + 24

        surf = self._make_surf(total_h + 40)
        y = 20
        PAD = 48

        for title, lines in sections:
            pygame.draw.line(surf, (100, 160, 220),
                             (PAD, y + 20), (SCREEN_W - PAD, y + 20), 1)
            draw_text(surf, title, (PAD, y), color=HUD_ACCENT, font_size=FONT_MEDIUM)
            y += 30
            for line in lines:
                if line == "":
                    y += line_h // 2
                    continue
                col = HUD_DIM if line.startswith("  ") else HUD_TEXT
                draw_text(surf, line, (PAD + 8, y), color=col, font_size=FONT_SMALL)
                y += line_h
            y += 24

        return surf

    # ------------------------------------------------------------------
    @staticmethod
    def _wrap_text(surface, text, x, y, max_w, size, color):
        font = pygame.font.Font(None, size)
        words = text.split()
        line = ""
        line_y = y
        for word in words:
            test = (line + " " + word).strip()
            if font.size(test)[0] <= max_w:
                line = test
            else:
                if line:
                    surf = font.render(line, True, color)
                    surface.blit(surf, (x, line_y))
                    line_y += size + 2
                line = word
        if line:
            surf = font.render(line, True, color)
            surface.blit(surf, (x, line_y))


# ---------------------------------------------------------------------------
# Type annotations pulled from renderer without circular import
# ---------------------------------------------------------------------------
try:
    from src.ui.mech_renderer import GLOW_BLUE
except ImportError:
    GLOW_BLUE = (70, 195, 255)
