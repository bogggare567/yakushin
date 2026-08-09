"""Measure how accurate the stud counter is, without anyone counting by eye.

Squinting at thumbnails does not scale and it is not repeatable. Two checks
here need no labels at all and both are strict:

  СОГЛАСИЕ ПО МАСШТАБУ   the same slot rendered at three different sizes must
                         come back with the same count. The renders differ in
                         pixels but not in what they show, so any disagreement
                         is the measurement being unstable.

  СОГЛАСИЕ ПО ЭКЗЕМПЛЯРАМ  the same part appears in many boxes across the
                         booklet at many drawing scales. Every one of them must
                         give the same answer.

Neither is used to produce a count, so neither can be gamed by loosening a
threshold: making the counter more permissive shows up immediately as
disagreement, and making it stricter shows up as lost coverage. Both numbers
have to be read together.

Usage: studs_check.py file.pdf [--pages 140]
"""
import argparse
from collections import defaultdict

import fitz
import numpy as np

import pipeline as P
import studs_count as SC

SCALES = [3.0, 2.4, 1.9]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", type=int, default=140)
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    n = min(args.pages, doc.page_count)
    per_slot = defaultdict(dict)      # (page, box, slot) -> {scale: size}
    for scale in SCALES:
        for page in range(n):
            for bi, si, icon in P.iter_page_icons(doc, page, scale):
                r = SC.measure(icon)
                per_slot[(page, bi, si)][scale] = r[0] if r else None
        print(f"  масштаб {scale} готов", flush=True)
    doc.close()

    measured = {k: v for k, v in per_slot.items() if any(x is not None for x in v.values())}
    full = {k: v for k, v in measured.items() if all(x is not None for x in v.values())}
    agree = sum(1 for v in full.values() if len(set(v.values())) == 1)
    # a slot measured at some scales and not others is not a disagreement, but
    # it is not a clean answer either, so count it separately
    partial = len(measured) - len(full)

    print(f"\nслотов {len(per_slot)}")
    print(f"  измерено хотя бы раз:     {len(measured)} ({len(measured)/len(per_slot)*100:.0f}%)")
    print(f"  измерено во всех масштабах: {len(full)}")
    print(f"  из них согласны:          {agree} ({agree/max(1,len(full))*100:.0f}%)")
    print(f"  измерено не везде:        {partial}")

    # What a vote across the readings gives — which is what the app can do,
    # since one part appears in dozens of boxes and gets measured every time.
    voted, voted_ok = 0, 0
    for v in measured.values():
        got = [x for x in v.values() if x is not None]
        counts = {}
        for g in got:
            counts[g] = counts.get(g, 0) + 1
        top = max(counts.values())
        if top >= 2:
            voted += 1
            if top == len(got):
                voted_ok += 1
    print(f"  большинство сходится:     {voted} из {len(measured)} "
          f"({voted/max(1,len(measured))*100:.0f}%), из них единогласно {voted_ok}")

    bad = [(k, v) for k, v in full.items() if len(set(v.values())) > 1]
    if bad:
        print("\nпримеры расхождений:")
        for k, v in bad[:8]:
            sizes = " / ".join(f"{s[0]}x{s[1]}" for s in v.values())
            print(f"   стр.{k[0]+1} рамка {k[1]} слот {k[2]}: {sizes}")

    hist = {}
    for v in full.values():
        if len(set(v.values())) == 1:
            s = next(iter(v.values()))
            hist[s] = hist.get(s, 0) + 1
    print("\nчто получилось (только согласованные):")
    print("   " + ", ".join(f"{k[0]}x{k[1]}:{c}"
                            for k, c in sorted(hist.items(), key=lambda kv: -kv[1])[:16]))


if __name__ == "__main__":
    main()
