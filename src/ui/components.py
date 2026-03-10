"""Reusable Pygame UI widgets."""
import pygame
from typing import Callable, Optional, Tuple
from src.ui.constants import *


class Button:
    def __init__(
        self,
        rect: Tuple[int, int, int, int],
        text: str,
        enabled: bool = True,
        color_normal=BTN_NORMAL,
        color_hover=BTN_HOVER,
        color_disabled=BTN_DISABLED,
        font_size: int = FONT_MEDIUM,
    ):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.enabled = enabled
        self.hovered = False
        self._cn = color_normal
        self._ch = color_hover
        self._cd = color_disabled

        self._font = pygame.font.Font(None, font_size)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Return True if the button was clicked."""
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.enabled and self.rect.collidepoint(event.pos):
                return True
        return False

    def draw(self, surface: pygame.Surface):
        if not self.enabled:
            bg = self._cd
            txt_col = BTN_DIM_TEXT
        elif self.hovered:
            bg = self._ch
            txt_col = WHITE
        else:
            bg = self._cn
            txt_col = BTN_TEXT

        pygame.draw.rect(surface, bg, self.rect, border_radius=6)
        pygame.draw.rect(surface, HUD_BORDER, self.rect, 1, border_radius=6)

        txt_surf = self._font.render(self.text, True, txt_col)
        txt_rect = txt_surf.get_rect(center=self.rect.center)
        surface.blit(txt_surf, txt_rect)


class HpBar:
    def __init__(self, rect: Tuple[int, int, int, int]):
        self.rect = pygame.Rect(rect)

    def draw(self, surface: pygame.Surface, hp: int, max_hp: int):
        pygame.draw.rect(surface, HP_BG, self.rect, border_radius=3)
        if max_hp > 0:
            ratio = max(0.0, hp / max_hp)
            if ratio > 0.6:
                color = HP_HIGH
            elif ratio > 0.3:
                color = HP_MED
            else:
                color = HP_LOW
            filled = pygame.Rect(
                self.rect.x, self.rect.y,
                int(self.rect.width * ratio), self.rect.height
            )
            pygame.draw.rect(surface, color, filled, border_radius=3)
        pygame.draw.rect(surface, GRAY, self.rect, 1, border_radius=3)


class FloatingText:
    """A damage / miss number that floats upward and fades out."""

    def __init__(self, text: str, world_pos: Tuple[float, float],
                 color: Tuple[int, int, int], font_size: int = 22,
                 duration: float = 1.4):
        self.text = text
        self.x = float(world_pos[0])
        self.y = float(world_pos[1])
        self.color = color
        self.duration = duration
        self.elapsed = 0.0
        self._font = pygame.font.Font(None, font_size)

    def update(self, dt: float) -> bool:
        """Return True while still alive."""
        self.elapsed += dt
        self.y -= 35 * dt
        return self.elapsed < self.duration

    def draw(self, surface: pygame.Surface):
        alpha = int(255 * max(0.0, 1.0 - self.elapsed / self.duration))
        txt_surf = self._font.render(self.text, True, self.color)
        txt_surf.set_alpha(alpha)
        surface.blit(txt_surf, (int(self.x), int(self.y)))


def draw_text(surface: pygame.Surface, text: str, pos: Tuple[int, int],
              color=HUD_TEXT, font_size: int = FONT_MEDIUM,
              anchor: str = "topleft") -> pygame.Rect:
    """One-shot text render helper. Returns the blit rect."""
    font = pygame.font.Font(None, font_size)
    surf = font.render(text, True, color)
    rect = surf.get_rect(**{anchor: pos})
    surface.blit(surf, rect)
    return rect


def draw_panel(surface: pygame.Surface, rect: Tuple[int, int, int, int],
               border_radius: int = 8):
    """Draw a standard HUD panel background."""
    r = pygame.Rect(rect)
    pygame.draw.rect(surface, HUD_PANEL, r, border_radius=border_radius)
    pygame.draw.rect(surface, HUD_BORDER, r, 1, border_radius=border_radius)
