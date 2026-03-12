"""Roster selection screen – all players pick 3 mechs each."""
import pygame
from typing import List, Optional

from src.models.mech import Mech
from src.ui.constants import *
from src.ui.components import Button, HpBar, draw_text, draw_panel
from src.ui.mech_renderer import draw_mech_portrait


MECHS_PER_TEAM = 3
COLS_PER_ROW   = 3          # 3 cards per row → 2 rows of 3
CARD_W         = 590
CARD_H         = 345
CARD_PAD_X     = 20         # horizontal gap between cards
CARD_PAD_Y     = 20         # vertical gap between rows

# Portrait sub-column (left side of card)
PORTRAIT_W   = 260          # portrait column width → ~172×214 ≈ portrait aspect ratio
PORTRAIT_PAD = 10            # padding around the portrait box

# Derived right-column offsets (relative to card rect.x)
_DIV_X   = PORTRAIT_PAD + PORTRAIT_W + PORTRAIT_PAD        # 8+172+8  = 188
_INFO_X  = _DIV_X + 10                                      # 188+8    = 196
_INFO_W  = CARD_W - _INFO_X - 10                             # 390-196-8 = 186

_TEAM_COLS = [TEAM1_BORDER, TEAM2_BORDER, TEAM3_BORDER]


class RosterScreen:
    def __init__(self, manager):
        self.manager = manager
        self.templates: List[Mech] = []
        self.picks: List[List[Mech]] = [[], [], []]   # picks[0]=p1, [1]=p2, [2]=p3
        self.hovered_idx: Optional[int] = None
        self.current_player: int = 1      # 1-based
        self._player_count: int = 2

        self._hp_bars: List[HpBar] = []
        self._card_rects: List[pygame.Rect] = []
        self._btn_ready: Optional[Button] = None
        self._btn_back:  Optional[Button] = None

    def on_enter(self, **_):
        self._player_count = getattr(self.manager, "player_count", 2)
        self.templates = self.manager.mech_templates
        self.picks = [[], [], []]
        self.current_player = 1
        self.hovered_idx = None
        self._build_layout()

    def _build_layout(self):
        n = len(self.templates)
        total_w = COLS_PER_ROW * CARD_W + (COLS_PER_ROW - 1) * CARD_PAD_X
        start_x = (SCREEN_W - total_w) // 2
        top_y   = 200   # header occupies 0-155

        self._card_rects = []
        self._hp_bars    = []
        for i in range(n):
            col = i % COLS_PER_ROW
            row = i // COLS_PER_ROW
            cx  = start_x + col * (CARD_W + CARD_PAD_X)
            cy  = top_y   + row * (CARD_H + CARD_PAD_Y)
            self._card_rects.append(pygame.Rect(cx, cy, CARD_W, CARD_H))
            # HP bar sits at the bottom of the right info column
            self._hp_bars.append(
                HpBar((cx + _INFO_X, cy + CARD_H - 20, _INFO_W, 12))
            )

        self._btn_ready = Button(
            (SCREEN_W // 2 - 110, SCREEN_H - 54, 220, 42),
            "READY →",
            enabled=False,
            color_normal=BTN_SUCCESS,
            color_hover=BTN_SUCCESS_H,
            font_size=FONT_LARGE,
        )
        self._btn_back = Button(
            (12, SCREEN_H - 54, 120, 42), "← Back",
            font_size=FONT_MEDIUM,
        )

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _picks_for(self, player: int) -> List[Mech]:
        return self.picks[player - 1]

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self.hovered_idx = None
            for i, rect in enumerate(self._card_rects):
                if rect.collidepoint(pos):
                    self.hovered_idx = i

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self._card_rects):
                if rect.collidepoint(event.pos):
                    self._toggle_pick(i)

        ready_enabled = len(self._picks_for(self.current_player)) == MECHS_PER_TEAM
        self._btn_ready.enabled = ready_enabled

        if self._btn_ready.handle_event(event):
            self._advance_player()

        if self._btn_back.handle_event(event):
            self.manager.switch_to("name_entry")

    def _toggle_pick(self, idx: int):
        mech  = self.templates[idx]
        picks = self._picks_for(self.current_player)
        if mech in picks:
            picks.remove(mech)
        elif len(picks) < MECHS_PER_TEAM:
            picks.append(mech)

    def _advance_player(self):
        if self.current_player < self._player_count:
            self.current_player += 1
            self.hovered_idx = None
        else:
            self.manager.team1_templates = list(self.picks[0])
            self.manager.team2_templates = list(self.picks[1])
            if self._player_count == 3:
                self.manager.team3_templates = list(self.picks[2])
            else:
                self.manager.team3_templates = []
            self.manager.switch_to("map_select")

    def update(self, dt: float):
        pass

    # ------------------------------------------------------------------
    # Drawing – screen
    # ------------------------------------------------------------------

    def draw(self, surface: pygame.Surface):
        surface.fill(DARK_GRAY)

        # ── Header ──────────────────────────────────────────────────────
        pygame.draw.rect(surface, (22, 28, 38), (0, 0, SCREEN_W, 155))
        pi          = self.current_player - 1
        player_col  = _TEAM_COLS[pi]
        raw_name    = getattr(self.manager, f"player{self.current_player}_name", None)
        player_name = (raw_name or f"Player {self.current_player}").upper()

        draw_text(surface, "CHOOSE YOUR MECHS", (SCREEN_W // 2, 22),
                  color=HUD_ACCENT, font_size=FONT_LARGE, anchor="center")
        draw_text(surface, f"{player_name} – Select {MECHS_PER_TEAM}", (SCREEN_W // 2, 60),
                  color=player_col, font_size=FONT_LARGE + 4, anchor="center")

        # Pick indicators (filled circles for already-picked, empty for remaining)
        picks = self._picks_for(self.current_player)
        for i in range(MECHS_PER_TEAM):
            px    = SCREEN_W // 2 - (MECHS_PER_TEAM * 28) // 2 + i * 28
            color = player_col if i < len(picks) else GRAY
            pygame.draw.circle(surface, color, (px, 104), 10)
            pygame.draw.circle(surface, HUD_BORDER, (px, 104), 10, 1)

        # ── Player progress breadcrumb – inside header ───────────────────
        # Centered below pick indicators, well above cards
        total_steps = self._player_count
        step_spacing = 120
        bx_start = SCREEN_W // 2 - (total_steps - 1) * step_spacing // 2
        for j in range(total_steps):
            done      = (j + 1) <= self.current_player
            active    = (j + 1) == self.current_player
            step_col  = _TEAM_COLS[j] if done else HUD_BORDER
            raw       = getattr(self.manager, f"player{j + 1}_name", f"P{j + 1}")
            label     = (raw or f"P{j + 1}")[:8].upper()
            bx        = bx_start + j * step_spacing

            # Connector line to next step
            if j < total_steps - 1:
                next_bx = bx_start + (j + 1) * step_spacing
                line_col = _TEAM_COLS[j] if (j + 2) <= self.current_player else HUD_BORDER
                pygame.draw.line(surface, line_col,
                                 (bx + 10, 140), (next_bx - 10, 140), 1)

            # Step circle
            r = 6 if active else 4
            pygame.draw.circle(surface, step_col, (bx, 140), r)
            if active:
                pygame.draw.circle(surface, WHITE, (bx, 140), r, 1)

            # Label
            draw_text(surface, label, (bx, 128),
                      color=player_col if active else (step_col if done else HUD_DIM),
                      font_size=FONT_TINY, anchor="center")

        # ── Cards ────────────────────────────────────────────────────────
        pick_sets = [set(id(m) for m in self.picks[j]) for j in range(3)]
        for i, (rect, mech) in enumerate(zip(self._card_rects, self.templates)):
            selected = id(mech) in pick_sets[self.current_player - 1]
            self._draw_card(surface, rect, mech, i, selected, pick_sets)

        # ── Instruction + buttons ────────────────────────────────────────
        remaining = MECHS_PER_TEAM - len(picks)
        if remaining > 0:
            msg = f"Select {remaining} more mech{'s' if remaining > 1 else ''}"
        else:
            msg = "All mechs selected! Press READY to continue."
        draw_text(surface, msg, (SCREEN_W // 2, SCREEN_H - 68),
                  color=HUD_DIM, font_size=FONT_MEDIUM, anchor="center")

        self._btn_ready.enabled = len(picks) == MECHS_PER_TEAM
        self._btn_ready.draw(surface)
        self._btn_back.draw(surface)

    # ------------------------------------------------------------------
    # Drawing – card
    # ------------------------------------------------------------------

    def _draw_card(self, surface, rect, mech, idx, selected, pick_sets):
        hovered = self.hovered_idx == idx
        pi      = self.current_player - 1

        bg = (42, 50, 66) if hovered else (32, 38, 50)
        if selected:
            border_col = _TEAM_COLS[pi]
            border_w   = 3
        else:
            border_col = HUD_BORDER
            border_w   = 1

        pygame.draw.rect(surface, bg, rect, border_radius=8)
        pygame.draw.rect(surface, border_col, rect, border_w, border_radius=8)

        # ── Left column: Portrait ─────────────────────────────────────
        portrait_rect = pygame.Rect(
            rect.x + PORTRAIT_PAD,
            rect.y + PORTRAIT_PAD,
            PORTRAIT_W,
            rect.h - PORTRAIT_PAD * 2,   # full card height → tall portrait ~172×214
        )
        pygame.draw.rect(surface, (18, 20, 28), portrait_rect, border_radius=4)

        # Gradient tint at bottom of portrait
        team_bg_col = _TEAM_COLS[pi] if selected else HUD_BORDER
        for gy in range(24):
            pygame.draw.line(surface, team_bg_col,
                             (portrait_rect.x, portrait_rect.bottom - gy),
                             (portrait_rect.right, portrait_rect.bottom - gy))

        draw_mech_portrait(surface, mech.id, mech.color, portrait_rect)
        pygame.draw.rect(surface, border_col, portrait_rect, 1, border_radius=4)

        # Vertical divider
        div_x = rect.x + _DIV_X
        pygame.draw.line(surface, HUD_BORDER,
                         (div_x, rect.y + 6), (div_x, rect.bottom - 6))

        # ── Right column: Info ────────────────────────────────────────
        rx = rect.x + _INFO_X
        rw = _INFO_W
        y  = rect.y + PORTRAIT_PAD

        # Mech name
        draw_text(surface, mech.name, (rx, y),
                  color=WHITE, font_size=FONT_LARGE, anchor="topleft")
        y += 22

        # Mech description (1 line, subtle)
        self._wrap_text(surface, mech.description, rx, y, rw,
                        FONT_TINY, HUD_DIM, max_lines=1)
        y += 14

        # Separator
        pygame.draw.line(surface, HUD_BORDER, (rx, y), (rx + rw, y))
        y += 6

        # Stats – 2×2 grid
        stats = [
            ("HP",   str(mech.max_hp)),
            ("ARM",  str(mech.armor)),
            ("MOV",  str(mech.move_range)),
            ("INIT", str(mech.initiative)),
        ]
        half_w = rw // 2
        for si, (label, val) in enumerate(stats):
            sx = rx + (si % 2) * half_w
            sy = y  + (si // 2) * 17
            draw_text(surface, f"{label}:", (sx, sy),
                      color=HUD_DIM, font_size=FONT_SMALL)
            draw_text(surface, val, (sx + 42, sy),
                      color=WHITE, font_size=FONT_SMALL)
        y += 38   # 2 rows × 17px + 4px gap

        # Separator
        pygame.draw.line(surface, HUD_BORDER, (rx, y), (rx + rw, y))
        y += 6

        # Weapons
        for wi, weapon in enumerate(mech.weapons[:2]):
            ammo  = f" ×{weapon.ammo}" if weapon.ammo else " ∞"
            wtext = f"{weapon.name} ({weapon.damage}dmg{ammo})"
            draw_text(surface, wtext, (rx, y + wi * 17),
                      color=HUD_TEXT, font_size=FONT_SMALL)
        y += 38   # 2 weapons × 17px + 4px gap

        # Separator
        pygame.draw.line(surface, HUD_BORDER, (rx, y), (rx + rw, y))
        y += 6

        # Ability name + description (up to 2 lines)
        draw_text(surface, f"✦ {mech.ability.name}", (rx, y),
                  color=(200, 165, 55), font_size=FONT_SMALL)
        y += 16
        self._wrap_text(surface, mech.ability.description,
                        rx, y, rw, FONT_TINY, HUD_DIM, max_lines=2)

        # HP bar (bottom of right column, positioned by _build_layout)
        self._hp_bars[idx].draw(surface, mech.max_hp, mech.max_hp)

        # ── Already-picked badges (over portrait, top-right corner) ───
        bx = portrait_rect.right - 10
        by = portrait_rect.y + 10
        for j in range(self._player_count):
            if id(mech) in pick_sets[j]:
                dot_x = bx - (self._player_count - 1 - j) * 16
                pygame.draw.circle(surface, _TEAM_COLS[j], (dot_x, by), 7)
                draw_text(surface, str(j + 1), (dot_x, by), color=WHITE,
                          font_size=FONT_TINY, anchor="center")

    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_text(surface, text, x, y, max_w, size, color, max_lines=3):
        font  = pygame.font.Font(None, size)
        words = text.split()
        lines = []
        line  = ""
        for word in words:
            test = (line + " " + word).strip()
            if font.size(test)[0] <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        if line:
            lines.append(line)
        for li, l in enumerate(lines[:max_lines]):
            surf = font.render(l, True, color)
            surface.blit(surf, (x, y + li * (size + 1)))
