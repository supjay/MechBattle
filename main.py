"""Mech Battle – entry point. Run from the project root: python main.py"""
import sys
import pygame

from src.ui.constants import SCREEN_W, SCREEN_H, FPS
from src.ui.screen_manager import ScreenManager


def main():
    pygame.init()
    pygame.display.set_caption("Mech Battle")
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    clock = pygame.time.Clock()

    manager = ScreenManager(screen)

    while True:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()
            manager.handle_event(event)

        manager.update(dt)
        manager.draw()
        pygame.display.flip()


if __name__ == "__main__":
    main()
