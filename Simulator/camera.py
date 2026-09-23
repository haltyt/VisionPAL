"""First-person camera renderer (numpy raycaster with a per-pixel z-buffer).

Walls, boxes and people are vertical quads; the floor is a perspective
checkerboard.  Surfaces carry stripe textures so the connectome layer's
optical flow sees real motion and looming, not flat colour fields.
"""

from __future__ import annotations

import math

import numpy as np

from .world import World, ray_segment_hits

CAMERA_HEIGHT = 0.12   # JetBot camera ~12 cm above the floor
H_FOV = math.radians(100)  # JetBot wide-angle lens (IMX219 160° is cropped by the pipeline)
SKIN = np.array([225.0, 185.0, 150.0])
TROUSERS = np.array([55.0, 60.0, 85.0])


class Camera:
    def __init__(self, width: int = 320, height: int = 240, fov: float = H_FOV, noise: float = 3.0):
        self.w, self.h = width, height
        self.fov = fov
        self.noise = noise
        self.focal = (width / 2) / math.tan(fov / 2)
        self.cy = height / 2
        self._x_ndc = (np.arange(width) + 0.5 - width / 2) / (width / 2)
        rows = np.arange(height, dtype=np.float64)[:, None]
        self._rows = rows
        self._rng = np.random.default_rng(0)
        sky = np.linspace(1.0, 0.75, height)[:, None, None]
        self._ceiling = (np.array([225, 225, 235])[None, None, :] * sky).repeat(width, axis=1)

    def render(self, world: World) -> np.ndarray:
        """Return an RGB uint8 image (H, W, 3)."""
        r = world.robot
        fwd = np.array([math.cos(r.theta), math.sin(r.theta)])
        right = np.array([math.sin(r.theta), -math.cos(r.theta)])
        tan_half = math.tan(self.fov / 2)
        dirs = fwd[None, :] + right[None, :] * (self._x_ndc * tan_half)[:, None]   # (W, 2), forward comp = 1
        origin = np.array([r.x, r.y])

        img = self._ceiling.copy()
        zbuf = np.full((self.h, self.w), np.inf)

        # Floor: perspective checkerboard below the horizon.
        rows_below = np.arange(int(self.cy) + 1, self.h)
        depth = CAMERA_HEIGHT * self.focal / (rows_below + 0.5 - self.cy)                 # (R,)
        fx = origin[0] + depth[:, None] * dirs[None, :, 0]
        fy = origin[1] + depth[:, None] * dirs[None, :, 1]
        checker = ((np.floor(fx / 0.25) + np.floor(fy / 0.25)) % 2)[..., None]
        floor = np.where(checker > 0, np.array([138, 112, 86]), np.array([126, 101, 77])).astype(np.float64)
        fade = np.clip(1.2 - depth / 5.0, 0.35, 1.0)[:, None, None]
        img[rows_below] = floor * fade
        zbuf[rows_below] = depth[:, None]

        # Vertical surfaces.
        segs = world.segments(include_people=True, viewer=(r.x, r.y))
        t = ray_segment_hits(origin, dirs, segs["a"], segs["b"])                         # (W, N)
        for i in range(t.shape[1]):
            ti = t[:, i]
            cols = np.isfinite(ti)
            if not cols.any():
                continue
            ti_c = np.where(cols, ti, 1.0)
            top = self.cy - self.focal * (segs["zmax"][i] - CAMERA_HEIGHT) / ti_c
            bottom = self.cy - self.focal * (segs["zmin"][i] - CAMERA_HEIGHT) / ti_c
            mask = (self._rows >= top[None, :]) & (self._rows < bottom[None, :]) & cols[None, :]
            mask &= ti_c[None, :] < zbuf
            if not mask.any():
                continue
            zbuf = np.where(mask, ti_c[None, :], zbuf)

            # Texture coordinate along the surface (meters) → stripes.
            hit = origin[None, :] + dirs * ti_c[:, None]
            u = np.linalg.norm(hit - segs["a"][i][None, :], axis=1)
            kind = segs["kind"][i]
            dist_fade = np.clip(1.25 - ti_c / 5.0, 0.35, 1.0)[None, :]
            if kind == 2:   # person: skin head / coloured shirt / dark trousers
                z = CAMERA_HEIGHT + (self.cy - self._rows) * ti_c[None, :] / self.focal
                shirt = segs["color"][i][None, None, :]
                colour = np.where((z > 1.4)[..., None], SKIN[None, None, :],
                                  np.where((z > 0.85)[..., None], shirt, TROUSERS[None, None, :]))
                colour = colour * dist_fade[..., None]
                img = np.where(mask[..., None], colour, img)
                continue
            period = 0.2 if kind == 0 else 0.1
            stripe = 0.78 + 0.22 * ((np.floor(u / period) % 2) == 0)
            z = CAMERA_HEIGHT + (self.cy - self._rows) * ti_c[None, :] / self.focal
            hband = 0.9 + 0.1 * ((np.floor(z / 0.15) % 2) == 0)
            shade = stripe[None, :] * hband
            colour = segs["color"][i][None, None, :] * (shade * dist_fade)[..., None]
            img = np.where(mask[..., None], colour, img)

        if self.noise:
            img = img + self._rng.normal(0.0, self.noise, img.shape)
        return np.clip(img, 0, 255).astype(np.uint8)
