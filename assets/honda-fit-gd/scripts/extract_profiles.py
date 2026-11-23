"""
Measure the auxiliary orthographic blueprint (read-only) and write ONLY numbers to data/profiles.json: side top profile, plan
half-width along the car, front-view silhouette width by height, wheel centres. The blueprint image itself is never copied.
Calibration (see docs): the side view is 905 px for the 3830 mm of the Honda manual -> px/m; the vertical axis is scaled so the
roof is exactly 1525 mm (the drawing is ~3.5 % taller than the manual).
"""
# folder with the (third-party, never versioned) reference pack: set FITGD_REFERENCES_DIR, or keep the pack next to the repository
import os as _os
_REFS = _os.environ.get('FITGD_REFERENCES_DIR') or _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '..', '..', 'FIT_AI_Blender_Honda_Fit_2005_Pacote', 'FitAI_HondaFit2005_Modelagem', 'referencias'))

import json
import numpy as np
from PIL import Image

REF = _os.path.join(_REFS, 'uvUtO48dKKMlhzPc-yfK6IfipxxUXOmHo3V-ZSPNZ8YzTj0LupsxjhvKuonfs_6mLM-JpTTaxoSKongrxjg1KM7CWbq08WreoEOl0YxOjKSoJRJP5I8_dcOY2JsxFswN8kr1X4M1QtntvQm894QBWFuhBGUuyZQd9tMlVeTh2OsGQ05rwlxLT7wvv2k_Q3bO.jpg')
im = np.array(Image.open(REF).convert('L')).astype(float)
dark = im < 175

X0, X1 = 5, 910                    # side view: nose .. tail (px)
LEN = 3.830
S = (X1 - X0) / LEN                # px per metre (horizontal)
GROUND = 377                       # tyre contact row of the side view
ROOF_PX = 4
H_OFFICIAL = 1.525
VF = H_OFFICIAL / ((GROUND - ROOF_PX) / S)   # vertical factor to hit the official height
FRONT_AXLE, REAR_AXLE = 172, 755   # wheel centres in the side view (px), wheelbase check below

def side_top(x):
    ys = np.nonzero(dark[0:380, x])[0]
    return int(ys.min())

xs = list(range(X0, X1 + 1, 5))
top = [(x, side_top(x)) for x in xs]

# plan half-width (top view rows 395..839), outliers removed (door mirrors at x 290..350 and handles)
rows = []
for x in xs:
    ys = np.nonzero(dark[395:839, min(x + 2, 912)])[0]
    rows.append((x, (ys.max() - ys.min()) / 2 if len(ys) else 0.0))
hw = np.array([r[1] for r in rows])
mask = np.array([(290 <= x <= 350) for x, _ in rows])
good = np.where(~mask)[0]
hw[mask] = np.interp(np.where(mask)[0], good, hw[good])
# light smoothing
hw = np.convolve(np.pad(hw, 2, mode='edge'), np.ones(5) / 5, mode='valid')

# front view: half silhouette width by row (the car is centred at the mean of the body extent)
fx0, fx1 = 929, 1386
front = []
for y in range(10, 372, 6):
    xs_ = np.nonzero(dark[y, fx0:fx1])[0]
    if len(xs_):
        front.append((y, (xs_.max() - xs_.min()) / 2))
# door mirrors make rows 120-160 too wide: clamp to the running minimum of the neighbours
fr = np.array([w for _, w in front])
for i in range(1, len(fr) - 1):
    if fr[i] > fr[i - 1] + 8 and fr[i] > fr[i + 1] + 8:
        fr[i] = (fr[i - 1] + fr[i + 1]) / 2
out = {
    'meta': {'source': 'auxiliary orthographic blueprint (numbers only)', 'px_per_m': round(S, 3), 'vertical_factor': round(VF, 4),
             'wheelbase_m_from_blueprint': round((REAR_AXLE - FRONT_AXLE) / S, 3), 'official': {'L': 3.83, 'W': 1.675, 'H': 1.525, 'WB': 2.45}},
    'axle_px': [FRONT_AXLE, REAR_AXLE],
    'wheel_radius_m': round(71 / S * VF, 3),
    # all lengths below in metres; y along the car from the nose (0) to the tail, z up from the ground
    'top_profile': [[round((x - X0) / S, 4), round((GROUND - y) / S * VF, 4)] for x, y in top],
    'plan_halfwidth': [[round((x - X0) / S, 4), round(float(w) / S, 4)] for (x, _), w in zip(rows, hw)],
    'front_halfwidth_by_height': [[round((GROUND - 0 - (y - 10) - 4) / S * VF if False else (H_OFFICIAL - (y - 10) / S * VF), 4), round(float(w) / S, 4)] for (y, _), w in zip(front, fr)],
}
json.dump(out, open('data/profiles.json', 'w'), indent=1)
print(out['meta'])
print('top profile sample', out['top_profile'][::30])
print('plan halfwidth sample', out['plan_halfwidth'][::25])
print('front hw by height', out['front_halfwidth_by_height'][::5])
