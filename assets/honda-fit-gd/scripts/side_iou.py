"""Overlay of the model's side silhouette on the independent side PHOTO silhouette (both scaled to the 3830 mm length); prints the IoU.
This is a geometric overlap of two outlines, not a visual-similarity score: it says nothing about surface shape or details."""
import os, sys
import numpy as np
from PIL import Image
ver = os.environ.get('FITGD_VERSION', 'v3')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
photo = np.array(Image.open(os.path.join(ROOT, 'refs_local', 'photo_side_mask.png'))) > 128
ys, xs = np.nonzero(photo)
pb = photo[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
m = Image.open(os.path.join(ROOT, 'out', ver, 'renders', 'mask_side.png')).convert('RGBA')
ma = np.array(m)[:, :, 3] > 40
ys2, xs2 = np.nonzero(ma)
mb = ma[ys2.min():ys2.max() + 1, xs2.min():xs2.max() + 1]
# common size: 3830 px long; the photo's tyre-to-roof height is kept as measured (no stretching), model scaled by the same factor
W = 1000
def rs(a, W):
    im = Image.fromarray((a * 255).astype('uint8')); h = round(a.shape[0] * W / a.shape[1]); return np.array(im.resize((W, h), Image.NEAREST)) > 128
P, M = rs(pb, W), rs(mb, W)
H = max(P.shape[0], M.shape[0])
def pad(a): out = np.zeros((H, W), bool); out[H - a.shape[0]:, :] = a; return out   # bottom aligned (tyres on the ground)
P, M = pad(P), pad(M)
iou = (P & M).sum() / (P | M).sum()
print(f'{ver}: side silhouette IoU vs photo = {iou:.3f}  (photo aspect {pb.shape[1]/pb.shape[0]:.3f}, model {mb.shape[1]/mb.shape[0]:.3f})')
rgb = np.zeros((H, W, 3), 'uint8') + 245
rgb[P & ~M] = (60, 120, 255)   # only the photo
rgb[M & ~P] = (255, 80, 60)    # only the model
rgb[P & M] = (170, 170, 170)
Image.fromarray(rgb).save(os.path.join(ROOT, 'out', ver, 'renders', 'overlay_side_photo.png'))
