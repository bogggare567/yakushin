"""Folds BatchNorm into the convolutions and writes a flat float32 blob the
browser can read with one fetch - no ML runtime needed on the client."""
import sys
import numpy as np, torch, json
from model import IconEmbedder, fold_bn, IN_SIDE, EMB_DIM

src = sys.argv[1] if len(sys.argv) > 1 else "model.pt"
net = IconEmbedder(); net.load_state_dict(torch.load(src, map_location="cpu")); net.eval()
print("экспортирую", src, f"(вход {IN_SIDE}x{IN_SIDE})")
parts, meta = [], []
for name, conv, bn in [("conv1", net.conv1, net.bn1), ("conv2", net.conv2, net.bn2),
                       ("conv3", net.conv3, net.bn3), ("conv4", net.conv4, net.bn4)]:
    w, b = fold_bn(conv, bn)
    meta.append({"name": name, "cout": w.shape[0], "cin": w.shape[1]})
    parts += [w.detach().numpy().ravel(), b.detach().numpy().ravel()]
parts += [net.fc.weight.detach().numpy().ravel(), net.fc.bias.detach().numpy().ravel()]
meta.append({"name": "fc", "out": net.fc.out_features, "in": net.fc.in_features})

blob = np.concatenate(parts).astype("<f4")
blob.tofile("../../webapp/vendor/partmodel.bin")
print("wrote webapp/vendor/partmodel.bin:", blob.nbytes, "bytes,", blob.size, "floats")
print("layers:", json.dumps(meta))

# reference vectors so the JS port can be checked numerically
rng = np.random.default_rng(0)
img = rng.random((3, 3, IN_SIDE, IN_SIDE), dtype=np.float32)
asp = rng.standard_normal(3).astype(np.float32)
with torch.no_grad():
    ref = net(torch.from_numpy(img), torch.from_numpy(asp)).numpy()
json.dump({"img": img.tolist(), "aspect": asp.tolist(), "emb": ref.tolist()},
          open("reference_vectors.json", "w"))
print("wrote reference_vectors.json for the JS parity check")
