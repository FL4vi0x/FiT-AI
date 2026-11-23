# Honda Fit LX 2005 BR (GD) - 3D body, stage 2 (grey, no final details)

Original work: the geometry is built by `scripts/build_body.py` from MEASUREMENTS (numbers in `data/profiles.json`) taken from an
auxiliary orthographic blueprint and calibrated on the Honda Brasil owner's manual (3830 x 1675 x 1525 mm, wheelbase 2450 mm).
No third-party 3D model is used.

## Versions (nothing is overwritten)
- `out/v1/`  first loft (kept as the reversible reference); scripts `*_v1.py` are its frozen copies.
- `out/v3/`  photo-driven refinement (current): hood saddle (the centre of the nose below the headlamp tops), headlamps / grille / intake /
             plate recess projected from the front photo, tail lamps from the rear photo, smooth glazing outlines from the side photo,
             swept mirrors. Scripts `build_body.py`, `render_views.py`, `compare_sheets.py`, `side_iou.py`, `photo_features.py`.
- `out/v2/`  refinement (frozen; scripts `*_v2.py`): bonnet groove, wheel flares, shoulder crease, real window outlines (pillars stay body), tailgate width,
             headlamp / tail-lamp blocking volumes, door mirrors. Scripts `build_body.py`, `render_views.py`, `compare_sheets.py`.

Run (Windows, Blender 5.3 from blender.org installed in Program Files; the default version is v3, `FITGD_VERSION=v2` selects another output folder):
    blender --background --python scripts/build_body.py
    blender --background out/v3/fit_gd_2005_lx_stage2_body_v3.blend --python scripts/render_views.py
    python scripts/compare_sheets.py          (needs the local reference pack; see below)

## References (third-party, NOT versioned; each has its own licence)
They live in `FIT_AI_Blender_Honda_Fit_2005_Pacote/.../referencias/` outside this repository. The files there have hash names, so which
Wikimedia Commons file each one is, and its licence, could NOT be confirmed. The blueprint (getoutlines.com) is listed as "Creative
Commons, subtype to be verified". Boards and overlays embed these images, so `out/*/renders/board_*` and `overlay_*` are git-ignored.
Honda is a third-party trademark; this project has no affiliation with Honda.

## Photos added for v3 (kept in `refs_local/`, git-ignored; each has its own copyright; origin and licence NOT verified)
| file in refs_local | what it is | used for |
|---|---|---|
| photo_front.jpg | straight front, 800x600, Japanese-market car | headlamp, grille, intake and plate outlines; hood saddle |
| photo_side.jpg | clean side, 640x480, catalogue-style | side glazing outlines; silhouette cross-check (IoU 0.937 vs the model) |
| photo_front34_br.jpg | front 3/4 of a BRAZILIAN car, 1600x1200 (a number plate is visible: keep local, never publish) | visual comparison |
| photo_rear.jpg | straight rear, 800x600, Japanese-market car | tail lamp and plate outlines |
Photos are of GD1 cars that may differ in trim from the Brazilian LX 2005 (e.g. the amber marker inside the headlamps).
Outlines in `scripts/photo_features.py` were read by eye on the photos and projected onto the body; the photos are not orthographic, so
the scale of far features (windscreen, tail window) is approximate.

## O que NÃO é versionado (e por quê)
Por cautela com licenças de referências não verificadas, o Git guarda só scripts, medidas próprias (`out/*/measurements.json`, `diagnosis_v3.json`) e documentação. Ficam fora, e são regeneráveis a partir de um pacote local de referências (`FITGD_REFERENCES_DIR`): os `.blend` e renders procedurais v1 a v3, os perfis extraídos (`data/*.json`, gerados por `extract_profiles.py` e `side_photo_probe.py`) e `scripts/photo_features.py` (contornos lidos a olho nas fotos, necessário para `build_body.py`). Também fora: `candidates_local/` (modelos de terceiros), `refs_local/` (fotos) e `out/candidate_*/` (derivados de modelos de terceiros). Ver `DIAGNOSTICO_E_VIABILIDADE.md` e `CANDIDATOS_MODELOS_3D.md`.
