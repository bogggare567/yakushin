"""Are colour and proportions safe to use as a hard veto?

The model sees an icon stretched into a square, so two things it structurally
under-weights are exactly the two the audit caught it getting wrong: a yellow
plate put in the same row as an orange one, and a 2x3 put in with a 2x4.

Both of those are measurable directly, and both are scale-invariant, which is
the property the whole problem hinges on: the booklet redraws an icon at
whatever size fits the box, and w/h does not change when it does.

So: measure how far apart colour and log(w/h) get for pairs that are certainly
the same part, and how far apart they get for pairs that are certainly
different. If the same-part side stays tight, a veto is free accuracy.
"""
import sys
import numpy as np
import fitz

import pipeline as P
import baseline as B

SCALES = [3.0, 2.4, 1.9]


def collect(pdfs):
    slots, boxes = {}, {}
    for pdf in pdfs:
        doc = fitz.open(pdf)
        for scale in SCALES:
            for page in range(doc.page_count):
                for bi, si, icon in P.iter_page_icons(doc, page, scale):
                    key = (pdf, page, bi, si)
                    h, w = icon.shape[:2]
                    slots.setdefault(key, []).append(
                        (B.dominant_color(icon), float(np.log(w / h))))
                    boxes.setdefault((pdf, page, bi), set()).add(key)
        doc.close()
        print(f"  {pdf.split('/')[-1]}: слотов {len(slots)}", flush=True)
    return slots, boxes


def report(name, pos, neg):
    pos, neg = np.array(pos), np.array(neg)
    print(f"\n=== {name}")
    print(f"  одна деталь ({len(pos)} пар):   среднее {pos.mean():.2f}  "
          f"95% {np.percentile(pos,95):.2f}  99% {np.percentile(pos,99):.2f}  "
          f"99.9% {np.percentile(pos,99.9):.2f}  макс {pos.max():.2f}")
    print(f"  разные детали ({len(neg)} пар): среднее {neg.mean():.2f}  "
          f"5% {np.percentile(neg,5):.2f}  25% {np.percentile(neg,25):.2f}  "
          f"медиана {np.median(neg):.2f}")
    print(f"  {'порог':>8}{'ложных разрывов':>18}{'пойманных склеек':>20}")
    for t in ([12, 16, 20, 24, 30, 40, 50] if "цвет" in name else
              [0.03, 0.05, 0.07, 0.10, 0.13, 0.18, 0.25]):
        fp = (pos > t).mean() * 100
        caught = (neg > t).mean() * 100
        print(f"  {t:>8}{fp:>17.2f}%{caught:>19.1f}%")


def main():
    pdfs = sys.argv[1:]
    slots, boxes = collect(pdfs)
    col_pos, col_neg, asp_pos, asp_neg = [], [], [], []

    for key, vals in slots.items():
        for a in range(len(vals)):
            for b in range(a + 1, len(vals)):
                col_pos.append(float(np.max(np.abs(vals[a][0] - vals[b][0]))))
                asp_pos.append(abs(vals[a][1] - vals[b][1]))

    for bkey, keys in boxes.items():
        keys = sorted(keys)
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                for va in slots[keys[a]]:
                    for vb in slots[keys[b]]:
                        col_neg.append(float(np.max(np.abs(va[0] - vb[0]))))
                        asp_neg.append(abs(va[1] - vb[1]))

    report("цвет (максимальное расхождение канала)", col_pos, col_neg)
    report("пропорции |Δ log(ширина/высота)|", asp_pos, asp_neg)


if __name__ == "__main__":
    main()
