"""Silhouette of the clean side photo (independent of the blueprint): mask by difference from the background, then top/bottom profile."""
import json
import numpy as np
from PIL import Image
im = np.array(Image.open('refs_local/photo_side.jpg').convert('RGB')).astype(float)
h, w, _ = im.shape
bg = np.median(np.concatenate([im[5:60, 5:60].reshape(-1, 3), im[5:60, w-60:w-5].reshape(-1, 3), im[h-60:h-5, 5:60].reshape(-1, 3)]), axis=0)
diff = np.abs(im - bg).sum(2)
mask = diff > 38
# keep the largest connected blob only (drops the floor shadow fringe)
from collections import deque
def largest_blob(m):
    """largest 4-connected component (pure numpy/python: no extra packages)"""
    seen = np.zeros_like(m, bool); best = []
    H, W = m.shape
    for sy, sx in zip(*np.nonzero(m)):
        if seen[sy, sx]:
            continue
        comp = []; dq = deque([(sy, sx)]); seen[sy, sx] = True
        while dq:
            y, x = dq.popleft(); comp.append((y, x))
            for ny, nx in ((y+1, x), (y-1, x), (y, x+1), (y, x-1)):
                if 0 <= ny < H and 0 <= nx < W and m[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True; dq.append((ny, nx))
        if len(comp) > len(best):
            best = comp
    out = np.zeros_like(m)
    for y, x in best:
        out[y, x] = True
    return out
mask = largest_blob(mask)
ys, xs = np.nonzero(mask)
print('bg', bg, 'bbox x', xs.min(), xs.max(), 'y', ys.min(), ys.max())
Image.fromarray((mask * 255).astype('uint8')).save('refs_local/photo_side_mask.png')
X0, X1 = xs.min(), xs.max()
S = (X1 - X0) / 3.83
GROUND = ys.max()
print('px/m', S, 'height m', (ys.max() - ys.min()) / S)
top = []
for x in range(X0, X1 + 1, 4):
    col = np.nonzero(mask[:, x])[0]
    top.append(((x - X0) / S, (GROUND - col.min()) / S))
print('top profile (t, z) every 40 px:', [(round(a, 3), round(b, 3)) for a, b in top[::10]])
json.dump({'px_per_m': S, 'top': top}, open('data/side_photo_profile.json', 'w'))
