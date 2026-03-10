"""Main battle screen – WH40K-style visuals with animations."""
import math
import random
import pygame
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

from src.game.game_state import GameState
from src.models.mech import Mech
from src.ui.constants import *
from src.ui.components import Button, HpBar, FloatingText, draw_text, draw_panel
from src.ui.mech_renderer import draw_mech
from src.ui.animations import (
    MoveAnimation, LaserBeamAnimation, AutocannonAnimation,
    MissileAnimation, MeleeAnimation, ExplosionAnimation, DamageFlash,
    SelfBuffAnimation,
)

TILE_COLOURS = {
    "open":    COL_OPEN,
    "cover":   COL_COVER,
    "blocked": COL_BLOCKED,
}


class BattleMode(Enum):
    IDLE             = auto()
    MECH_SELECTED    = auto()
    CHOOSING_MOVE    = auto()
    CHOOSING_ATTACK  = auto()
    CHOOSING_ABILITY = auto()
    GAME_OVER        = auto()


class BattleScreen:
    GRID_PAD_X = 10
    GRID_PAD_Y = 20

    def __init__(self, manager):
        self.manager = manager
        self.gs: Optional[GameState] = None
        self.mode: BattleMode = BattleMode.IDLE

        self.tile_size: int = 48
        self.grid_off_x: int = self.GRID_PAD_X
        self.grid_off_y: int = self.GRID_PAD_Y

        self.hovered_tile: Optional[Tuple[int, int]] = None
        self.floaters: List[FloatingText] = []

        self._btns: List = []
        self._btn_end_turn: Optional[Button] = None

        self._hl_move_surf: Optional[pygame.Surface] = None
        self._hl_atk_surf:  Optional[pygame.Surface] = None
        self._hl_sel_surf:  Optional[pygame.Surface] = None
        self._hl_abl_surf:  Optional[pygame.Surface] = None

        self._message: str = ""
        self._msg_timer: float = 0.0
        self.winner: Optional[int] = None

        # Auto end-turn timer (>0 means countdown is running)
        self._pending_auto_end: float = 0.0

        # Visual polish state
        self._anim_time:    float = 0.0          # wall-clock for pulsing effects
        self._tile_surfs:   dict  = {}           # pre-baked tile textures
        self._scanline_surf: Optional[pygame.Surface] = None

        # Animation state
        self.attack_animations: List = []
        self.mech_move_anims:   Dict[int, MoveAnimation]   = {}
        self.mech_damage_flash: Dict[int, DamageFlash]     = {}
        self.mech_melee_anim:   Dict[int, MeleeAnimation]  = {}
        # Fire-pose animation: mech_id → elapsed since fire triggered
        self.mech_fire_anims:   Dict[int, float]           = {}
        _FIRE_ANIM_DUR = 0.50   # seconds for one fire cycle
        self._FIRE_DUR  = _FIRE_ANIM_DUR
        # Delayed visual effects: list of [time_remaining, callable]
        self._pending_effects: List = []
        # Frozen HP values shown on bars until the projectile visually hits.
        # Maps id(mech) → HP to display.  Cleared per-mech in each impact callback.
        self._display_hp: Dict[int, int] = {}

    # Seconds from weapon fire until projectile visually hits target
    _IMPACT_DELAY = {
        "laser":      0.18,
        "autocannon": 0.32,
        "missiles":   0.72,
        "melee":      0.21,
    }

    # ------------------------------------------------------------------
    def on_enter(self, **_):
        self.gs = self.manager.game_state
        self.mode = BattleMode.IDLE
        self.floaters.clear()
        self.attack_animations.clear()
        self.mech_move_anims.clear()
        self.mech_damage_flash.clear()
        self.mech_melee_anim.clear()
        self.winner = None
        self._message = ""

        mw = self.gs.map_width
        mh = self.gs.map_height
        ts = min(
            (GRID_AREA_W - 2 * self.GRID_PAD_X) // mw,
            (SCREEN_H - 2 * self.GRID_PAD_Y) // mh,
            TILE_SIZE_MAX,
        )
        self.tile_size = max(ts, TILE_SIZE_MIN)
        total_px = self.tile_size * mw
        total_py = self.tile_size * mh
        self.grid_off_x = self.GRID_PAD_X + (GRID_AREA_W - 2*self.GRID_PAD_X - total_px) // 2
        self.grid_off_y = self.GRID_PAD_Y + (SCREEN_H - 2*self.GRID_PAD_Y - total_py) // 2

        self._pending_auto_end = 0.0
        self.mech_fire_anims.clear()
        self._pending_effects.clear()
        self._display_hp.clear()
        self._rebuild_hl_surfs()
        self._bake_tile_surfs()
        self._bake_scanlines()
        self._rebuild_hud_buttons()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------
    def grid_to_px(self, gx: int, gy: int) -> Tuple[int, int]:
        return (self.grid_off_x + gx * self.tile_size,
                self.grid_off_y + gy * self.tile_size)

    def px_to_grid(self, px: int, py: int) -> Optional[Tuple[int, int]]:
        gx = (px - self.grid_off_x) // self.tile_size
        gy = (py - self.grid_off_y) // self.tile_size
        if self.gs and 0 <= gx < self.gs.map_width and 0 <= gy < self.gs.map_height:
            return gx, gy
        return None

    def tile_center_px(self, gx: int, gy: int) -> Tuple[int, int]:
        px, py = self.grid_to_px(gx, gy)
        return px + self.tile_size // 2, py + self.tile_size // 2

    # ------------------------------------------------------------------
    def _rebuild_hl_surfs(self):
        ts = self.tile_size
        def make(col):
            s = pygame.Surface((ts, ts), pygame.SRCALPHA)
            s.fill(col)
            return s
        self._hl_move_surf = make(COL_HL_MOVE)
        self._hl_atk_surf  = make(COL_HL_ATTACK)
        self._hl_sel_surf  = make(COL_HL_SELECT)
        self._hl_abl_surf  = make(COL_HL_ABILITY)

    # ------------------------------------------------------------------
    # HUD buttons
    # ------------------------------------------------------------------
    def _rebuild_hud_buttons(self):
        self._btns = []
        self._btn_end_turn = None
        if not self.gs:
            return

        bx = HUD_X + 12
        bw = HUD_W - 24
        by = 275
        bh = 40
        gap = 8

        cm = self.gs.current_mech
        if cm is None:
            return

        self._btns.append(("move", Button(
            (bx, by, bw, bh), f"Move  ({cm.move_range} tiles)",
            enabled=cm.can_move(), font_size=FONT_MEDIUM,
        )))
        by += bh + gap

        for wi, weapon in enumerate(cm.weapons):
            ammo_str = f" [{weapon.ammo_display}]" if weapon.ammo is not None else ""
            self._btns.append((f"weapon_{wi}", Button(
                (bx, by, bw, bh),
                f"{weapon.name}  {weapon.damage}dmg{ammo_str}",
                enabled=cm.can_act() and weapon.has_ammo(),
                font_size=FONT_SMALL + 1,
            )))
            by += bh + gap

        ab = cm.ability
        self._btns.append(("ability", Button(
            (bx, by, bw, bh),
            f"✦ {ab.name}  [{ab.uses_remaining}/{ab.uses_per_battle}]",
            enabled=cm.can_act() and ab.can_use(),
            color_normal=(55, 50, 25), color_hover=(80, 75, 35),
            font_size=FONT_SMALL + 1,
        )))
        by += bh + gap + 4

        self._btn_end_turn = Button(
            (bx, by, bw, bh + 4), "End Turn",
            color_normal=BTN_DANGER, color_hover=BTN_DANGER_H,
            font_size=FONT_MEDIUM,
        )
        self._btns.append(("end_turn", self._btn_end_turn))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event):
        if self.mode == BattleMode.GAME_OVER:
            if event.type == pygame.MOUSEBUTTONDOWN:
                self.manager.winner = self.winner
                self.manager.switch_to("result")
            return

        if event.type == pygame.MOUSEMOTION:
            self.hovered_tile = self.px_to_grid(*event.pos)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            tile = self.px_to_grid(*event.pos)
            if tile and event.pos[0] < GRID_AREA_W:
                self._handle_grid_click(tile)
            else:
                self._handle_hud_click(event)
        else:
            self._handle_hud_event(event)

    def _handle_grid_click(self, tile: Tuple[int, int]):
        gs = self.gs
        cm = gs.current_mech
        if cm is None:
            return

        tx, ty = tile
        clicked_tile = gs.map_data[ty][tx]

        if self.mode in (BattleMode.IDLE, BattleMode.MECH_SELECTED, BattleMode.CHOOSING_MOVE):
            if tile in gs.valid_move_tiles:
                old_px = self.grid_to_px(*cm.position)
                gs.move_mech(cm, tile)
                new_px = self.grid_to_px(*cm.position)
                self.mech_move_anims[id(cm)] = MoveAnimation(old_px, new_px)
                self.mode = BattleMode.MECH_SELECTED
                self._rebuild_hud_buttons()
                self._check_auto_end_turn()
                return

            if clicked_tile.mech is not None:
                mech = clicked_tile.mech
                if mech.team == cm.team and mech is cm:
                    if self.mode == BattleMode.MECH_SELECTED:
                        gs.select_mech(cm)
                        self.mode = BattleMode.CHOOSING_MOVE
                return

        elif self.mode == BattleMode.CHOOSING_ATTACK:
            if tile in gs.valid_attack_tiles:
                weapon = gs.active_weapon          # capture before execute clears it
                attacker_pos = cm.position
                # Snapshot HP of every mech BEFORE damage is applied so bars
                # stay frozen until the projectile visually arrives.
                pre_hp = {id(m): m.hp
                          for m in gs.team1 + gs.team2 + gs.team3}
                results = gs.execute_attack(tile)
                # Freeze display_hp at pre-attack values for every hit target
                for r in results:
                    tgt_id = id(r["target"])
                    if tgt_id in pre_hp:
                        self._display_hp[tgt_id] = pre_hp[tgt_id]
                self._spawn_attack_effects(cm, weapon, attacker_pos, tile, results)
                self._check_victory()
                if self.mode != BattleMode.GAME_OVER:
                    self.mode = BattleMode.MECH_SELECTED
                    self._rebuild_hud_buttons()
                    self._check_auto_end_turn()

        elif self.mode == BattleMode.CHOOSING_ABILITY:
            ab = cm.ability if cm else None
            if ab and ab.needs_target and tile in gs.valid_attack_tiles:
                # Capture enemies in the splash zone BEFORE execution
                # (dead mechs lose their position after execute_ability)
                splash_victims = [
                    m for m in gs.team1 + gs.team2 + gs.team3
                    if m.is_alive and m.team != cm.team and m.position is not None
                    and max(abs(tile[0] - m.position[0]),
                            abs(tile[1] - m.position[1])) <= 2
                ]
                # Snapshot HP before artillery damage is applied
                pre_hp_arty = {id(m): m.hp for m in splash_victims}
                result = gs.execute_ability(target_pos=tile)
                # Freeze display HP so bars don't drop until missiles land
                for v in splash_victims:
                    self._display_hp[id(v)] = pre_hp_arty[id(v)]
                self._spawn_ability_effects(cm, ab.effect, tile, splash_victims)
                self._show_message(result.get("message", ""))
                self._check_victory()
                if self.mode != BattleMode.GAME_OVER:
                    self.mode = BattleMode.MECH_SELECTED
                    self._rebuild_hud_buttons()
                    self._check_auto_end_turn()

    def _handle_hud_click(self, event):
        for tag, btn in self._btns:
            if btn.handle_event(event):
                self._on_button(tag)

    def _handle_hud_event(self, event):
        for _, btn in self._btns:
            btn.handle_event(event)

    def _on_button(self, tag: str):
        gs = self.gs
        cm = gs.current_mech
        if cm is None:
            return

        if tag == "move":
            if cm.can_move():
                gs.select_mech(cm)
                self.mode = BattleMode.CHOOSING_MOVE

        elif tag.startswith("weapon_"):
            wi = int(tag.split("_")[1])
            weapon = cm.weapons[wi]
            if cm.can_act() and weapon.has_ammo():
                gs.selected_mech = cm
                gs.select_weapon(weapon)
                self.mode = BattleMode.CHOOSING_ATTACK

        elif tag == "ability":
            ab = cm.ability
            if cm.can_act() and ab.can_use():
                if ab.needs_target:
                    gs.selected_mech = cm
                    gs.select_ability()
                    self.mode = BattleMode.CHOOSING_ABILITY
                else:
                    caster_pos = cm.position    # capture before execute
                    result = gs.execute_ability()
                    self._spawn_ability_effects(cm, ab.effect)
                    self._show_message(result.get("message", ""))
                    self._check_victory()
                    if self.mode != BattleMode.GAME_OVER:
                        if result.get("extra_move"):
                            self.mode = BattleMode.CHOOSING_MOVE
                        else:
                            self.mode = BattleMode.MECH_SELECTED
                        self._rebuild_hud_buttons()
                        self._check_auto_end_turn()

        elif tag == "end_turn":
            self._do_end_turn()

    def _player_name(self, team: int) -> str:
        names = {
            1: getattr(self.manager, "player1_name", "Player 1"),
            2: getattr(self.manager, "player2_name", "Player 2"),
            3: getattr(self.manager, "player3_name", "Player 3"),
        }
        return names.get(team, f"Player {team}")

    def _do_end_turn(self):
        self._pending_auto_end = 0.0
        self.gs.end_turn()
        self.mode = BattleMode.IDLE
        self._rebuild_hud_buttons()
        cm = self.gs.current_mech
        if cm:
            self._show_message(f"{self._player_name(cm.team)}'s turn: {cm.name}")

    def _check_auto_end_turn(self):
        """Schedule an automatic end-turn if the current mech has nothing left to do."""
        if self.mode == BattleMode.GAME_OVER or self._pending_auto_end > 0:
            return
        cm = self.gs.current_mech if self.gs else None
        if cm and not cm.can_move() and not cm.can_act():
            self._pending_auto_end = 0.8   # 0.8 s delay before auto-advancing

    def _check_victory(self):
        winner = self.gs.check_victory()
        if winner:
            self.winner = winner
            self.mode = BattleMode.GAME_OVER

    # ------------------------------------------------------------------
    # Animation spawning
    # ------------------------------------------------------------------
    def _spawn_attack_effects(self, attacker, weapon, attacker_pos, target_pos, results):
        if attacker_pos is None or weapon is None:
            return
        self.mech_fire_anims[id(attacker)] = 0.0
        a_cx, a_cy = self.tile_center_px(*attacker_pos)
        t_cx, t_cy = self.tile_center_px(*target_pos)

        wtype = weapon.type
        if wtype == "laser":
            self.attack_animations.append(LaserBeamAnimation((a_cx, a_cy), (t_cx, t_cy)))
        elif wtype == "autocannon":
            self.attack_animations.append(AutocannonAnimation((a_cx, a_cy), (t_cx, t_cy)))
        elif wtype == "missiles":
            self.attack_animations.append(MissileAnimation((a_cx, a_cy), (t_cx, t_cy)))
        elif wtype == "melee":
            self.mech_melee_anim[id(attacker)] = MeleeAnimation(
                (float(a_cx), float(a_cy)), (float(t_cx), float(t_cy))
            )

        delay = self._IMPACT_DELAY.get(wtype, 0.18)

        def _make_impact_cb(r, tx, ty):
            def cb():
                tgt = r["target"]
                # Unfreeze the HP bar now that the projectile has visually arrived
                self._display_hp.pop(id(tgt), None)
                self.mech_damage_flash[id(tgt)] = DamageFlash()
                if not tgt.is_alive:
                    self.attack_animations.append(ExplosionAnimation((tx, ty)))
                # Floating damage text
                if tgt.position:
                    fx2, fy2 = self.tile_center_px(*tgt.position)
                else:
                    fx2, fy2 = tx, ty
                if r["hit"]:
                    text  = f"-{r['damage']}{'!' if r['critical'] else ''}"
                    color = DMG_CRIT_COL if r["critical"] else DMG_HIT_COL
                else:
                    text, color = "MISS", DMG_MISS_COL
                self.floaters.append(FloatingText(text, (fx2 - 14, fy2 - 20), color, font_size=24))
            return cb

        for r in results:
            self._pending_effects.append((delay, _make_impact_cb(r, t_cx, t_cy)))

    def _spawn_damage_floaters(self, results):
        for r in results:
            tgt = r["target"]
            if tgt.position:
                cx, cy = self.tile_center_px(*tgt.position)
            else:
                cx, cy = SCREEN_W // 2, SCREEN_H // 2

            if r["hit"]:
                text  = f"-{r['damage']}{'!' if r['critical'] else ''}"
                color = DMG_CRIT_COL if r["critical"] else DMG_HIT_COL
            else:
                text, color = "MISS", DMG_MISS_COL

            self.floaters.append(FloatingText(text, (cx - 14, cy - 20), color, font_size=24))

    def _spawn_ability_effects(self, attacker, effect: str,
                               target_pos=None, splash_victims=None):
        """Spawn visual effects for a used ability."""
        import math
        # Trigger firing pose on attacker for offensive abilities
        if effect in ("artillery", "overcharge"):
            self.mech_fire_anims[id(attacker)] = 0.0

        # Attacker centre pixel (position is still valid at this point)
        a_cx, a_cy = self.tile_center_px(*attacker.position)

        # ---- Self-buff abilities ----
        style_map = {
            "shield_wall": "shield",
            "sprint":      "sprint",
            "cloak":       "cloak",
            "overcharge":  "overcharge",
        }
        if effect in style_map:
            self.attack_animations.append(
                SelfBuffAnimation((a_cx, a_cy), style_map[effect])
            )
            return

        # ---- Artillery barrage ----
        if effect == "artillery" and target_pos is not None:
            t_cx, t_cy = self.tile_center_px(*target_pos)
            tx, ty = target_pos

            # 3 missiles fanning toward the impact zone (120° spread)
            for i in range(3):
                angle  = i * (2 * math.pi / 3)
                spread = self.tile_size * 0.35
                xt = t_cx + int(math.cos(angle) * spread)
                yt = t_cy + int(math.sin(angle) * spread)
                self.attack_animations.append(MissileAnimation((a_cx, a_cy), (xt, yt)))

            # Collect splash pixel coords now (tile layout won't change)
            splash_px = []
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = tx + dx, ty + dy
                if 0 <= nx < self.gs.map_width and 0 <= ny < self.gs.map_height:
                    splash_px.append(self.tile_center_px(nx, ny))

            # ALL impact visuals delayed until missiles arrive —
            # explosions, damage flash, floaters, and HP-bar unfreeze
            # are triggered together in a single callback.
            def _make_arty_cb(victims, bx, by, s_px):
                def cb():
                    # Central explosion
                    self.attack_animations.append(ExplosionAnimation((bx, by)))
                    # Smaller splash explosions
                    for spx in s_px:
                        self.attack_animations.append(
                            ExplosionAnimation(spx, duration=0.65)
                        )
                    # Damage flash + floaters + HP-bar unfreeze per victim
                    for m in victims:
                        self._display_hp.pop(id(m), None)
                        self.mech_damage_flash[id(m)] = DamageFlash()
                        if m.position:
                            fx2, fy2 = self.tile_center_px(*m.position)
                        else:
                            fx2, fy2 = (bx, by)
                        self.floaters.append(
                            FloatingText("HIT!", (fx2 - 14, fy2 - 20), DMG_HIT_COL, font_size=22)
                        )
                return cb

            self._pending_effects.append((
                self._IMPACT_DELAY["missiles"],
                _make_arty_cb(splash_victims or [], t_cx, t_cy, splash_px),
            ))

    def _show_message(self, msg: str, duration: float = 2.5):
        self._message = msg
        self._msg_timer = duration

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(self, dt: float):
        self._anim_time += dt
        self.floaters = [f for f in self.floaters if f.update(dt)]
        self.attack_animations = [a for a in self.attack_animations if a.update(dt)]

        for mid in list(self.mech_move_anims):
            if not self.mech_move_anims[mid].update(dt):
                del self.mech_move_anims[mid]
        for mid in list(self.mech_damage_flash):
            if not self.mech_damage_flash[mid].update(dt):
                del self.mech_damage_flash[mid]
        for mid in list(self.mech_melee_anim):
            if not self.mech_melee_anim[mid].update(dt):
                del self.mech_melee_anim[mid]

        for mid in list(self.mech_fire_anims):
            self.mech_fire_anims[mid] += dt
            if self.mech_fire_anims[mid] >= self._FIRE_DUR:
                del self.mech_fire_anims[mid]

        still_pending = []
        for delay, cb in self._pending_effects:
            delay -= dt
            if delay <= 0:
                cb()
            else:
                still_pending.append((delay, cb))
        self._pending_effects = still_pending

        if self._msg_timer > 0:
            self._msg_timer -= dt
            if self._msg_timer <= 0:
                self._message = ""

        if self._pending_auto_end > 0:
            self._pending_auto_end -= dt
            if self._pending_auto_end <= 0:
                self._pending_auto_end = 0.0
                if self.mode != BattleMode.GAME_OVER:
                    self._do_end_turn()

    # ------------------------------------------------------------------
    # Draw
    # ------------------------------------------------------------------
    def draw(self, surface: pygame.Surface):
        surface.fill(DARK_GRAY)
        self._draw_background(surface)
        self._draw_grid(surface)
        self._draw_highlights(surface)
        self._draw_mechs(surface)
        for anim in self.attack_animations:
            anim.draw(surface)
        for f in self.floaters:
            f.draw(surface)
        self._draw_hud(surface)
        if self.mode == BattleMode.GAME_OVER:
            self._draw_game_over(surface)

    # -- Pre-baked surfaces --
    def _bake_tile_surfs(self):
        """Render one texture surface per tile type (noise + inset bevel)."""
        ts  = self.tile_size
        rng = random.Random(0x4B3A)          # fixed seed → stable every battle
        tile_defs = {
            "open":    (38,  45,  38),
            "cover":   (55,  78,  48),
            "blocked": (30,  26,  23),
        }
        self._tile_surfs = {}
        for tile_type, base in tile_defs.items():
            surf = pygame.Surface((ts, ts))
            surf.fill(base)
            # Subtle per-pixel noise
            n_px = max(0, ts * ts // 12)
            for _ in range(n_px):
                nx = rng.randint(1, ts - 2)
                ny = rng.randint(1, ts - 2)
                v  = rng.randint(-11, 11)
                c  = tuple(max(0, min(255, ch + v)) for ch in base)
                surf.set_at((nx, ny), c)
            # Inset bevel (lighter top/left, darker bottom/right)
            lt = tuple(min(255, ch + 18) for ch in base)
            dk = tuple(max(0,   ch - 18) for ch in base)
            pygame.draw.line(surf, lt, (0,      0),      (ts - 1, 0),      1)
            pygame.draw.line(surf, lt, (0,      0),      (0,      ts - 1), 1)
            pygame.draw.line(surf, dk, (ts - 1, 0),      (ts - 1, ts - 1), 1)
            pygame.draw.line(surf, dk, (0,      ts - 1), (ts - 1, ts - 1), 1)
            self._tile_surfs[tile_type] = surf

    def _bake_scanlines(self):
        """Horizontal scanline overlay for a tactical-display atmosphere."""
        gw = self.gs.map_width  * self.tile_size + 2 * self.GRID_PAD_X + 20
        gh = self.gs.map_height * self.tile_size + 2 * self.GRID_PAD_Y + 20
        surf = pygame.Surface((gw, gh), pygame.SRCALPHA)
        for y in range(0, gh, 2):
            pygame.draw.line(surf, (0, 0, 0, 16), (0, y), (gw, y))
        self._scanline_surf = surf

    # -- Background / atmosphere --
    def _draw_background(self, surface: pygame.Surface):
        """Tactical display frame, corner brackets, and scanline overlay."""
        ts = self.tile_size
        gw = self.gs.map_width  * ts
        gh = self.gs.map_height * ts
        ox, oy = self.grid_off_x, self.grid_off_y

        # Outer frame (two nested thin rectangles)
        frame = pygame.Rect(ox - 4, oy - 4, gw + 8, gh + 8)
        pygame.draw.rect(surface, (45, 65, 45), frame, 1)
        pygame.draw.rect(surface, (28, 42, 28), frame.inflate(3, 3), 1)

        # Corner bracket accents
        blen      = max(10, ts // 2)
        blen_s    = max(6,  ts // 4)
        b_col     = (75, 155, 75)
        b_col_dim = (45, 90,  45)
        for fx, fy in [frame.topleft, frame.topright,
                       frame.bottomleft, frame.bottomright]:
            dx = 1 if fx == frame.left  else -1
            dy = 1 if fy == frame.top   else -1
            pygame.draw.line(surface, b_col,
                             (fx, fy), (fx + dx * blen, fy), 2)
            pygame.draw.line(surface, b_col,
                             (fx, fy), (fx, fy + dy * blen), 2)
            # Inner secondary tick
            pygame.draw.line(surface, b_col_dim,
                             (fx + dx * 4, fy + dy * 4),
                             (fx + dx * (4 + blen_s), fy + dy * 4), 1)
            pygame.draw.line(surface, b_col_dim,
                             (fx + dx * 4, fy + dy * 4),
                             (fx + dx * 4, fy + dy * (4 + blen_s)), 1)

        # Scanlines
        if self._scanline_surf is not None:
            surface.blit(self._scanline_surf, (0, 0))

    # -- Grid --
    def _draw_grid(self, surface: pygame.Surface):
        gs = self.gs
        ts = self.tile_size
        for y in range(gs.map_height):
            for x in range(gs.map_width):
                tile = gs.map_data[y][x]
                px, py = self.grid_to_px(x, y)

                # Baked textured tile surface (fallback to flat colour)
                baked = self._tile_surfs.get(tile.type)
                if baked:
                    surface.blit(baked, (px, py))
                else:
                    pygame.draw.rect(surface, TILE_COLOURS.get(tile.type, COL_OPEN),
                                     (px, py, ts, ts))

                # Grid line
                pygame.draw.rect(surface, COL_GRID_LINE, (px, py, ts, ts), 1)

                # Cover tile – diagonal hatch + corner brackets
                if tile.is_cover:
                    m = 4
                    bx, by, bw, bh = px + m, py + m, ts - m*2, ts - m*2
                    # Diagonal X hatch (barricade symbol)
                    pygame.draw.line(surface, (68, 100, 58),
                                     (bx, by + bh), (bx + bw, by), 1)
                    pygame.draw.line(surface, (68, 100, 58),
                                     (bx, by), (bx + bw, by + bh), 1)
                    # Corner dot brackets
                    bd_col = (88, 128, 70)
                    for cx2, cy2 in [(bx, by), (bx+bw, by),
                                     (bx, by+bh), (bx+bw, by+bh)]:
                        pygame.draw.rect(surface, bd_col, (cx2-1, cy2-1, 3, 3))

                # Blocked tile – wall-height cap + X
                if tile.type == "blocked":
                    cap_h = max(2, ts // 7)
                    pygame.draw.rect(surface, (58, 53, 48),
                                     (px + 1, py + 1, ts - 2, cap_h))
                    pygame.draw.line(surface, (48, 43, 38),
                                     (px + 4, py + 4), (px + ts - 4, py + ts - 4), 1)
                    pygame.draw.line(surface, (48, 43, 38),
                                     (px + 4, py + ts - 4), (px + ts - 4, py + 4), 1)

    # -- Highlights --
    def _draw_highlights(self, surface: pygame.Surface):
        gs = self.gs
        if gs.selected_mech and gs.selected_mech.position:
            surface.blit(self._hl_sel_surf, self.grid_to_px(*gs.selected_mech.position))

        if self.mode in (BattleMode.MECH_SELECTED, BattleMode.CHOOSING_MOVE):
            for tx, ty in gs.valid_move_tiles:
                surface.blit(self._hl_move_surf, self.grid_to_px(tx, ty))

        if self.mode == BattleMode.CHOOSING_ATTACK:
            for tx, ty in gs.valid_attack_tiles:
                surface.blit(self._hl_atk_surf, self.grid_to_px(tx, ty))

        if self.mode == BattleMode.CHOOSING_ABILITY:
            for tx, ty in gs.valid_attack_tiles:
                surface.blit(self._hl_abl_surf, self.grid_to_px(tx, ty))

        if self.hovered_tile:
            px, py = self.grid_to_px(*self.hovered_tile)
            pygame.draw.rect(surface, WHITE, (px, py, self.tile_size, self.tile_size), 2)

    # -- Mechs (WH40K renderer + animations) --
    def _draw_mechs(self, surface: pygame.Surface):
        gs       = self.gs
        ts       = self.tile_size
        cm       = gs.current_mech
        hp_bar_h = max(4, ts // 10)

        for mech in gs.team1 + gs.team2 + gs.team3:
            if not mech.is_alive or mech.position is None:
                continue

            mid = id(mech)
            if mid in self.mech_move_anims:
                base_px, base_py = self.mech_move_anims[mid].current_pos
            else:
                base_px, base_py = self.grid_to_px(*mech.position)
                # Idle breathing bob (phase offset per mech to avoid lockstep)
                phase = (mid * 1.618) % (2 * math.pi)
                base_py += math.sin(self._anim_time * 2.0 + phase) * 1.2

            if mid in self.mech_melee_anim:
                dx, dy = self.mech_melee_anim[mid].draw_offset
                base_px += dx
                base_py += dy

            ipx, ipy = int(base_px), int(base_py)
            tile_rect = pygame.Rect(ipx, ipy, ts, ts)
            team_col  = {1: TEAM1_BORDER, 2: TEAM2_BORDER, 3: TEAM3_BORDER}.get(mech.team, TEAM2_BORDER)

            # == Ground shadow (dark ellipse at the base of the tile) ==
            sh_w  = max(4, ts * 2 // 3)
            sh_h  = max(3, ts // 9)
            sh_sf = pygame.Surface((sh_w, sh_h), pygame.SRCALPHA)
            pygame.draw.ellipse(sh_sf, (0, 0, 0, 85), sh_sf.get_rect())
            surface.blit(sh_sf, (ipx + (ts - sh_w) // 2, ipy + ts - sh_h - 2))

            # == Soft team-colour ambient glow beneath the mech ==
            glow_r  = max(5, ts * 5 // 12)
            glow_sf = pygame.Surface((ts, ts), pygame.SRCALPHA)
            pygame.draw.circle(glow_sf, (*team_col, 28),
                               (ts // 2, ts * 3 // 4), glow_r)
            surface.blit(glow_sf, (ipx, ipy))

            # == WH40K mech art ==
            walk_t = self.mech_move_anims[mid].walk_t if mid in self.mech_move_anims else 0.0
            fire_t = (self.mech_fire_anims[mid] / self._FIRE_DUR
                      if mid in self.mech_fire_anims else -1.0)
            draw_mech(surface, mech, tile_rect, walk_t=walk_t, fire_t=fire_t)

            # == Damage flash overlay ==
            if mid in self.mech_damage_flash:
                alpha = self.mech_damage_flash[mid].alpha
                flash = pygame.Surface((ts, ts), pygame.SRCALPHA)
                flash.fill((255, 60, 60, alpha))
                surface.blit(flash, (ipx, ipy))

            # == Status icons (top-right corner, with inner highlight dot) ==
            icon_x, icon_y = ipx + ts - 8, ipy + 4
            if mech.is_shielded:
                pygame.draw.circle(surface, (80,  200, 255), (icon_x, icon_y), 4)
                pygame.draw.circle(surface, (200, 240, 255), (icon_x, icon_y), 2)
                icon_y += 10
            if mech.is_cloaked:
                pygame.draw.circle(surface, (160, 100, 220), (icon_x, icon_y), 4)
                pygame.draw.circle(surface, (200, 160, 255), (icon_x, icon_y), 2)
                icon_y += 10
            if mech.is_overcharged:
                pygame.draw.circle(surface, (255, 200,  50), (icon_x, icon_y), 4)
                pygame.draw.circle(surface, (255, 240, 160), (icon_x, icon_y), 2)

            # == HP bar (bottom of tile) ==
            # Use _display_hp (frozen until projectile lands) instead of mech.hp
            shown_hp = self._display_hp.get(id(mech), mech.hp)
            bar = pygame.Rect(ipx + 2, ipy + ts - hp_bar_h - 2, ts - 4, hp_bar_h)
            ratio = shown_hp / mech.max_hp if mech.max_hp > 0 else 0.0
            pygame.draw.rect(surface, HP_BG, bar, border_radius=2)
            if ratio > 0:
                filled = pygame.Rect(bar.x, bar.y, int(bar.width * ratio), bar.height)
                col = HP_HIGH if ratio > 0.6 else (HP_MED if ratio > 0.3 else HP_LOW)
                pygame.draw.rect(surface, col, filled, border_radius=2)

            # == Active-mech: pulsing team-colour border + corner tick marks ==
            if cm and mech is cm:
                pulse    = 0.55 + 0.45 * math.sin(self._anim_time * 5.2)
                border_w = max(2, int(3 * pulse))
                pygame.draw.rect(surface, team_col, (ipx, ipy, ts, ts), border_w)
                # Corner L-ticks in white
                tick = max(4, ts // 9)
                for (cx2, cy2, xd, yd) in [
                    (ipx,      ipy,      1,  1),
                    (ipx + ts, ipy,     -1,  1),
                    (ipx,      ipy + ts, 1, -1),
                    (ipx + ts, ipy + ts,-1, -1),
                ]:
                    pygame.draw.line(surface, WHITE,
                                     (cx2, cy2), (cx2 + xd * tick, cy2), 2)
                    pygame.draw.line(surface, WHITE,
                                     (cx2, cy2), (cx2, cy2 + yd * tick), 2)

    # -- HUD --
    def _draw_hud(self, surface: pygame.Surface):
        gs = self.gs
        pygame.draw.rect(surface, HUD_BG, (HUD_X, 0, HUD_W, HUD_H))
        pygame.draw.line(surface, HUD_BORDER, (HUD_X, 0), (HUD_X, HUD_H), 2)

        y = 14
        cm = gs.current_mech
        _tc_map = {1: TEAM1_BORDER, 2: TEAM2_BORDER, 3: TEAM3_BORDER}
        team_col = _tc_map.get(cm.team if cm else 0, TEAM2_BORDER)
        team_name = self._player_name(cm.team) if cm else "—"
        draw_text(surface, f"Round {gs.round_number}",
                  (HUD_X + 12, y), color=HUD_DIM, font_size=FONT_MEDIUM)
        draw_text(surface, f"{team_name}'s Turn",
                  (HUD_X + HUD_W - 12, y), color=team_col,
                  font_size=FONT_MEDIUM, anchor="topright")
        y += 30

        pygame.draw.line(surface, HUD_BORDER, (HUD_X+8, y), (HUD_X+HUD_W-8, y))
        y += 10

        if cm:
            draw_text(surface, cm.name, (HUD_X + 12, y), color=WHITE, font_size=FONT_LARGE)
            badge_col = _tc_map.get(cm.team, TEAM2_BORDER)
            pygame.draw.circle(surface, badge_col, (HUD_X + HUD_W - 20, y + 12), 10)
            y += 35

            shown_cm_hp = self._display_hp.get(id(cm), cm.hp)
            hp_bar = HpBar((HUD_X + 12, y, HUD_W - 24, 16))
            hp_bar.draw(surface, shown_cm_hp, cm.max_hp)
            draw_text(surface, f"HP {shown_cm_hp}/{cm.max_hp}",
                      (HUD_X + HUD_W//2, y + 18), color=HUD_DIM,
                      font_size=FONT_SMALL, anchor="center")
            y += 38

            stats = [("ARM", cm.armor), ("MOV", cm.move_range), ("INIT", cm.initiative)]
            col_w = (HUD_W - 24) // len(stats)
            for si, (lbl, val) in enumerate(stats):
                sx = HUD_X + 12 + si * col_w
                draw_text(surface, lbl, (sx, y), color=HUD_DIM, font_size=FONT_SMALL)
                draw_text(surface, str(val), (sx + 38, y), color=WHITE, font_size=FONT_SMALL)
            y += 22

            status = cm.status_string()
            if status:
                draw_text(surface, status, (HUD_X + 12, y),
                          color=(200, 160, 50), font_size=FONT_SMALL)
            y += 20

        pygame.draw.line(surface, HUD_BORDER, (HUD_X+8, y), (HUD_X+HUD_W-8, y))
        y += 10

        mode_labels = {
            BattleMode.IDLE:             "SELECT YOUR MECH",
            BattleMode.MECH_SELECTED:    "CHOOSE ACTION",
            BattleMode.CHOOSING_MOVE:    "CLICK TILE TO MOVE",
            BattleMode.CHOOSING_ATTACK:  "CLICK TARGET TO ATTACK",
            BattleMode.CHOOSING_ABILITY: "CLICK TARGET FOR ABILITY",
            BattleMode.GAME_OVER:        "",
        }
        draw_text(surface, mode_labels.get(self.mode, ""),
                  (HUD_X + HUD_W//2, y), color=HUD_ACCENT,
                  font_size=FONT_SMALL, anchor="center")
        y += 6

        # ── Mini scoreboard (fits in the gap before buttons) ──────────────
        pygame.draw.line(surface, HUD_BORDER, (HUD_X+8, y), (HUD_X+HUD_W-8, y))
        y += 8
        if gs.team3:
            col_w3 = (HUD_W - 24) // 3
            self._draw_team_summary(surface, gs.team1, 1, HUD_X + 12,                  y)
            self._draw_team_summary(surface, gs.team2, 2, HUD_X + 12 + col_w3,         y)
            self._draw_team_summary(surface, gs.team3, 3, HUD_X + 12 + col_w3 * 2,     y)
        else:
            self._draw_team_summary(surface, gs.team1, 1, HUD_X + 12,           y)
            self._draw_team_summary(surface, gs.team2, 2, HUD_X + HUD_W//2 + 6, y)
        # ──────────────────────────────────────────────────────────────────

        for _, btn in self._btns:
            btn.draw(surface)

        # Hover info
        info_y = SCREEN_H - 200
        pygame.draw.line(surface, HUD_BORDER, (HUD_X+8, info_y), (HUD_X+HUD_W-8, info_y))
        info_y += 8
        if self.hovered_tile:
            gx, gy = self.hovered_tile
            tile = gs.map_data[gy][gx]
            draw_text(surface, f"Tile ({gx},{gy})  {tile.type.upper()}",
                      (HUD_X + 12, info_y), color=HUD_DIM, font_size=FONT_SMALL)
            if tile.is_cover:
                draw_text(surface, "+4 armor (cover)",
                          (HUD_X + 12, info_y + 16), color=HP_HIGH, font_size=FONT_SMALL)
            if tile.mech:
                m = tile.mech
                info_y2 = info_y + 36
                team_c = {1: TEAM1_BORDER, 2: TEAM2_BORDER, 3: TEAM3_BORDER}.get(m.team, TEAM2_BORDER)
                draw_text(surface, m.name, (HUD_X+12, info_y2),
                          color=team_c, font_size=FONT_MEDIUM)
                shown_m_hp = self._display_hp.get(id(m), m.hp)
                hp_b = HpBar((HUD_X+12, info_y2+24, HUD_W-24, 10))
                hp_b.draw(surface, shown_m_hp, m.max_hp)
                draw_text(surface, f"{shown_m_hp}/{m.max_hp} HP  ARM:{m.armor}",
                          (HUD_X+12, info_y2+38), color=HUD_DIM, font_size=FONT_SMALL)

        # Combat log
        log_y = SCREEN_H - 105
        pygame.draw.line(surface, HUD_BORDER, (HUD_X+8, log_y), (HUD_X+HUD_W-8, log_y))
        log_y += 6
        draw_text(surface, "COMBAT LOG", (HUD_X+12, log_y), color=HUD_DIM, font_size=FONT_TINY)
        log_y += 14
        for entry in gs.combat_log[-5:]:
            draw_text(surface, entry, (HUD_X+12, log_y), color=HUD_TEXT, font_size=FONT_TINY)
            log_y += 14

        if self._message:
            msg_surf = pygame.Surface((GRID_AREA_W, 34), pygame.SRCALPHA)
            msg_surf.fill((0, 0, 0, 160))
            surface.blit(msg_surf, (0, SCREEN_H - 34))
            draw_text(surface, self._message, (GRID_AREA_W//2, SCREEN_H-26),
                      color=WHITE, font_size=FONT_MEDIUM, anchor="center")


    def _draw_team_summary(self, surface, team, team_num, x, y):
        col = {1: TEAM1_BORDER, 2: TEAM2_BORDER, 3: TEAM3_BORDER}.get(team_num, TEAM2_BORDER)
        draw_text(surface, f"P{team_num}:", (x, y), color=col, font_size=FONT_SMALL)
        for mi, mech in enumerate(team):
            my = y + 14 + mi * 14
            dot_col = col if mech.is_alive else GRAY
            pygame.draw.circle(surface, dot_col, (x+6, my+6), 5)
            name_col = WHITE if mech.is_alive else GRAY
            draw_text(surface, mech.name[:7], (x+16, my), color=name_col, font_size=FONT_TINY)

    def _draw_game_over(self, surface: pygame.Surface):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        surface.blit(overlay, (0, 0))
        banner_col = {1: TEAM1_BORDER, 2: TEAM2_BORDER, 3: TEAM3_BORDER}.get(self.winner, TEAM2_BORDER)
        draw_text(surface, f"{self._player_name(self.winner).upper()} WINS!",
                  (SCREEN_W//2, SCREEN_H//2 - 40),
                  color=banner_col, font_size=62, anchor="center")
        draw_text(surface, "Click anywhere to continue",
                  (SCREEN_W//2, SCREEN_H//2 + 40),
                  color=LIGHT_GRAY, font_size=FONT_MEDIUM, anchor="center")
