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


# ===========================================================================
# TITAN  -  Space Marine Dreadnought
# ===========================================================================

def _draw_titan_cairo(cr, w: float, h: float,
                      color, team_color, walk_t: float, fire_t: float):
    track_phase = walk_t
    bob   = _body_bob(walk_t)
    lean  = _torso_lean(fire_t)
    ff    = _fire_frac(fire_t)
    rise  = _shoulder_rise(fire_t)
    is_firing = fire_t >= 0

    GLOW_RED  = (255, 60,  25)
    GLOW_ORG  = (255, 145, 30)

    def X(fx): return fx * w
    def Y(fy): return fy * h

    # --- Track-block legs ---
    for lx0, lx1 in ((0.08, 0.43), (0.57, 0.92)):
        tx, ty = X(lx0), Y(0.66) + bob
        tw, th = X(lx1) - X(lx0), Y(0.97) - Y(0.66)
        # shadow
        cr.save(); cr.translate(2, 2)
        _rrect(cr, tx, ty, tw, th, 4)
        cr.set_source_rgba(0, 0, 0, 0.20); cr.fill(); cr.restore()
        # track body
        _rrect(cr, tx, ty, tw, th, 4)
        _metal_grad(cr, tx, ty, ty + th)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(METAL_MID, 0.6, 0.5)); cr.set_line_width(0.8); cr.stroke()
        # animated tread lines
        seg_w = tw / 7.0
        offset = (track_phase * tw) % seg_w
        x_pos = tx + offset
        while x_pos < tx + tw:
            if tx + 2 < x_pos < tx + tw - 2:
                cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.55))
                cr.set_line_width(1.2)
                cr.move_to(x_pos, ty + 3); cr.line_to(x_pos, ty + th - 4); cr.stroke()
            x_pos += seg_w
        # road wheels
        for wx_f in (lx0 + 0.03, (lx0 + lx1) / 2, lx1 - 0.03):
            wcx, wcy = X(wx_f), Y(0.66) + bob + th / 2
            _sphere_grad(cr, wcx - 2, wcy - 2, max(3, w * 0.028), METAL_LIGHT)
            cr.arc(wcx, wcy, max(3, w * 0.028), 0, 2*math.pi); cr.fill()
            cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.45))
            cr.arc(wcx, wcy, max(3, w * 0.028), 0, 2*math.pi)
            cr.set_line_width(0.6); cr.stroke()
        # skirt plate on bottom
        _rrect(cr, tx + 1, ty + th - 4, tw - 2, 4, 2)
        cr.set_source_rgba(*_c(METAL_MID, 1.2, 0.70)); cr.fill()

    # --- Body ---
    bx = X(0.16) - lean;  by = Y(0.22) + bob
    bw = X(0.68);          bh = Y(0.46)
    cr.save(); cr.translate(2, 2)
    _rrect(cr, bx, by, bw, bh, 5)
    cr.set_source_rgba(0, 0, 0, 0.22); cr.fill(); cr.restore()
    _rrect(cr, bx, by, bw, bh, 5)
    _armor_grad(cr, bx + bw / 2, by, by + bh, color, lo=0.28, hi=1.65)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.85, 0.65)); cr.set_line_width(1.2); cr.stroke()
    # vertical center groove
    _panel_line(cr, bx + bw / 2, by + 4, bx + bw / 2, by + bh - 4)
    # horizontal cross-hair
    cx2, cy2 = bx + bw / 2, by + bh / 2 + 2
    cr.set_source_rgba(*_c(team_color, 1.0, 0.80)); cr.set_line_width(1.5)
    cr.move_to(cx2 - 10, cy2); cr.line_to(cx2 + 10, cy2); cr.stroke()
    cr.move_to(cx2, cy2 - 10); cr.line_to(cx2, cy2 + 10); cr.stroke()
    # targeting reticle circle
    _glow(cr, cx2, cy2, max(4, bw * 0.12), team_color, 0.38)
    cr.set_source_rgba(*_c(team_color, 1.2, 0.75))
    cr.arc(cx2, cy2, max(4, bw * 0.12), 0, 2*math.pi)
    cr.set_line_width(1.0); cr.stroke()
    # corner rivets
    for rx2, ry2 in ((bx+5,by+5),(bx+bw-6,by+5),(bx+5,by+bh-6),(bx+bw-6,by+bh-6)):
        _rivet(cr, rx2, ry2, max(1.5, w * 0.014))
    # horizontal vent lines
    for vy_f in (0.30, 0.40, 0.50):
        _panel_line(cr, bx + 8, Y(vy_f) + bob, bx + bw - 8, Y(vy_f) + bob)

    # --- Shoulder plates ---
    for sx0, sx1 in ((0.02, 0.19), (0.81, 0.98)):
        spx, spy = X(sx0) - lean, Y(0.22) + bob
        spw, sph = X(sx1) - X(sx0), Y(0.17)
        _rrect(cr, spx, spy, spw, sph, 4)
        _armor_grad(cr, spx + spw/2, spy, spy + sph, METAL_DARK, lo=0.4, hi=1.3)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(team_color, 0.7, 0.55)); cr.set_line_width(0.8); cr.stroke()
        _rivet(cr, spx + spw/2, spy + sph/2, max(1.5, w * 0.013))

    # --- Left arm: Power Fist ---
    fire_off = ff * X(0.06)
    fist_x = X(0.0) - fire_off - lean
    fist_y = Y(0.29) + bob - rise
    fist_w = X(0.16);  fist_h = Y(0.36)
    _rrect(cr, fist_x, fist_y, fist_w, fist_h, 3)
    _metal_grad(cr, fist_x, fist_y, fist_y + fist_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.5)); cr.set_line_width(0.7); cr.stroke()
    # knuckle bars
    kbase = fist_y + fist_h * 0.58
    for ki in range(3):
        ky = kbase + ki * fist_h * 0.12
        _rrect(cr, fist_x + 2, ky, fist_w - 4, max(3, fist_h * 0.09), 1)
        cr.set_source_rgba(*_c(METAL_LIGHT, 1.1, 0.80)); cr.fill()
    # hydraulic line
    cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.55)); cr.set_line_width(1.0)
    cr.move_to(fist_x + fist_w/2, fist_y + 3)
    cr.line_to(fist_x + fist_w/2, fist_y + fist_h * 0.50); cr.stroke()
    # claw tips
    claw_extra = ff * 5
    for ci in range(3):
        cx3 = fist_x + 3 + ci * (fist_w - 6) / 2
        cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.75))
        cr.set_line_width(max(1, fist_w * 0.10))
        cr.move_to(cx3, fist_y + fist_h)
        cr.line_to(cx3 - 1, fist_y + fist_h + 5 + claw_extra); cr.stroke()

    # --- Right arm: Missile Pod ---
    sh_drop = ff * 2
    pod_fire = ff * X(0.04)
    pod_x = X(0.84) + pod_fire - lean
    pod_y = Y(0.28) + bob + sh_drop
    pod_w = X(0.15);  pod_h = Y(0.36)
    _rrect(cr, pod_x, pod_y, pod_w, pod_h, 3)
    _metal_grad(cr, pod_x, pod_y, pod_y + pod_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.6, 0.5)); cr.set_line_width(0.8); cr.stroke()
    # top cap
    _rrect(cr, pod_x + 1, pod_y + 1, pod_w - 2, max(4, pod_h * 0.09), 2)
    cr.set_source_rgba(*_c(METAL_LIGHT, 1.0, 0.75)); cr.fill()
    # launch tubes (3)
    tube_h = max(3, (pod_h - pod_h * 0.14 - 6) / 3)
    for ti in range(3):
        ty2 = pod_y + pod_h * 0.14 + 3 + ti * (tube_h + 2)
        _rrect(cr, pod_x + 2, ty2, pod_w - 4, tube_h, 1)
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.90)); cr.fill()
        # warhead nose
        cr.set_source_rgba(*_c(GLOW_RED, 0.8 if is_firing and ti == 1 else 0.5, 0.85))
        cr.arc(pod_x + 5, ty2 + tube_h / 2, max(1.5, tube_h * 0.35), 0, 2*math.pi); cr.fill()
        if is_firing and ti == 1:
            _glow(cr, pod_x + 5, ty2 + tube_h / 2, tube_h * 0.7, GLOW_ORG, 0.55)

    # --- Head ---
    hl = _torso_lean(fire_t) * 1.5
    head_x = X(0.28) - hl;  head_y = Y(0.03) + bob
    head_w = X(0.44);        head_h = Y(0.20)
    cr.save(); cr.translate(1.5, 1.5)
    _rrect(cr, head_x, head_y, head_w, head_h, 6)
    cr.set_source_rgba(0, 0, 0, 0.22); cr.fill(); cr.restore()
    _rrect(cr, head_x, head_y, head_w, head_h, 6)
    _armor_grad(cr, head_x + head_w/2, head_y, head_y + head_h, METAL_DARK, lo=0.35, hi=1.30)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.9, 0.70)); cr.set_line_width(1.0); cr.stroke()
    # T-visor slit
    vx, vy = head_x + 4, head_y + head_h/2 - max(2, head_h*0.18)
    vw, vh = head_w - 8, max(4, head_h * 0.36)
    _rrect(cr, vx, vy, vw, vh, 2)
    v_alpha = 0.90 if is_firing else 0.65
    _glow(cr, vx + vw/2, vy + vh/2, vw * 0.45, GLOW_RED, v_alpha)
    cr.set_source_rgba(*_c(GLOW_RED, 1.0, 0.85))
    cr.arc(vx + vw/2, vy + vh/2, min(vw/2, vh/2) * 0.85, 0, 2*math.pi); cr.fill()
    # crest antenna stubs
    for ax in (head_x + head_w*0.3, head_x + head_w*0.5, head_x + head_w*0.7):
        cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.70)); cr.set_line_width(1.2)
        cr.move_to(ax, head_y); cr.line_to(ax, head_y - max(3, h*0.04)); cr.stroke()
        cr.set_source_rgba(*_c(METAL_LIGHT, 1.0, 0.75))
        cr.arc(ax, head_y - max(3, h*0.04), max(1, h*0.006), 0, 2*math.pi); cr.fill()


# ===========================================================================
# RAPTOR  -  Imperial Guard Sentinel (chicken-walker)
# ===========================================================================

def _draw_raptor_cairo(cr, w: float, h: float,
                       color, team_color, walk_t: float, fire_t: float):
    l_sw = _leg_sw(walk_t,  1) * 1.67
    r_sw = _leg_sw(walk_t, -1) * 1.67
    l_ank = _leg_sw(walk_t, -1) * 1.0
    r_ank = _leg_sw(walk_t,  1) * 1.0
    ff = _fire_frac(fire_t)
    is_firing = fire_t >= 0

    GLOW_RED  = (255, 60,  25)
    GLOW_BLU  = (70,  195, 255)

    def X(fx): return fx * w
    def Y(fy): return fy * h

    # --- Reverse-knee legs ---
    for hip_fx, knee_fx, ank_fx, foot_fx, sw, ank_sw, side in (
        (0.33, 0.17, 0.22, 0.27, l_sw, l_ank, -1),
        (0.67, 0.83, 0.78, 0.73, r_sw, r_ank,  1),
    ):
        hip   = (X(hip_fx),  Y(0.50))
        knee  = (X(knee_fx), Y(0.71) + sw)
        ankle = (X(ank_fx),  Y(0.83) + ank_sw)
        foot  = (X(foot_fx), Y(0.93))

        lw = max(2, w * 0.040)
        # upper leg (hip->knee)
        pat = cairo.LinearGradient(hip[0], hip[1], knee[0], knee[1])
        pat.add_color_stop_rgba(0, *_c(METAL_SHEEN, 1.0)); pat.add_color_stop_rgba(1, *_c(METAL_DARK, 0.8))
        cr.set_source(pat); cr.set_line_width(lw)
        cr.move_to(*hip); cr.line_to(*knee); cr.stroke()
        # hydraulic piston
        po = 3 * side
        cr.set_source_rgba(*_c(METAL_MID, 0.9, 0.60)); cr.set_line_width(max(1, lw*0.45))
        cr.move_to(hip[0]+po, hip[1]+4); cr.line_to(knee[0]+po, knee[1]-4); cr.stroke()
        # shin (knee->ankle)
        cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.80)); cr.set_line_width(lw * 0.85)
        cr.move_to(*knee); cr.line_to(*ankle); cr.stroke()
        # foot segment (ankle->foot)
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.75)); cr.set_line_width(lw * 0.70)
        cr.move_to(*ankle); cr.line_to(*foot); cr.stroke()
        # knee joint sphere
        kr = max(4, w * 0.045)
        _sphere_grad(cr, knee[0]-kr*0.3, knee[1]-kr*0.3, kr, METAL_LIGHT)
        cr.arc(*knee, kr, 0, 2*math.pi); cr.fill()
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.4))
        cr.arc(*knee, kr, 0, 2*math.pi); cr.set_line_width(0.6); cr.stroke()
        # ankle joint
        ar = max(2.5, w * 0.028)
        _sphere_grad(cr, ankle[0]-ar*0.3, ankle[1]-ar*0.3, ar, METAL_MID)
        cr.arc(*ankle, ar, 0, 2*math.pi); cr.fill()
        # foot plate
        fp_w = max(12, w * 0.14)
        fp_h = max(4, h * 0.025)
        _rrect(cr, foot[0]-fp_w/2, foot[1]-fp_h/2, fp_w, fp_h, 2)
        _metal_grad(cr, foot[0], foot[1]-fp_h/2, foot[1]+fp_h/2)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.5); cr.stroke()
        # toe spurs
        for tsx in (-1, 1):
            cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.65)); cr.set_line_width(max(1, lw*0.50))
            cr.move_to(foot[0]+tsx*fp_w*0.35, foot[1]+fp_h/2)
            cr.line_to(foot[0]+tsx*(fp_w*0.35+3*side), foot[1]+fp_h/2+max(3, h*0.03)); cr.stroke()

    # --- Cockpit body ---
    bx, by = X(0.27), Y(0.18)
    bw, bh = X(0.46), Y(0.35)
    cr.save(); cr.translate(1.5, 1.5)
    _rrect(cr, bx, by, bw, bh, 5)
    cr.set_source_rgba(0,0,0,0.20); cr.fill(); cr.restore()
    _rrect(cr, bx, by, bw, bh, 5)
    _armor_grad(cr, bx + bw/2, by, by + bh, color, lo=0.30, hi=1.60)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.85, 0.65)); cr.set_line_width(1.1); cr.stroke()
    # canopy glass (lighter upper panel)
    canopy_h = bh * 0.42
    _rrect(cr, bx + 2, by + 2, bw - 4, canopy_h, 4)
    pat2 = cairo.LinearGradient(bx, by, bx, by + canopy_h)
    pat2.add_color_stop_rgba(0.0, *_c(color, 1.80, 0.70))
    pat2.add_color_stop_rgba(0.5, *_c(color, 1.30, 0.55))
    pat2.add_color_stop_rgba(1.0, *_c(color, 0.90, 0.30))
    cr.set_source(pat2); cr.fill()
    # canopy glint
    cr.set_source_rgba(1, 1, 1, 0.40); cr.set_line_width(1.5)
    cr.move_to(bx + bw*0.12, by + 4); cr.line_to(bx + bw*0.40, by + canopy_h - 4); cr.stroke()
    # vent lines on lower body
    for vy_f in (0.60, 0.80):
        _panel_line(cr, bx + 5, by + bh * vy_f, bx + bw - 5, by + bh * vy_f)
    # leg attachment lines
    cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.50)); cr.set_line_width(2.0)
    cr.move_to(bx + bw*0.30, by + bh); cr.line_to(X(0.33), Y(0.50)); cr.stroke()
    cr.move_to(bx + bw*0.70, by + bh); cr.line_to(X(0.67), Y(0.50)); cr.stroke()

    # --- Left arm: Laser Cannon ---
    fire_tilt = ff * 6
    sh_rise2 = _shoulder_rise(fire_t) * 0.60
    arm_y = Y(0.27) + fire_tilt - sh_rise2
    a0 = (bx - 2, arm_y)
    a1 = (X(0.02), arm_y)
    # cannon tube
    tube_r = max(2, h * 0.022)
    _rrect(cr, a1[0], arm_y - tube_r, a0[0]-a1[0], tube_r*2, tube_r)
    _metal_grad(cr, a1[0], arm_y - tube_r, arm_y + tube_r)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 0.6, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # heat dissipation rings
    for fi in range(4):
        ring_x = a1[0] + (a0[0]-a1[0]) * (0.15 + fi * 0.22)
        _rrect(cr, ring_x - max(1, w*0.008), arm_y - tube_r*1.35,
               max(2, w*0.016), tube_r*2.7, 1)
        _metal_grad(cr, ring_x, arm_y - tube_r*1.35, arm_y + tube_r*1.35)
        cr.fill()
    # muzzle glow
    g_a = 0.80 if is_firing else 0.45
    _glow(cr, a1[0] + 2, arm_y, tube_r * 2.2, GLOW_RED, g_a)
    cr.set_source_rgba(*_c(GLOW_RED, 1.3, 0.90))
    cr.arc(a1[0]+2, arm_y, tube_r * 0.7, 0, 2*math.pi); cr.fill()
    # laser streak when firing
    if is_firing and ff < 0.90:
        streak_a = max(0, 1.0 - ff * 1.8)
        cr.set_source_rgba(1.0, 0.7, 0.15, streak_a * 0.80)
        cr.set_line_width(tube_r * 0.6)
        cr.move_to(a1[0]+2, arm_y); cr.line_to(a1[0] - max(10, w*0.08), arm_y); cr.stroke()

    # --- Right arm: Autocannon ---
    arm2_y = Y(0.27) + Y(0.03)
    b_ext  = ff * X(0.06)
    b0 = (bx + bw + 2, arm2_y)
    b1 = (X(0.98) + b_ext, arm2_y)
    sep = max(2, h * 0.016)
    # housing block
    hb_w = max(6, w * 0.06)
    _rrect(cr, b0[0]-2, arm2_y - sep*2.5, hb_w, sep*5, 2)
    _metal_grad(cr, b0[0]-2, arm2_y - sep*2.5, arm2_y + sep*2.5)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # twin barrels
    for dy in (-sep, sep):
        cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.80)); cr.set_line_width(sep * 1.2)
        cr.move_to(b0[0]+hb_w-2, arm2_y+dy); cr.line_to(b1[0], arm2_y+dy); cr.stroke()
        cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.45)); cr.set_line_width(sep*0.4)
        cr.move_to(b0[0]+hb_w-2, arm2_y+dy); cr.line_to(b1[0], arm2_y+dy); cr.stroke()
        # muzzle cap
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.80))
        cr.arc(b1[0], arm2_y+dy, sep*0.7, 0, 2*math.pi); cr.fill()

    # --- Head ---
    hs = -_torso_lean(fire_t) * 1.5
    hx, hy = X(0.32) + hs, Y(0.03)
    hw, hh = X(0.36), Y(0.16)
    _rrect(cr, hx, hy, hw, hh, 4)
    _armor_grad(cr, hx+hw/2, hy, hy+hh, METAL_DARK, lo=0.38, hi=1.25)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.85, 0.65)); cr.set_line_width(0.9); cr.stroke()
    # sensor eye (right side)
    ex = hx + hw - max(5, hw*0.25)
    ey = hy + hh/2
    er = max(2, hh*0.28)
    _glow(cr, ex, ey, er*1.8, GLOW_RED, 0.65 if is_firing else 0.40)
    cr.set_source_rgba(*_c(GLOW_RED, 1.2, 0.85))
    cr.arc(ex, ey, er, 0, 2*math.pi); cr.fill()
    # blue comms dot (left side)
    _glow(cr, hx + hw*0.2, ey, er*0.9, GLOW_BLU, 0.50)
    cr.set_source_rgba(*_c(GLOW_BLU, 1.1, 0.80))
    cr.arc(hx + hw*0.2, ey, er*0.55, 0, 2*math.pi); cr.fill()
    # antenna pair
    for ax_f, ax_off in ((0.35, -2), (0.65, 2)):
        ax = hx + hw*ax_f
        cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.65)); cr.set_line_width(1.0)
        cr.move_to(ax, hy); cr.line_to(ax + ax_off, hy - max(4, h*0.04)); cr.stroke()
        cr.set_source_rgba(*_c(METAL_LIGHT, 1.0, 0.70))
        cr.arc(ax + ax_off, hy - max(4, h*0.04), max(1, h*0.006), 0, 2*math.pi); cr.fill()


# ===========================================================================
# COLOSSUS  -  Imperial Knight / Reaver Titan
# ===========================================================================

def _draw_colossus_cairo(cr, w: float, h: float,
                         color, team_color, walk_t: float, fire_t: float):
    sway  = math.sin(walk_t * math.pi * 2) * 2.0
    dip   = _body_bob(walk_t)
    track_ph = walk_t
    ff    = _fire_frac(fire_t)
    is_firing = fire_t >= 0

    GLOW_RED = (255, 60,  25)
    GLOW_ORG = (255, 145, 30)

    def X(fx): return fx * w
    def Y(fy): return fy * h

    # --- Tank track ---
    tx, ty = X(0.03), Y(0.80)
    tw, th = X(0.94), Y(0.19)
    cr.save(); cr.translate(2, 2)
    _rrect(cr, tx, ty, tw, th, 3)
    cr.set_source_rgba(0,0,0,0.22); cr.fill(); cr.restore()
    _rrect(cr, tx, ty, tw, th, 3)
    _metal_grad(cr, tx, ty, ty+th)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.45)); cr.set_line_width(0.8); cr.stroke()
    # track pad lines
    seg_w2 = tw / 9.0
    offset2 = (track_ph * tw) % seg_w2
    xp = tx + offset2
    while xp < tx + tw:
        if tx + 2 < xp < tx + tw - 2:
            cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.42)); cr.set_line_width(1.0)
            cr.move_to(xp, ty+2); cr.line_to(xp, ty+4); cr.stroke()
        xp += seg_w2
    # drive wheels (5)
    for wi in range(5):
        wx2 = tx + 5 + wi * (tw-10)/4
        wy2 = ty + th/2
        cr.set_source_rgba(*_c(METAL_DARK, 0.9, 0.80))
        cr.arc(wx2, wy2, max(3, th*0.34), 0, 2*math.pi); cr.fill()
        _sphere_grad(cr, wx2-2, wy2-2, max(2, th*0.26), METAL_LIGHT)
        cr.arc(wx2, wy2, max(2, th*0.26), 0, 2*math.pi); cr.fill()
    # lower hull housing
    hx3, hy3 = X(0.03), Y(0.66)
    hw3, hh3 = X(0.94), Y(0.15)
    _rrect(cr, hx3, hy3, hw3, hh3, 2)
    _armor_grad(cr, hx3+hw3/2, hy3, hy3+hh3, METAL_DARK, lo=0.40, hi=1.20)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.40)); cr.set_line_width(0.7); cr.stroke()

    # --- Massive carapace body ---
    bx, by = X(0.09) + sway, Y(0.17) + dip
    bw, bh = X(0.82), Y(0.50)
    cr.save(); cr.translate(2, 2)
    _rrect(cr, bx, by, bw, bh, 4)
    cr.set_source_rgba(0,0,0,0.22); cr.fill(); cr.restore()
    _rrect(cr, bx, by, bw, bh, 4)
    _armor_grad(cr, bx+bw/2, by, by+bh, color, lo=0.25, hi=1.60)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.85, 0.65)); cr.set_line_width(1.4); cr.stroke()
    # heraldic shield polygon
    scx, scy = bx+bw/2, by+bh*0.45
    shield_r = min(bw, bh) * 0.26
    sh_pts = [
        (scx,              scy - shield_r),
        (scx + shield_r,   scy - shield_r*0.5),
        (scx + shield_r*0.8, scy + shield_r*0.2),
        (scx,              scy + shield_r),
        (scx - shield_r*0.8, scy + shield_r*0.2),
        (scx - shield_r,   scy - shield_r*0.5),
    ]
    cr.move_to(*sh_pts[0])
    for p in sh_pts[1:]: cr.line_to(*p)
    cr.close_path()
    cr.set_source_rgba(*_c(color, 1.12, 0.18)); cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 1.0, 0.75)); cr.set_line_width(1.2); cr.stroke()
    # vertical edge grooves
    _panel_line(cr, bx+5, by+4, bx+5, by+bh-4)
    _panel_line(cr, bx+bw-6, by+4, bx+bw-6, by+bh-4)
    # horizontal panel lines
    for fy_f in (0.25, 0.45, 0.65):
        _panel_line(cr, bx+10, by+bh*fy_f, bx+bw-10, by+bh*fy_f)
    # corner rivets + top center
    for rx2, ry2 in ((bx+5,by+5),(bx+bw-6,by+5),(bx+5,by+bh-6),(bx+bw-6,by+bh-6),(scx,by+5)):
        _rivet(cr, rx2, ry2, max(2, w*0.016))
    # battle damage scorch marks (stable random positions)
    rng2 = __import__('random').Random(0xC0105505)
    for _ in range(5):
        sx3 = bx + rng2.uniform(10, bw-10)
        sy3 = by + rng2.uniform(8, bh-8)
        ex3 = sx3 + rng2.uniform(-10, 10)
        ey3 = sy3 + rng2.uniform(-6,  6)
        cr.set_source_rgba(0, 0, 0, 0.35); cr.set_line_width(1.5)
        cr.move_to(sx3, sy3); cr.line_to(ex3, ey3); cr.stroke()
        cr.set_source_rgba(*_c(METAL_LIGHT, 1.0, 0.18)); cr.set_line_width(0.8)
        cr.move_to(sx3-1, sy3); cr.line_to(ex3-1, ey3); cr.stroke()

    # --- Left arm: Battle Cannon ---
    recoil = ff * X(0.05)
    elevate = ff * 6
    mount_x, mount_y = X(0.09)+sway, Y(0.27)+dip
    mount_w, mount_h = X(0.12), Y(0.29)
    _rrect(cr, mount_x, mount_y, mount_w, mount_h, 3)
    _metal_grad(cr, mount_x, mount_y, mount_y+mount_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.7); cr.stroke()
    # barrel
    brl_len = X(0.14)
    brl_y0  = Y(0.32) + dip
    brl_y1  = brl_y0 - elevate
    brl_x0  = X(0.00) - recoil
    brl_d   = max(4, h*0.026)
    _rrect(cr, brl_x0, brl_y1 - brl_d, brl_len, brl_d*2, brl_d*0.7)
    _metal_grad(cr, brl_x0, brl_y1-brl_d, brl_y1+brl_d)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 0.6, 0.40)); cr.set_line_width(0.7); cr.stroke()
    # muzzle brake
    _rrect(cr, brl_x0, brl_y1 - brl_d*1.5, max(5, brl_len*0.10), brl_d*3, 2)
    _metal_grad(cr, brl_x0, brl_y1-brl_d*1.5, brl_y1+brl_d*1.5)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # muzzle blast
    if is_firing and ff < 0.45:
        blast = (1.0 - ff/0.45)
        _glow(cr, brl_x0+2, brl_y1, max(4, brl_d*2)*blast, GLOW_ORG, 0.80*blast)

    # --- Right arm: Missile Battery ---
    bat_x, bat_y = X(0.80)+sway, Y(0.26)+dip
    bat_w, bat_h = X(0.19), Y(0.33)
    _rrect(cr, bat_x, bat_y, bat_w, bat_h, 3)
    _metal_grad(cr, bat_x, bat_y, bat_y+bat_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.6, 0.50)); cr.set_line_width(0.8); cr.stroke()
    # 2 x 4 launch tubes
    for col3 in range(2):
        for row3 in range(4):
            tx3 = bat_x + 3 + col3 * (bat_w-8)/2
            ty3 = bat_y + 3 + row3 * (bat_h-8)/4
            tw3 = (bat_w-8)/2 - 1
            th3 = max(3, (bat_h-8)/4 - 1)
            _rrect(cr, tx3, ty3, tw3, th3, 1)
            cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.90)); cr.fill()
            cr.set_source_rgba(*_c((170,50,50), 0.8 if (is_firing and row3==1) else 0.5, 0.80))
            cr.arc(tx3+3, ty3+th3/2, max(1.5, th3*0.35), 0, 2*math.pi); cr.fill()
            if is_firing and row3 == 1:
                _glow(cr, tx3+3, ty3+th3/2, th3*0.8, GLOW_ORG, 0.50)

    # --- Head ---
    hl2 = -_torso_lean(fire_t) * 1.5
    hx4, hy4 = X(0.27)+sway+hl2, Y(0.03)+dip
    hw4, hh4  = X(0.46), Y(0.16)
    cr.save(); cr.translate(1.5,1.5)
    _rrect(cr, hx4, hy4, hw4, hh4, 6)
    cr.set_source_rgba(0,0,0,0.22); cr.fill(); cr.restore()
    _rrect(cr, hx4, hy4, hw4, hh4, 6)
    _armor_grad(cr, hx4+hw4/2, hy4, hy4+hh4, METAL_DARK, lo=0.35, hi=1.30)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.90, 0.70)); cr.set_line_width(1.1); cr.stroke()
    # visor
    vx2, vy2 = hx4+4, hy4+hh4/2-max(2,hh4*0.20)
    vw2, vh2 = hw4-8, max(4,hh4*0.38)
    _rrect(cr, vx2, vy2, vw2, vh2, 2)
    v_a2 = 0.85 if is_firing else 0.60
    _glow(cr, vx2+vw2/2, vy2+vh2/2, vw2*0.42, GLOW_RED, v_a2)
    cr.set_source_rgba(*_c(GLOW_RED, 1.0, 0.80))
    cr.arc(vx2+vw2/2, vy2+vh2/2, min(vw2,vh2)/2*0.80, 0, 2*math.pi); cr.fill()
    # top crest
    crest_pts = [(hx4+hw4/2-8, hy4+2), (hx4+hw4/2+8, hy4+2),
                 (hx4+hw4/2+6, hy4-max(4,h*0.035)), (hx4+hw4/2, hy4-max(6,h*0.048)),
                 (hx4+hw4/2-6, hy4-max(4,h*0.035))]
    cr.move_to(*crest_pts[0])
    for p in crest_pts[1:]: cr.line_to(*p)
    cr.close_path()
    cr.set_source_rgba(*_c(team_color, 1.0, 0.75)); cr.fill()
    # side antenna
    cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.65)); cr.set_line_width(1.2)
    cr.move_to(hx4+hw4-6, hy4-1)
    cr.line_to(hx4+hw4+max(3,w*0.025), hy4-max(4,h*0.038)); cr.stroke()
    cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.70))
    cr.arc(hx4+hw4+max(3,w*0.025), hy4-max(4,h*0.038), max(1.5, h*0.010), 0, 2*math.pi); cr.fill()


# ===========================================================================
# PHANTOM  -  Tau XV-8 Battlesuit
# ===========================================================================

def _draw_phantom_cairo(cr, w: float, h: float,
                        color, team_color, walk_t: float, fire_t: float):
    l_sw  = _leg_sw(walk_t,  1) * 1.67
    r_sw  = _leg_sw(walk_t, -1) * 1.67
    l_ank = _leg_sw(walk_t, -1) * 1.0
    r_ank = _leg_sw(walk_t,  1) * 1.0
    ff    = _fire_frac(fire_t)
    boost = abs(math.sin(walk_t * math.pi * 2)) if walk_t > 0 else 0.0
    is_firing = fire_t >= 0

    GLOW_BLU = (70, 195, 255)

    def X(fx): return fx * w
    def Y(fy): return fy * h

    # --- Swept reverse-knee legs ---
    for hip_fx, knee_fx, ank_fx, foot_fx, sw, ank_sw, side in (
        (0.33, 0.21, 0.25, 0.29, l_sw, l_ank, -1),
        (0.67, 0.79, 0.75, 0.71, r_sw, r_ank,  1),
    ):
        hip   = (X(hip_fx),  Y(0.52))
        knee  = (X(knee_fx), Y(0.71) + sw)
        ankle = (X(ank_fx),  Y(0.84) + ank_sw)
        foot  = (X(foot_fx), Y(0.94))

        lw = max(2, w * 0.038)
        # upper leg (colored armor)
        pat = cairo.LinearGradient(*hip, *knee)
        pat.add_color_stop_rgba(0, *_c(color, 1.40)); pat.add_color_stop_rgba(1, *_c(color, 0.65))
        cr.set_source(pat); cr.set_line_width(lw)
        cr.move_to(*hip); cr.line_to(*knee); cr.stroke()
        # shin (dark)
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.75)); cr.set_line_width(lw*0.80)
        cr.move_to(*knee); cr.line_to(*ankle); cr.stroke()
        # foot segment
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.65)); cr.set_line_width(lw*0.65)
        cr.move_to(*ankle); cr.line_to(*foot); cr.stroke()
        # knee joint (team colored)
        kr = max(4, w * 0.042)
        cr.set_source_rgba(*_c(METAL_DARK, 0.8, 0.80))
        cr.arc(*knee, kr, 0, 2*math.pi); cr.fill()
        _sphere_grad(cr, knee[0]-kr*0.3, knee[1]-kr*0.3, kr*0.80, color)
        cr.arc(*knee, kr*0.80, 0, 2*math.pi); cr.fill()
        cr.set_source_rgba(*_c(team_color, 1.0, 0.75))
        cr.arc(*knee, kr, 0, 2*math.pi); cr.set_line_width(1.0); cr.stroke()
        # ankle joint
        ar = max(2, w * 0.025)
        _sphere_grad(cr, ankle[0]-ar*0.3, ankle[1]-ar*0.3, ar, METAL_MID)
        cr.arc(*ankle, ar, 0, 2*math.pi); cr.fill()
        # foot hover plate
        fp_w = max(14, w * 0.16)
        fp_h = max(4, h * 0.030)
        _rrect(cr, foot[0]-fp_w/2, foot[1]-fp_h/2, fp_w, fp_h, 3)
        _metal_grad(cr, foot[0], foot[1]-fp_h/2, foot[1]+fp_h/2)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.5); cr.stroke()
        # thruster glow under foot
        thr_a = 0.55 + boost * 0.35
        _glow(cr, foot[0] - side*3, foot[1] - fp_h*1.2, fp_h*1.4, GLOW_BLU, thr_a)
        cr.set_source_rgba(*_c(GLOW_BLU, 1.3, 0.85))
        cr.arc(foot[0]-side*3, foot[1]-fp_h*1.2, max(1.5, fp_h*0.35), 0, 2*math.pi); cr.fill()

    # --- Trapezoidal torso ---
    tor_pts = [
        (X(0.27), Y(0.18)), (X(0.73), Y(0.18)),
        (X(0.79), Y(0.53)), (X(0.21), Y(0.53)),
    ]
    cr.save(); cr.translate(1.5,1.5)
    cr.move_to(*tor_pts[0])
    for p in tor_pts[1:]: cr.line_to(*p)
    cr.close_path(); cr.set_source_rgba(0,0,0,0.22); cr.fill(); cr.restore()
    cr.move_to(*tor_pts[0])
    for p in tor_pts[1:]: cr.line_to(*p)
    cr.close_path()
    _armor_grad(cr, X(0.50), Y(0.18), Y(0.53), color, lo=0.28, hi=1.65)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.85, 0.65)); cr.set_line_width(1.3); cr.stroke()
    # top highlight edge
    cr.set_source_rgba(*_c(color, 1.70, 0.45)); cr.set_line_width(1.5)
    cr.move_to(*tor_pts[0]); cr.line_to(*tor_pts[1]); cr.stroke()
    # chest panel with blue dot array
    px3, py3 = X(0.32), Y(0.25)
    pw3, ph3 = X(0.36), Y(0.12)
    _rrect(cr, px3, py3, pw3, ph3, 3)
    _armor_grad(cr, px3+pw3/2, py3, py3+ph3, METAL_DARK, lo=0.50, hi=1.30)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(GLOW_BLU, 0.8, 0.50)); cr.set_line_width(0.7); cr.stroke()
    for di in range(3):
        dx3 = px3 + pw3*(0.20 + di*0.30)
        _glow(cr, dx3, py3+ph3/2, max(2, ph3*0.42), GLOW_BLU, 0.62)
        cr.set_source_rgba(*_c(GLOW_BLU, 1.3, 0.88))
        cr.arc(dx3, py3+ph3/2, max(1.5, ph3*0.22), 0, 2*math.pi); cr.fill()
    # jetpack (right side)
    jp_x, jp_y = X(0.73), Y(0.19)
    jp_w, jp_h = X(0.14), Y(0.24)
    _rrect(cr, jp_x, jp_y, jp_w, jp_h, 4)
    _armor_grad(cr, jp_x+jp_w/2, jp_y, jp_y+jp_h, METAL_DARK, lo=0.38, hi=1.25)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(GLOW_BLU, 0.7, 0.45)); cr.set_line_width(0.8); cr.stroke()
    for ni in range(2):
        ny3 = jp_y + 5 + ni*(jp_h*0.45)
        nz_h = max(5, jp_h*0.20)
        _rrect(cr, jp_x+2, ny3, jp_w-4, nz_h, 2)
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.90)); cr.fill()
        jt_a = 0.50 + boost * 0.40
        _glow(cr, jp_x+jp_w/2, ny3+nz_h/2, nz_h*1.1, GLOW_BLU, jt_a)
        cr.set_source_rgba(*_c(GLOW_BLU, 1.2, 0.80))
        cr.arc(jp_x+jp_w/2, ny3+nz_h/2, max(1.5, nz_h*0.30), 0, 2*math.pi); cr.fill()
        if boost > 0.25:
            for ej in range(1, 5):
                fade = (1 - ej/5) * boost
                cr.set_source_rgba(0, 0.5*fade, 0.9*fade, fade*0.60)
                cr.set_line_width(max(1, (jp_w-6)*(1-ej/6)))
                cr.move_to(jp_x+2, ny3+nz_h+ej); cr.line_to(jp_x+jp_w-2, ny3+nz_h+ej); cr.stroke()
    # panel lines on torso
    for fy_f in (0.35, 0.60, 0.80):
        _panel_line(cr, X(0.29), Y(0.18)+(Y(0.53)-Y(0.18))*fy_f,
                        X(0.71), Y(0.18)+(Y(0.53)-Y(0.18))*fy_f)

    # --- Left arm: Pulse Laser ---
    arm_ext = ff * X(0.06)
    sh_rise3 = _shoulder_rise(fire_t) * 0.67
    arm_y3 = Y(0.27) - sh_rise3
    a0_3 = (X(0.27), arm_y3)
    a1_3 = (X(0.00) - arm_ext, arm_y3)
    tube_r3 = max(2, h*0.018)
    _rrect(cr, a1_3[0], arm_y3-tube_r3, a0_3[0]-a1_3[0], tube_r3*2, tube_r3)
    _armor_grad(cr, (a0_3[0]+a1_3[0])/2, arm_y3-tube_r3, arm_y3+tube_r3, METAL_DARK, lo=0.40, hi=1.45)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_DARK, 0.5, 0.4)); cr.set_line_width(0.6); cr.stroke()
    g_a3 = 0.80 if is_firing else 0.45
    _glow(cr, a1_3[0]+1, arm_y3, tube_r3*2.5, GLOW_BLU, g_a3)
    cr.set_source_rgba(*_c(GLOW_BLU, 1.3, 0.90))
    cr.arc(a1_3[0]+1, arm_y3, tube_r3*0.85, 0, 2*math.pi); cr.fill()
    cr.set_source_rgba(1,1,1,0.75)
    cr.arc(a1_3[0]+1, arm_y3, tube_r3*0.38, 0, 2*math.pi); cr.fill()

    # --- Right arm: Vibro-Blade ---
    blade_ext3 = ff * X(0.08)
    blade_y3   = Y(0.38)
    mnt_x, mnt_y = X(0.71), blade_y3 - max(3, h*0.025)
    mnt_w, mnt_h = X(0.08), max(6, h*0.050)
    _rrect(cr, mnt_x, mnt_y, mnt_w, mnt_h, 2)
    _armor_grad(cr, mnt_x+mnt_w/2, mnt_y, mnt_y+mnt_h, METAL_DARK, lo=0.45, hi=1.35)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # blade triangle
    blade_pts3 = [
        (X(0.79)+blade_ext3, blade_y3 - max(4, h*0.032)),
        (X(0.99)+blade_ext3, blade_y3),
        (X(0.79)+blade_ext3, blade_y3 + max(4, h*0.032)),
    ]
    cr.move_to(*blade_pts3[0])
    for p in blade_pts3[1:]: cr.line_to(*p)
    cr.close_path()
    _metal_grad(cr, blade_pts3[0][0], blade_pts3[0][1], blade_pts3[2][1])
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.55)); cr.set_line_width(0.7); cr.stroke()
    # blade edge glow
    b_a3 = 0.60 if is_firing else 0.32
    cr.set_source_rgba(*_c(GLOW_BLU, 1.0, b_a3)); cr.set_line_width(1.2)
    cr.move_to(*blade_pts3[0]); cr.line_to(*blade_pts3[1]); cr.stroke()
    _glow(cr, blade_pts3[1][0]-2, blade_pts3[1][1], max(3, h*0.025), GLOW_BLU, b_a3*1.2)

    # --- Angular head ---
    sl3 = -_torso_lean(fire_t) * 1.5
    hd_pts = [
        (X(0.36)+sl3, Y(0.02)), (X(0.64)+sl3, Y(0.02)),
        (X(0.67)+sl3, Y(0.18)), (X(0.33)+sl3, Y(0.18)),
    ]
    cr.move_to(*hd_pts[0])
    for p in hd_pts[1:]: cr.line_to(*p)
    cr.close_path()
    _armor_grad(cr, X(0.50)+sl3, Y(0.02), Y(0.18), METAL_DARK, lo=0.35, hi=1.30)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.90, 0.65)); cr.set_line_width(1.0); cr.stroke()
    # top highlight edge
    cr.set_source_rgba(*_c(METAL_LIGHT, 1.0, 0.40)); cr.set_line_width(1.2)
    cr.move_to(*hd_pts[0]); cr.line_to(*hd_pts[1]); cr.stroke()
    # sensor bar (horizontal blue line)
    sy3 = Y(0.09)
    bar_a = 0.80 if is_firing else 0.55
    _glow(cr, X(0.50)+sl3, sy3, (X(0.61)-X(0.39))*0.45, GLOW_BLU, bar_a)
    cr.set_source_rgba(*_c(GLOW_BLU, 1.2, 0.85)); cr.set_line_width(max(2, h*0.020))
    cr.move_to(X(0.39)+sl3, sy3); cr.line_to(X(0.61)+sl3, sy3); cr.stroke()
    cr.set_source_rgba(1,1,1,0.65)
    cr.arc(X(0.60)+sl3, sy3, max(1.5, h*0.012), 0, 2*math.pi); cr.fill()


# ===========================================================================
# VANGUARD  -  Blood Angels Dreadnought
# ===========================================================================

def _draw_vanguard_cairo(cr, w: float, h: float,
                         color, team_color, walk_t: float, fire_t: float):
    l_sw  = _leg_sw(walk_t,  1) * 1.33
    r_sw  = _leg_sw(walk_t, -1) * 1.33
    dip   = _body_bob(walk_t)
    ff    = _fire_frac(fire_t)
    is_firing = fire_t >= 0

    GLOW_RED = (255, 60,  25)
    GLOW_BLU = (70, 195, 255)

    def X(fx): return fx * w
    def Y(fy): return fy * h

    # --- Two-segment articulated legs ---
    for lx0, lx1, ux0, ux1, sw in (
        (0.13, 0.41, 0.16, 0.38, l_sw),
        (0.59, 0.87, 0.62, 0.84, r_sw),
    ):
        uleg_x, uleg_y = X(lx0), Y(0.57) + sw + dip
        uleg_w, uleg_h = X(lx1)-X(lx0), Y(0.19)
        lleg_x, lleg_y = X(ux0), Y(0.76) + sw + dip
        lleg_w, lleg_h = X(ux1)-X(ux0), Y(0.21)
        # shadows
        cr.save(); cr.translate(1.5, 1.5)
        _rrect(cr, uleg_x, uleg_y, uleg_w, uleg_h, 3)
        cr.set_source_rgba(0,0,0,0.18); cr.fill()
        _rrect(cr, lleg_x, lleg_y, lleg_w, lleg_h, 2)
        cr.set_source_rgba(0,0,0,0.18); cr.fill(); cr.restore()
        # upper leg
        _rrect(cr, uleg_x, uleg_y, uleg_w, uleg_h, 3)
        _armor_grad(cr, uleg_x+uleg_w/2, uleg_y, uleg_y+uleg_h, METAL_DARK, lo=0.38, hi=1.30)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.45)); cr.set_line_width(0.7); cr.stroke()
        # lower leg
        _rrect(cr, lleg_x, lleg_y, lleg_w, lleg_h, 2)
        _metal_grad(cr, lleg_x, lleg_y, lleg_y+lleg_h)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.40)); cr.set_line_width(0.6); cr.stroke()
        # knee joint sphere
        jx = uleg_x + uleg_w/2
        jy = uleg_y + uleg_h
        jr = max(3.5, w*0.032)
        cr.set_source_rgba(*_c(METAL_DARK, 0.8, 0.80))
        cr.arc(jx, jy, jr, 0, 2*math.pi); cr.fill()
        _sphere_grad(cr, jx-jr*0.3, jy-jr*0.3, jr*0.82, METAL_LIGHT)
        cr.arc(jx, jy, jr*0.82, 0, 2*math.pi); cr.fill()
        # hydraulic piston line on lower leg
        cr.set_source_rgba(*_c(METAL_MID, 1.0, 0.50)); cr.set_line_width(1.0)
        cr.move_to(lleg_x+3, lleg_y+3); cr.line_to(lleg_x+3, lleg_y+lleg_h-5); cr.stroke()
        # track pad feet
        for tx4 in (lleg_x+3, lleg_x+lleg_w-5):
            _rrect(cr, tx4-2, lleg_y+lleg_h-1, 4, 4, 1)
            cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.80)); cr.fill()

    # --- Rounded body ---
    bx, by = X(0.16), Y(0.19) + dip
    bw, bh = X(0.68), Y(0.41)
    cr.save(); cr.translate(2,2)
    _rrect(cr, bx, by, bw, bh, 7)
    cr.set_source_rgba(0,0,0,0.22); cr.fill(); cr.restore()
    _rrect(cr, bx, by, bw, bh, 7)
    _armor_grad(cr, bx+bw/2, by, by+bh, color, lo=0.28, hi=1.65)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.85, 0.65)); cr.set_line_width(1.2); cr.stroke()
    # chest panel inset
    cp2 = (X(0.27), Y(0.24)+dip, X(0.46), Y(0.30))
    _rrect(cr, cp2[0], cp2[1], cp2[2], cp2[3], 3)
    _armor_grad(cr, cp2[0]+cp2[2]/2, cp2[1], cp2[1]+cp2[3], color, lo=0.45, hi=1.45)
    cr.fill()
    # chapter symbol (wing/cross motif)
    ic2, iy2 = bx+bw/2, by+bh*0.45
    cr.set_source_rgba(*_c(team_color, 1.0, 0.82)); cr.set_line_width(1.8)
    for dx2, dy2 in ((-10,0),(10,0),(0,-10),(0,10)):
        cr.move_to(ic2, iy2); cr.line_to(ic2+dx2, iy2+dy2); cr.stroke()
    cr.arc(ic2, iy2, max(3, bw*0.08), 0, 2*math.pi)
    cr.set_source_rgba(*_c(team_color, 1.0, 0.75)); cr.fill()
    cr.set_source_rgba(*_c(team_color, 1.5, 0.80)); cr.arc(ic2, iy2, max(2, bw*0.05), 0, 2*math.pi); cr.fill()
    # wing lines
    for dx2, dy2 in ((-9,-3),(9,-3),(-9,3),(9,3)):
        cr.set_source_rgba(*_c(team_color, 0.9, 0.60)); cr.set_line_width(1.0)
        cr.move_to(ic2+dx2, iy2); cr.line_to(ic2+dx2+(-2 if dx2<0 else 2), iy2+dy2); cr.stroke()
    # seal/tabard (parchment colour)
    sc_x, sc_y = ic2+6, by+bh-max(5, h*0.04)
    sc_w, sc_h = max(5, bw*0.045), max(8, h*0.058)
    _rrect(cr, sc_x, sc_y, sc_w, sc_h, 1)
    cr.set_source_rgba(0.70, 0.66, 0.55, 0.90); cr.fill()
    _rrect(cr, sc_x, sc_y, sc_w, sc_h*0.42, 1)
    cr.set_source_rgba(*_c(team_color, 0.9, 0.80)); cr.fill()
    # side panel grooves
    _panel_line(cr, bx+5, by+4, bx+5, by+bh-4)
    _panel_line(cr, bx+bw-6, by+4, bx+bw-6, by+bh-4)
    for rx2, ry2 in ((bx+5,by+5),(bx+bw-6,by+5),(bx+5,by+bh-6)):
        _rivet(cr, rx2, ry2, max(1.5, w*0.013))

    # --- Wide shoulders ---
    for sx0, sx1 in ((0.02, 0.19), (0.81, 0.98)):
        spx2, spy2 = X(sx0), Y(0.19)+dip
        spw2, sph2 = X(sx1)-X(sx0), Y(0.17)
        _rrect(cr, spx2, spy2, spw2, sph2, 4)
        _armor_grad(cr, spx2+spw2/2, spy2, spy2+sph2, METAL_DARK, lo=0.38, hi=1.25)
        cr.fill_preserve()
        cr.set_source_rgba(*_c(team_color, 0.75, 0.55)); cr.set_line_width(0.8); cr.stroke()
        # team stripe
        _rrect(cr, spx2+2, spy2+5, spw2-4, max(3, sph2*0.18), 1)
        cr.set_source_rgba(*_c(team_color, 1.0, 0.70)); cr.fill()
        _rivet(cr, spx2+spw2/2, spy2+sph2*0.62, max(1.5, w*0.013))

    # --- Left arm: Plasma Cannon (two-segment) ---
    fire_raise2 = ff * 6
    shoulder_x2 = X(0.09)
    shoulder_y2 = Y(0.26) - fire_raise2
    elbow_x2    = X(0.05)
    elbow_y2    = Y(0.40) - fire_raise2 * 0.6
    # upper arm
    ua_w = max(6, abs(shoulder_x2-elbow_x2)+6)
    ua_h = max(6, elbow_y2-shoulder_y2+4)
    _rrect(cr, min(shoulder_x2,elbow_x2)-3, shoulder_y2, ua_w, ua_h, 3)
    _metal_grad(cr, min(shoulder_x2,elbow_x2)-3, shoulder_y2, shoulder_y2+ua_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # elbow joint
    ej_r = max(3, w*0.032)
    cr.set_source_rgba(*_c(METAL_DARK, 0.8, 0.80))
    cr.arc(elbow_x2, elbow_y2, ej_r, 0, 2*math.pi); cr.fill()
    _sphere_grad(cr, elbow_x2-ej_r*0.3, elbow_y2-ej_r*0.3, ej_r*0.80, METAL_LIGHT)
    cr.arc(elbow_x2, elbow_y2, ej_r*0.80, 0, 2*math.pi); cr.fill()
    # forearm + plasma housing
    fa_top = elbow_y2 - 4
    fa_bot = Y(0.57) - fire_raise2*0.35
    fa_w   = max(8, X(0.16))
    _rrect(cr, X(0.00), fa_top, fa_w, max(8, fa_bot-fa_top+4), 4)
    _metal_grad(cr, X(0.00), fa_top, fa_bot+4)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.7); cr.stroke()
    # plasma coil rings
    for ci2, cy_frac2 in enumerate((0.22, 0.38, 0.54)):
        cy_abs2 = fa_top + (fa_bot - fa_top + 4) * cy_frac2
        ring_w  = fa_w - 4 - ci2
        _rrect(cr, X(0.00)+2+ci2, cy_abs2, ring_w, max(3, (fa_bot-fa_top)*0.12), 2)
        cr.set_source_rgba(*_c(METAL_MID, 1.1, 0.78)); cr.fill_preserve()
        cr.set_source_rgba(*_c(METAL_DARK, 0.8, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # plasma emitter muzzle
    ecx2, ecy2 = X(0.00)+fa_w/2, fa_bot - max(5, h*0.04)
    gs2 = max(6, fa_w*0.55)
    g_a4 = 0.85 if is_firing else 0.60
    _glow(cr, ecx2, ecy2, gs2, GLOW_BLU, g_a4)
    cr.set_source_rgba(*_c(GLOW_BLU, 1.2, 0.88))
    cr.arc(ecx2, ecy2, max(3.5, fa_w*0.25), 0, 2*math.pi); cr.fill()
    cr.set_source_rgba(0.78, 0.93, 1.0, 0.85)
    cr.arc(ecx2, ecy2, max(2, fa_w*0.16), 0, 2*math.pi); cr.fill()
    cr.set_source_rgba(1,1,1,0.85)
    cr.arc(ecx2, ecy2, max(1, fa_w*0.08), 0, 2*math.pi); cr.fill()
    # discharge arcs during fire
    if is_firing and ff < 0.55:
        arc_a2 = max(0, 1.0 - ff / 0.55)
        for i2 in range(4):
            ang2 = i2 * math.pi/2 + fire_t*10
            ax2 = ecx2 + math.cos(ang2)*max(7, fa_w*0.60)
            ay2 = ecy2 + math.sin(ang2)*max(7, fa_w*0.60)
            cr.set_source_rgba(*_c(GLOW_BLU, 1.0, arc_a2*0.75)); cr.set_line_width(1.0)
            cr.move_to(ecx2, ecy2); cr.line_to(ax2, ay2); cr.stroke()

    # --- Right arm: Chainsword ---
    blade_ext4 = ff * X(0.06)
    sword_y    = Y(0.37)
    sh4_x      = X(0.84)
    sh4_y      = sword_y - max(4, h*0.028)
    sh4_w, sh4_h = X(0.10), max(8, h*0.055)
    _rrect(cr, sh4_x, sh4_y, sh4_w, sh4_h, 2)
    _metal_grad(cr, sh4_x, sh4_y, sh4_y+sh4_h)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_MID, 0.5, 0.4)); cr.set_line_width(0.6); cr.stroke()
    # sword blade body
    blade_len = X(0.16) + blade_ext4
    blade_h   = max(6, h*0.042)
    _rrect(cr, sh4_x+sh4_w, sword_y-blade_h/2, blade_len, blade_h, 2)
    _metal_grad(cr, sh4_x+sh4_w, sword_y-blade_h/2, sword_y+blade_h/2)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(METAL_SHEEN, 1.0, 0.50)); cr.set_line_width(0.7); cr.stroke()
    # chain teeth (small nubs along top edge)
    tooth_spacing = max(3, w*0.025)
    tx5 = sh4_x + sh4_w + tooth_spacing/2
    while tx5 < sh4_x+sh4_w+blade_len-2:
        cr.set_source_rgba(*_c(METAL_DARK, 1.0, 0.65))
        cr.arc(tx5, sword_y - blade_h/2, max(1, blade_h*0.18), 0, 2*math.pi); cr.fill()
        tx5 += tooth_spacing
    # blood-red team highlight stripe
    cr.set_source_rgba(*_c(team_color, 1.0, 0.55)); cr.set_line_width(1.0)
    cr.move_to(sh4_x+sh4_w, sword_y+blade_h*0.20)
    cr.line_to(sh4_x+sh4_w+blade_len-3, sword_y+blade_h*0.20); cr.stroke()

    # --- Head: T-visor Dreadnought ---
    hl3 = _torso_lean(fire_t) * 1.0
    hx5, hy5 = X(0.27)+hl3, Y(0.03)+dip
    hw5, hh5  = X(0.46), Y(0.17)
    cr.save(); cr.translate(1.5,1.5)
    _rrect(cr, hx5, hy5, hw5, hh5, 6)
    cr.set_source_rgba(0,0,0,0.22); cr.fill(); cr.restore()
    _rrect(cr, hx5, hy5, hw5, hh5, 6)
    _armor_grad(cr, hx5+hw5/2, hy5, hy5+hh5, METAL_DARK, lo=0.35, hi=1.30)
    cr.fill_preserve()
    cr.set_source_rgba(*_c(team_color, 0.90, 0.70)); cr.set_line_width(1.1); cr.stroke()
    # T-visor slit
    vx5, vy5 = hx5+4, hy5+hh5/2-max(2,hh5*0.18)
    vw5, vh5  = hw5-8, max(4, hh5*0.36)
    _rrect(cr, vx5, vy5, vw5, vh5, 2)
    v_a5 = 0.88 if is_firing else 0.60
    _glow(cr, vx5+vw5/2, vy5+vh5/2, vw5*0.42, GLOW_RED if not is_firing else GLOW_BLU, v_a5)
    cr.set_source_rgba(*_c(GLOW_RED if not is_firing else GLOW_BLU, 1.0, 0.82))
    cr.arc(vx5+vw5/2, vy5+vh5/2, min(vw5,vh5)/2*0.82, 0, 2*math.pi); cr.fill()
    cr.set_source_rgba(1,1,1,0.30); cr.set_line_width(0.7)
    cr.move_to(vx5+vw5*0.12, vy5+vh5*0.28)
    cr.line_to(vx5+vw5*0.50, vy5+vh5*0.28); cr.stroke()
    # horn stubs (chapter crest)
    for hsx, hso in ((hx5+hw5*0.30, -max(3,h*0.030)), (hx5+hw5*0.70, -max(3,h*0.030))):
        cr.set_source_rgba(*_c(team_color, 1.0, 0.70)); cr.set_line_width(1.5)
        cr.move_to(hsx, hy5); cr.line_to(hsx, hy5+hso); cr.stroke()
        cr.set_source_rgba(*_c(team_color, 1.2, 0.80))
        cr.arc(hsx, hy5+hso, max(1, h*0.009), 0, 2*math.pi); cr.fill()


# ===========================================================================
# Per-mech public render functions
# ===========================================================================

_DRAW_FUNCS = {
    "titan":    _draw_titan_cairo,
    "raptor":   _draw_raptor_cairo,
    "colossus": _draw_colossus_cairo,
    "phantom":  _draw_phantom_cairo,
    "vanguard": _draw_vanguard_cairo,
    "sniper":   _draw_sniper_cairo,
}

def render_mech_cairo(mech_id: str, w: int, h: int,
                      color: Tuple, team_color: Tuple,
                      walk_t: float = 0.0, fire_t: float = -1.0,
                      flip: bool = False) -> pygame.Surface:
    """General Cairo renderer for any mech.

    Falls back gracefully: if mech_id is not in _DRAW_FUNCS,
    returns None so caller can use the pygame fallback.
    """
    draw_fn = _DRAW_FUNCS.get(mech_id)
    if draw_fn is None:
        return None

    wf, ff2 = _frame_key(walk_t, fire_t)
    key = (mech_id, w, h, color, team_color, wf, ff2, flip)
    if key in _cache:
        return _cache[key]

    resolved_walk = wf / WALK_FRAMES
    resolved_fire = -1.0 if ff2 < 0 else (ff2 + 0.5) / FIRE_FRAMES

    cr_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ctx = cairo.Context(cr_surf)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)

    draw_fn(ctx, float(w), float(h), color, team_color, resolved_walk, resolved_fire)

    import numpy as np
    data = cr_surf.get_data()
    arr  = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
    rgba = np.ascontiguousarray(arr[:, :, [2, 1, 0, 3]])
    pg_surf = pygame.image.frombytes(bytes(rgba), (w, h), "RGBA")

    if flip:
        pg_surf = pygame.transform.flip(pg_surf, True, False)

    _cache[key] = pg_surf
    return pg_surf

