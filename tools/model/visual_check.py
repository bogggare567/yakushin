"""Bucket real pages with the model and eyeball the biggest groups: if the
model were over-merging, these are where it would show."""
import sys, numpy as np, torch, fitz
from PIL import Image, ImageDraw
import pipeline as P
from model import IconEmbedder, IN_SIDE

net = IconEmbedder(); net.load_state_dict(torch.load("model.pt", map_location="cpu")); net.eval()
TOL = float(sys.argv[3]) if len(sys.argv)>3 else 0.337

def embed(icon):
    h, w = icon.shape[:2]
    im = Image.fromarray(icon.astype(np.uint8)).resize((IN_SIDE, IN_SIDE), Image.BILINEAR)
    x = torch.from_numpy(np.asarray(im, dtype=np.float32)/255).permute(2,0,1)[None]
    a = torch.tensor([float(np.log(w/h))])
    with torch.no_grad(): return net(x, a)[0].numpy()

doc = fitz.open(sys.argv[1]); pages = int(sys.argv[2])
buckets = []
for p in range(pages):
    for bi, si, icon in P.iter_page_icons(doc, p):
        e = embed(icon)
        best, bd = None, 9
        for b in buckets:
            d = float(np.linalg.norm(b["e"]-e))
            if d < bd: bd, best = d, b
        if best is not None and bd <= TOL: best["m"].append((p+1, icon))
        else: buckets.append({"e": e, "m": [(p+1, icon)]})
    if p % 100 == 0: print(f"  page {p}: {len(buckets)} rows", flush=True)
print("rows:", len(buckets))

buckets.sort(key=lambda b: -len(b["m"]))
show = buckets[:12]
CELL=104
im = Image.new("RGB",(70+CELL*10, sum(CELL+22 for _ in show)+12),(22,24,30)); d=ImageDraw.Draw(im); y=6
for b in show:
    d.text((4,y+CELL//2), f"n={len(b['m'])}", fill=(255,255,255)); x=70
    for (pg, icon) in b["m"][:10]:
        q=Image.fromarray(icon.astype(np.uint8)); q.thumbnail((CELL-8,CELL-8))
        im.paste(q,(x+4,y+4)); d.text((x+4,y+CELL-2), f"p{pg}", fill=(220,210,90)); x+=CELL
    y+=CELL+22
im.save(f"model_buckets_{TOL:.2f}.png"); print(f"wrote model_buckets_{TOL:.2f}.png")
