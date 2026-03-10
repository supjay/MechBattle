"""Victory / result screen."""
import pygame
from src.ui.constants import *
from src.ui.components import Button, draw_text


class ResultScreen:
    def __init__(self, manager):
        self.manager = manager
        self.winner: int = 0
        self.winner_name: str = "Player 1"
        self._btn_play_again: Button = Button(
            (SCREEN_W // 2 - 140, 430, 260, 52), "PLAY AGAIN",
            color_normal=BTN_SUCCESS, color_hover=BTN_SUCCESS_H,
            font_size=FONT_LARGE)
        self._btn_menu: Button = Button(
            (SCREEN_W // 2 - 140, 496, 260, 52), "MAIN MENU",
            font_size=FONT_LARGE)

    def on_enter(self, **_):
        self.winner = getattr(self.manager, "winner", 0) or 0
        w = self.winner
        if w == 1:
            self.winner_name = getattr(self.manager, "player1_name", "Player 1")
        elif w == 2:
            self.winner_name = getattr(self.manager, "player2_name", "Player 2")
        else:
            self.winner_name = "???"
        self._btn_play_again = Button(
            (SCREEN_W // 2 - 140, 430, 260, 52), "PLAY AGAIN",
            color_normal=BTN_SUCCESS, color_hover=BTN_SUCCESS_H,
            font_size=FONT_LARGE)
        self._btn_menu = Button(
            (SCREEN_W // 2 - 140, 496, 260, 52), "MAIN MENU",
            font_size=FONT_LARGE)

    def handle_event(self, event: pygame.event.Event):
        if self._btn_play_again.handle_event(event):
            self.manager.switch_to("roster")
        if self._btn_menu.handle_event(event):
            self.manager.switch_to("main_menu")

    def update(self, dt: float):
        pass

    def draw(self, surface: pygame.Surface):
        surface.fill(DARK_GRAY)
        pygame.draw.rect(surface, (22, 28, 38), (0, 0, SCREEN_W, 380))

        winner_col = TEAM1_BORDER if self.winner == 1 else TEAM2_BORDER

        draw_text(surface, "BATTLE OVER", (SCREEN_W // 2, 80),
                  color=HUD_DIM, font_size=FONT_LARGE, anchor="center")

        draw_text(surface, self.winner_name.upper(),
                  (SCREEN_W // 2, 160),
                  color=winner_col, font_size=78, anchor="center")
        draw_text(surface, "WINS",
                  (SCREEN_W // 2, 258),
                  color=winner_col, font_size=60, anchor="center")

        draw_text(surface, "Victory on the battlefield!",
                  (SCREEN_W // 2, 350),
                  color=LIGHT_GRAY, font_size=FONT_MEDIUM, anchor="center")

        # Divider
        pygame.draw.line(surface, HUD_BORDER,
                         (SCREEN_W // 2 - 200, 400), (SCREEN_W // 2 + 200, 400), 1)

        self._btn_play_again.draw(surface)
        self._btn_menu.draw(surface)
