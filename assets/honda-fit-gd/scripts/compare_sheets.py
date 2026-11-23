"""
Side-by-side boards: grey render | reference photo, and silhouette overlays on the blueprint (red = our silhouette).
References are read from the local pack (third-party, never copied into the repo); the boards are local review material only.
"""
# folder with the (third-party, never versioned) reference pack: set FITGD_REFERENCES_DIR, or keep the pack next to the repository
import os as _os
_REFS = _os.environ.get('FITGD_REFERENCES_DIR') or _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', '..', '..', 'FIT_AI_Blender_Honda_Fit_2005_Pacote', 'FitAI_HondaFit2005_Modelagem', 'referencias'))

import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, 'out', os.environ.get('FITGD_VERSION', 'v3'), 'renders')
REFDIR = _REFS
pick = lambda prefix: next(os.path.join(REFDIR, f) for f in os.listdir(REFDIR) if f.startswith(prefix))
BP = Image.open(pick('uvUtO48')).convert('RGB')
PH_FRONT34 = Image.open(pick('n0EAs6')).convert('RGB')      # front 3/4 (studio, from the first pack)
PH_FRONT34B = Image.open(pick('gLs288')).convert('RGB')     # front 3/4 (street, from the first pack)
PH_REAR34 = Image.open(pick('pGdXZt')).convert('RGB')       # rear 3/4 (from the first pack)
LOCAL = os.path.join(ROOT, 'refs_local')
PH_FRONT = Image.open(os.path.join(LOCAL, 'photo_front.jpg')).convert('RGB')        # NEW: straight front
PH_SIDE = Image.open(os.path.join(LOCAL, 'photo_side.jpg')).convert('RGB')          # NEW: clean side
PH_FRONT34BR = Image.open(os.path.join(LOCAL, 'photo_front34_br.jpg')).convert('RGB')  # NEW: front 3/4 of a Brazilian car (plate visible: local only)
PH_REAR = Image.open(os.path.join(LOCAL, 'photo_rear.jpg')).convert('RGB')          # NEW: straight rear
font = ImageFont.load_default()
LABEL = os.environ.get('FITGD_VERSION', 'v3').replace('candidate_', 'CANDIDATO ').upper()

def fit(im, h):
    return im.resize((round(im.width * h / im.height), h), Image.LANCZOS)

def board(name, left, right, ll, rl, h=560):
    a, b = fit(left, h), fit(right, h)
    sheet = Image.new('RGB', (a.width + b.width + 30, h + 40), (24, 24, 26))
    sheet.paste(a, (10, 30)); sheet.paste(b, (a.width + 20, 30))
    d = ImageDraw.Draw(sheet)
    d.text((12, 8), ll, fill=(255, 200, 120), font=font); d.text((a.width + 22, 8), rl, fill=(255, 200, 120), font=font)
    sheet.save(os.path.join(R, name)); print('board', name, sheet.size)

def im(n): return Image.open(os.path.join(R, n)).convert('RGB')

board('board_front34.png', im('front34.png'), PH_FRONT34BR, LABEL + ' (grey, no effects) - front 3/4', 'REFERENCE (new) - Fit 1st gen, Brazilian car, front 3/4')
board('board_front34b.png', im('front34.png'), PH_FRONT34, LABEL + ' (grey) - front 3/4', 'REFERENCE - Fit 1st gen, studio front 3/4')
board('board_front.png', im('front.png'), PH_FRONT, LABEL + ' (grey, 85 mm) - front', 'REFERENCE (new) - straight front')
board('board_side.png', im('side.png').resize((905, 380)), PH_SIDE, LABEL + ' (grey, orthographic) - side', 'REFERENCE (new) - clean side 90 deg')
board('board_rear.png', im('rear.png'), PH_REAR, LABEL + ' (grey, 85 mm) - rear', 'REFERENCE (new) - straight rear')
board('board_rear34.png', im('rear34.png'), PH_REAR34, LABEL + ' (grey) - rear 3/4', 'REFERENCE - rear 3/4')

def overlay(mask_name, box, label, out_name, resize_to=None):
    m = Image.open(os.path.join(R, mask_name)).convert('RGBA')
    if resize_to: m = m.resize(resize_to, Image.LANCZOS)
    a = np.array(m)[:, :, 3] > 40
    edge = a & ~(np.roll(a, 1, 0) & np.roll(a, -1, 0) & np.roll(a, 1, 1) & np.roll(a, -1, 1))
    crop = BP.crop(box).convert('RGB'); arr = np.array(crop)
    h, w = min(arr.shape[0], edge.shape[0]), min(arr.shape[1], edge.shape[1])
    arr[:h, :w][edge[:h, :w]] = (255, 30, 30)
    out = Image.fromarray(arr); d = ImageDraw.Draw(out); d.text((6, 4), label, fill=(200, 0, 0), font=font)
    out.save(os.path.join(R, out_name)); print('overlay', out_name, out.size)

overlay('mask_side.png', (5, 0, 910, 380), 'side: red = model silhouette over the blueprint', 'overlay_side.png', (905, 380))
overlay('mask_front.png', (929, 0, 1386, 380), 'front: red = model silhouette', 'overlay_front.png', (457, 380))
overlay('mask_top.png', (5, 395, 912, 835), 'top: red = model silhouette', 'overlay_top.png')
