"""WH40K-inspired procedural mech art renderer – animated edition.

Each mech is drawn into a temporary SRCALPHA surface facing RIGHT,
then flipped horizontally for team 2 before being blitted to the screen.

Animation parameters (all optional):
  walk_t  – 0.0-1.0 walk-cycle phase.  0 = neutral, drives leg swing.
  fire_t  – -1.0   = not firing.
              0.0-1.0 = fire-cycle progress: extend (0→0.4), hold (0.4→0.55),
                        recoil / return (0.55→1.0).

Archetypes:
  titan    → Space Marine Dreadnought  (boxy, squat, heavy)
  raptor   → Imperial Guard Sentinel   (tall, chicken-walker legs)
  colossus → Imperial Knight           (massive, tracked, siege weapons)
  phantom  → Tau XV-8 Battlesuit       (sleek, angular, high-tech)
  vanguard → Blood Angels Dreadnought  (classic, plasma arm, T-visor)
"""
import math
import random as _rnd
import pygame
from typing import Tuple

_STABLE_RNG = _rnd.Random(0xC0105505)

# ---------------------------------------------------------------------------
# Shared colour palette
# ---------------------------------------------------------------------------
METAL_LIGHT  = (162, 157, 148)
METAL_MID    = (98,  94,  88)
METAL_DARK   = (48,  46,  42)
METAL_SHEEN  = (200, 196, 188)
GLOW_RED     = (255, 60,  25)
GLOW_BLUE    = (70,  195, 255)
GLOW_ORANGE  = (255, 145, 30)
EXHAUST      = (220, 145, 50)
WHITE        = (255, 255, 255)
DARK_PLATE   = (26,  24,  22)


def _dk(c: Tuple, f: float = 0.45) -> Tuple:
    return tuple(max(0, int(v * (1 - f))) for v in c)


def _lt(c: Tuple, f: float = 0.35) -> Tuple:
    return tuple(min(255, int(v + (255 - v) * f)) for v in c)


def _fr(rect: pygame.Rect, x0: float, y0: float, x1: float, y1: float) -> pygame.Rect:
    x = rect.x + int(x0 * rect.w)
    y = rect.y + int(y0 * rect.h)
    w = max(1, int((x1 - x0) * rect.w))
    h = max(1, int((y1 - y0) * rect.h))
    return pygame.Rect(x, y, w, h)


def _panel(surf, rect, color, br=2, border=None):
    pygame.draw.rect(surf, color, rect, border_radius=br)
    if rect.w > 5 and rect.h > 5:
        lt = _lt(color, 0.30)
        dk = _dk(color, 0.30)
        pygame.draw.line(surf, lt, (rect.x+1, rect.y+1), (rect.right-2, rect.y+1))
        pygame.draw.line(surf, lt, (rect.x+1, rect.y+2), (rect.x+1, rect.bottom-2))
        pygame.draw.line(surf, dk, (rect.x+2, rect.bottom-2), (rect.right-2, rect.bottom-2))
        pygame.draw.line(surf, dk, (rect.right-2, rect.y+2), (rect.right-2, rect.bottom-2))
    if border:
        pygame.draw.rect(surf, border, rect, 1, border_radius=br)


def _glow(surf, cx, cy, radius, color, alpha_max=130):
    for i in range(3, 0, -1):
        rad = max(1, radius * i // 3)
        a   = alpha_max * i * i // 9
        gs  = pygame.Surface((rad*2+1, rad*2+1), pygame.SRCALPHA)
        pygame.draw.circle(gs, (*color[:3], a), (rad, rad), rad)
        surf.blit(gs, (cx - rad, cy - rad))


def _rivet(surf, x, y):
    pygame.draw.circle(surf, METAL_DARK,  (x, y), 2)
    pygame.draw.circle(surf, METAL_MID,   (x, y), 2, 1)
    pygame.draw.circle(surf, METAL_SHEEN, (x-1, y-1), 1)


def _panel_line(surf, color, p1, p2):
    dk = _dk(color, 0.5)
    lt = _lt(color, 0.18)
    pygame.draw.line(surf, dk, p1, p2)
    dx, dy = p2[0]-p1[0], p2[1]-p1[1]
    if abs(dy) >= abs(dx):
        pygame.draw.line(surf, lt, (p1[0]+1, p1[1]), (p2[0]+1, p2[1]))
    else:
        pygame.draw.line(surf, lt, (p1[0], p1[1]+1), (p2[0], p2[1]+1))

def _shade(color: tuple, f: float) -> tuple:
    """Multiply each RGB channel by f, clamped to 0-255."""
    return tuple(min(255, max(0, int(c * f))) for c in color[:3])


def _blend(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linear blend between two RGB colours: t=0 -> c1, t=1 -> c2."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1[:3], c2[:3]))


def _lit_rect(surf, rect, color, br=0, border=None):
    """8-zone vertical gradient rect: bright top -> dark bottom, left highlight, right/bottom shadow."""
    FACTORS = (1.55, 1.38, 1.20, 1.04, 0.88, 0.70, 0.54, 0.38)
    for i, f in enumerate(FACTORS):
        y0 = rect.y + i * rect.h // 8
        y1 = rect.y + (i + 1) * rect.h // 8 + 1
        pygame.draw.rect(surf, _shade(color, f), (rect.x, y0, rect.w, y1 - y0))
    for xi in range(min(2, rect.w)):
        pygame.draw.line(surf, _shade(color, 1.85 - xi * 0.28),
                         (rect.x + xi, rect.y), (rect.x + xi, rect.bottom - 1))
    for xi in range(min(2, rect.w)):
        pygame.draw.line(surf, _shade(color, 0.18 + xi * 0.12),
                         (rect.right - 1 - xi, rect.y), (rect.right - 1 - xi, rect.bottom - 1))
    pygame.draw.line(surf, _shade(color, 0.18),
                     (rect.x, rect.bottom - 1), (rect.right - 1, rect.bottom - 1))
    out = border if border else _shade(color, 0.22)
    pygame.draw.rect(surf, out, rect, 1, border_radius=br)


def _lit_poly(surf, pts, color, border=None):
    """Polygon with 5-band clip gradient + edge shading by outward normal."""
    ipts = [(int(p[0]), int(p[1])) for p in pts]
    min_y = min(p[1] for p in ipts)
    max_y = max(p[1] for p in ipts)
    ht = max(1, max_y - min_y)
    pygame.draw.polygon(surf, _shade(color, 0.30), ipts)
    old_clip = surf.get_clip()
    sw = surf.get_width()
    for t0, t1, f in (
        (0.00, 0.22, 1.55),
        (0.22, 0.47, 1.16),
        (0.47, 0.68, 0.82),
        (0.68, 0.85, 0.54),
        (0.85, 1.00, 0.32),
    ):
        y0 = min_y + int(t0 * ht)
        y1 = min_y + int(t1 * ht) + 2
        surf.set_clip(pygame.Rect(0, y0, sw, max(1, y1 - y0)))
        pygame.draw.polygon(surf, _shade(color, f), ipts)
    surf.set_clip(old_clip)
    for i in range(len(ipts)):
        p1, p2 = ipts[i], ipts[(i + 1) % len(ipts)]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = math.sqrt(dx * dx + dy * dy)
        if L < 1:
            continue
        ny = dx / L
        if ny < -0.20:
            pygame.draw.line(surf, _shade(color, 1.90), p1, p2, 2)
        elif ny > 0.30:
            pygame.draw.line(surf, _shade(color, 0.18), p1, p2, 2)
    if border:
        pygame.draw.polygon(surf, border, ipts, 1)


def _joint_ball(surf, cx, cy, radius, color):
    """Metallic sphere: dark base + lit upper + shadowed lower + specular glint."""
    r = max(1, radius)
    old_clip = surf.get_clip()
    pygame.draw.circle(surf, _shade(color, 0.15), (cx, cy), r)
    surf.set_clip(pygame.Rect(cx - r - 1, cy - r - 1, (r + 1) * 2 + 2, r + 2))
    pygame.draw.circle(surf, _shade(color, 1.28), (cx, cy), max(1, r - 1))
    surf.set_clip(old_clip)
    surf.set_clip(pygame.Rect(cx - r - 1, cy, (r + 1) * 2 + 2, r + 2))
    pygame.draw.circle(surf, _shade(color, 0.38), (cx, cy), max(1, r - 1))
    surf.set_clip(old_clip)
    pygame.draw.circle(surf, _shade(color, 2.20),
                       (cx - max(1, r // 3), cy - max(1, r // 3)), max(1, r // 3))
    pygame.draw.circle(surf, _shade(color, 0.10), (cx, cy), r, 1)


# ---------------------------------------------------------------------------
# Animation helpers
# ---------------------------------------------------------------------------

def _leg_swing(walk_t: float, side: int = 1, amplitude: int = 5) -> int:
    """Vertical leg-swing offset.  side=+1 left leg, -1 right leg."""
    return int(math.sin(walk_t * math.pi * 2) * amplitude * side)


def _fire_arm_offset(fire_t: float) -> float:
    """Fraction 0→1 of how far the arm extends during the fire cycle."""
    if fire_t < 0:
        return 0.0
    if fire_t < 0.40:
        return math.sin(fire_t / 0.40 * math.pi * 0.5)
    elif fire_t < 0.55:
        return 1.0
    else:
        return 1.0 - math.sin((fire_t - 0.55) / 0.45 * math.pi * 0.5)


def _knee_dip(walk_t: float) -> int:
    """Body dips 2 px at each foot-plant (walk_t ≈ 0 and 0.5)."""
    return int(abs(math.cos(walk_t * math.pi * 2)) * 2)


def _ankle_off(walk_t: float, side: int = 1, amplitude: int = 4) -> int:
    """Ankle flex – opposite phase to knee for a push-off feel."""
    return int(math.sin(walk_t * math.pi * 2 + math.pi) * amplitude * side)


def _shoulder_rise(fire_t: float, px: int = 4) -> int:
    """Firing shoulder rises during aim/fire cycle (pixels upward)."""
    return int(_fire_arm_offset(fire_t) * px)


def _torso_lean(fire_t: float, px: int = 2) -> int:
    """Torso leans toward weapon during fire (pixels toward weapon side)."""
    return int(_fire_arm_offset(fire_t) * px)


# ---------------------------------------------------------------------------
# TITAN  –  Space Marine Dreadnought
# ---------------------------------------------------------------------------

def draw_titan(surf, r, color, team_color, walk_t=0.0, fire_t=-1.0):
    dk = _dk(color)

    track_shift = int(walk_t * 10) % 8
    body_bob    = int(math.sin(walk_t * math.pi * 2) * 1.5) + _knee_dip(walk_t)
    lean_x      = _torso_lean(fire_t, 2)   # body leans left toward weapon

    # == Track-block legs ==
    for lx0, lx1 in [(0.08, 0.43), (0.57, 0.92)]:
        leg = _fr(r, lx0, 0.66, lx1, 0.97)
        _panel(surf, leg, dk, br=2, border=METAL_MID)
        for i in range(6):
            lx = (leg.x + track_shift + i * leg.w // 5) % (leg.right - leg.x) + leg.x
            if leg.x <= lx <= leg.right:
                pygame.draw.line(surf, METAL_DARK, (lx, leg.y+2), (lx, leg.bottom-3))
        for wxi in [leg.x+4, leg.right-5]:
            pygame.draw.circle(surf, METAL_MID,   (wxi, leg.centery), 5)
            pygame.draw.circle(surf, METAL_DARK,  (wxi, leg.centery), 3)
            pygame.draw.circle(surf, METAL_SHEEN, (wxi-1, leg.centery-1), 1)
        pygame.draw.rect(surf, METAL_MID, (leg.x+1, leg.bottom-4, leg.w-2, 3))

    # == Main body (with walk bob + fire lean) ==
    body = pygame.Rect(
        r.x + int(0.16 * r.w) - lean_x,
        r.y + int(0.22 * r.h) + body_bob,
        int(0.68 * r.w),
        int(0.46 * r.h)
    )
    _panel(surf, body, color, br=3, border=team_color)
    _panel_line(surf, color, (body.centerx, body.y+4), (body.centerx, body.bottom-4))
    cx, cy2 = body.centerx, body.centery + 2
    pygame.draw.line(surf, team_color, (cx-9, cy2), (cx+9, cy2), 2)
    pygame.draw.line(surf, team_color, (cx, cy2-9), (cx, cy2+9), 2)
    for dx2, dy2 in [(-9,-3),(9,-3),(-9,3),(9,3)]:
        pygame.draw.line(surf, team_color, (cx+dx2, cy2), (cx+dx2+(-2 if dx2<0 else 2), cy2+dy2), 1)
    pygame.draw.circle(surf, _lt(team_color, 0.5), (cx, cy2), 4)
    pygame.draw.circle(surf, WHITE, (cx, cy2), 2)
    for rx2, ry2 in [(body.x+4,body.y+4),(body.right-5,body.y+4),
                     (body.x+4,body.bottom-5),(body.right-5,body.bottom-5)]:
        _rivet(surf, rx2, ry2)

    # == Wide shoulder plates ==
    for sx0, sx1 in [(0.02, 0.19), (0.81, 0.98)]:
        sp = _fr(r, sx0, 0.22, sx1, 0.39)
        sp = sp.move(-lean_x, body_bob)
        _panel(surf, sp, dk, br=3, border=team_color)
        _rivet(surf, sp.centerx, sp.centery)

    # == LEFT arm – Power Fist (shoulder rises + extends leftward) ==
    fire_off = int(_fire_arm_offset(fire_t) * int(r.w * 0.06))
    sh_rise  = _shoulder_rise(fire_t, 5)
    fist = pygame.Rect(
        r.x - fire_off - lean_x,
        r.y + int(0.29 * r.h) + body_bob - sh_rise,
        int(0.16 * r.w),
        int(0.36 * r.h)
    )
    _panel(surf, fist, METAL_DARK, br=2, border=METAL_MID)
    pygame.draw.line(surf, METAL_MID, (fist.centerx, fist.y+3), (fist.centerx, fist.centery), 2)
    pygame.draw.circle(surf, METAL_MID, (fist.centerx, fist.centery), 3)
    kbase = fist.bottom - int(fist.h * 0.42)
    for ki in range(3):
        ky = kbase + ki * int(fist.h * 0.12)
        kbar = pygame.Rect(fist.x+2, ky, fist.w-4, 3)
        _panel(surf, kbar, METAL_LIGHT, br=1)
    claw_extra = int(fire_off * 0.4)
    for ci in range(3):
        claw_x = fist.x + 3 + ci * int((fist.w-6)//2)
        pygame.draw.line(surf, METAL_MID,
                         (claw_x, fist.bottom), (claw_x-1, fist.bottom+5+claw_extra), 2)

    # == RIGHT arm – Missile Pod (counter-drops as left fires) ==
    sh_drop  = _shoulder_rise(fire_t, 2)   # counter-balance drop
    pod_fire = int(_fire_arm_offset(fire_t) * int(r.w * 0.04))
    pod = pygame.Rect(
        r.x + int(0.84 * r.w) + pod_fire - lean_x,
        r.y + int(0.28 * r.h) + body_bob + sh_drop,
        int(0.15 * r.w),
        int(0.36 * r.h)
    )
    _panel(surf, pod, METAL_DARK, br=2, border=team_color)
    pygame.draw.rect(surf, METAL_MID, (pod.x+1, pod.y+1, pod.w-2, 5))
    pygame.draw.circle(surf, GLOW_RED, (pod.centerx, pod.y+3), 2)
    tube_h = max(3, (pod.h-14)//3)
    for ti in range(3):
        ty = pod.y + 9 + ti*(tube_h+2)
        pygame.draw.rect(surf, DARK_PLATE, (pod.x+2, ty, pod.w-4, tube_h))
        pygame.draw.circle(surf, (180, 50, 50), (pod.x+5, ty+tube_h//2), 2)
        if fire_t > 0 and ti == 1:
            _glow(surf, pod.x+4, ty+tube_h//2, 4, GLOW_ORANGE, 120)
        pygame.draw.rect(surf, METAL_MID, (pod.x+2, ty, pod.w-4, tube_h), 1)

    # == Head (tracks toward weapon side during fire) ==
    head_lean = _torso_lean(fire_t, 3)
    head = _fr(r, 0.28, 0.03, 0.72, 0.23)
    head = head.move(-head_lean, body_bob)
    _panel(surf, head, dk, br=5, border=team_color)
    eye = pygame.Rect(head.x+4, head.centery-3, head.w-8, 6)
    pygame.draw.rect(surf, GLOW_RED, eye, border_radius=2)
    _glow(surf, eye.centerx, eye.centery, 5, GLOW_RED, 90)
    pygame.draw.rect(surf, (255,200,180), (eye.x+2, eye.y+1, 6, 2))
    for ax in [head.centerx-5, head.centerx, head.centerx+5]:
        pygame.draw.line(surf, METAL_MID, (ax, head.y), (ax, head.y-5), 1)
        pygame.draw.circle(surf, METAL_LIGHT, (ax, head.y-5), 1)


# ---------------------------------------------------------------------------
# RAPTOR  –  Imperial Guard Sentinel (chicken-walker)
# ---------------------------------------------------------------------------

def draw_raptor(surf, r, color, team_color, walk_t=0.0, fire_t=-1.0):
    dk = _dk(color)

    l_swing = _leg_swing(walk_t,  1, 5)
    r_swing = _leg_swing(walk_t, -1, 5)
    l_ankle = _ankle_off(walk_t,  1, 3)
    r_ankle = _ankle_off(walk_t, -1, 3)

    # == Legs – reverse-knee walker with 3-segment ankle joints ==
    for hip_fx, knee_fx, ankle_fx, foot_fx, swing, ankle_sw, side in [
        (0.33, 0.17, 0.22, 0.27, l_swing, l_ankle, -1),   # left
        (0.67, 0.83, 0.78, 0.73, r_swing, r_ankle,  1),   # right
    ]:
        hip   = (r.x + int(r.w * hip_fx),   r.y + int(r.h * 0.50))
        knee  = (r.x + int(r.w * knee_fx),  r.y + int(r.h * 0.71) + swing)
        ankle = (r.x + int(r.w * ankle_fx), r.y + int(r.h * 0.83) + ankle_sw)
        foot  = (r.x + int(r.w * foot_fx),  r.y + int(r.h * 0.93))

        # Upper leg (hip → knee)
        pygame.draw.line(surf, METAL_MID,   hip, knee, 6)
        pygame.draw.line(surf, METAL_SHEEN, hip, knee, 1)
        # Hydraulic piston alongside
        po = 3 * side
        pygame.draw.line(surf, METAL_DARK, (hip[0]+po, hip[1]+4), (knee[0]+po, knee[1]-4), 2)
        # Shin (knee → ankle)
        pygame.draw.line(surf, METAL_MID, knee, ankle, 5)
        # Foot segment (ankle → foot)
        pygame.draw.line(surf, METAL_DARK, ankle, foot, 4)
        # Knee joint
        pygame.draw.circle(surf, METAL_DARK,  knee, 6)
        pygame.draw.circle(surf, METAL_MID,   knee, 6, 1)
        pygame.draw.circle(surf, METAL_LIGHT, knee, 2)
        # Ankle joint
        pygame.draw.circle(surf, METAL_DARK, ankle, 4)
        pygame.draw.circle(surf, METAL_MID,  ankle, 4, 1)
        pygame.draw.circle(surf, METAL_LIGHT, (ankle[0]-1, ankle[1]-1), 1)
        # Foot pivot
        pygame.draw.circle(surf, METAL_DARK, foot, 4)
        foot_rect = pygame.Rect(foot[0]-9, foot[1]-2, 18, 5)
        _panel(surf, foot_rect, METAL_DARK, br=1, border=METAL_MID)
        for sx in [-5, 5]:
            pygame.draw.line(surf, METAL_MID,
                             (foot[0]+sx, foot[1]+3), (foot[0]+sx+sx//2, foot[1]+7), 2)

    # == Cockpit body ==
    body = _fr(r, 0.27, 0.18, 0.73, 0.53)
    _panel(surf, body, color, br=4, border=team_color)
    canopy = _fr(r, 0.29, 0.18, 0.71, 0.34)
    _panel(surf, canopy, _lt(color, 0.20), br=4)
    pygame.draw.line(surf, _lt(color, 0.5), (canopy.x+4, canopy.y+3), (canopy.centerx-2, canopy.bottom-4), 2)
    for vi in range(2):
        vy = body.y + int(body.h*(0.58+vi*0.22))
        pygame.draw.line(surf, dk, (body.x+5, vy), (body.right-5, vy))
    _panel_line(surf, color, (body.x+int(body.w*0.3), body.bottom), (r.x+int(r.w*0.33), r.y+int(r.h*0.50)))
    _panel_line(surf, color, (body.x+int(body.w*0.7), body.bottom), (r.x+int(r.w*0.67), r.y+int(r.h*0.50)))

    # == Left arm – Laser Cannon (shoulder rises + tilts forward when firing) ==
    fire_tilt = int(_fire_arm_offset(fire_t) * 6)
    sh_rise   = _shoulder_rise(fire_t, 3)
    arm_y     = r.y + int(r.h * 0.27) + fire_tilt - sh_rise
    a_base    = (body.x-2, arm_y)
    a_tip     = (r.x+2,    arm_y)
    pygame.draw.line(surf, METAL_DARK,  a_base, a_tip, 6)
    pygame.draw.line(surf, METAL_SHEEN, a_base, a_tip, 1)
    for fi in range(3):
        fx = a_tip[0] + int((a_base[0]-a_tip[0])*(0.25+fi*0.18))
        pygame.draw.line(surf, METAL_MID, (fx, arm_y-4), (fx, arm_y+4), 1)
    glow_a = 130 if fire_t >= 0 else 80
    _glow(surf, a_tip[0]+2, a_tip[1], 5 if fire_t >= 0 else 3, GLOW_RED, glow_a)
    pygame.draw.circle(surf, DARK_PLATE, (a_tip[0]+2, a_tip[1]), 3)
    pygame.draw.circle(surf, GLOW_RED,   (a_tip[0]+2, a_tip[1]), 2)
    if fire_t >= 0 and fire_t < 0.55:
        streak_a = 1.0 - abs(fire_t - 0.25) / 0.25
        if streak_a > 0:
            sc = (int(255*streak_a), int(180*streak_a), int(40*streak_a))
            pygame.draw.line(surf, sc, a_tip, (a_tip[0]-12, a_tip[1]), 3)

    # == Right arm – Autocannon (extends when firing) ==
    arm2_y   = r.y + int(r.h * 0.27) + 6
    fire_ext = int(_fire_arm_offset(fire_t) * 8)
    b_base   = (body.right+2, arm2_y)
    b_tip    = (r.right-2+fire_ext, arm2_y)
    hb = pygame.Rect(b_base[0]-2, arm2_y-6, 10, 12)
    _panel(surf, hb, METAL_DARK, br=1, border=METAL_MID)
    pygame.draw.line(surf, METAL_MID, (hb.right, arm2_y-3), (b_tip[0], b_tip[1]-3), 3)
    pygame.draw.line(surf, METAL_MID, (hb.right, arm2_y+3), (b_tip[0], b_tip[1]+3), 3)
    pygame.draw.line(surf, METAL_SHEEN, (hb.right, arm2_y-3), (b_tip[0], b_tip[1]-3), 1)
    for my in [b_tip[1]-3, b_tip[1]+3]:
        pygame.draw.circle(surf, DARK_PLATE, (b_tip[0], my), 2)

    # == Head (sensor tracks toward weapon during fire) ==
    head_shift = -_torso_lean(fire_t, 4)
    head = _fr(r, 0.32, 0.03, 0.68, 0.19)
    head = head.move(head_shift, 0)
    _panel(surf, head, dk, br=3, border=team_color)
    for hax, hdir in [(head.x+5,-2),(head.right-5,2)]:
        pygame.draw.line(surf, METAL_MID, (hax, head.y), (hax+hdir, head.y-7), 1)
        pygame.draw.circle(surf, METAL_LIGHT, (hax+hdir, head.y-7), 1)
    eye_x = head.right-10
    eye_rect = pygame.Rect(eye_x, head.centery-2, 8, 5)
    pygame.draw.rect(surf, GLOW_RED, eye_rect, border_radius=1)
    _glow(surf, eye_rect.centerx, eye_rect.centery, 4, GLOW_RED, 80)
    pygame.draw.circle(surf, GLOW_BLUE, (head.x+6, head.centery), 2)


# ---------------------------------------------------------------------------
# COLOSSUS  –  Imperial Knight / Reaver Titan
# ---------------------------------------------------------------------------

def draw_colossus(surf, r, color, team_color, walk_t=0.0, fire_t=-1.0):
    dk = _dk(color)

    body_sway    = int(math.sin(walk_t * math.pi * 2) * 2)
    body_dip     = _knee_dip(walk_t)
    track_shift  = int(walk_t * 12) % 10
    fire_frac    = _fire_arm_offset(fire_t)

    # == Track system ==
    track = _fr(r, 0.03, 0.80, 0.97, 0.99)
    _panel(surf, track, METAL_DARK, br=2, border=METAL_MID)
    whl_count = 5
    for wi in range(whl_count):
        wx = track.x + 5 + wi * int((track.w-10)/(whl_count-1))
        wy = track.centery
        pygame.draw.circle(surf, METAL_MID,   (wx, wy), 5)
        pygame.draw.circle(surf, METAL_DARK,  (wx, wy), 3)
        pygame.draw.circle(surf, METAL_SHEEN, (wx-1, wy-1), 1)
    for pi in range(8):
        px2 = (track.x + pi * 12 + track_shift) % (track.w) + track.x
        if track.x <= px2 <= track.right:
            pygame.draw.line(surf, METAL_MID, (px2, track.y+1), (px2, track.y+3))
    house = _fr(r, 0.03, 0.66, 0.97, 0.81)
    _panel(surf, house, dk, br=2, border=METAL_MID)

    # == Massive carapace body ==
    body = pygame.Rect(
        r.x + int(0.09*r.w) + body_sway,
        r.y + int(0.17*r.h) + body_dip,
        int(0.82*r.w), int(0.50*r.h)
    )
    _panel(surf, body, color, br=3, border=team_color)
    shield = [
        (body.centerx-10, body.y+5),
        (body.centerx+10, body.y+5),
        (body.centerx+8,  body.centery-4),
        (body.centerx,    body.centery+2),
        (body.centerx-8,  body.centery-4),
    ]
    pygame.draw.polygon(surf, _lt(color, 0.12), shield)
    pygame.draw.polygon(surf, team_color, shield, 1)
    _panel_line(surf, color, (body.x+4, body.y+3), (body.x+4, body.bottom-3))
    _panel_line(surf, color, (body.right-5, body.y+3), (body.right-5, body.bottom-3))
    for rx2, ry2 in [(body.x+5,body.y+5),(body.right-6,body.y+5),
                     (body.x+5,body.bottom-6),(body.right-6,body.bottom-6),
                     (body.centerx, body.y+5)]:
        _rivet(surf, rx2, ry2)
    _STABLE_RNG.seed(0xC0105505)
    for _ in range(5):
        sx = body.x + _STABLE_RNG.randint(10, body.w-10)
        sy = body.y + _STABLE_RNG.randint(8, body.h-8)
        ex = sx + _STABLE_RNG.randint(-10, 10)
        ey = sy + _STABLE_RNG.randint(-6, 6)
        pygame.draw.line(surf, dk, (sx, sy), (ex, ey))
        pygame.draw.line(surf, METAL_LIGHT, (sx-1, sy), (ex-1, ey))

    # == LEFT arm – Massive Battle Cannon (recoil + barrel elevation) ==
    fire_recoil    = int(fire_frac * int(r.w * 0.05))
    barrel_elevate = int(fire_frac * 6)
    mount = _fr(r, 0.09, 0.27, 0.21, 0.56)
    mount = mount.move(body_sway, body_dip)
    _panel(surf, mount, METAL_DARK, br=2, border=METAL_MID)
    barrel_base_y = r.y + int(r.h * 0.32) + body_dip
    barrel_tip_y  = barrel_base_y - barrel_elevate     # barrel tip rises during fire
    blen          = int(r.w * 0.12)
    barrel_x      = r.x - fire_recoil
    # Draw barrel as angled line set (thick upper + thin shadow)
    pygame.draw.line(surf, METAL_DARK,
                     (barrel_x+4, barrel_base_y+4), (barrel_x+blen, barrel_tip_y-4), 8)
    pygame.draw.line(surf, METAL_MID,
                     (barrel_x+4, barrel_base_y+2), (barrel_x+blen, barrel_tip_y-2), 2)
    pygame.draw.line(surf, _dk(METAL_DARK),
                     (barrel_x+4, barrel_base_y+5), (barrel_x+blen, barrel_tip_y+4), 2)
    brake = pygame.Rect(barrel_x, barrel_base_y-6, 8, 12)
    _panel(surf, brake, DARK_PLATE, br=1, border=METAL_MID)
    for fi in range(3):
        fx2 = barrel_x + 10 + fi * 6
        pygame.draw.line(surf, METAL_MID, (fx2, barrel_base_y-6), (fx2, barrel_base_y+6))
    if fire_t >= 0 and fire_t < 0.45:
        blast_a = 1.0 - fire_t / 0.45
        _glow(surf, barrel_x+2, barrel_tip_y, max(2, int(10*blast_a)), GLOW_ORANGE, int(180*blast_a))

    # == RIGHT arm – Missile Battery ==
    bat = _fr(r, 0.80, 0.26, 0.99, 0.59)
    bat = bat.move(body_sway, body_dip)
    _panel(surf, bat, METAL_DARK, br=2, border=team_color)
    for col2 in range(2):
        for row in range(4):
            tx2 = bat.x+3+col2*int((bat.w-6)//2)
            ty2 = bat.y+3+row*int((bat.h-6)//4)
            tw  = int((bat.w-8)//2)
            th  = max(2, int((bat.h-10)//4))
            pygame.draw.rect(surf, DARK_PLATE, (tx2, ty2, tw, th))
            pygame.draw.circle(surf, (170, 50, 50), (tx2+3, ty2+th//2), 2)
            if fire_t >= 0 and row == 1:
                _glow(surf, tx2+3, ty2+th//2, 3, GLOW_ORANGE, 100)

    # == Head (tracks toward cannon during fire) ==
    head_shift = -_torso_lean(fire_t, 3)
    head = _fr(r, 0.27, 0.03, 0.73, 0.19)
    head = head.move(body_sway + head_shift, body_dip)
    _panel(surf, head, dk, br=5, border=team_color)
    visor = pygame.Rect(head.x+4, head.centery-3, head.w-8, 6)
    pygame.draw.rect(surf, GLOW_RED, visor, border_radius=2)
    _glow(surf, visor.centerx, visor.centery, 6, GLOW_RED, 110)
    pygame.draw.rect(surf, (255,180,160), (visor.x+2, visor.y+1, 8, 2))
    pygame.draw.line(surf, METAL_MID, (head.right-6, head.y-1), (head.right+4, head.y-6), 2)
    pygame.draw.circle(surf, DARK_PLATE, (head.right+4, head.y-6), 2)
    pygame.draw.line(surf, team_color, (head.centerx-6, head.y-2), (head.centerx+6, head.y-2))
    pygame.draw.line(surf, team_color, (head.centerx, head.y-5), (head.centerx, head.y-1))


# ---------------------------------------------------------------------------
# PHANTOM  –  Tau XV-8 Battlesuit
# ---------------------------------------------------------------------------

def draw_phantom(surf, r, color, team_color, walk_t=0.0, fire_t=-1.0):
    dk  = _dk(color, 0.40)
    lt  = _lt(color, 0.38)

    l_swing = _leg_swing(walk_t,  1, 5)
    r_swing = _leg_swing(walk_t, -1, 5)
    l_ankle = _ankle_off(walk_t,  1, 4)
    r_ankle = _ankle_off(walk_t, -1, 4)

    # Thruster intensity scales with step speed
    thruster_boost = abs(math.sin(walk_t * math.pi * 2)) if walk_t > 0 else 0.0
    jt_a_base = int(55 + 110 * thruster_boost)

    # == Swept reverse-knee legs with ankle joints ==
    for hip_fx, knee_fx, ankle_fx, foot_fx, swing, ankle_sw, side in [
        (0.33, 0.21, 0.25, 0.29, l_swing, l_ankle, -1),
        (0.67, 0.79, 0.75, 0.71, r_swing, r_ankle,  1),
    ]:
        hip   = (r.x + int(r.w * hip_fx),   r.y + int(r.h * 0.52))
        knee  = (r.x + int(r.w * knee_fx),  r.y + int(r.h * 0.71) + swing)
        ankle = (r.x + int(r.w * ankle_fx), r.y + int(r.h * 0.84) + ankle_sw)
        foot  = (r.x + int(r.w * foot_fx),  r.y + int(r.h * 0.94))
        # Upper leg
        pygame.draw.line(surf, color, hip, knee, 6)
        pygame.draw.line(surf, lt,    hip, knee, 1)
        # Shin
        pygame.draw.line(surf, dk, knee, ankle, 5)
        # Foot segment
        pygame.draw.line(surf, METAL_DARK, ankle, foot, 4)
        # Joints
        pygame.draw.circle(surf, lt,         knee, 5)
        pygame.draw.circle(surf, team_color, knee, 5, 1)
        pygame.draw.circle(surf, WHITE,      knee, 2)
        pygame.draw.circle(surf, METAL_MID,  ankle, 3)
        pygame.draw.circle(surf, METAL_DARK, ankle, 3, 1)
        pygame.draw.circle(surf, METAL_LIGHT, (ankle[0]-1, ankle[1]-1), 1)
        # Foot plate
        foot_rect = pygame.Rect(foot[0]-9, foot[1]-3, 20, 6)
        _panel(surf, foot_rect, METAL_DARK, br=2, border=METAL_MID)
        _glow(surf, foot[0]-3*side, foot[1]-5, 3, GLOW_BLUE, 70)
        pygame.draw.circle(surf, GLOW_BLUE, (foot[0]-3*side, foot[1]-5), 2)

    # == Trapezoid torso ==
    pts = [
        (r.x + int(r.w * 0.27), r.y + int(r.h * 0.18)),
        (r.x + int(r.w * 0.73), r.y + int(r.h * 0.18)),
        (r.x + int(r.w * 0.79), r.y + int(r.h * 0.53)),
        (r.x + int(r.w * 0.21), r.y + int(r.h * 0.53)),
    ]
    pygame.draw.polygon(surf, color, pts)
    pygame.draw.polygon(surf, team_color, pts, 2)
    pygame.draw.line(surf, lt, pts[0], pts[1], 2)
    panel2 = _fr(r, 0.32, 0.25, 0.68, 0.37)
    _panel(surf, panel2, dk, br=2, border=GLOW_BLUE)
    for di in range(3):
        dx2 = panel2.x + 5 + di * int(panel2.w // 3)
        _glow(surf, dx2, panel2.centery, 3, GLOW_BLUE, 80)
        pygame.draw.circle(surf, GLOW_BLUE, (dx2, panel2.centery), 2)

    # Jetpack with dynamic thrust glow + exhaust streaks
    pack = _fr(r, 0.73, 0.19, 0.87, 0.43)
    _panel(surf, pack, dk, br=3, border=GLOW_BLUE)
    for ni in range(2):
        ny2 = pack.y + 5 + ni * int(pack.h * 0.45)
        nozzle = pygame.Rect(pack.x+2, ny2, pack.w-4, 7)
        pygame.draw.rect(surf, DARK_PLATE, nozzle, border_radius=2)
        _glow(surf, nozzle.centerx, nozzle.centery, 4, GLOW_BLUE, jt_a_base)
        pygame.draw.circle(surf, GLOW_BLUE, (nozzle.centerx, nozzle.centery), 2)
        # Exhaust streak when thrusting
        if thruster_boost > 0.25:
            for ej in range(1, 5):
                fade = 1.0 - ej / 5.0
                ec = (0, int(130 * thruster_boost * fade), int(230 * thruster_boost * fade))
                pygame.draw.line(surf, ec,
                                 (nozzle.x + 2, nozzle.bottom + ej - 1),
                                 (nozzle.right - 2, nozzle.bottom + ej - 1))

    # == Left arm – Pulse Laser (shoulder rises + extends during fire) ==
    fire_ext = int(_fire_arm_offset(fire_t) * 7)
    sh_rise  = _shoulder_rise(fire_t, 4)
    arm_y    = r.y + int(r.h * 0.27) - sh_rise
    a0 = (r.x + int(r.w * 0.27), arm_y)
    a1 = (r.x - fire_ext, arm_y)
    pygame.draw.line(surf, METAL_DARK, a0, a1, 4)
    pygame.draw.line(surf, lt,         a0, a1, 1)
    glow_a2 = 160 if fire_t >= 0 else 100
    _glow(surf, a1[0]+1, a1[1], 5 if fire_t >= 0 else 3, GLOW_BLUE, glow_a2)
    pygame.draw.circle(surf, GLOW_BLUE, (a1[0]+1, a1[1]), 3)
    pygame.draw.circle(surf, WHITE,     (a1[0]+1, a1[1]), 1)

    # == Right arm – Vibro-Blade (lunges forward) ==
    blade_ext = int(_fire_arm_offset(fire_t) * 10)
    blade_y   = r.y + int(r.h * 0.38)
    mount_r   = pygame.Rect(r.x + int(r.w * 0.71), blade_y-5, int(r.w * 0.08), 10)
    _panel(surf, mount_r, dk, br=1, border=METAL_MID)
    b_pts = [
        (r.x + int(r.w * 0.79) + blade_ext, blade_y-5),
        (r.right - 2 + blade_ext,             blade_y),
        (r.x + int(r.w * 0.79) + blade_ext, blade_y+5),
    ]
    pygame.draw.polygon(surf, METAL_MID, b_pts)
    pygame.draw.polygon(surf, METAL_SHEEN, b_pts, 1)
    pygame.draw.line(surf, GLOW_BLUE, b_pts[0], b_pts[1])
    glow_b = 100 if fire_t >= 0 else 50
    _glow(surf, b_pts[1][0]-2, b_pts[1][1], 4, GLOW_BLUE, glow_b)

    # == Angular head + sensor (tracks toward weapon) ==
    sensor_lean = -_torso_lean(fire_t, 4)
    head_pts = [
        (r.x + int(r.w * 0.36) + sensor_lean, r.y + int(r.h * 0.02)),
        (r.x + int(r.w * 0.64) + sensor_lean, r.y + int(r.h * 0.02)),
        (r.x + int(r.w * 0.67) + sensor_lean, r.y + int(r.h * 0.18)),
        (r.x + int(r.w * 0.33) + sensor_lean, r.y + int(r.h * 0.18)),
    ]
    pygame.draw.polygon(surf, dk, head_pts)
    pygame.draw.polygon(surf, team_color, head_pts, 1)
    pygame.draw.line(surf, lt, head_pts[0], head_pts[1])
    sensor_y = r.y + int(r.h * 0.09)
    pygame.draw.line(surf, GLOW_BLUE,
                     (r.x + int(r.w * 0.39) + sensor_lean, sensor_y),
                     (r.x + int(r.w * 0.61) + sensor_lean, sensor_y), 3)
    _glow(surf, r.x + int(r.w * 0.52) + sensor_lean, sensor_y, 5, GLOW_BLUE, 80)
    pygame.draw.circle(surf, WHITE, (r.x + int(r.w * 0.60) + sensor_lean, sensor_y), 2)


# ---------------------------------------------------------------------------
# VANGUARD  –  Blood Angels Dreadnought
# ---------------------------------------------------------------------------

def draw_vanguard(surf, r, color, team_color, walk_t=0.0, fire_t=-1.0):
    dk = _dk(color)
    lt = _lt(color, 0.25)

    l_swing  = _leg_swing(walk_t,  1, 4)
    r_swing  = _leg_swing(walk_t, -1, 4)
    body_dip = _knee_dip(walk_t)
    fire_frac = _fire_arm_offset(fire_t)

    # == Articulated legs (animated swing + body dip) ==
    for lx0, lx1, ux0, ux1, swing in [
        (0.13, 0.41,  0.16, 0.38, l_swing),
        (0.59, 0.87,  0.62, 0.84, r_swing),
    ]:
        upper = _fr(r, lx0, 0.57, lx1, 0.76)
        lower = _fr(r, ux0, 0.76, ux1, 0.97)
        upper = upper.move(0, swing + body_dip)
        lower = lower.move(0, swing + body_dip)
        _panel(surf, upper, dk,         br=3, border=METAL_MID)
        _panel(surf, lower, METAL_DARK, br=2, border=METAL_MID)
        jx = (upper.x + upper.right) // 2
        pygame.draw.circle(surf, METAL_MID,   (jx, upper.bottom), 5)
        pygame.draw.circle(surf, METAL_DARK,  (jx, upper.bottom), 3)
        pygame.draw.circle(surf, METAL_LIGHT, (jx-1, upper.bottom-1), 1)
        pygame.draw.line(surf, METAL_MID, (lower.x+2, lower.y+3), (lower.x+2, lower.bottom-4))
        for tx2 in [lower.x+3, lower.right-4]:
            pygame.draw.rect(surf, METAL_DARK, (tx2-2, lower.bottom-1, 4, 4), border_radius=1)

    # == Rounded body ==
    body = _fr(r, 0.16, 0.19, 0.84, 0.60)
    _panel(surf, body, color, br=5, border=team_color)
    chest = _fr(r, 0.27, 0.24, 0.73, 0.54)
    pygame.draw.rect(surf, _lt(color, 0.08), chest, border_radius=3)
    ic, iy = body.centerx, body.centery - 4
    pygame.draw.line(surf, team_color, (ic-10, iy), (ic-5, iy-4))
    pygame.draw.line(surf, team_color, (ic-10, iy), (ic-6, iy+2))
    pygame.draw.line(surf, team_color, (ic+10, iy), (ic+5, iy-4))
    pygame.draw.line(surf, team_color, (ic+10, iy), (ic+6, iy+2))
    pygame.draw.circle(surf, team_color, (ic, iy), 4)
    pygame.draw.circle(surf, _lt(team_color, 0.5), (ic, iy), 2)
    pygame.draw.polygon(surf, team_color, [(ic-2, iy+3), (ic+2, iy+3), (ic, iy+7)])
    seal_x = body.centerx + 5
    pygame.draw.rect(surf, (180, 168, 140), (seal_x, body.bottom-4, 6, 10))
    pygame.draw.rect(surf, team_color, (seal_x, body.bottom-4, 6, 4))
    _panel_line(surf, color, (body.x+5, body.y+4), (body.x+5, body.bottom-4))
    _panel_line(surf, color, (body.right-6, body.y+4), (body.right-6, body.bottom-4))
    for rx2, ry2 in [(body.x+5,body.y+5),(body.right-6,body.y+5),(body.x+5,body.bottom-6)]:
        _rivet(surf, rx2, ry2)

    # == Wide shoulders ==
    for sx0, sx1 in [(0.02, 0.19), (0.81, 0.98)]:
        sp = _fr(r, sx0, 0.19, sx1, 0.36)
        _panel(surf, sp, dk, br=3, border=team_color)
        stripe = pygame.Rect(sp.x+2, sp.y+5, sp.w-4, 3)
        pygame.draw.rect(surf, team_color, stripe)
        _rivet(surf, sp.centerx, sp.centery+2)

    # == LEFT arm – Plasma Cannon with elbow joint (two-segment arm) ==
    fire_raise = int(fire_frac * 6)

    # Shoulder → elbow (upper arm)
    shoulder_x = r.x + int(r.w * 0.09)
    shoulder_y = r.y + int(r.h * 0.26) - fire_raise
    elbow_x    = r.x + int(r.w * 0.05)
    elbow_y    = r.y + int(r.h * 0.40) - int(fire_raise * 0.6)
    uarm = pygame.Rect(
        min(shoulder_x, elbow_x) - 3,
        shoulder_y,
        max(8, shoulder_x - elbow_x + 6),
        max(4, elbow_y - shoulder_y + 4)
    )
    _panel(surf, uarm, METAL_DARK, br=2, border=METAL_MID)

    # Elbow joint
    pygame.draw.circle(surf, METAL_MID,   (elbow_x, elbow_y), 5)
    pygame.draw.circle(surf, METAL_DARK,  (elbow_x, elbow_y), 3)
    pygame.draw.circle(surf, METAL_LIGHT, (elbow_x-1, elbow_y-1), 1)

    # Elbow → plasma emitter (forearm + weapon housing)
    farm_top    = elbow_y - 4
    farm_bottom = r.y + int(r.h * 0.57) - int(fire_raise * 0.35)
    farm = pygame.Rect(r.x, farm_top, int(r.w * 0.16), farm_bottom - farm_top + 4)
    _panel(surf, farm, METAL_DARK, br=3, border=METAL_MID)

    # Plasma coil rings on forearm
    for ci, cy_frac in enumerate([0.22, 0.38, 0.54]):
        cy_abs = farm.y + int(farm.h * cy_frac)
        w = farm.w - 4 - ci
        cring = pygame.Rect(farm.x+2+ci, cy_abs, w, 5)
        pygame.draw.rect(surf, METAL_MID, cring, border_radius=2)
        pygame.draw.rect(surf, METAL_DARK, cring, 1, border_radius=2)

    # Plasma emitter (muzzle at bottom of forearm)
    ecx, ecy = farm.centerx, farm.bottom - 8
    glow_size = 10 if fire_t >= 0 else 7
    glow_al   = 180 if fire_t >= 0 else 130
    _glow(surf, ecx, ecy, glow_size, GLOW_BLUE, glow_al)
    pygame.draw.circle(surf, GLOW_BLUE,       (ecx, ecy), 6)
    pygame.draw.circle(surf, (200, 238, 255), (ecx, ecy), 4)
    pygame.draw.circle(surf, WHITE,           (ecx, ecy), 2)
    pygame.draw.circle(surf, METAL_MID,       (ecx, ecy), 6, 1)

    # Energy discharge arcs when firing
    if fire_t >= 0 and fire_t < 0.55:
        arc_a = max(0, 1.0 - fire_t / 0.55)
        for i in range(4):
            ang = i * math.pi / 2 + fire_t * 10
            ax  = int(ecx + math.cos(ang) * 9)
            ay  = int(ecy + math.sin(ang) * 9)
            ac  = (int(GLOW_BLUE[0]*arc_a), int(GLOW_BLUE[1]*arc_a), int(GLOW_BLUE[2]*arc_a))
            pygame.draw.line(surf, ac, (ecx, ecy), (ax, ay), 1)
            # Secondary arc
            ang2 = ang + math.pi / 4
            bx = int(ecx + math.cos(ang2) * 5)
            by = int(ecy + math.sin(ang2) * 5)
            pygame.draw.line(surf, ac, (ecx, ecy), (bx, by), 1)

    # == RIGHT arm – Rapid Autocannon (extends + recoils) ==
    fire_off2 = int(fire_frac * 6)
    rarm = _fr(r, 0.84, 0.26, 0.99, 0.52)
    _panel(surf, rarm, METAL_DARK, br=2, border=team_color)
    b_x0 = rarm.right
    b_x1 = min(r.right-1, rarm.right + 12 + fire_off2)
    for bdy2, bw in [(-3, 3), (3, 3)]:
        pygame.draw.line(surf, METAL_MID, (b_x0, rarm.centery+bdy2), (b_x1, rarm.centery+bdy2), bw)
        pygame.draw.line(surf, METAL_SHEEN, (b_x0, rarm.centery+bdy2), (b_x1, rarm.centery+bdy2), 1)
    pygame.draw.rect(surf, METAL_MID, (rarm.centerx-2, rarm.y+2, 5, int(rarm.h*0.5)), border_radius=1)
    if fire_t >= 0 and fire_t < 0.45:
        fa = 1.0 - fire_t / 0.45
        _glow(surf, b_x1, rarm.centery, max(2, int(7*fa)), GLOW_ORANGE, int(140*fa))

    # == Rounded T-visor helmet (visor glows brighter when fired) ==
    head = _fr(r, 0.30, 0.02, 0.70, 0.21)
    _panel(surf, head, dk, br=6, border=team_color)
    visor = pygame.Rect(head.x+4, head.centery-3, head.w-8, 6)
    visor_glow_a = 180 if fire_t >= 0 else 120
    pygame.draw.rect(surf, GLOW_RED, visor, border_radius=2)
    _glow(surf, visor.centerx, visor.centery, 6, GLOW_RED, visor_glow_a)
    pygame.draw.rect(surf, (255, 200, 180), (visor.x+2, visor.y+1, 8, 2))
    pygame.draw.line(surf, GLOW_RED, (head.centerx, head.y+3), (head.centerx, visor.y-1), 2)
    pygame.draw.line(surf, GLOW_RED, (head.centerx, visor.bottom+1), (head.centerx, head.bottom-3), 2)
    crest = _fr(r, 0.41, 0.01, 0.59, 0.07)
    _panel(surf, crest, lt, br=2, border=team_color)
    chin = pygame.Rect(head.x+6, head.bottom-5, head.w-12, 3)
    pygame.draw.rect(surf, METAL_DARK, chin)


# ---------------------------------------------------------------------------
# SNIPER  -  Long-range precision hunter  (Tau XV-25 Stealth Suit, redesigned)
# ---------------------------------------------------------------------------

def draw_sniper(surf, r, color, team_color, walk_t=0.0, fire_t=-1.0):
    W, H   = r.w, r.h
    fire_frac = _fire_arm_offset(fire_t)
    body_bob  = _knee_dip(walk_t)
    l_sw = _leg_swing(walk_t,  1, 3)
    r_sw = _leg_swing(walk_t, -1, 3)

    SCOPE_COL  = (30, 200, 200)
    STEALTH_LN = _shade(color, 1.08)

    def px(fx): return r.x + int(fx * W)
    def py(fy): return r.y + int(fy * H)

    # == FEET ==
    for lx_c, sw in ((0.19, l_sw), (0.81, r_sw)):
        foot_pts = [
            (px(lx_c - 0.15), py(0.94) + sw + body_bob),
            (px(lx_c + 0.18), py(0.94) + sw + body_bob),
            (px(lx_c + 0.14), py(0.87) + sw + body_bob),
            (px(lx_c - 0.11), py(0.87) + sw + body_bob),
        ]
        _lit_poly(surf, foot_pts, _shade(color, 0.70), border=_shade(color, 0.40))

    # == SHINS ==
    for lx_c, sw in ((0.19, l_sw), (0.81, r_sw)):
        shin_pts = [
            (px(lx_c - 0.07), py(0.87) + body_bob + sw),
            (px(lx_c + 0.07), py(0.87) + body_bob + sw),
            (px(lx_c + 0.06), py(0.68) + body_bob + sw),
            (px(lx_c - 0.06), py(0.68) + body_bob + sw),
        ]
        _lit_poly(surf, shin_pts, color, border=_shade(color, 0.45))
        sp_rect = pygame.Rect(px(lx_c - 0.04), py(0.71) + body_bob + sw,
                              max(3, int(0.08 * W)), max(3, int(0.09 * H)))
        _lit_rect(surf, sp_rect, _shade(color, 1.10), br=1)

    # == KNEE JOINTS ==
    for lx_c, sw in ((0.19, l_sw), (0.81, r_sw)):
        _joint_ball(surf, px(lx_c), py(0.68) + body_bob + sw, max(3, W // 13), METAL_MID)

    # == THIGHS ==
    for lx_c, sw, dx_off in ((0.19, l_sw, -0.04), (0.81, r_sw, 0.04)):
        thigh_pts = [
            (px(lx_c - 0.07 + dx_off), py(0.68) + body_bob + sw),
            (px(lx_c + 0.07 + dx_off), py(0.68) + body_bob + sw),
            (px(lx_c + 0.05),          py(0.49) + body_bob),
            (px(lx_c - 0.05),          py(0.49) + body_bob),
        ]
        _lit_poly(surf, thigh_pts, _shade(color, 1.05), border=team_color)
        stripe_y = py(0.54) + body_bob
        pygame.draw.line(surf, team_color,
                         (px(lx_c - 0.04), stripe_y), (px(lx_c + 0.04), stripe_y), 2)
        pygame.draw.line(surf, METAL_SHEEN,
                         (px(lx_c), py(0.67) + body_bob + sw),
                         (px(lx_c), py(0.52) + body_bob), 1)

    # == HIP BLOCK ==
    hip_pts = [
        (px(0.27), py(0.49) + body_bob),
        (px(0.73), py(0.49) + body_bob),
        (px(0.68), py(0.57) + body_bob),
        (px(0.32), py(0.57) + body_bob),
    ]
    _lit_poly(surf, hip_pts, _shade(color, 0.90), border=_shade(color, 0.45))
    for rx_f in (0.35, 0.50, 0.65):
        _rivet(surf, px(rx_f), py(0.53) + body_bob)

    # == HIP JOINTS ==
    for lx_c in (0.27, 0.73):
        _joint_ball(surf, px(lx_c), py(0.49) + body_bob, max(3, W // 14), METAL_MID)

    # == TORSO ==
    lean = _torso_lean(fire_t, 2)
    torso_pts = [
        (px(0.30) + lean, py(0.20) + body_bob),
        (px(0.70) + lean, py(0.20) + body_bob),
        (px(0.68) + lean, py(0.49) + body_bob),
        (px(0.32) + lean, py(0.49) + body_bob),
    ]
    _lit_poly(surf, torso_pts, color, border=team_color)
    cp = pygame.Rect(px(0.36) + lean, py(0.27) + body_bob,
                     max(4, int(0.28 * W)), max(4, int(0.14 * H)))
    _lit_rect(surf, cp, _shade(color, 1.18), br=2, border=_shade(color, 0.40))
    for gy in range(cp.y + 4, cp.bottom - 2, 4):
        pygame.draw.line(surf, STEALTH_LN, (cp.x + 2, gy), (cp.right - 2, gy))
    cell_x = px(0.64) + lean
    cell_y = py(0.27) + body_bob
    cell_h = max(6, int(0.16 * H))
    cell_rect = pygame.Rect(cell_x, cell_y, max(4, int(0.05 * W)), cell_h)
    pygame.draw.rect(surf, METAL_DARK, cell_rect, border_radius=2)
    segs = 3
    seg_h = max(1, (cell_h - 2) // segs)
    for ci in range(segs):
        pct = (1 - ci / segs) if fire_t >= 0 else 0.45
        gs = pygame.Surface((max(1, cell_rect.w - 2), seg_h), pygame.SRCALPHA)
        gs.fill((*SCOPE_COL, int(165 * pct)))
        surf.blit(gs, (cell_rect.x + 1, cell_rect.y + 1 + ci * seg_h))

    # == SHOULDER PAULDRONS ==
    for sx0, sx1 in ((0.22, 0.35), (0.65, 0.78)):
        sp_pts = [
            (px(sx0) + lean,        py(0.20) + body_bob),
            (px(sx1) + lean,        py(0.20) + body_bob),
            (px(sx1 + 0.02) + lean, py(0.29) + body_bob),
            (px(sx0 - 0.02) + lean, py(0.29) + body_bob),
        ]
        _lit_poly(surf, sp_pts, _shade(color, 1.12), border=_shade(color, 0.40))

    # == HEAD - hexagonal sensor pod ==
    hcx = px(0.40) + lean
    hcy = py(0.12) + body_bob
    hr  = max(5, W // 10)
    hex_pts = [
        (hcx + int(hr * math.cos(math.radians(a))),
         hcy + int(hr * math.sin(math.radians(a))))
        for a in range(-150, 210, 60)
    ]
    _lit_poly(surf, hex_pts, _shade(color, 1.02), border=team_color)
    visor_w = max(3, hr - 2)
    visor_h = max(2, hr // 3)
    visor_rect = pygame.Rect(hcx - visor_w // 2, hcy - visor_h // 2, visor_w, visor_h)
    vg_a = 200 if fire_t >= 0 else 130
    _glow(surf, visor_rect.centerx, visor_rect.centery, visor_w // 2, SCOPE_COL, vg_a)
    pygame.draw.rect(surf, SCOPE_COL, visor_rect, border_radius=1)
    ant_x = hcx + hr // 2
    ant_top = hcy - hr - max(4, H // 14)
    pygame.draw.line(surf, METAL_SHEEN, (ant_x, hcy - hr), (ant_x, ant_top), 2)
    pygame.draw.circle(surf, SCOPE_COL, (ant_x, ant_top), 2)

    # == LEFT GRIP ARM ==
    rifle_y_base = py(0.28) + body_bob - _shoulder_rise(fire_t, 5)
    grip = pygame.Rect(
        px(0.60) + lean,
        rifle_y_base + 1,
        max(3, int(0.10 * W)),
        max(3, int(0.13 * H)),
    )
    _lit_rect(surf, grip, METAL_DARK, br=2)

    # == SNIPER RIFLE ==
    barrel_extend = int(fire_frac * W * 0.08)
    rifle_y = rifle_y_base

    stock = pygame.Rect(px(0.64) + lean, rifle_y - 4, max(4, int(0.13 * W)), 9)
    _lit_rect(surf, stock, METAL_DARK, br=2, border=METAL_MID)

    recv_x = stock.right
    recv = pygame.Rect(recv_x, rifle_y - 5, max(4, int(0.16 * W)), 10)
    _lit_rect(surf, recv, METAL_MID, br=1, border=_shade(METAL_MID, 0.55))
    ej = pygame.Rect(recv.x + recv.w // 3, recv.y + 2, max(2, recv.w // 4), 4)
    pygame.draw.rect(surf, METAL_DARK, ej, border_radius=1)

    brl_x0 = recv.right
    brl_x1 = r.x + int(r.w * 0.97) + barrel_extend
    pygame.draw.line(surf, METAL_DARK,  (brl_x0, rifle_y - 2), (brl_x1, rifle_y - 2), 1)
    pygame.draw.line(surf, METAL_MID,   (brl_x0, rifle_y),     (brl_x1, rifle_y),     4)
    pygame.draw.line(surf, METAL_SHEEN, (brl_x0, rifle_y + 1), (brl_x1, rifle_y + 1), 1)

    for rng_f in (0.05, 0.22, 0.42):
        rng_x = brl_x0 + int((brl_x1 - brl_x0) * rng_f)
        pygame.draw.line(surf, METAL_DARK,  (rng_x, rifle_y - 3), (rng_x, rifle_y + 3), 3)
        pygame.draw.line(surf, METAL_SHEEN, (rng_x - 1, rifle_y - 2), (rng_x - 1, rifle_y + 2), 1)

    hg_x = brl_x0 + int((brl_x1 - brl_x0) * 0.12)
    hg_rect = pygame.Rect(hg_x, rifle_y - 3, max(4, int(0.10 * W)), 7)
    _lit_rect(surf, hg_rect, METAL_MID, br=1)

    mag_rect = pygame.Rect(recv.x + recv.w // 4, recv.bottom,
                           max(3, recv.w // 3), max(5, H // 10))
    _lit_rect(surf, mag_rect, METAL_DARK, br=2, border=METAL_MID)

    rail_x0 = recv.x + 2
    rail_x1 = brl_x0 + int((brl_x1 - brl_x0) * 0.45)
    pygame.draw.line(surf, METAL_SHEEN, (rail_x0, rifle_y - 5), (rail_x1, rifle_y - 5), 1)
    sc_w = max(4, (rail_x1 - rail_x0) // 3)
    sc_rect = pygame.Rect(rail_x0 + (rail_x1 - rail_x0) // 3, rifle_y - 9, sc_w, 5)
    _lit_rect(surf, sc_rect, METAL_MID, br=1, border=METAL_DARK)
    sc_lens = (sc_rect.right + 1, sc_rect.centery)
    g_alpha = 75 + int(fire_frac * 110)
    _glow(surf, sc_lens[0], sc_lens[1], 3, SCOPE_COL, g_alpha)
    pygame.draw.circle(surf, SCOPE_COL, sc_lens, 2)

    supp_x = brl_x1 - max(5, int(0.06 * W))
    supp_rect = pygame.Rect(supp_x, rifle_y - 5, max(5, int(0.07 * W)), 10)
    _lit_rect(surf, supp_rect, METAL_DARK, br=2, border=METAL_MID)
    for vi in range(3):
        vx = supp_rect.x + 2 + vi * (supp_rect.w // 4)
        pygame.draw.line(surf, METAL_SHEEN,
                         (vx, supp_rect.y + 2), (vx, supp_rect.bottom - 2), 1)
    pygame.draw.circle(surf, METAL_MID, (supp_rect.right - 1, rifle_y), 3)

    if walk_t < 0.12 or walk_t > 0.88:
        bpd_x = brl_x0 + int((brl_x1 - brl_x0) * 0.08)
        bpd_bot = rifle_y + max(8, H // 9)
        pygame.draw.line(surf, METAL_MID, (bpd_x, rifle_y + 3), (bpd_x - 4, bpd_bot), 2)
        pygame.draw.line(surf, METAL_MID, (bpd_x, rifle_y + 3), (bpd_x + 4, bpd_bot), 2)

    if fire_t >= 0 and fire_frac > 0.35:
        muzzle = (brl_x1 + 2, rifle_y)
        flash_size = int((fire_frac - 0.35) * 14 * (1 - fire_frac))
        if flash_size > 0:
            _glow(surf, muzzle[0] + flash_size // 2, muzzle[1],
                  flash_size, SCOPE_COL, 210)
            for angle in (0, 90, 45, 135):
                rad = math.radians(angle)
                ex = int(muzzle[0] + math.cos(rad) * flash_size)
                ey = int(muzzle[1] + math.sin(rad) * flash_size)
                pygame.draw.line(surf, (*SCOPE_COL, 180), muzzle, (ex, ey), 2)


# ---------------------------------------------------------------------------
# Dispatch table + public API
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Cairo dispatch (all mechs use high-quality cairo renderer when available)
# ---------------------------------------------------------------------------

try:
    from src.ui.cairo_renderer import render_mech_cairo as _render_mech_cairo
    _CAIRO = True
except Exception:
    _CAIRO = False

# Fallback pygame renderers (used when Cairo unavailable or mech not in cairo)
_PG_RENDERERS = {
    "titan":    draw_titan,
    "raptor":   draw_raptor,
    "colossus": draw_colossus,
    "phantom":  draw_phantom,
    "vanguard": draw_vanguard,
    "sniper":   draw_sniper,
}


def _make_cairo_dispatch(mech_id: str, pg_fallback):
    """Return a dispatch fn: tries Cairo first, falls back to pygame."""
    def _dispatch(surf: pygame.Surface, r: pygame.Rect,
                  color, team_color, walk_t=0.0, fire_t=-1.0):
        if _CAIRO:
            pg_surf = _render_mech_cairo(mech_id, r.w, r.h, color, team_color,
                                         walk_t, fire_t)
            if pg_surf is not None:
                surf.blit(pg_surf, (r.x, r.y))
                return
        pg_fallback(surf, r, color, team_color, walk_t=walk_t, fire_t=fire_t)
    return _dispatch


_RENDERERS = {mid: _make_cairo_dispatch(mid, pg) for mid, pg in _PG_RENDERERS.items()}

# ---------------------------------------------------------------------------
# Sprite dispatch – overrides Cairo for mechs that have PNG sprite sheets
# ---------------------------------------------------------------------------

try:
    from src.ui.sprite_renderer import draw_mech_sprite as _draw_mech_sprite, has_sprite as _has_sprite
    _SPRITES = True
except Exception:
    _SPRITES = False


def _make_sprite_dispatch(mech_id: str, cairo_fallback):
    """Sprite → Cairo/pygame fallback chain."""
    def _dispatch(surf: pygame.Surface, r: pygame.Rect,
                  color, team_color, walk_t=0.0, fire_t=-1.0):
        if _SPRITES and _draw_mech_sprite(surf, r, mech_id, color, team_color,
                                          walk_t, fire_t):
            return
        cairo_fallback(surf, r, color, team_color, walk_t=walk_t, fire_t=fire_t)
    return _dispatch


if _SPRITES:
    from src.ui.sprite_renderer import _SHEETS as _SPRITE_SHEETS
    for _mid in list(_SPRITE_SHEETS.keys()):
        if _mid in _RENDERERS:
            _RENDERERS[_mid] = _make_sprite_dispatch(_mid, _RENDERERS[_mid])


def draw_mech(surface: pygame.Surface, mech, tile_rect: pygame.Rect,
              pad: int = 2, walk_t: float = 0.0, fire_t: float = -1.0):
    """Draw the mech's WH40K art into tile_rect.

    walk_t  – 0.0-1.0 walk-cycle phase (drives leg swing).
    fire_t  – -1.0 = idle; 0.0-1.0 = firing animation progress.
    Team 1 faces right; Team 2 is mirrored.
    """
    iw = max(1, tile_rect.w - 2 * pad)
    ih = max(1, tile_rect.h - 2 * pad)

    _tc = {1: (80, 140, 255), 2: (255, 80, 80), 3: (80, 220, 100)}
    team_color = _tc.get(mech.team, (255, 80, 80))

    temp = pygame.Surface((iw, ih), pygame.SRCALPHA)
    renderer = _RENDERERS.get(mech.id, draw_vanguard)
    renderer(temp, pygame.Rect(0, 0, iw, ih), mech.color, team_color,
             walk_t=walk_t, fire_t=fire_t)

    if mech.team == 2:
        temp = pygame.transform.flip(temp, True, False)

    surface.blit(temp, (tile_rect.x + pad, tile_rect.y + pad))


def draw_mech_portrait(surface: pygame.Surface, mech_id: str,
                       color: Tuple, rect: pygame.Rect, team: int = 1,
                       walk_t: float = 0.0, fire_t: float = -1.0):
    """Draw a mech portrait directly into rect (no Mech object needed)."""
    iw = max(1, rect.w)
    ih = max(1, rect.h)
    team_color = (80, 140, 255) if team == 1 else (255, 80, 80)

    temp = pygame.Surface((iw, ih), pygame.SRCALPHA)
    renderer = _RENDERERS.get(mech_id, draw_vanguard)
    renderer(temp, pygame.Rect(0, 0, iw, ih), color, team_color,
             walk_t=walk_t, fire_t=fire_t)

    surface.blit(temp, rect.topleft)
