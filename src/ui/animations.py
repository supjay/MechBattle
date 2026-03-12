"""Battle animations – movement, attack effects, explosions, damage flash."""
import math
import random
from typing import Tuple, List, Dict, Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Move animation
# ---------------------------------------------------------------------------

class MoveAnimation:
    """Smooth pixel-lerp for a mech gliding from one tile to another."""

    def __init__(self, from_px: Tuple[int, int], to_px: Tuple[int, int],
                 duration: float = 1.10):
        self.from_px  = (float(from_px[0]), float(from_px[1]))
        self.to_px    = (float(to_px[0]),   float(to_px[1]))
        self.duration = duration
        self.elapsed  = 0.0

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        return self.elapsed < self.duration

    def is_done(self) -> bool:
        return self.elapsed >= self.duration

    @property
    def walk_t(self) -> float:
        """0→1 walk cycle phase usable as a sin argument."""
        return _clamp(self.elapsed / self.duration, 0.0, 1.0)

    @property
    def current_pos(self) -> Tuple[float, float]:
        t = _smoothstep(self.elapsed / self.duration)
        return (
            _lerp(self.from_px[0], self.to_px[0], t),
            _lerp(self.from_px[1], self.to_px[1], t),
        )


# ---------------------------------------------------------------------------
# Laser beam – multi-layer SRCALPHA glow with electric zigzag
# ---------------------------------------------------------------------------

class LaserBeamAnimation:
    """Bright glow beam with electric zigzag from attacker to target."""

    def __init__(self, from_px: Tuple[int, int], to_px: Tuple[int, int],
                 color: Tuple[int, int, int] = (80, 220, 255),
                 duration: float = 0.42):
        self.from_px  = from_px
        self.to_px    = to_px
        self.color    = color
        self.duration = duration
        self.elapsed  = 0.0
        # Stable impact sparks spawned once
        spark_rng = random.Random(99)
        self._impact_sparks = []
        for _ in range(8):
            ang = spark_rng.uniform(0, 2 * math.pi)
            spd = spark_rng.uniform(12, 28)
            self._impact_sparks.append({
                'dx': math.cos(ang) * spd,
                'dy': math.sin(ang) * spd,
                'len': spark_rng.uniform(6, 16),
            })

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        return self.elapsed < self.duration

    def draw(self, surface):
        import pygame
        t     = self.elapsed / self.duration
        alpha = _clamp(1.0 - t, 0.0, 1.0)

        r, g, b = self.color
        fx, fy  = self.from_px
        tx, ty  = self.to_px

        beam_len = math.hypot(tx - fx, ty - fy)
        perp_x   = -(ty - fy) / max(1, beam_len)
        perp_y   =  (tx - fx) / max(1, beam_len)

        # Outer glow (wide, translucent)
        glow_w = max(1, int(14 * alpha))
        glow_a = int(80 * alpha)
        min_x  = min(fx, tx) - glow_w - 2
        min_y  = min(fy, ty) - glow_w - 2
        gs_w   = abs(tx - fx) + glow_w * 2 + 4
        gs_h   = abs(ty - fy) + glow_w * 2 + 4
        if gs_w > 0 and gs_h > 0:
            gs = pygame.Surface((gs_w, gs_h), pygame.SRCALPHA)
            pygame.draw.line(gs, (r, g, b, glow_a),
                             (fx - min_x, fy - min_y),
                             (tx - min_x, ty - min_y), glow_w)
            surface.blit(gs, (min_x, min_y))

        # Jagged electric mid-beam (zigzag segments)
        n_segs  = 12
        mid_w   = max(1, int(4 * alpha))
        seg_rng = random.Random(int(self.elapsed * 20))  # slowly drifts
        for i in range(n_segs):
            t0 = i / n_segs
            t1 = (i + 1) / n_segs
            bx0 = fx + (tx - fx) * t0
            by0 = fy + (ty - fy) * t0
            bx1 = fx + (tx - fx) * t1
            by1 = fy + (ty - fy) * t1
            off0 = seg_rng.uniform(-3.0, 3.0) * alpha
            off1 = seg_rng.uniform(-3.0, 3.0) * alpha
            p0 = (int(bx0 + perp_x * off0), int(by0 + perp_y * off0))
            p1 = (int(bx1 + perp_x * off1), int(by1 + perp_y * off1))
            col = (int(r * alpha), int(g * alpha), int(b * alpha))
            pygame.draw.line(surface, col, p0, p1, mid_w)

        # White hot core (straight)
        if alpha > 0.15:
            pygame.draw.line(surface, (255, 255, 255), self.from_px, self.to_px, 1)

        # Muzzle glow at source
        if alpha > 0.4:
            mg_r = max(1, int(12 * alpha))
            mgs  = pygame.Surface((mg_r * 2 + 2, mg_r * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(mgs, (r, g, b, int(180 * alpha)),
                               (mg_r + 1, mg_r + 1), mg_r)
            surface.blit(mgs, (fx - mg_r - 1, fy - mg_r - 1))

        # Impact glow at target
        ig_r = max(1, int(18 * alpha))
        igs  = pygame.Surface((ig_r * 2 + 2, ig_r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(igs, (r, g, b, int(210 * alpha)),
                           (ig_r + 1, ig_r + 1), ig_r)
        surface.blit(igs, (tx - ig_r - 1, ty - ig_r - 1))
        pygame.draw.circle(surface, (255, 255, 255), (tx, ty),
                           max(1, int(4 * alpha)))

        # Impact spark burst (radiates outward as beam fades)
        if t > 0.35:
            spark_a = (1.0 - (t - 0.35) / 0.65)
            sc_base = (int(r * spark_a), int(g * spark_a), int(b * spark_a))
            travel  = (t - 0.35) / 0.65
            for sp in self._impact_sparks:
                ex = int(tx + sp['dx'] * travel * 1.8)
                ey = int(ty + sp['dy'] * travel * 1.8)
                pygame.draw.line(surface, sc_base, (tx, ty), (ex, ey), 1)


# ---------------------------------------------------------------------------
# Autocannon – multi-burst muzzle flash + tracers + shell casings
# ---------------------------------------------------------------------------

class AutocannonAnimation:
    """Three-burst autocannon: muzzle flash, tracer rounds, shell casings."""

    _BURST_TIMES = (0.0, 0.13, 0.26)

    def __init__(self, from_px: Tuple[int, int], to_px: Tuple[int, int],
                 duration: float = 0.52):
        self.from_px  = from_px
        self.to_px    = to_px
        self.duration = duration
        self.elapsed  = 0.0
        self._n_tracers = 4
        self._casings: List[Dict[str, Any]] = []
        # Eject shell casings at each burst time (pre-spawned all upfront)
        for _ in range(6):
            ang = math.pi * 0.5 + random.uniform(-0.6, 0.6)
            spd = random.uniform(55, 140)
            self._casings.append({
                'x': float(from_px[0]), 'y': float(from_px[1]),
                'vx': math.cos(ang) * spd,
                'vy': math.sin(ang) * spd - random.uniform(10, 50),
                'rot': random.uniform(0, 360),
                'rot_v': random.uniform(-420, 420),
                'life': random.uniform(0.25, duration),
                'elapsed': 0.0,
            })

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        for c in self._casings:
            c['elapsed'] += dt
            c['x']   += c['vx'] * dt
            c['y']   += c['vy'] * dt
            c['vy']  += 320 * dt   # gravity
            c['rot'] += c['rot_v'] * dt
        return self.elapsed < self.duration

    def draw(self, surface):
        import pygame
        fx, fy = self.from_px
        tx, ty = self.to_px

        # == Per-burst muzzle flash + tracers + impact ==
        for burst_t in self._BURST_TIMES:
            local_elapsed = self.elapsed - burst_t
            if local_elapsed < 0:
                continue
            local_dur = (self.duration - burst_t)
            lt = local_elapsed / max(0.001, local_dur)

            # Muzzle flash (first 25% of burst)
            if lt < 0.25:
                fa   = 1.0 - lt / 0.25
                fr   = max(2, int(18 * fa))
                fcol = (int(255 * fa), int(200 * fa), int(70 * fa))
                pygame.draw.circle(surface, fcol, self.from_px, fr)
                pygame.draw.circle(surface, (255, 255, 255),
                                   self.from_px, max(1, fr // 3))
                # 4-spoke muzzle star
                for i in range(4):
                    ang = i * math.pi / 2
                    ex  = int(fx + math.cos(ang) * fr * 1.5)
                    ey  = int(fy + math.sin(ang) * fr * 1.5)
                    pygame.draw.line(surface, fcol, (fx, fy), (ex, ey), 1)
                # Smoke wisp
                if fa < 0.7:
                    wisp_a = int(60 * (0.7 - fa) / 0.7)
                    ws = pygame.Surface((20, 20), pygame.SRCALPHA)
                    pygame.draw.circle(ws, (150, 145, 140, wisp_a), (10, 10), 8)
                    surface.blit(ws, (fx - 10, fy - 14))

            # Tracer rounds travelling to target
            for i in range(self._n_tracers):
                offset = (lt + i / self._n_tracers) % 1.0
                px = int(fx + (tx - fx) * offset)
                py = int(fy + (ty - fy) * offset)
                h_a = 1.0 - offset * 0.5
                pygame.draw.circle(surface, (255, int(240 * h_a), int(100 * h_a)),
                                   (px, py), 2)
                # Tail streak
                tail_len = 10
                dist = max(1, abs(tx-fx) + abs(ty-fy))
                tail_x = int(px - (tx - fx) / dist * tail_len)
                tail_y = int(py - (ty - fy) / dist * tail_len)
                pygame.draw.line(surface, (200, 175, 55), (px, py), (tail_x, tail_y), 1)

            # Impact flash (hits at ~70% of each burst)
            if lt > 0.65:
                ia = (lt - 0.65) / 0.35
                ir = max(1, int(14 * (1 - ia)))
                pygame.draw.circle(surface, (255, int(230 * (1-ia)), 80),
                                   self.to_px, ir)
                pygame.draw.circle(surface, (255, 255, 255),
                                   self.to_px, max(1, ir // 3))
                # Impact spark shower
                if ia < 0.5:
                    for i in range(5):
                        ang = i * math.pi * 2 / 5 + ia * 6
                        sl  = int(10 * (1 - ia * 2))
                        ex  = int(tx + math.cos(ang) * sl)
                        ey  = int(ty + math.sin(ang) * sl)
                        pygame.draw.line(surface, (255, 210, 80), (tx, ty), (ex, ey), 1)

        # == Shell casings ==
        for c in self._casings:
            if c['elapsed'] >= c['life']:
                continue
            ca  = max(0.0, 1.0 - c['elapsed'] / c['life'])
            cx2, cy2 = int(c['x']), int(c['y'])
            cs = pygame.Surface((6, 3), pygame.SRCALPHA)
            cs.fill((180, 160, 60, int(220 * ca)))
            rot = pygame.transform.rotate(cs, c['rot'])
            rr  = rot.get_rect(center=(cx2, cy2))
            surface.blit(rot, rr.topleft)


# ---------------------------------------------------------------------------
# Missile – rotated rocket body + fire trail + launch puff + shockwave impact
# ---------------------------------------------------------------------------

def _build_rocket_surf(length: int = 28, height: int = 9) -> 'pygame.Surface':
    """Build a detailed rocket sprite pointing RIGHT (+x). Cached on first call."""
    import pygame
    pad   = height + 8
    sz_w  = length + 12
    sz_h  = height + pad * 2
    surf  = pygame.Surface((sz_w, sz_h), pygame.SRCALPHA)
    cy    = sz_h // 2

    # Body
    body = pygame.Rect(6, cy - height // 2, length - 4, height)
    pygame.draw.rect(surf, (215, 207, 194), body, border_radius=1)
    # Warning stripe near nose
    stripe_x = body.right - 8
    pygame.draw.rect(surf, (220, 80, 20), (stripe_x, body.y, 5, height))
    pygame.draw.rect(surf, (240, 180, 20), (stripe_x + 1, body.y + 1, 2, height - 2))
    # Top highlight
    pygame.draw.line(surf, (245, 238, 228),
                     (body.x + 1, body.y + 1), (stripe_x - 1, body.y + 1))
    # Bottom shadow
    pygame.draw.line(surf, (148, 142, 136),
                     (body.x + 1, body.bottom - 2), (stripe_x - 1, body.bottom - 2))
    # Mid body seam
    seam_y = cy - 1
    pygame.draw.line(surf, (170, 163, 154), (body.x + 2, seam_y), (stripe_x - 2, seam_y))

    # Nose cone (orange-red, pointing right)
    nose = [
        (body.right - 1, cy - height // 2),
        (body.right - 1, cy + height // 2),
        (body.right + 9, cy),
    ]
    pygame.draw.polygon(surf, (225, 88, 30), nose)
    pygame.draw.polygon(surf, (255, 145, 65), nose, 1)
    # Nose tip highlight
    pygame.draw.line(surf, (255, 200, 120),
                     (body.right, cy - height // 2 + 1),
                     (body.right + 7, cy))

    # Upper fin
    uf = [(6, cy - height // 2),
          (6 + 9, cy - height // 2),
          (6, cy - height // 2 - 7)]
    pygame.draw.polygon(surf, (170, 162, 152), uf)
    pygame.draw.polygon(surf, (200, 194, 186), uf, 1)

    # Lower fin
    lf = [(6, cy + height // 2),
          (6 + 9, cy + height // 2),
          (6, cy + height // 2 + 7)]
    pygame.draw.polygon(surf, (170, 162, 152), lf)
    pygame.draw.polygon(surf, (200, 194, 186), lf, 1)

    # Side fins (for depth)
    sf_col = (185, 178, 168)
    pygame.draw.line(surf, sf_col, (8, cy), (16, cy - 1), 2)
    pygame.draw.line(surf, sf_col, (8, cy), (16, cy + 1), 2)

    # Exhaust cone + glow at tail
    ex = 5
    gsurf = pygame.Surface((ex * 2 + 2, ex * 2 + 2), pygame.SRCALPHA)
    pygame.draw.circle(gsurf, (255, 175, 30, 200), (ex, ex), ex)
    pygame.draw.circle(gsurf, (255, 245, 110, 230), (ex, ex), ex // 2)
    surf.blit(gsurf, (6 - ex - 1, cy - ex))

    return surf


class MissileAnimation:
    """Physically-rotated rocket body with fire trail, launch puff, and impact shockwave."""

    _rocket_surf = None   # class-level cache

    def __init__(self, from_px: Tuple[int, int], to_px: Tuple[int, int],
                 duration: float = 0.87):
        self.from_px  = (float(from_px[0]), float(from_px[1]))
        self.to_px    = (float(to_px[0]),   float(to_px[1]))
        self.duration = duration
        self.elapsed  = 0.0
        mx = (from_px[0] + to_px[0]) / 2
        my = min(from_px[1], to_px[1]) - 55
        self._ctrl = (mx, my)
        self._trail: List[Tuple[float, float]] = []
        self._fire:  List[Dict[str, Any]] = []
        # Launch smoke puffs at origin
        self._launch_smoke: List[Dict[str, Any]] = []
        self._launch_done = False
        # Impact debris
        self._debris: List[Dict[str, Any]] = []
        self._impact_triggered = False

        if MissileAnimation._rocket_surf is None:
            MissileAnimation._rocket_surf = _build_rocket_surf(28, 9)

    # ---- Bezier math -------------------------------------------------
    def _pos_at(self, t: float) -> Tuple[float, float]:
        x0, y0 = self.from_px
        x1, y1 = self._ctrl
        x2, y2 = self.to_px
        x = (1-t)**2 * x0 + 2*(1-t)*t * x1 + t**2 * x2
        y = (1-t)**2 * y0 + 2*(1-t)*t * y1 + t**2 * y2
        return x, y

    def _tangent_at(self, t: float) -> Tuple[float, float]:
        x0, y0 = self.from_px
        x1, y1 = self._ctrl
        x2, y2 = self.to_px
        dx = 2*(1-t)*(x1-x0) + 2*t*(x2-x1)
        dy = 2*(1-t)*(y1-y0) + 2*t*(y2-y1)
        return dx, dy

    # ---- Update ------------------------------------------------------
    def update(self, dt: float) -> bool:
        self.elapsed += dt
        t = _clamp(self.elapsed / self.duration, 0.0, 1.0)
        pos = self._pos_at(t)

        # Launch smoke puffs at origin for first 0.12 s
        if not self._launch_done:
            if self.elapsed < 0.12:
                for _ in range(3):
                    ang = random.uniform(0, 2 * math.pi)
                    spd = random.uniform(18, 55)
                    self._launch_smoke.append({
                        'x': self.from_px[0], 'y': self.from_px[1],
                        'vx': math.cos(ang) * spd,
                        'vy': math.sin(ang) * spd - 38,
                        'r':  random.uniform(5, 12),
                        'life': random.uniform(0.28, 0.48),
                        'elapsed': 0.0,
                    })
            else:
                self._launch_done = True

        live_ls = []
        for s in self._launch_smoke:
            s['elapsed'] += dt
            s['x'] += s['vx'] * dt
            s['y'] += s['vy'] * dt
            s['vy'] += 25 * dt
            if s['elapsed'] < s['life']:
                live_ls.append(s)
        self._launch_smoke = live_ls

        # Trail position
        self._trail.append(pos)
        if len(self._trail) > 28:
            self._trail.pop(0)

        # Fire/smoke exhaust particles
        if t < 0.97:
            hx, hy = pos
            dx, dy = self._tangent_at(t)
            mag = math.hypot(dx, dy)
            if mag > 0:
                ndx, ndy = dx / mag, dy / mag
            else:
                ndx, ndy = 1.0, 0.0
            ex = hx - ndx * 16
            ey = hy - ndy * 16
            for _ in range(4):
                spread   = random.uniform(-0.60, 0.60)
                spd      = random.uniform(30, 95)
                ang      = math.atan2(-ndy, -ndx) + spread
                is_fire  = random.random() < 0.55
                self._fire.append({
                    'x': ex, 'y': ey,
                    'vx': math.cos(ang) * spd,
                    'vy': math.sin(ang) * spd,
                    'life': random.uniform(0.08, 0.24),
                    'elapsed': 0.0,
                    'fire': is_fire,
                    'r': random.uniform(2.5, 5.5),
                })

        live_f = []
        for p in self._fire:
            p['elapsed'] += dt
            p['x']  += p['vx'] * dt
            p['y']  += p['vy'] * dt
            p['vy'] += 55 * dt
            if p['elapsed'] < p['life']:
                live_f.append(p)
        self._fire = live_f

        # Spawn impact debris when missile arrives
        if t > 0.88 and not self._impact_triggered:
            self._impact_triggered = True
            ix, iy = int(self.to_px[0]), int(self.to_px[1])
            for _ in range(8):
                ang = random.uniform(0, 2 * math.pi)
                spd = random.uniform(40, 120)
                self._debris.append({
                    'x': float(ix), 'y': float(iy),
                    'vx': math.cos(ang) * spd,
                    'vy': math.sin(ang) * spd - 30,
                    'r':  random.uniform(3, 7),
                    'life': random.uniform(0.25, 0.55),
                    'elapsed': 0.0,
                    'col': random.choice([(80, 72, 65), (50, 45, 40), (120, 55, 20)]),
                })

        live_d = []
        for d in self._debris:
            d['elapsed'] += dt
            d['x']  += d['vx'] * dt
            d['y']  += d['vy'] * dt
            d['vy'] += 260 * dt
            if d['elapsed'] < d['life']:
                live_d.append(d)
        self._debris = live_d

        return self.elapsed < self.duration

    # ---- Draw --------------------------------------------------------
    def draw(self, surface):
        import pygame
        t = self.elapsed / self.duration

        # == Launch smoke puffs at origin ==
        for s in self._launch_smoke:
            frac = s['elapsed'] / s['life']
            a    = int(140 * (1 - frac))
            rad  = max(1, int(s['r'] * (1 + frac * 0.8)))
            gray = int(110 + 60 * frac)
            ls = pygame.Surface((rad*2+1, rad*2+1), pygame.SRCALPHA)
            pygame.draw.circle(ls, (gray, gray, gray, a), (rad, rad), rad)
            surface.blit(ls, (int(s['x']) - rad, int(s['y']) - rad))

        # == Volumetric smoke trail (older = cooler, fading) ==
        n = len(self._trail)
        for i, (px, py) in enumerate(self._trail):
            frac  = i / max(n - 1, 1)   # 0=oldest, 1=newest
            alpha = int(100 * frac)
            rad   = max(1, int(2 + frac * 5))
            gray  = int(75 + 80 * frac)
            gs = pygame.Surface((rad*2+1, rad*2+1), pygame.SRCALPHA)
            pygame.draw.circle(gs, (gray, gray, gray, alpha), (rad, rad), rad)
            surface.blit(gs, (int(px) - rad, int(py) - rad))

        # == Fire / smoke exhaust particles ==
        for p in self._fire:
            frac = p['elapsed'] / p['life']
            a    = int(230 * (1 - frac))
            rad  = max(1, int(p['r'] * (1 - frac * 0.5)))
            if p['fire']:
                col = (int(255 * (1 - frac * 0.3)),
                       int(155 * (1 - frac)),
                       int(18 * (1 - frac)))
            else:
                gv = int(105 + 85 * frac)
                col = (gv, gv, gv)
            ps = pygame.Surface((rad*2+1, rad*2+1), pygame.SRCALPHA)
            pygame.draw.circle(ps, (*col, a), (rad, rad), rad)
            surface.blit(ps, (int(p['x']) - rad, int(p['y']) - rad))

        # == Rotated rocket body ==
        if t < 1.0:
            hx, hy = self._pos_at(t)
            dx, dy = self._tangent_at(t)
            angle  = math.atan2(dy, dx) if (dx or dy) else 0.0
            rot    = pygame.transform.rotate(
                MissileAnimation._rocket_surf, -math.degrees(angle))
            rr = rot.get_rect(center=(int(hx), int(hy)))
            surface.blit(rot, rr.topleft)

        # == Impact: shockwave ring + fireball + debris ==
        if t > 0.85:
            imp = _clamp((t - 0.85) / 0.15, 0.0, 1.0)
            ix  = int(self.to_px[0])
            iy  = int(self.to_px[1])

            # Shockwave ring
            ring_r = max(1, int(36 * imp))
            ring_a = int(200 * (1 - imp))
            rs = pygame.Surface((ring_r*2+4, ring_r*2+4), pygame.SRCALPHA)
            pygame.draw.circle(rs, (255, 200, 80, ring_a),
                               (ring_r+2, ring_r+2), ring_r, 3)
            surface.blit(rs, (ix - ring_r - 2, iy - ring_r - 2))

            # Fireball core
            fb_r = max(1, int(22 * (1 - imp)))
            pygame.draw.circle(surface,
                               (255, int(230 * (1-imp)), int(50 * (1-imp))),
                               (ix, iy), fb_r)
            if fb_r > 3:
                pygame.draw.circle(surface, (255, 255, 200), (ix, iy), max(1, fb_r // 3))

        # == Debris chunks from impact ==
        for d in self._debris:
            frac = d['elapsed'] / d['life']
            a    = int(200 * (1 - frac))
            rad  = max(1, int(d['r'] * (1 - frac * 0.6)))
            col  = tuple(int(c * (1 - frac * 0.5)) for c in d['col'])
            ds = pygame.Surface((rad*2+1, rad*2+1), pygame.SRCALPHA)
            pygame.draw.circle(ds, (*col, a), (rad, rad), rad)
            surface.blit(ds, (int(d['x']) - rad, int(d['y']) - rad))


# ---------------------------------------------------------------------------
# Melee rush – rush + X-slash arc + rush sparks
# ---------------------------------------------------------------------------

class MeleeAnimation:
    """Attacker rushes toward the target with sparks, snap back + X-slash."""

    def __init__(self, attacker_px: Tuple[float, float],
                 target_px: Tuple[float, float],
                 duration: float = 0.48):
        self.attacker_px = attacker_px
        self.target_px   = target_px
        self.duration    = duration
        self.elapsed     = 0.0
        self._rush = (
            attacker_px[0] + (target_px[0] - attacker_px[0]) * 0.75,
            attacker_px[1] + (target_px[1] - attacker_px[1]) * 0.75,
        )
        # Slash arc points
        self._arc_pts: List[Tuple[float, float]] = []
        mx = (self._rush[0] + target_px[0]) / 2
        my = (self._rush[1] + target_px[1]) / 2
        for i in range(6):
            ang = i * math.pi * 2 / 6 + math.pi * 0.1
            r   = random.uniform(14, 26)
            self._arc_pts.append((mx + math.cos(ang) * r,
                                  my + math.sin(ang) * r))
        # Rush sparks (particles left behind during rush)
        self._rush_sparks: List[Dict[str, Any]] = []

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        t = self.elapsed / self.duration

        # Spawn sparks flying backward from the rushing mech
        if t < 0.45:
            rush_factor = _smoothstep(t / 0.45)
            cx = self.attacker_px[0] + (self._rush[0] - self.attacker_px[0]) * rush_factor
            cy = self.attacker_px[1] + (self._rush[1] - self.attacker_px[1]) * rush_factor
            bdx = self.attacker_px[0] - self._rush[0]
            bdy = self.attacker_px[1] - self._rush[1]
            blen = math.hypot(bdx, bdy)
            if blen > 0:
                back_nx, back_ny = bdx / blen, bdy / blen
            else:
                back_nx, back_ny = 1.0, 0.0
            for _ in range(2):
                ang = math.atan2(back_ny, back_nx) + random.uniform(-0.9, 0.9)
                spd = random.uniform(45, 110)
                self._rush_sparks.append({
                    'x': cx, 'y': cy,
                    'vx': math.cos(ang) * spd,
                    'vy': math.sin(ang) * spd,
                    'life': random.uniform(0.08, 0.18),
                    'elapsed': 0.0,
                })

        live = []
        for s in self._rush_sparks:
            s['elapsed'] += dt
            s['x']  += s['vx'] * dt
            s['y']  += s['vy'] * dt
            s['vy'] += 200 * dt
            if s['elapsed'] < s['life']:
                live.append(s)
        self._rush_sparks = live

        return self.elapsed < self.duration

    @property
    def draw_offset(self) -> Tuple[float, float]:
        t = self.elapsed / self.duration
        if t < 0.45:
            factor = _smoothstep(t / 0.45)
        else:
            factor = _smoothstep((1.0 - t) / 0.55)
        dx = (self._rush[0] - self.attacker_px[0]) * factor
        dy = (self._rush[1] - self.attacker_px[1]) * factor
        return dx, dy

    def draw(self, surface):
        import pygame
        t = self.elapsed / self.duration

        # Rush sparks flying behind mech
        for s in self._rush_sparks:
            frac = s['elapsed'] / s['life']
            a    = int(220 * (1 - frac))
            col  = (int(255 * (1 - frac * 0.4)),
                    int(200 * (1 - frac)),
                    int(55 * (1 - frac)))
            rad  = max(1, int(2 * (1 - frac)))
            pygame.draw.circle(surface, col, (int(s['x']), int(s['y'])), rad)

        # Impact zone (35%–65% of animation)
        if 0.35 < t < 0.65:
            phase = (t - 0.35) / 0.30
            imp_a = 1.0 - abs(phase - 0.5) / 0.5
            imp_r = max(1, int(28 * imp_a))
            mx = int((self._rush[0] + self.target_px[0]) / 2)
            my = int((self._rush[1] + self.target_px[1]) / 2)

            # Glow burst
            col = (int(255 * imp_a), int(210 * imp_a), int(60 * imp_a))
            gs = pygame.Surface((imp_r*2+4, imp_r*2+4), pygame.SRCALPHA)
            pygame.draw.circle(gs, (*col, int(170 * imp_a)),
                               (imp_r+2, imp_r+2), imp_r)
            surface.blit(gs, (mx - imp_r - 2, my - imp_r - 2))

            # X-slash (two diagonal lines crossing at impact)
            slash_len = int(22 * imp_a)
            slash_col = (int(255 * imp_a), int(245 * imp_a), int(130 * imp_a))
            for slash_ang in [math.pi/4, -math.pi/4]:
                dxs = int(math.cos(slash_ang) * slash_len)
                dys = int(math.sin(slash_ang) * slash_len)
                pygame.draw.line(surface, slash_col,
                                 (mx - dxs, my - dys), (mx + dxs, my + dys), 2)

            # Radial spark burst
            for px2, py2 in self._arc_pts:
                travel = phase * 1.4
                ex = int(mx + (px2 - mx) * travel)
                ey = int(my + (py2 - my) * travel)
                arc_a = int(200 * imp_a * (random.random() * 0.5 + 0.5))
                pygame.draw.line(surface, (255, 240, 120), (mx, my), (ex, ey), 1)

        # Orange/white streak trail behind the rush
        if 0.10 < t < 0.55:
            streak_a = 1.0 - abs(t - 0.35) / 0.35
            sc = (int(255 * streak_a), int(175 * streak_a), int(40 * streak_a))
            ax, ay = self.attacker_px
            rx, ry = self._rush
            pygame.draw.line(surface, sc, (int(ax), int(ay)),
                             (int(rx), int(ry)), max(1, int(3 * streak_a)))


# ---------------------------------------------------------------------------
# Explosion (mech death / artillery impact)
# ---------------------------------------------------------------------------

class _Particle:
    def __init__(self, x: float, y: float, vx: float, vy: float,
                 color: Tuple, lifetime: float, size: float = 5.0):
        self.x, self.y   = x, y
        self.vx, self.vy = vx, vy
        self.color       = color
        self.lifetime    = lifetime
        self.elapsed     = 0.0
        self.size        = size

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        self.x  += self.vx * dt
        self.y  += self.vy * dt
        self.vy += 240 * dt   # gravity
        return self.elapsed < self.lifetime

    def draw(self, surface):
        import pygame
        alpha = max(0.0, 1.0 - self.elapsed / self.lifetime)
        r     = max(1, int(self.size * alpha))
        col   = tuple(int(c * alpha) for c in self.color)
        pygame.draw.circle(surface, col, (int(self.x), int(self.y)), r)


class ExplosionAnimation:
    """Dramatic particle burst with ground scorch and optional secondary pop."""

    _COLOURS = [
        (255, 210, 60),
        (255, 130, 30),
        (220, 55,  20),
        (200, 200, 200),
        (255, 255, 180),
        (180, 180, 180),
    ]

    def __init__(self, center: Tuple[int, int], duration: float = 0.98):
        self.center   = center
        self.duration = duration
        self.elapsed  = 0.0
        self._particles: List[_Particle] = []
        self._debris:    List[_Particle] = []
        self._scorch_r   = 32
        self._secondary_done = False
        self._secondary: List[_Particle] = []
        self._spawn()

    def _spawn(self):
        cx, cy = self.center
        for _ in range(38):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(65, 240)
            vx    = math.cos(angle) * speed
            vy    = math.sin(angle) * speed - random.uniform(30, 110)
            color = random.choice(self._COLOURS)
            life  = random.uniform(0.30, self.duration)
            size  = random.uniform(3.0, 6.5)
            self._particles.append(_Particle(cx, cy, vx, vy, color, life, size))
        # Debris chunks
        for _ in range(10):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(30, 95)
            self._debris.append(_Particle(
                cx, cy,
                math.cos(angle) * speed, math.sin(angle) * speed - 25,
                (78, 72, 68), random.uniform(0.5, self.duration),
                random.uniform(5.0, 10.0),
            ))

    def _spawn_secondary(self):
        cx, cy = self.center
        ox = cx + random.randint(-18, 18)
        oy = cy + random.randint(-14, 14)
        for _ in range(14):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(35, 130)
            color = random.choice(self._COLOURS)
            self._secondary.append(_Particle(
                ox, oy,
                math.cos(angle) * speed, math.sin(angle) * speed - random.uniform(20, 70),
                color, random.uniform(0.2, 0.5), random.uniform(2.5, 5.0),
            ))

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        # Trigger secondary mini-explosion
        if not self._secondary_done and self.elapsed > self.duration * 0.35:
            self._secondary_done = True
            self._spawn_secondary()
        self._particles = [p for p in self._particles if p.update(dt)]
        self._debris    = [p for p in self._debris    if p.update(dt)]
        self._secondary = [p for p in self._secondary if p.update(dt)]
        return self.elapsed < self.duration

    def draw(self, surface):
        import pygame
        t  = self.elapsed / self.duration
        cx, cy = self.center

        # Ground scorch ellipse (persistent, fades over time)
        scorch_a = max(0, int(90 * (1.0 - t)))
        if scorch_a > 4:
            sr = self._scorch_r
            ss = pygame.Surface((sr*2+4, sr//2*2+4), pygame.SRCALPHA)
            pygame.draw.ellipse(ss, (18, 14, 10, scorch_a),
                                (2, 2, sr*2, sr//2*2))
            surface.blit(ss, (cx - sr - 2, cy - sr//4))

        # Expanding shockwave ring
        if t < 0.40:
            ring_r = int(52 * (t / 0.40))
            ring_a = int(210 * (1 - t / 0.40))
            rs = pygame.Surface((ring_r*2+6, ring_r*2+6), pygame.SRCALPHA)
            pygame.draw.circle(rs, (255, 200, 80, ring_a),
                               (ring_r+3, ring_r+3), ring_r, 3)
            surface.blit(rs, (cx - ring_r - 3, cy - ring_r - 3))

        # Fire column (bright flash in first 22%)
        if t < 0.22:
            frac = 1.0 - t / 0.22
            fr = max(1, int(22 * frac))
            pygame.draw.circle(surface, (255, int(200 * frac), 40),
                               self.center, fr)

        for p in self._debris:
            p.draw(surface)
        for p in self._particles:
            p.draw(surface)
        for p in self._secondary:
            p.draw(surface)


# ---------------------------------------------------------------------------
# Damage flash
# ---------------------------------------------------------------------------

class DamageFlash:
    """Red overlay that flashes briefly on a mech when hit."""

    def __init__(self, duration: float = 0.25):
        self.duration = duration
        self.elapsed  = 0.0

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        return self.elapsed < self.duration

    @property
    def alpha(self) -> int:
        return max(0, int(210 * (1.0 - self.elapsed / self.duration)))


# ---------------------------------------------------------------------------
# Self-buff ability effect
# ---------------------------------------------------------------------------

class SelfBuffAnimation:
    """Concentric expanding rings + particle burst for self-targeting abilities."""

    _STYLES: dict = {
        "shield":     (60,  180, 255),
        "sprint":     (160, 255,  60),
        "cloak":      (160,  80, 220),
        "overcharge": (255, 200,  30),
    }

    def __init__(self, center: Tuple[int, int], style: str = "shield",
                 duration: float = 0.65):
        self.center   = center
        self.color    = self._STYLES.get(style, (255, 255, 255))
        self.duration = duration
        self.elapsed  = 0.0
        self._particles: List[_Particle] = []
        self._spawn()

    def _spawn(self):
        cx, cy = self.center
        for _ in range(22):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(55, 150)
            life  = random.uniform(0.22, self.duration * 0.85)
            self._particles.append(_Particle(
                cx, cy,
                math.cos(angle) * speed, math.sin(angle) * speed,
                self.color, life, random.uniform(2.0, 4.5),
            ))

    def update(self, dt: float) -> bool:
        self.elapsed += dt
        self._particles = [p for p in self._particles if p.update(dt)]
        return self.elapsed < self.duration

    def draw(self, surface):
        import pygame
        t  = self.elapsed / self.duration
        cx, cy = self.center
        r, g, b = self.color

        if t < 0.25:
            gt  = t / 0.25
            ga  = max(0, int(210 * (1.0 - gt)))
            gr  = max(1, int(24 * gt))
            gs  = pygame.Surface((gr*2+4, gr*2+4), pygame.SRCALPHA)
            pygame.draw.circle(gs, (r, g, b, ga), (gr+2, gr+2), gr)
            surface.blit(gs, (cx - gr - 2, cy - gr - 2))

        for start_t in (0.0, 0.20, 0.40):
            if t < start_t:
                continue
            rt     = min(1.0, (t - start_t) / (1.0 - start_t))
            ring_r = max(1, int(52 * rt))
            ring_a = max(0, int(230 * (1.0 - rt)))
            rs     = pygame.Surface((ring_r*2+4, ring_r*2+4), pygame.SRCALPHA)
            pygame.draw.circle(rs, (r, g, b, ring_a),
                               (ring_r+2, ring_r+2), ring_r, 2)
            surface.blit(rs, (cx - ring_r - 2, cy - ring_r - 2))

        for p in self._particles:
            p.draw(surface)
