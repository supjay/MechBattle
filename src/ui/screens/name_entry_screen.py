"""Name entry screen – select player count and collect player names."""
import math
import pygame
from src.ui.constants import *
from src.ui.components import Button, draw_text


_TEAM_COLS = [TEAM1_BORDER, TEAM2_BORDER, TEAM3_BORDER]


class NameEntryScreen:
    _MAX_LEN = 18

    def __init__(self, manager):
        self.manager = manager
        self._player_count = 2          # 2 or 3
        self._names = ["Player 1", "Player 2", "Player 3"]
        self._active = 0

        cx = SCREEN_W // 2
        self._btn_continue = Button(
            (cx - 130, 530, 260, 52), "CONTINUE",
            color_normal=BTN_SUCCESS, color_hover=BTN_SUCCESS_H,
            font_size=FONT_LARGE,
        )
        # Player-count toggle buttons
        self._btn_2p = Button((cx - 160, 195, 140, 38), "2 PLAYERS",
                              color_normal=BTN_ACTIVE, color_hover=BTN_HOVER,
                              font_size=FONT_MEDIUM)
        self._btn_3p = Button((cx + 20, 195, 140, 38), "3 PLAYERS",
                              color_normal=BTN_NORMAL, color_hover=BTN_HOVER,
                              font_size=FONT_MEDIUM)

    # ------------------------------------------------------------------
    def on_enter(self, **_):
        self._player_count = getattr(self.manager, "player_count", 2)
        self._names = [
            getattr(self.manager, "player1_name", "Player 1"),
            getattr(self.manager, "player2_name", "Player 2"),
            getattr(self.manager, "player3_name", "Player 3"),
        ]
        self._active = 0
        self._rebuild_fields()
        pygame.key.start_text_input()

    def _rebuild_fields(self):
        cx = SCREEN_W // 2
        n = self._player_count
        # 3 fields stacked; only show n of them
        tops = [280, 370, 460]
        self._field_rects = [
            pygame.Rect(cx - 180, tops[i], 360, 46)
            for i in range(n)
        ]
        # Update continue button y
        cont_y = tops[n - 1] + 62
        self._btn_continue = Button(
            (cx - 130, cont_y, 260, 52), "CONTINUE",
            color_normal=BTN_SUCCESS, color_hover=BTN_SUCCESS_H,
            font_size=FONT_LARGE,
        )

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event):
        # Player-count toggle
        if self._btn_2p.handle_event(event):
            self._player_count = 2
            self._rebuild_fields()
        if self._btn_3p.handle_event(event):
            self._player_count = 3
            self._rebuild_fields()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self._field_rects):
                if rect.collidepoint(event.pos):
                    self._active = i
                    return
            if self._btn_continue.handle_event(event):
                self._commit_and_continue()
                return
        else:
            self._btn_continue.handle_event(event)

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self._active < self._player_count - 1:
                    self._active += 1
                else:
                    self._commit_and_continue()
            elif event.key == pygame.K_TAB:
                self._active = (self._active + 1) % self._player_count
            elif event.key == pygame.K_BACKSPACE:
                self._names[self._active] = self._names[self._active][:-1]

        elif event.type == pygame.TEXTINPUT:
            if len(self._names[self._active]) < self._MAX_LEN:
                self._names[self._active] += event.text

    # ------------------------------------------------------------------
    def _commit_and_continue(self):
        self.manager.player_count  = self._player_count
        self.manager.player1_name  = self._names[0].strip() or "Player 1"
        self.manager.player2_name  = self._names[1].strip() or "Player 2"
        self.manager.player3_name  = self._names[2].strip() or "Player 3"
        pygame.key.stop_text_input()
        self.manager.switch_to("roster")

    def update(self, dt: float):
        pass

    # ------------------------------------------------------------------
    def draw(self, surface: pygame.Surface):
        surface.fill(DARK_GRAY)
        pygame.draw.rect(surface, (30, 36, 50), (0, 0, SCREEN_W, 200))

        draw_text(surface, "MECH BATTLE", (SCREEN_W // 2, 80),
                  color=(220, 80, 50), font_size=78, anchor="center")
        draw_text(surface, "Enter Player Names", (SCREEN_W // 2, 160),
                  color=HUD_DIM, font_size=FONT_LARGE, anchor="center")

        # Player count selector
        draw_text(surface, "Players:", (SCREEN_W // 2 - 205, 203),
                  color=HUD_DIM, font_size=FONT_MEDIUM)
        self._btn_2p.color_normal = BTN_ACTIVE if self._player_count == 2 else BTN_NORMAL
        self._btn_3p.color_normal = BTN_ACTIVE if self._player_count == 3 else BTN_NORMAL
        self._btn_2p.draw(surface)
        self._btn_3p.draw(surface)

        labels    = [f"Player {i+1} Name" for i in range(self._player_count)]
        label_y   = [r.top - 28 for r in self._field_rects]

        cursor_visible = math.fmod(pygame.time.get_ticks() / 1000.0, 1.0) < 0.55

        for i in range(self._player_count):
            draw_text(surface, labels[i],
                      (self._field_rects[i].x, label_y[i]),
                      color=_TEAM_COLS[i], font_size=FONT_MEDIUM)

            rect = self._field_rects[i]
            active = (self._active == i)
            border_col = _TEAM_COLS[i] if active else HUD_BORDER
            border_w   = 2            if active else 1

            pygame.draw.rect(surface, (25, 30, 40), rect, border_radius=4)
            pygame.draw.rect(surface, border_col, rect, border_w, border_radius=4)

            display = self._names[i]
            if active and cursor_visible:
                display += "|"

            draw_text(surface, display,
                      (rect.x + 12, rect.centery),
                      color=WHITE, font_size=FONT_LARGE, anchor="midleft")

        self._btn_continue.draw(surface)

        draw_text(surface, "Tab / click to switch field  •  Enter to confirm",
                  (SCREEN_W // 2, self._btn_continue.rect.bottom + 14),
                  color=HUD_DIM, font_size=FONT_SMALL, anchor="center")
