# -*- coding: utf-8 -*-
"""Emit the loader's keyframes from a table of beats, so six bricks moving
through five poses stay in step without hand-copying percentages."""
import io

DUR = "9s"
# brick: (fall-in delay %, house pose, figure pose, sorted-row x, scatter dx,dy,rot)
# brick: fall-in delay %, house pose, figure pose, x in the sorted row,
# where it ends up after the stamp, and whether the foot lands on it. The two
# in the middle are crushed; the rest are only startled, which is what makes
# the stamp read as a stamp rather than as everything moving at once.
BRICKS = {
  "b1": (0,  (79, 72, 0),   (96, 54, 0),    10, (-52, -30, -34), False),
  "b2": (3,  (79, 52, 0),   (96, 36, 0),    51, (-30, -44, -20), False),
  "b3": (6,  (79, 28, -28), (104, 14, 0),  174, ( 30, -46,  28), False),
  "b4": (9,  (113, 28, 28), (66, 40, -16), 133, ( 16, -22, -12), True),
  "b5": (12, (113, 52, 0),  (126, 40, 16), 215, ( 58, -34,  32), False),
  "b6": (15, (113, 72, 0),  (105, 72, 0),   92, (-20, -18,  14), True),
}
ROW_Y = 72

def tf(x, y, r=0, extra=""):
    s = f"translate({x}px, {y}px)"
    if r: s += f" rotate({r}deg)"
    return s + (" " + extra if extra else "")

out = io.StringIO()
for name, (delay, house, figure, rowx, scatter, stomped) in BRICKS.items():
    hx, hy, hr = house
    fx, fy, fr = figure
    sx, sy, sr = scatter
    k = [
        (0,               f"{tf(hx, -60, hr)}; opacity: 0"),
        (delay,           f"{tf(hx, -60, hr)}; opacity: 0"),
        (delay + 8,       f"{tf(hx, hy + 6, hr)}; opacity: 1"),   # overshoot on landing
        (delay + 11,      f"{tf(hx, hy, hr)}; opacity: 1"),
        (26,              f"{tf(hx, hy, hr)}"),                   # the house holds
        (34,              f"{tf(fx, fy, fr)}"),                   # becomes a figure
        (44,              f"{tf(fx, fy, fr)}"),
        (52,              f"{tf(rowx, ROW_Y, 0)}"),               # falls into a colour row
        (61,              f"{tf(rowx, ROW_Y, 0)}"),
        (63,              f"{tf(rowx, ROW_Y + 8, 0, 'scaleY(.45)')}" if stomped
                          else f"{tf(rowx, ROW_Y - 7, -5)}"),               # crushed, or startled
        (70,              f"{tf(rowx + sx, ROW_Y + sy, sr)}; opacity: 1"),
        (76,              f"{tf(round(rowx + sx * 1.3), round(ROW_Y + sy * 0.2), round(sr * 1.5))}; opacity: 0"),
        (100,             f"{tf(hx, -60, hr)}; opacity: 0"),
    ]
    out.write(f"@keyframes {name}-fly {{\n")
    seen = set()
    for pct, val in k:
        if pct in seen: continue
        seen.add(pct)
        out.write(f"  {pct}% {{ transform: {val}; }}\n" if "opacity" not in val
                  else f"  {pct}% {{ transform: {val.split(';')[0]}; opacity: {val.split('opacity:')[1].strip()}; }}\n")
    out.write("}\n")

# dust: circles pushed outward from the point of impact
DUST = [(-46, -6, 1.7), (-26, -16, 1.3), (-8, -20, 1.1), (14, -17, 1.4), (34, -8, 1.6), (52, 2, 1.2)]
for i, (dx, dy, sc) in enumerate(DUST, 1):
    out.write(f"""@keyframes dust{i} {{
  0%, 62% {{ transform: translate(0, 0) scale(.2); opacity: 0; }}
  64%     {{ transform: translate({dx*0.3:.0f}px, {dy*0.3:.0f}px) scale(.9); opacity: .85; }}
  72%     {{ transform: translate({dx}px, {dy}px) scale({sc}); opacity: .35; }}
  78%, 100% {{ transform: translate({dx*1.25:.0f}px, {dy*1.2:.0f}px) scale({sc*1.2:.2f}); opacity: 0; }}
}}
""")

# specks kicked up by the stamp
SPECK = [(-58, -40, -160), (-30, -54, 120), (28, -50, -140), (58, -34, 170)]
for i, (dx, dy, rot) in enumerate(SPECK, 1):
    out.write(f"""@keyframes speck{i} {{
  0%, 62%   {{ transform: translate(0, 0) rotate(0deg); opacity: 0; }}
  64%       {{ transform: translate(0, 0) rotate(0deg); opacity: 1; }}
  74%       {{ transform: translate({dx}px, {dy}px) rotate({rot}deg); opacity: 1; }}
  80%, 100% {{ transform: translate({dx*1.2:.0f}px, {dy*0.55:.0f}px) rotate({rot*1.3:.0f}deg); opacity: 0; }}
}}
""")
print(out.getvalue())
