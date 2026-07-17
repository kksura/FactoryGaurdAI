"""Procedural synthetic inspection images (crimp close-ups).

Not photorealistic (assumption A8): geometric renderings of a wire/terminal
crimp with defect-specific distortions, sufficient to exercise the vision
pipeline, Grad-CAM, robustness tests, and image-quality drift.

Deterministic per (seed, unit_id). Camera-misalignment windows (latent,
Scenario C) blur/shift images without changing the true label.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFilter

from factoryguard.data.profiles import Profile
from factoryguard.utilities.seeding import derive_seed

# Visual defect classes renderable in an inspection image.
VISUAL_CLASSES = [
    "normal",
    "under_crimp",
    "over_crimp",
    "bent_terminal",
    "missing_seal",
    "surface_damage",
    "misalignment",
    "partial_insertion",
]

# Map process defect categories -> visual class (non-visual categories -> normal).
_CATEGORY_TO_VISUAL = {
    "crimp_height_oot": "over_crimp",
    "crimp_force_anomaly": "under_crimp",
    "terminal_deformation": "bent_terminal",
    "missing_seal": "missing_seal",
    "damaged_insulation": "surface_damage",
    "partial_insertion": "partial_insertion",
}


def visual_class_for(defect_category: str, rng: np.random.Generator) -> str:
    if defect_category in _CATEGORY_TO_VISUAL:
        cls = _CATEGORY_TO_VISUAL[defect_category]
        # under/over crimp both plausible for height deviation
        if defect_category == "crimp_height_oot" and rng.uniform() < 0.5:
            cls = "under_crimp"
        return cls
    return "normal"


def render_crimp(
    size: int, visual_class: str, rng: np.random.Generator, blur_sigma: float = 0.0
) -> Image.Image:
    """Render one synthetic crimp image with controlled nuisance variation."""
    bg = int(rng.integers(30, 70))
    img = Image.new("L", (size * 2, size * 2), color=bg)
    d = ImageDraw.Draw(img)
    cx, cy = size, size
    scale = size / 96.0 * float(rng.uniform(0.85, 1.15))

    wire_half = int(9 * scale)
    term_len = int(46 * scale)
    term_half = int(14 * scale)
    crimp_w = int(26 * scale)

    wire_shade = int(rng.integers(120, 160))
    term_shade = int(rng.integers(170, 220))

    insertion = 0
    if visual_class == "partial_insertion":
        insertion = int(18 * scale)
    # wire entering from the left
    d.rectangle(
        (0, cy - wire_half, cx - int(10 * scale) - insertion, cy + wire_half),
        fill=wire_shade,
    )
    # terminal body to the right
    angle_offset = 0
    if visual_class == "bent_terminal":
        angle_offset = int(14 * scale)
    d.polygon(
        [
            (cx - int(12 * scale), cy - term_half),
            (cx + term_len, cy - term_half - angle_offset),
            (cx + term_len, cy + term_half - angle_offset),
            (cx - int(12 * scale), cy + term_half),
        ],
        fill=term_shade,
    )
    # crimp barrel over the wire/terminal junction
    crimp_half = int(16 * scale)
    if visual_class == "under_crimp":
        crimp_half = int(22 * scale)  # too open
    elif visual_class == "over_crimp":
        crimp_half = int(9 * scale)  # squashed
    d.rectangle(
        (cx - int(10 * scale), cy - crimp_half, cx - int(10 * scale) + crimp_w, cy + crimp_half),
        fill=int(term_shade * 0.85),
        outline=int(term_shade * 0.6),
        width=max(1, int(2 * scale)),
    )
    # seal ring behind the crimp (absent for missing_seal)
    if visual_class != "missing_seal":
        seal_x = cx - int(26 * scale)
        d.ellipse(
            (
                seal_x - int(7 * scale),
                cy - wire_half - int(5 * scale),
                seal_x + int(7 * scale),
                cy + wire_half + int(5 * scale),
            ),
            outline=int(rng.integers(90, 120)),
            width=max(2, int(3 * scale)),
        )
    if visual_class == "surface_damage":
        for _ in range(int(rng.integers(2, 5))):
            x0 = int(rng.integers(cx - 10 * scale, cx + term_len - 8 * scale))
            y0 = int(rng.integers(cy - term_half, cy + term_half - 4))
            d.line(
                (x0, y0, x0 + int(9 * scale), y0 + int(rng.integers(-6, 6))),
                fill=40,
                width=max(1, int(1.5 * scale)),
            )

    # nuisance variation: rotation, translation (misalignment class = extreme)
    angle = float(rng.normal(0, 3.0))
    tx, ty = int(rng.normal(0, 2 * scale)), int(rng.normal(0, 2 * scale))
    if visual_class == "misalignment":
        angle += float(rng.choice([-1, 1]) * rng.uniform(12, 20))
        tx += int(rng.choice([-1, 1]) * 14 * scale)
    img = img.rotate(angle, translate=(tx, ty), fillcolor=bg)

    # crop center, lighting, blur, noise
    left = (img.width - size) // 2
    img = img.crop((left, left, left + size, left + size))
    arr = np.asarray(img, dtype=np.float32)
    arr *= float(rng.uniform(0.8, 1.25))  # lighting
    arr += rng.normal(0, 4.0, arr.shape).astype(np.float32)  # camera noise
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="L")
    total_blur = float(rng.uniform(0.0, 0.7)) + blur_sigma
    if total_blur > 0.05:
        out = out.filter(ImageFilter.GaussianBlur(total_blur))
    return out


def generate_images(
    units: pd.DataFrame,
    labels: pd.DataFrame,
    camera_windows: pd.DataFrame,
    profile: Profile,
    out_dir: Path,
) -> pd.DataFrame:
    """Render inspection images for a sampled subset of units; returns metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cat_by_unit = labels.set_index("unit_id")["defect_category"].to_dict()
    windows = [
        (str(w.line_id), w.start_day, w.end_day, float(w.blur_sigma))
        for w in camera_windows.itertuples()
    ]
    rows = []
    for row in units.itertuples():
        rng = np.random.default_rng(derive_seed(profile.seed, "images", row.unit_id))
        if rng.uniform() > profile.images.per_unit_probability:
            continue
        category = cat_by_unit.get(row.unit_id, "none")
        vclass = visual_class_for(category, rng)
        day = row.produced_at.date()
        degraded_sigma = 0.0
        for line_id, start, end, sigma in windows:
            if row.line_id == line_id and start <= day <= end:
                degraded_sigma = sigma
                break
        img = render_crimp(profile.images.size, vclass, rng, blur_sigma=degraded_sigma)
        rel = f"{row.plant_id}/{row.unit_id}.png"
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, format="PNG")
        rows.append(
            {
                "unit_id": row.unit_id,
                "image_path": f"images/{rel}",
                "station": "vision_inspection",
                "visual_class": vclass,
                "camera_degraded": degraded_sigma > 0,
                "captured_at": row.produced_at,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "unit_id",
            "image_path",
            "station",
            "visual_class",
            "camera_degraded",
            "captured_at",
        ],
    )
