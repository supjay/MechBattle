"""Cairo-based high-quality sniper mech renderer.

Renders into a cairo.ImageSurface (ARGB32), converts to a pygame.Surface,
and caches by (size, colours, animation-frame) so each unique frame is only
rasterised once per session.

Public API
----------
render_sniper_cairo(w, h, color, team_color, walk_t, fire_t, flip=False)
    -> pygame.Surface  (SRCALPHA, ready to blit)
"""

import math
import cairo
import pygame
from typing import Tuple

# ---------------------------------------------------------------------------
# Animation helpers (self-contained, no circular import)
# ---------------------------------------------------------------------------

def _fire_frac(fire_t: float) -> float:
    if fire_t < 0:
        return 0.0
    if fire_t < 0.40:
        return math.sin(fire_t / 0.40 * math.pi * 0.5)
    elif fire_t < 0.55:
        return 1.0
    return 1.0 - math.sin((fire_t - 0.55) / 0.45 * math.pi * 0.5)

def _body_bob(walk_t: float) -> float:
    return abs(math.cos(walk_t * math.pi * 2)) * 2.0

def _leg_sw(walk_t: float, side: int) -> float:
    return math.sin(walk_t * math.pi * 2) * 3.0 * side

def _shoulder_rise(fire_t: float) -> float:
    if fire_t < 0:
        return 0.0
    return math.sin(min(fire_t / 0.55, 1.0) * math.pi) * 5.0

def _torso_lean(fire_t: float) -> float:
    if fire_t < 0:
        return 0.0
    return math.sin(min(fire_t / 0.55, 1.0) * math.pi) * 2.0

# ---------------------------------------------------------------------------
# Sprite cache
# ---------------------------------------------------------------------------

WALK_FRAMES = 8
FIRE_FRAMES = 6
_cache: dict = {}

def _frame_key(walk_t: float, fire_t: float):
    wf = int(walk_t * WALK_FRAMES) % WALK_FRAMES
    ff = -1 if fire_t < 0 else min(FIRE_FRAMES - 1, int(fire_t * FIRE_FRAMES))
    return wf, ff

# ---------------------------------------------------------------------------
# Cairo colour helpers
# ---------------------------------------------------------------------------

METAL_LIGHT = (162, 157, 148)
METAL_MID   = (98,  94,  88)
METAL_DARK  = (48,  46,  42)
METAL_SHEEN = (200, 196, 188)
SCOPE_COL   = (30,  200, 200)

def _n(v: float) -> float:
    """Clamp 0-1."""
    return min(1.0, max(0.0, v))

def _c(rgb: Tuple, f: float = 1.0, a: float = 1.0) -> Tuple:
    """RGB 0-255 tuple -> cairo RGBA 0-1 tuple, optionally scaled by f."""
    return (_n(rgb[0] / 255 * f), _n(rgb[1] / 255 * f), _n(rgb[2] / 255 * f), a)

def _blend_c(c1: Tuple, c2: Tuple, t: float) -> Tuple:
    return tuple(_n(a + (b - a) * t) for a, b in zip(_c(c1), _c(c2)))

# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

def _rrect(cr, x, y, w, h, radius):
    """Append a rounded-rectangle path."""
    r = min(radius, w / 2, h / 2)
    cr.arc(x + r,     y + r,     r, math.pi,       3 * math.pi / 2)
    cr.arc(x + w - r, y + r,     r, 3 * math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0,               math.pi / 2)
    cr.arc(x + r,     y + h - r, r, math.pi / 2,     math.pi)
    cr.close_path()


def _armor_grad(cr, x, y_top, y_bot, color, lo=0.28, hi=1.70):
    """Vertical armor gradient: bright at top, dark at bottom."""
    pat = cairo.LinearGradient(x, y_top, x, y_bot)
    pat.add_color_stop_rgba(0.00, *_c(color, hi))
    pat.add_color_stop_rgba(0.20, *_c(color, 1.25))
    pat.add_color_stop_rgba(0.55, *_c(color, 0.90))
    pat.add_color_stop_rgba(1.00, *_c(color, lo))
    cr.set_source(pat)


def _metal_grad(cr, x, y_top, y_bot):
    """Metallic gradient for structural parts."""
    pat = cairo.LinearGradient(x, y_top, x, y_bot)
    pat.add_color_stop_rgba(0.00, *_c(METAL_SHEEN, 1.0))
    pat.add_color_stop_rgba(0.30, *_c(METAL_LIGHT, 1.0))
    pat.add_color_stop_rgba(0.70, *_c(METAL_MID,   1.0))
    pat.add_color_stop_rgba(1.00, *_c(METAL_DARK,  0.85))
    cr.set_source(pat)


def _sphere_grad(cr, cx, cy, radius, color):
    """Metallic radial sphere gradient."""
    off = radius * 0.32
    pat = cairo.RadialGradient(cx - off, cy - off, 0, cx, cy, radius)
    pat.add_color_stop_rgba(0.00, *_c(color, 2.10))
    pat.add_color_stop_rgba(0.30, *_c(color, 1.30))
    pat.add_color_stop_rgba(0.70, *_c(color, 0.60))
    pat.add_color_stop_rgba(1.00, *_c(color, 0.18))
    cr.set_source(pat)


def _glow(cr, cx, cy, radius, color, alpha=0.85):
    """Soft additive glow circle."""
    pat = cairo.RadialGradient(cx, cy, 0, cx, cy, radius * 1.6)
    pat.add_color_stop_rgba(0.00, *_c(color, 1.8, alpha))
    pat.add_color_stop_rgba(0.40, *_c(color, 1.0, alpha * 0.55))
    pat.add_color_stop_rgba(1.00, *_c(color, 0.5, 0.0))
    cr.set_source(pat)
    cr.arc(cx, cy, radius * 1.6, 0, 2 * math.pi)
    cr.fill()
    # hard center dot
    cr.set_source_rgba(*_c(color, 2.0))
    cr.arc(cx, cy, max(0.5, radius * 0.25), 0, 2 * math.pi)
    cr.fill()


def _panel_line(cr, x0, y0, x1, y1, width=0.9):
    """Engraved panel groove line."""
    cr.set_line_width(width * 1.4)
    cr.set_source_rgba(0, 0, 0, 0.52)
    cr.move_to(x0, y0); cr.line_to(x1, y1); cr.stroke()
    # bright lip on one side
    dx, dy = x1 - x0, y1 - y0
    L = math.sqrt(dx * dx + dy * dy)
    if L > 0:
        ox, oy = -dy / L * 1.1, dx / L * 1.1
        cr.set_line_width(width * 0.6)
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.move_to(x0 + ox, y0 + oy); cr.line_to(x1 + ox, y1 + oy); cr.stroke()


def _rivet(cr, cx, cy, r=2.0):
    """Metallic bolt head."""
    _sphere_grad(cr, cx, cy, r, METAL_LIGHT)
    cr.arc(cx, cy, r, 0, 2 * math.pi); cr.fill()
    cr.set_source_rgba(0, 0, 0, 0.35)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.set_line_width(0.5); cr.stroke()


def _border(cr, color, width=1.0, alpha=0.55):
    """Stroke the current path as a dark border."""
    cr.set_source_rgba(*_c(color, 0.35, alpha))
    cr.set_line_width(width)
    cr.stroke_preserve()


def _drop_shadow(cr, alpha=0.18):
    """Fill current path as a soft drop shadow (offset already applied)."""
    cr.set_source_rgba(0, 0, 0, alpha)
    cr.fill_preserve()

# ---------------------------------------------------------------------------
# Sniper mech drawing
# ---------------------------------------------------------------------------

def _draw_sniper_cairo(cr, w: float, h: float,
                       color: Tuple, team_color: Tuple,
                       walk_t: float, fire_t: float):
    """Draw the sniper onto a cairo context of dimensions w×h."""

    ff     = _fire_frac(fire_t)
    bob    = _body_bob(walk_t)
    l_sw   = _leg_sw(walk_t,  1)
    r_sw   = _leg_sw(walk_t, -1)
    lean   = _torso_lean(fire_t)
    rise   = _shoulder_rise(fire_t)
    is_firing = fire_t >= 0

    def X(fx): return fx * w
    def Y(fy): return fy * h + bob

    # ----------------------------------------------------------------
    # FEET (rounded trapezoid – wider at front)
    # ----------------------------------------------------------------
    for lx, sw in ((0.19, l_sw), (0.81, r_sw)):
        fx0, fx1 = lx - 0.14, lx + 0.19
        fy_t, fy_b = 0.87, 0.95
        # shadow
        cr.save()
        cr.translate(1.5, 1.5)
        _rrect(cr, X(fx0), Y(fy_t) + sw, X(fx1) - X(fx0), (fy_b - fy_t) * h, 3)
        _drop_shadow(cr, 0.22); cr.new_path()
        cr.restore()
        # fill
        _rrect(cr, X(fx0), Y(fy_t) + sw, X(fx1) - X(fx0), (fy_b - fy_t) * h, 3)
        _armor_grad(cr, X(lx), Y(fy_t) + sw, Y(fy_b) + sw, color, lo=0.35, hi=1.30)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(team_color, 0.7, 0.5))
        cr.set_line_width(0.8); cr.stroke()
        # toe cap line
        toe_x = X(fx1 - 0.04)
        _panel_line(cr, toe_x, Y(fy_t) + sw, toe_x, Y(fy_b) + sw)

    # ----------------------------------------------------------------
    # SHINS (tapered – wider at knee, narrower at ankle)
    # ----------------------------------------------------------------
    for lx, sw in ((0.19, l_sw), (0.81, r_sw)):
        top_w, bot_w = 0.09, 0.07
        pts = [
            (X(lx - top_w), Y(0.68) + sw), (X(lx + top_w), Y(0.68) + sw),
            (X(lx + bot_w), Y(0.88) + sw), (X(lx - bot_w), Y(0.88) + sw),
        ]
        # shadow
        cr.save(); cr.translate(1, 1)
        cr.move_to(*pts[0])
        for p in pts[1:]: cr.line_to(*p)
        cr.close_path(); _drop_shadow(cr, 0.18); cr.new_path(); cr.restore()
        # fill
        cr.move_to(*pts[0])
        for p in pts[1:]: cr.line_to(*p)
        cr.close_path()
        _armor_grad(cr, X(lx), Y(0.68) + sw, Y(0.88) + sw, color)
        cr.fill_preserve(); _border(cr, color); cr.new_path()
        # shin plate accent (bright raised strip on front face)
        sp_x, sp_w = X(lx - 0.05), X(lx + 0.05) - X(lx - 0.05)
        sp_y, sp_h = Y(0.71) + sw, 0.11 * h
        _rrect(cr, sp_x, sp_y, sp_w, sp_h, 2)
        _armor_grad(cr, sp_x + sp_w * 0.5, sp_y, sp_y + sp_h, color, lo=0.55, hi=1.90)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(color, 1.60, 0.6)); cr.set_line_width(0.6); cr.stroke()
        # three panel lines across the shin
        for fy in (0.73, 0.77, 0.81):
            _panel_line(cr, X(lx - top_w + 0.01), Y(fy) + sw,
                            X(lx + top_w - 0.01), Y(fy) + sw, 0.7)

    # ----------------------------------------------------------------
    # KNEE JOINTS
    # ----------------------------------------------------------------
    for lx, sw in ((0.19, l_sw), (0.81, r_sw)):
        r = max(3, w * 0.06)
        cx, cy = X(lx), Y(0.68) + sw
        # shadow
        cr.set_source_rgba(0, 0, 0, 0.25)
        cr.arc(cx + 1, cy + 1, r, 0, 2 * math.pi); cr.fill()
        # rim (dark ring)
        cr.set_source_rgba(*_c(METAL_DARK, 0.85))
        cr.arc(cx, cy, r, 0, 2 * math.pi); cr.fill()
        # metallic sphere
        _sphere_grad(cr, cx, cy, r * 0.88, METAL_LIGHT)
        cr.arc(cx, cy, r * 0.88, 0, 2 * math.pi); cr.fill()
        # highlight ring
        cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.35))
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_line_width(0.7); cr.stroke()

    # ----------------------------------------------------------------
    # THIGHS (parallelogram leaning outward)
    # ----------------------------------------------------------------
    for lx, sw, dx_off in ((0.19, l_sw, -0.03), (0.81, r_sw, 0.03)):
        pts = [
            (X(lx - 0.07 + dx_off), Y(0.68) + sw),
            (X(lx + 0.07 + dx_off), Y(0.68) + sw),
            (X(lx + 0.06),          Y(0.48) + bob),
            (X(lx - 0.06),          Y(0.48) + bob),
        ]
        cr.move_to(*pts[0])
        for p in pts[1:]: cr.line_to(*p)
        cr.close_path()
        _armor_grad(cr, X(lx), Y(0.48), Y(0.68) + sw, color, lo=0.32, hi=1.60)
        cr.fill_preserve(); _border(cr, color); cr.new_path()
        # team colour stripe
        sy = Y(0.54) + bob
        cr.set_source_rgba(*_c(team_color, 1.0, 0.85))
        cr.set_line_width(2.0)
        cr.move_to(X(lx - 0.05), sy); cr.line_to(X(lx + 0.05), sy); cr.stroke()
        # hydraulic piston line
        cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.50))
        cr.set_line_width(1.0)
        cr.move_to(X(lx + 0.01), Y(0.67) + sw)
        cr.line_to(X(lx + 0.01), Y(0.51) + bob); cr.stroke()
        # side panel line
        _panel_line(cr, X(lx - 0.04 + dx_off), Y(0.60) + sw * 0.5 + bob * 0.5,
                        X(lx + 0.04 + dx_off), Y(0.60) + sw * 0.5 + bob * 0.5)

    # ----------------------------------------------------------------
    # HIP BLOCK (trapezoidal)
    # ----------------------------------------------------------------
    hp = [
        (X(0.26), Y(0.48)), (X(0.74), Y(0.48)),
        (X(0.69), Y(0.57)), (X(0.31), Y(0.57)),
    ]
    cr.move_to(*hp[0])
    for p in hp[1:]: cr.line_to(*p)
    cr.close_path()
    _armor_grad(cr, X(0.50), Y(0.48), Y(0.57), color, lo=0.40, hi=1.35)
    cr.fill_preserve(); _border(cr, color, 1.0); cr.new_path()
    # three rivets across hip
    for rfx in (0.35, 0.50, 0.65):
        _rivet(cr, X(rfx), Y(0.525), max(1.5, w * 0.013))
    # panel groove
    _panel_line(cr, X(0.28), Y(0.52), X(0.72), Y(0.52))

    # ----------------------------------------------------------------
    # HIP JOINTS
    # ----------------------------------------------------------------
    for lx in (0.27, 0.73):
        r = max(2.5, w * 0.05)
        cx, cy = X(lx), Y(0.48)
        cr.set_source_rgba(*_c(METAL_DARK, 0.85))
        cr.arc(cx, cy, r, 0, 2 * math.pi); cr.fill()
        _sphere_grad(cr, cx, cy, r * 0.85, METAL_LIGHT)
        cr.arc(cx, cy, r * 0.85, 0, 2 * math.pi); cr.fill()

    # ----------------------------------------------------------------
    # TORSO (trapezoidal, leaning forward during fire)
    # ----------------------------------------------------------------
    tor = [
        (X(0.29) + lean, Y(0.20)),
        (X(0.71) + lean, Y(0.20)),
        (X(0.69) + lean, Y(0.48)),
        (X(0.31) + lean, Y(0.48)),
    ]
    cr.move_to(*tor[0])
    for p in tor[1:]: cr.line_to(*p)
    cr.close_path()
    _armor_grad(cr, X(0.50) + lean, Y(0.20), Y(0.48), color, lo=0.30, hi=1.65)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.8, 0.60))
    cr.set_line_width(1.2); cr.stroke()

    # torso panel lines (horizontal grooves)
    for fy in (0.27, 0.33, 0.40, 0.45):
        lmargin, rmargin = 0.04, 0.04
        _panel_line(cr, X(0.29 + lmargin) + lean, Y(fy),
                        X(0.71 - rmargin) + lean, Y(fy))

    # chest inset panel
    cp_x = X(0.35) + lean;  cp_y = Y(0.27)
    cp_w = X(0.65) - X(0.35);  cp_h = 0.14 * h
    _rrect(cr, cp_x, cp_y, cp_w, cp_h, 3)
    _armor_grad(cr, cp_x + cp_w * 0.5, cp_y, cp_y + cp_h, color, lo=0.50, hi=2.0)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(color, 1.60, 0.45)); cr.set_line_width(0.7); cr.stroke()
    # hex stealth pattern on chest panel (small hexagonal imprints)
    hex_r = max(2.5, cp_w * 0.09)
    hex_step_x = hex_r * 1.9
    hex_step_y = hex_r * 1.65
    hx0 = cp_x + hex_r * 1.1
    hy0 = cp_y + hex_r * 1.1
    row = 0
    while hy0 + row * hex_step_y < cp_y + cp_h - hex_r:
        col = 0
        offset_x = (hex_step_x * 0.5) if row % 2 else 0
        while hx0 + offset_x + col * hex_step_x < cp_x + cp_w - hex_r:
            hcx = hx0 + offset_x + col * hex_step_x
            hcy = hy0 + row * hex_step_y
            pts = [(hcx + hex_r * math.cos(math.radians(a + 30)),
                    hcy + hex_r * math.sin(math.radians(a + 30))) for a in range(0, 360, 60)]
            cr.move_to(*pts[0])
            for p in pts[1:]: cr.line_to(*p)
            cr.close_path()
            cr.set_source_rgba(0, 0, 0, 0.20); cr.fill_preserve()
            cr.set_source_rgba(*_c(color, 1.50, 0.18)); cr.set_line_width(0.5); cr.stroke()
            col += 1
        row += 1

    # energy cell (right side of torso)
    ec_x = X(0.64) + lean;  ec_y = Y(0.27)
    ec_w = max(3, w * 0.045);  ec_h = 0.15 * h
    _rrect(cr, ec_x, ec_y, ec_w, ec_h, 2)
    cr.set_source_rgba(*_c(METAL_DARK)); cr.fill()
    segs = 3
    seg_h = (ec_h - 2) / segs
    for ci in range(segs):
        pct = (1 - ci / segs) if is_firing else 0.45
        _rrect(cr, ec_x + 1, ec_y + 1 + ci * seg_h, ec_w - 2, seg_h - 1, 1)
        cr.set_source_rgba(*_c(SCOPE_COL, 1.0, 0.70 * pct))
        cr.fill()

    # ----------------------------------------------------------------
    # SHOULDER PAULDRONS
    # ----------------------------------------------------------------
    for sx0, sx1 in ((0.20, 0.34), (0.66, 0.80)):
        pts = [
            (X(sx0) + lean,        Y(0.20)),
            (X(sx1) + lean,        Y(0.20)),
            (X(sx1 + 0.025) + lean, Y(0.295)),
            (X(sx0 - 0.025) + lean, Y(0.295)),
        ]
        cr.move_to(*pts[0])
        for p in pts[1:]: cr.line_to(*p)
        cr.close_path()
        _armor_grad(cr, X((sx0 + sx1) / 2) + lean, Y(0.20), Y(0.295),
                    color, lo=0.45, hi=1.80)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(color, 0.55, 0.60)); cr.set_line_width(0.8); cr.stroke()

    # ----------------------------------------------------------------
    # HEAD – hexagonal sensor pod
    # ----------------------------------------------------------------
    hcx = X(0.40) + lean
    hcy = Y(0.115)
    hr  = max(5, w * 0.095)
    hex_pts = [
        (hcx + hr * math.cos(math.radians(a)),
         hcy + hr * math.sin(math.radians(a)))
        for a in range(-150, 210, 60)
    ]
    # shadow
    cr.save(); cr.translate(1.5, 1.5)
    cr.move_to(*hex_pts[0])
    for p in hex_pts[1:]: cr.line_to(*p)
    cr.close_path(); _drop_shadow(cr, 0.25); cr.new_path(); cr.restore()
    # fill
    cr.move_to(*hex_pts[0])
    for p in hex_pts[1:]: cr.line_to(*p)
    cr.close_path()
    _armor_grad(cr, hcx, hcy - hr, hcy + hr, color, lo=0.38, hi=1.65)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.9, 0.80))
    cr.set_line_width(1.1); cr.stroke()
    # facet lines between hex vertices
    for i in range(len(hex_pts)):
        midx = (hcx + hex_pts[i][0]) / 2
        midy = (hcy + hex_pts[i][1]) / 2
        _panel_line(cr, hcx, hcy, midx, midy, 0.6)

    # visor slit (horizontal rectangle across center of hex)
    vw = hr * 1.0;  vh = max(3, hr * 0.32)
    vx, vy = hcx - vw / 2, hcy - vh / 2
    _rrect(cr, vx, vy, vw, vh, 2)
    cr.set_source_rgba(*_c(SCOPE_COL, 0.90, 0.20)); cr.fill_preserve()
    # visor glow
    _glow(cr, hcx, hcy, vw * 0.38, SCOPE_COL, 0.80 if is_firing else 0.48)
    # visor lens streaks
    cr.set_source_rgba(*_c(SCOPE_COL, 1.8, 0.75))
    cr.arc(hcx, hcy, min(vw / 2, vh / 2) * 0.9, 0, 2 * math.pi); cr.fill()
    cr.set_source_rgba(1, 1, 1, 0.30)
    cr.set_line_width(0.7)
    cr.move_to(vx + vw * 0.15, vy + vh * 0.25)
    cr.line_to(vx + vw * 0.55, vy + vh * 0.25); cr.stroke()

    # antenna
    ant_x = hcx + hr * 0.50
    ant_base_y = hcy - hr * 0.85
    ant_top_y  = ant_base_y - max(5, h * 0.06)
    cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.80))
    cr.set_line_width(1.2)
    cr.move_to(ant_x, ant_base_y); cr.line_to(ant_x, ant_top_y); cr.stroke()
    _glow(cr, ant_x, ant_top_y, max(2, h * 0.018), SCOPE_COL,
          0.90 if is_firing else 0.55)

    # ----------------------------------------------------------------
    # LEFT GRIP ARM
    # ----------------------------------------------------------------
    grip_y = Y(0.29) + bob - rise
    grip_x = X(0.60) + lean
    grip_w = max(4, w * 0.10);  grip_h = max(4, h * 0.13)
    _rrect(cr, grip_x, grip_y + 1, grip_w, grip_h, 3)
    _metal_grad(cr, grip_x, grip_y, grip_y + grip_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.6)); cr.set_line_width(0.7); cr.stroke()

    # ----------------------------------------------------------------
    # SNIPER RIFLE
    # ----------------------------------------------------------------
    barrel_ext = ff * w * 0.08
    rifle_cy   = Y(0.29) + bob - rise   # center-line y

    # --- Stock ---
    stk_x = X(0.63) + lean
    stk_w = max(6, w * 0.135)
    stk_h = max(6, h * 0.055)
    _rrect(cr, stk_x, rifle_cy - stk_h / 2, stk_w, stk_h, 3)
    _metal_grad(cr, stk_x, rifle_cy - stk_h / 2, rifle_cy + stk_h / 2)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.6)); cr.set_line_width(0.7); cr.stroke()
    # butt plate detail
    _panel_line(cr, stk_x + 2, rifle_cy - stk_h / 2 + 2,
                    stk_x + 2, rifle_cy + stk_h / 2 - 2, 0.8)

    # --- Receiver ---
    rcv_x = stk_x + stk_w
    rcv_w = max(6, w * 0.160)
    rcv_h = max(7, h * 0.062)
    _rrect(cr, rcv_x, rifle_cy - rcv_h / 2, rcv_w, rcv_h, 2)
    # receiver gets a side-lit metallic gradient
    pat = cairo.LinearGradient(rcv_x, rifle_cy - rcv_h / 2,
                               rcv_x, rifle_cy + rcv_h / 2)
    pat.add_color_stop_rgba(0.0, *_c(METAL_SHEEN, 1.1))
    pat.add_color_stop_rgba(0.3, *_c(METAL_LIGHT, 1.0))
    pat.add_color_stop_rgba(0.7, *_c(METAL_MID,   1.0))
    pat.add_color_stop_rgba(1.0, *_c(METAL_DARK,  0.8))
    cr.set_source(pat); cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 0.7, 0.55)); cr.set_line_width(0.7); cr.stroke()
    # ejection port
    ej_x = rcv_x + rcv_w * 0.35
    ej_w = max(3, rcv_w * 0.25)
    _rrect(cr, ej_x, rifle_cy - rcv_h / 2 + 1, ej_w, rcv_h * 0.45, 1)
    cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.9)); cr.fill()
    # serial number groove
    _panel_line(cr, rcv_x + rcv_w * 0.1, rifle_cy + rcv_h * 0.15,
                    rcv_x + rcv_w * 0.3, rifle_cy + rcv_h * 0.15, 0.6)

    # --- Magazine ---
    mag_x = rcv_x + rcv_w * 0.25
    mag_h = max(5, h * 0.10)
    mag_w = max(4, rcv_w * 0.35)
    _rrect(cr, mag_x, rifle_cy + rcv_h / 2, mag_w, mag_h, 2)
    _metal_grad(cr, mag_x, rifle_cy + rcv_h / 2, rifle_cy + rcv_h / 2 + mag_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.5)); cr.set_line_width(0.6); cr.stroke()
    # magazine floor plate
    _panel_line(cr, mag_x + 1, rifle_cy + rcv_h / 2 + mag_h - 2,
                    mag_x + mag_w - 1, rifle_cy + rcv_h / 2 + mag_h - 2, 0.7)

    # --- Barrel ---
    brl_x0 = rcv_x + rcv_w
    brl_x1 = X(0.97) + barrel_ext
    brl_d  = max(4, h * 0.028)  # barrel half-diameter
    # outer jacket (slightly thicker tube)
    _rrect(cr, brl_x0, rifle_cy - brl_d * 1.3,
               brl_x1 - brl_x0, brl_d * 2.6, brl_d * 0.8)
    _metal_grad(cr, brl_x0, rifle_cy - brl_d * 1.3, rifle_cy + brl_d * 1.3)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 0.7, 0.45)); cr.set_line_width(0.7); cr.stroke()
    # inner bore line
    cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.6))
    cr.set_line_width(brl_d * 0.45)
    cr.move_to(brl_x0, rifle_cy); cr.line_to(brl_x1, rifle_cy); cr.stroke()
    # top sheen
    cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.50))
    cr.set_line_width(brl_d * 0.35)
    cr.move_to(brl_x0, rifle_cy - brl_d * 0.55)
    cr.line_to(brl_x1, rifle_cy - brl_d * 0.55); cr.stroke()

    # barrel rings (3 evenly spaced)
    for rng_f in (0.06, 0.24, 0.44):
        rx = brl_x0 + (brl_x1 - brl_x0) * rng_f
        rng_w = max(2, w * 0.012)
        _rrect(cr, rx - rng_w / 2, rifle_cy - brl_d * 1.55,
               rng_w, brl_d * 3.1, 1)
        _metal_grad(cr, rx, rifle_cy - brl_d * 1.55, rifle_cy + brl_d * 1.55)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(METAL_DARK, 0.7, 0.5)); cr.set_line_width(0.5); cr.stroke()

    # --- Handguard ---
    hg_x = brl_x0 + (brl_x1 - brl_x0) * 0.10
    hg_w = max(5, (brl_x1 - brl_x0) * 0.20)
    hg_h = max(5, brl_d * 4.0)
    _rrect(cr, hg_x, rifle_cy - hg_h / 2, hg_w, hg_h, 2)
    _armor_grad(cr, hg_x + hg_w * 0.5, rifle_cy - hg_h / 2, rifle_cy + hg_h / 2,
                METAL_MID, lo=0.40, hi=1.45)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 0.7, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # vent slots
    for vi in range(3):
        vx = hg_x + hg_w * (0.25 + vi * 0.25)
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.set_line_width(0.8)
        cr.move_to(vx, rifle_cy - hg_h * 0.30)
        cr.line_to(vx, rifle_cy + hg_h * 0.30); cr.stroke()

    # --- Scope Rail + Scope Body ---
    rail_x0 = rcv_x + 2
    rail_x1 = brl_x0 + (brl_x1 - brl_x0) * 0.46
    rail_y  = rifle_cy - brl_d * 1.3 - max(1, h * 0.005)
    cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.65))
    cr.set_line_width(max(1, h * 0.007))
    cr.move_to(rail_x0, rail_y); cr.line_to(rail_x1, rail_y); cr.stroke()
    # scope body
    sc_x = rail_x0 + (rail_x1 - rail_x0) * 0.28
    sc_w = max(5, (rail_x1 - rail_x0) * 0.40)
    sc_h = max(4, h * 0.038)
    sc_y = rail_y - sc_h
    _rrect(cr, sc_x, sc_y, sc_w, sc_h, sc_h / 2)
    _metal_grad(cr, sc_x, sc_y, sc_y + sc_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 0.8, 0.55)); cr.set_line_width(0.7); cr.stroke()
    # scope lens
    lens_cx = sc_x + sc_w + max(2, sc_h * 0.4)
    lens_cy = sc_y + sc_h / 2
    lens_r  = sc_h / 2 + max(1, h * 0.006)
    g_a = 0.70 + ff * 0.20
    _glow(cr, lens_cx, lens_cy, lens_r, SCOPE_COL, g_a)
    cr.set_source_rgba(*_c(SCOPE_COL, 1.3, 0.90))
    cr.arc(lens_cx, lens_cy, lens_r * 0.55, 0, 2 * math.pi); cr.fill()
    # lens glint
    cr.set_source_rgba(1, 1, 1, 0.55)
    cr.arc(lens_cx - lens_r * 0.25, lens_cy - lens_r * 0.25,
           lens_r * 0.28, 0, 2 * math.pi); cr.fill()
    # scope elevation knob
    cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.80))
    cr.arc(sc_x + sc_w * 0.55, sc_y - max(1, h * 0.01),
           max(1, h * 0.013), 0, 2 * math.pi); cr.fill()

    # --- Suppressor ---
    sup_x = brl_x1 - max(6, w * 0.065)
    sup_w = max(6, w * 0.072)
    sup_h = max(7, brl_d * 3.6)
    _rrect(cr, sup_x, rifle_cy - sup_h / 2, sup_w, sup_h, sup_h / 2.4)
    _metal_grad(cr, sup_x, rifle_cy - sup_h / 2, rifle_cy + sup_h / 2)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.5)); cr.set_line_width(0.7); cr.stroke()
    # vent channels
    for vi in range(4):
        vy = rifle_cy - sup_h / 2 + (vi + 1) * sup_h / 5
        cr.set_source_rgba(0, 0, 0, 0.38)
        cr.set_line_width(0.8)
        cr.move_to(sup_x + 2, vy); cr.line_to(sup_x + sup_w - 2, vy); cr.stroke()
    # muzzle end cap
    _sphere_grad(cr, brl_x1 - 1, rifle_cy, sup_h / 2 - 1, METAL_LIGHT)
    cr.arc(brl_x1 - 1, rifle_cy, sup_h / 2 - 1, -math.pi / 2, math.pi / 2); cr.fill()

    # --- Bipod (visible when stationary) ---
    if walk_t < 0.12 or walk_t > 0.88:
        bpd_x  = brl_x0 + (brl_x1 - brl_x0) * 0.09
        bpd_y0 = rifle_cy + brl_d * 1.4
        bpd_y1 = bpd_y0 + max(8, h * 0.085)
        cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.80))
        cr.set_line_width(max(1, h * 0.012))
        cr.move_to(bpd_x, bpd_y0)
        cr.line_to(bpd_x - max(4, w * 0.035), bpd_y1); cr.stroke()
        cr.move_to(bpd_x, bpd_y0)
        cr.line_to(bpd_x + max(4, w * 0.035), bpd_y1); cr.stroke()
        # feet
        for bfx in (-1, 1):
            foot_cx = bpd_x + bfx * max(4, w * 0.035)
            cr.set_source_rgba(*_c(METAL_LIGHT, 1.0, 0.80))
            cr.arc(foot_cx, bpd_y1, max(1, h * 0.010), 0, 2 * math.pi); cr.fill()

    # --- Muzzle Flash ---
    if is_firing and ff > 0.35:
        muzz_x = brl_x1 + max(2, w * 0.01)
        muzz_y = rifle_cy
        fs = (ff - 0.35) * max(8, w * 0.06) * (1 - ff)
        if fs > 0.5:
            _glow(cr, muzz_x + fs / 2, muzz_y, fs, SCOPE_COL, 0.92)
            # star rays
            for angle in (0, 60, 120, 180, 240, 300):
                rad = math.radians(angle)
                ex = muzz_x + math.cos(rad) * fs * 1.6
                ey = muzz_y + math.sin(rad) * fs * 1.6
                cr.set_source_rgba(*_c(SCOPE_COL, 1.6, 0.65))
                cr.set_line_width(max(1, fs * 0.18))
                cr.move_to(muzz_x, muzz_y); cr.line_to(ex, ey); cr.stroke()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_sniper_cairo(w: int, h: int,
                        color: Tuple, team_color: Tuple,
                        walk_t: float = 0.0, fire_t: float = -1.0,
                        flip: bool = False) -> pygame.Surface:
    """Render sniper mech to a pygame.Surface using Cairo.

    Results are cached by (w, h, color, team_color, walk_frame, fire_frame, flip).
    """
    wf, ff = _frame_key(walk_t, fire_t)
    key = (w, h, color, team_color, wf, ff, flip)
    if key in _cache:
        return _cache[key]

    # Resolve actual walk_t / fire_t from discretized frame index
    resolved_walk = wf / WALK_FRAMES
    resolved_fire = -1.0 if ff < 0 else (ff + 0.5) / FIRE_FRAMES

    # Create cairo surface
    cr_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(cr_surf)
    cr.set_antialias(cairo.ANTIALIAS_BEST)

    _draw_sniper_cairo(cr, w, h, color, team_color, resolved_walk, resolved_fire)

    # Convert to pygame
    # Cairo ARGB32 little-endian = B,G,R,A bytes in memory
    # Swap to R,G,B,A for pygame using numpy
    import numpy as np
    data = cr_surf.get_data()
    arr  = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
    rgba = np.ascontiguousarray(arr[:, :, [2, 1, 0, 3]])
    pg_surf = pygame.image.frombytes(bytes(rgba), (w, h), 'RGBA')

    if flip:
        pg_surf = pygame.transform.flip(pg_surf, True, False)

    _cache[key] = pg_surf
    return pg_surf


def clear_cache():
    """Clear the sprite cache (call on resize or colour change)."""
    _cache.clear()
