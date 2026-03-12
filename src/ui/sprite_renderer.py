"""
sprite_renderer.py – PNG sprite-sheet renderer for mechs.

Drop-in alongside cairo_renderer.py.  Falls back gracefully when a
sprite sheet is not found, allowing per-mech independent adoption.

Sheet config per mech:
  (filename, total_frames, frame_w, frame_h, cols_per_row)

Team detection from team_color tuple:
  blue  (80,140,255) → team 1   green sprite
  red   (255,80,80)  → team 2   red sprite
  green (80,220,100) → team 3   green sprite (reuse)
"""

import pathlib
from typing import Dict, List, Optional, Tuple

import pygame

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE        = pathlib.Path(__file__).parent          # src/ui/
_SPRITE_DIR  = _HERE.parent.parent / "MechSprites"   # project root / MechSprites

# ---------------------------------------------------------------------------
# Sheet registry
# name → { team_key → (filename, total_frames, fw, fh, cols) }
# team_key: 1=team1(blue), 2=team2(red), 3=team3(green)
# ---------------------------------------------------------------------------
_SHEETS: Dict[str, Dict[int, Tuple]] = {
    "raptor": {
        1: ("Mech4-b7d7.png",   7, 70, 70, 7),   # 490×70,  7 frames, 1 row
        2: ("Mech4 2-b851.png", 9, 70, 70, 8),   # 560×140, 9 frames, 8+1 rows
        3: ("Mech4-b7d7.png",   7, 70, 70, 7),   # reuse green for team 3
    },
}

# ---------------------------------------------------------------------------
# Caches
# _raw_cache  : (mech_id, team) → List[pygame.Surface]  70×70 originals
# _scaled_cache: (mech_id, team, w, h) → List[pygame.Surface]  scaled
# ---------------------------------------------------------------------------
_raw_cache:    Dict[Tuple, List[pygame.Surface]] = {}
_scaled_cache: Dict[Tuple, List[pygame.Surface]] = {}


def _team_from_color(team_color: Tuple) -> int:
    r, g, b = int(team_color[0]), int(team_color[1]), int(team_color[2])
    if r > 200 and b < 150:
        return 2   # red  → team 2
    elif b > 150 and r < 150:
        return 1   # blue → team 1
    else:
        return 3   # green (or unknown) → team 3


def _load_raw_frames(mech_id: str, team: int) -> Optional[List[pygame.Surface]]:
    """Load & slice a sprite sheet into 70×70 RGBA surfaces. Cached."""
    key = (mech_id, team)
    if key in _raw_cache:
        return _raw_cache[key]

    cfg = _SHEETS.get(mech_id, {}).get(team)
    if cfg is None:
        return None

    fname, total, fw, fh, cols = cfg
    path = _SPRITE_DIR / fname
    if not path.exists():
        return None

    try:
        sheet = pygame.image.load(str(path)).convert_alpha()
    except Exception:
        return None

    frames: List[pygame.Surface] = []
    for i in range(total):
        col = i % cols
        row = i // cols
        rect = pygame.Rect(col * fw, row * fh, fw, fh)
        frames.append(sheet.subsurface(rect).copy())

    _raw_cache[key] = frames
    return frames


def _get_scaled_frames(mech_id: str, team: int,
                       w: int, h: int) -> Optional[List[pygame.Surface]]:
    """Return frames scaled to (w, h), using nearest-neighbour for pixel art."""
    key = (mech_id, team, w, h)
    if key in _scaled_cache:
        return _scaled_cache[key]

    raw = _load_raw_frames(mech_id, team)
    if raw is None:
        return None

    scaled = [pygame.transform.scale(f, (w, h)) for f in raw]
    _scaled_cache[key] = scaled
    return scaled


def draw_mech_sprite(surf: pygame.Surface, r: pygame.Rect,
                     mech_id: str,
                     color: Tuple, team_color: Tuple,
                     walk_t: float = 0.0,
                     fire_t: float = -1.0) -> bool:
    """
    Blit the mech's sprite frame onto surf at rect r.

    Returns True  if a sprite was drawn.
    Returns False if no sprite is registered for this mech (caller should fallback).

    walk_t : 0.0-1.0 walk cycle phase  → selects animation frame
    fire_t : -1.0 = idle; 0.0-1.0 = firing  (no separate attack sheet yet;
             uses a held mid-stride frame during fire)
    """
    team = _team_from_color(team_color)
    frames = _get_scaled_frames(mech_id, team, r.w, r.h)
    if frames is None:
        return False

    n = len(frames)

    if fire_t >= 0.0:
        # Hold a "aimed" frame while firing (second-to-last frame looks posed)
        frame_idx = max(0, n - 2)
    else:
        frame_idx = int(walk_t * n) % n

    surf.blit(frames[frame_idx], (r.x, r.y))
    return True


def has_sprite(mech_id: str) -> bool:
    """Return True if a sprite sheet is registered for this mech."""
    return mech_id in _SHEETS


def clear_sprite_cache() -> None:
    """Flush all cached surfaces (call after display resize)."""
    _raw_cache.clear()
    _scaled_cache.clear()
