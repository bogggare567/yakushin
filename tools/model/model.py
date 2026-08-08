"""The embedding network.

Deliberately tiny: it has to run in plain JavaScript in the browser, over ~2000
icons, without pulling in an ML runtime. ~36k parameters, ~1.1M multiply-adds
per icon.

Two design points worth knowing:

* the icon is STRETCHED to a square rather than letterboxed. Letterboxing is
  what the old hand-written signature did, and it wasted almost the whole
  image on padding for long thin parts (a 1x8 tile became a 2px strip), which
  is why tiles of different lengths were indistinguishable. Stretching keeps
  full resolution for the surface, and the aspect ratio - the thing stretching
  throws away - is handed to the network separately as a number.

* BatchNorm is used for training stability but folded into the convolution
  weights on export, so the JavaScript side only ever needs conv + ReLU.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

SIDE = 32          # icons are fed at 32x32
IN_SIDE = 32
EMB_DIM = 48


class IconEmbedder(nn.Module):
    def __init__(self, emb_dim=EMB_DIM):
        super().__init__()
        # sized for the browser: ~1M multiply-adds per icon, ~17k parameters
        c1, c2, c3, c4 = 8, 16, 32, 32
        self.conv1 = nn.Conv2d(3, c1, 3, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(c1)
        self.conv2 = nn.Conv2d(c1, c2, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(c2)
        self.conv3 = nn.Conv2d(c2, c3, 3, padding=1, bias=False)
        self.bn3 = nn.BatchNorm2d(c3)
        self.conv4 = nn.Conv2d(c3, c4, 3, padding=1, bias=False)
        self.bn4 = nn.BatchNorm2d(c4)
        self.fc = nn.Linear(c4 + 1, emb_dim)

    def forward(self, img, aspect):
        # img: (N,3,IN_SIDE,IN_SIDE) already scaled to 0..1
        x = F.max_pool2d(F.relu(self.bn1(self.conv1(img))), 2)   # 32 -> 16
        x = F.max_pool2d(F.relu(self.bn2(self.conv2(x))), 2)     # 16 -> 8
        x = F.max_pool2d(F.relu(self.bn3(self.conv3(x))), 2)     # 8 -> 4
        x = F.relu(self.bn4(self.conv4(x)))
        x = x.mean(dim=(2, 3))                                   # global average
        x = torch.cat([x, aspect.unsqueeze(1)], dim=1)
        x = self.fc(x)
        return F.normalize(x, dim=1)                             # unit sphere


def fold_bn(conv, bn):
    """conv(no bias) + BN  ->  equivalent conv with bias, for the JS runtime."""
    w = conv.weight.detach().clone()
    gamma, beta = bn.weight.detach(), bn.bias.detach()
    mean, var, eps = bn.running_mean, bn.running_var, bn.eps
    scale = gamma / torch.sqrt(var + eps)
    w = w * scale.reshape(-1, 1, 1, 1)
    b = beta - mean * scale
    return w, b
