"""Map selection screen."""
import pygame
from typing import Dict, Any, List, Optional

from src.ui.constants import *
from src.ui.components import Button, draw_text, draw_panel

TILE_COLOURS = {
    0: COL_OPEN,
    1: COL_COVER,
    2: COL_BLOCKED,
}

THUMB_W, THUMB_H = 300, 200
THUMB_PAD = 40


class MapSelectScreen:
    def __init__(self, manager):
        self.manager = manager
        self.maps: List[Dict[str, Any]] = []
        self.selected_idx: int = 0
        self.hovered_idx: Optional[int] = None
        self._thumb_rects: List[pygame.Rect] = []
        self._thumb_surfs: List[pygame.Surface] = []
        self._btn_start: Optional[Button] = None
        self._btn_back:  Optional[Button] = None

    def on_enter(self, **_):
        self.maps = self.manager.map_list
        self.selected_idx = 0
        self._build_thumbnails()
        self._btn_start = Button((SCREEN_W // 2 - 120, SCREEN_H - 70, 240, 50),
                                 "START BATTLE",
                                 color_normal=BTN_SUCCESS,
                                 color_hover=BTN_SUCCESS_H,
                                 font_size=FONT_LARGE)
        self._btn_back = Button((14, SCREEN_H - 70, 130, 50), "← Back",
                                font_size=FONT_MEDIUM)

    def _build_thumbnails(self):
        n = len(self.maps)
        total_w = n * THUMB_W + (n - 1) * THUMB_PAD
        start_x = (SCREEN_W - total_w) // 2
        top_y = 180

        self._thumb_rects = []
        self._thumb_surfs = []

        for i, m in enumerate(self.maps):
            rx = start_x + i * (THUMB_W + THUMB_PAD)
            self._thumb_rects.append(pygame.Rect(rx, top_y, THUMB_W, THUMB_H))
            self._thumb_surfs.append(self._render_map_thumb(m, THUMB_W, THUMB_H))

    @staticmethod
    def _render_map_thumb(map_data: Dict, w: int, h: int) -> pygame.Surface:
        surf = pygame.Surface((w, h))
        surf.fill(COL_BLOCKED)
        grid = map_data["grid"]
        rows = len(grid)
        cols = len(grid[0]) if rows else 1
        tw = max(1, w // cols)
        th = max(1, h // rows)
        for y, row in enumerate(grid):
            for x, cell in enumerate(row):
                color = TILE_COLOURS.get(cell, COL_OPEN)
                pygame.draw.rect(surf, color, (x * tw, y * th, tw - 1, th - 1))
        # Spawn markers
        for sx, sy in map_data.get("spawn_team1", []):
            cx = sx * tw + tw // 2
            cy = sy * th + th // 2
            pygame.draw.circle(surf, TEAM1_BORDER, (cx, cy), max(3, tw // 3))
        for sx, sy in map_data.get("spawn_team2", []):
            cx = sx * tw + tw // 2
            cy = sy * th + th // 2
            pygame.draw.circle(surf, TEAM2_BORDER, (cx, cy), max(3, tw // 3))
        return surf

    def handle_event(self, event: pygame.event.Event):
        if event.type == pygame.MOUSEMOTION:
            self.hovered_idx = None
            for i, r in enumerate(self._thumb_rects):
                if r.collidepoint(event.pos):
                    self.hovered_idx = i

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, r in enumerate(self._thumb_rects):
                if r.collidepoint(event.pos):
                    self.selected_idx = i

        if self._btn_start and self._btn_start.handle_event(event):
            self.manager.selected_map_idx = self.selected_idx
            self.manager.switch_to("battle")

        if self._btn_back and self._btn_back.handle_event(event):
            self.manager.switch_to("roster")

    def update(self, dt: float):
        pass

    def draw(self, surface: pygame.Surface):
        surface.fill(DARK_GRAY)
        pygame.draw.rect(surface, (22, 28, 38), (0, 0, SCREEN_W, 160))
        draw_text(surface, "SELECT BATTLEFIELD", (SCREEN_W // 2, 36),
                  color=HUD_ACCENT, font_size=FONT_LARGE, anchor="center")
        draw_text(surface, "Choose the map for your battle", (SCREEN_W // 2, 80),
                  color=HUD_DIM, font_size=FONT_MEDIUM, anchor="center")

        for i, (rect, surf, m) in enumerate(
                zip(self._thumb_rects, self._thumb_surfs, self.maps)):
            hov = self.hovered_idx == i
            sel = self.selected_idx == i
            border_col = HUD_ACCENT if sel else (HUD_BORDER if not hov else LIGHT_GRAY)
            border_w   = 3 if sel else 1

            surface.blit(surf, rect)
            pygame.draw.rect(surface, border_col, rect, border_w)

            # Map name
            draw_text(surface, m["name"],
                      (rect.centerx, rect.bottom + 14),
                      color=WHITE if sel else LIGHT_GRAY,
                      font_size=FONT_MEDIUM, anchor="center")
            draw_text(surface, m["description"],
                      (rect.centerx, rect.bottom + 36),
                      color=HUD_DIM, font_size=FONT_SMALL, anchor="center")

            if sel:
                draw_text(surface, "✔ SELECTED",
                          (rect.centerx, rect.bottom + 56),
                          color=BTN_SUCCESS, font_size=FONT_SMALL, anchor="center")

        self._btn_start.draw(surface)
        self._btn_back.draw(surface)
