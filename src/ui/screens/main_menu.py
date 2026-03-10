"""Main menu screen."""
import pygame
from src.ui.constants import *
from src.ui.components import Button, draw_text


class MainMenuScreen:
    def __init__(self, manager):
        self.manager = manager
        self._build_buttons()

    def _build_buttons(self):
        cx = SCREEN_W // 2
        self.btn_start = Button((cx - 130, 330, 260, 52), "START GAME",
                                color_normal=BTN_SUCCESS, color_hover=BTN_SUCCESS_H,
                                font_size=FONT_LARGE)
        self.btn_wiki  = Button((cx - 130, 398, 260, 52), "CODEX / WIKI",
                                color_normal=BTN_ACTIVE, color_hover=BTN_HOVER,
                                font_size=FONT_LARGE)
        self.btn_quit  = Button((cx - 130, 466, 260, 52), "QUIT",
                                color_normal=BTN_DANGER, color_hover=BTN_DANGER_H,
                                font_size=FONT_LARGE)

    def on_enter(self, **_):
        self._build_buttons()

    def handle_event(self, event: pygame.event.Event):
        if self.btn_start.handle_event(event):
            self.manager.switch_to("name_entry")
        if self.btn_wiki.handle_event(event):
            self.manager.switch_to("wiki")
        if self.btn_quit.handle_event(event):
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    def update(self, dt: float):
        pass

    def draw(self, surface: pygame.Surface):
        surface.fill(DARK_GRAY)

        # Decorative top stripe
        pygame.draw.rect(surface, (30, 36, 50), (0, 0, SCREEN_W, 260))

        # Title
        draw_text(surface, "MECH BATTLE", (SCREEN_W // 2, 100),
                  color=(220, 80, 50), font_size=88, anchor="center")
        draw_text(surface, "Turn-Based Tactical Combat", (SCREEN_W // 2, 175),
                  color=HUD_DIM, font_size=FONT_LARGE, anchor="center")
        draw_text(surface, "2 or 3 Players  •  Hot-Seat", (SCREEN_W // 2, 215),
                  color=HUD_DIM, font_size=FONT_MEDIUM, anchor="center")

        # Divider
        pygame.draw.line(surface, HUD_BORDER,
                         (SCREEN_W // 2 - 200, 270), (SCREEN_W // 2 + 200, 270), 1)

        draw_text(surface, "Select your mechs and fight!", (SCREEN_W // 2, 295),
                  color=LIGHT_GRAY, font_size=FONT_MEDIUM, anchor="center")

        self.btn_start.draw(surface)
        self.btn_wiki.draw(surface)
        self.btn_quit.draw(surface)

        draw_text(surface, "v0.2", (SCREEN_W - 10, SCREEN_H - 18),
                  color=GRAY, font_size=FONT_TINY, anchor="bottomright")
