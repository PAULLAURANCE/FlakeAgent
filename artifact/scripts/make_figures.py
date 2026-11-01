# -*- coding: utf-8 -*-
"""make_figures: generate paper/figures/*.pdf from data/summary/*.csv.
Run inside WSL after analyze.py. Style matches the paper (serif, muted palette).
"""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY = os.path.join(HERE, "..", "data", "summary")
FIGDIR = os.path.join(HERE, "..", "..", "paper", "figures")

BLUE = "#1f77b4"
ORANGE = "#ff7f0e"
GREEN = "#2ca02c"
RED = "#d62728"
PURPLE = "#9467bd"
GRAY = "#7f7f7f"
BROWN = "#8c564b"

METHOD_ORDER = [("agent_ds-flash", "FlakeAgent"), ("singleshot", "SingleShotLLM"),
                ("random", "RandomStr."), ("shuffle", "OrderShuffle"),
                ("sleepscan", "SleepScan"), ("naive", "NaiveRerun")]
CAT_LABEL = {"od": "OD", "td": "TD", "nio": "NIO", "id": "ID"}
CATS = ["od", "td", "nio", "id"]
METHOD_COLORS = [BLUE, PURPLE, GRAY, BROWN, GREEN, ORANGE]

plt.rcParams.update({
    "font.family": "DejaVu Serif", "font.size": 9,
    "axes.titlesize": 9, "axes.labelsize": 9, "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5, "legend.fontsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
})


def read(name):
    with open(os.path.join(SUMMARY, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(fig, name):
    os.makedirs(FIGDIR, exist_ok=True)
    fig.savefig(os.path.join(FIGDIR, name), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("[make_figures] wrote", name)


def fig_repro_overall():
    rates = {r["method"]: r for r in read("repro_rates.csv")}
    var = {}
    for r in read("variance.csv"):
        try:
            var[r["method"]] = (float(r["mean_rate"]), float(r["std_rate"]))
        except ValueError:
            pass
    labels, vals, errs, colors = [], [], [], []
    for key, label in METHOD_ORDER:
        r = rates.get(key)
        if not r:
            continue
        labels.append(label)
        vals.append(float(r["overall_rate"]))
        errs.append(var.get(key, (None, None))[1] if key in var else None)
        colors.append(METHOD_COLORS[len(labels) - 1])
    fig, ax = plt.subplots(figsize=(6.5, 2.6))
    x = np.arange(len(labels))
    bars = ax.bar(x, vals, 0.55, color=colors)
    err = [e if e else 0 for e in errs]
    ax.errorbar(x, vals, yerr=err, fmt="none", ecolor="black", capsize=3, linewidth=0.8)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 1.2, "%.1f%%" % v, ha="center", fontsize=8.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.set_ylim(0, max(vals) * 1.18)
    ax.set_ylabel("Reproduction rate")
    ax.set_title("Overall reproduction rate within the 8-execution budget")
    save(fig, "repro_overall.pdf")


def fig_repro_category():
    rates = {r["method"]: r for r in read("repro_rates.csv")}
    groups = [("agent_ds-flash", "FlakeAgent")]
    best_key, best_val = None, -1
    for key, label in METHOD_ORDER[2:]:
        r = rates.get(key)
        if r and float(r["overall_rate"]) > best_val:
            best_key, best_val = key, float(r["overall_rate"])
    groups.append((best_key, "Best baseline"))
    groups.append(("singleshot", "SingleShotLLM"))
    x = np.arange(len(CATS))
    width = 0.26
    colors = [BLUE, GRAY, PURPLE]
    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    for gi, (key, label) in enumerate(groups):
        r = rates.get(key)
        vals = [100.0 * int(r[c + "_repro"]) / int(r[c + "_n"]) if r and r[c + "_n"] != "0" else 0
                for c in CATS]
        bars = ax.bar(x + (gi - 1) * width, vals, width, label=label, color=colors[gi])
        for xi, v in zip(x + (gi - 1) * width, vals):
            ax.text(xi, v + 2, "%.0f" % v, ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([CAT_LABEL[c] for c in CATS])
    ax.set_ylabel("Reproduction rate (%)")
    ax.legend(frameon=False, loc="upper left", ncol=3)
    ax.set_ylim(0, 110)
    save(fig, "repro_category.pdf")


def fig_heatmap():
    rows = read("heatmap.csv")
    cats = CATS
    strats = ["T%d" % i for i in range(1, 13)]
    mat = np.zeros((len(cats), len(strats)))
    counts = np.zeros((len(cats), len(strats)))
    for r in rows:
        if r["category"] in cats and r["strategy"] in strats:
            i, j = cats.index(r["category"]), strats.index(r["strategy"])
            mat[i, j] += int(r["count"])
            counts[i, j] += int(r["count"])
    rowsum = mat.sum(axis=1, keepdims=True)
    norm = np.divide(mat, rowsum, out=np.zeros_like(mat), where=rowsum > 0)
    fig, ax = plt.subplots(figsize=(6.5, 2.6))
    im = ax.imshow(norm, cmap="YlOrRd", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(np.arange(len(strats)))
    ax.set_xticklabels(strats)
    ax.set_yticks(np.arange(len(cats)))
    ax.set_yticklabels([CAT_LABEL[c] for c in cats])
    for i in range(len(cats)):
        for j in range(len(strats)):
            if counts[i, j] > 0:
                ax.text(j, i, "%d" % counts[i, j], ha="center", va="center",
                        fontsize=8, fontweight="bold",
                        color="white" if norm[i, j] > 0.4 else "black")
    ax.set_xlabel("Strategy")
    ax.set_ylabel("Ground-truth category")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("share")
    save(fig, "heatmap.pdf")


def fig_atr_ecdf():
    rows = read("atr.csv")
    methods = [("agent_ds-flash", "FlakeAgent"), ("naive", "NaiveRerun"),
               ("random", "RandomStr."), ("singleshot", "SingleShotLLM")]
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    for key, label in methods:
        vals = sorted(int(r["attempts"]) for r in rows if r["method"] == key)
        if not vals:
            continue
        xs = np.array(vals)
        ys = np.arange(1, len(xs) + 1) / len(xs)
        ax.step(np.append(xs, 9), np.append(ys, ys[-1]), where="post",
                label="%s (n=%d)" % (label, len(vals)), linewidth=1.4)
    ax.set_xlim(1, 8)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Executions until first reproduction")
    ax.set_ylabel("Cumulative share")
    ax.legend(frameon=False, fontsize=6, loc="lower right")
    save(fig, "atr_ecdf.pdf")


def fig_cost_scatter():
    import sys
    import json
    import glob
    atr = read("atr.csv")
    rep = {(r["zip"], r["test"]): int(r["attempts"]) for r in atr
           if r["method"] == "agent_ds-flash"}
    js = []
    for p in glob.glob(os.path.join(HERE, "..", "data", "results", "agent_ds-flash*.jsonl")):
        if "_s" in os.path.basename(p):
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    js.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    xs_repro, ys_repro = [], []
    xs_miss, ys_miss = [], []
    for r in js:
        key = (r.get("zip"), r.get("test"))
        c = r.get("cost_usd") or 0
        if r.get("reproduced"):
            xs_repro.append(rep.get(key, 1))
            ys_repro.append(c)
        else:
            xs_miss.append(r.get("executions", 0))
            ys_miss.append(c)
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    ax.scatter(xs_miss, ys_miss, s=14, facecolors="none", edgecolors=GRAY,
               alpha=0.6, label="unreproduced")
    ax.scatter(xs_repro, ys_repro, s=14, color=BLUE, alpha=0.8, label="reproduced")
    ax.set_xlabel("Executions")
    ax.set_ylabel("Cost (USD, list)")
    ax.legend(frameon=False, fontsize=6)
    save(fig, "cost_scatter.pdf")


def fig_ablation():
    rates = {r["method"]: r for r in read("repro_rates.csv")}
    configs = [("agent_ds-flash", "Main"), ("agent_ds-flash_noreflection", "$-$reflection"),
               ("agent_ds-flash_space4", "$-$space4"), ("agent_ds-flash_nosource", "$-$source")]
    labels, vals, colors = [], [], []
    for key, label in configs:
        r = rates.get(key)
        if not r:
            continue
        labels.append(label)
        vals.append(float(r["overall_rate"]))
        colors.append([BLUE, ORANGE, GREEN, RED][len(labels) - 1])
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    x = np.arange(len(labels))
    ax.bar(x, vals, 0.55, color=colors)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 1.2, "%.1f%%" % v, ha="center", fontsize=8.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(vals) * 1.2)
    ax.set_ylabel("Reproduction rate")
    save(fig, "ablation.pdf")


if __name__ == "__main__":
    import sys
    fig_repro_overall()
    fig_repro_category()
    fig_heatmap()
    fig_atr_ecdf()
    fig_cost_scatter()
    fig_ablation()
    print("[make_figures] done")
