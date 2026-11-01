# -*- coding: utf-8 -*-
"""make_diagrams: the three schematic figures drawn with matplotlib:
motivating_example.pdf, overview.pdf, case_timeline.pdf.
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "..", "..", "paper", "figures")
os.makedirs(FIGDIR, exist_ok=True)

BLUE = "#1f77b4"
ORANGE = "#ff7f0e"
GREEN = "#2ca02c"
RED = "#d62728"
PURPLE = "#9467bd"
GRAY = "#666666"
LIGHT = "#eef4fa"
LIGHTG = "#eef9ee"
LIGHTR = "#fdeeee"
MONO = "DejaVu Sans Mono"

plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 8.5})


def box(ax, x, y, w, h, fc, ec, lw=1.0):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.03",
                       fc=fc, ec=ec, lw=lw)
    ax.add_patch(p)
    return p


def fitted_text(ax, x, y, s, max_width, ha="center", fontsize=8, weight="normal",
                color="black", fontfamily=None, style="normal"):
    """Draw text at (x, y), auto-shrinking the font size so the rendered width
    fits within max_width (data units). Guarantees no horizontal overflow."""
    fig = ax.figure
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    size = fontsize
    while size > 4.0:
        t = ax.text(x, y, s, ha=ha, va="center", fontsize=size, weight=weight,
                    color=color, fontfamily=fontfamily, style=style)
        bb = t.get_window_extent(renderer=renderer)
        (x0, _), (x1, _) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
        w = x1 - x0
        if w <= max_width:
            return t
        t.remove()
        size -= 0.5
    t = ax.text(x, y, s, ha=ha, va="center", fontsize=size, weight=weight,
                color=color, fontfamily=fontfamily, style=style)
    return t


def arrow(ax, x1, y1, x2, y2, color=GRAY, lw=1.2, style="-|>", ls="-"):
    a = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=11,
                        color=color, lw=lw, linestyle=ls)
    ax.add_patch(a)
    return a


def fig_overview():
    fig, ax = plt.subplots(figsize=(7.4, 2.4))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.4)
    ax.axis("off")
    # static context (left, stacked)
    box(ax, 0.15, 2.45, 1.75, 1.85, LIGHT, BLUE)
    fitted_text(ax, 1.02, 3.85, "Static context", 1.6, fontsize=8, color=BLUE, weight="bold")
    fitted_text(ax, 1.02, 3.35, "test source\nco-test candidates\nmodule, Java, budget", 1.6, fontsize=7)
    box(ax, 0.15, 0.35, 1.75, 1.85, LIGHT, BLUE)
    fitted_text(ax, 1.02, 1.7, "Last two\nobservations", 1.6, fontsize=7)
    # planner
    box(ax, 2.5, 2.7, 2.5, 1.6, "#ffffff", BLUE, 1.3)
    fitted_text(ax, 3.75, 3.85, "Planner (LLM API)", 2.3, fontsize=9, weight="bold", color=BLUE)
    fitted_text(ax, 3.75, 3.2, "hypothesis → strategy,\nparams", 2.3, fontsize=7)
    arrow(ax, 1.9, 3.3, 2.5, 3.3)
    arrow(ax, 1.9, 1.3, 2.5, 3.0, ls=":")
    arrow(ax, 1.9, 1.0, 2.5, 2.8, ls=":")
    # executor
    box(ax, 5.35, 2.7, 1.9, 1.6, "#ffffff", ORANGE, 1.3)
    fitted_text(ax, 6.3, 3.85, "Executor", 1.7, fontsize=9, weight="bold", color=ORANGE)
    fitted_text(ax, 6.3, 3.2, "12 strategies T1--T12\nMaven sandbox, 5-min cap", 1.7, fontsize=7)
    arrow(ax, 5.0, 3.3, 5.35, 3.3)
    # probe
    box(ax, 7.7, 2.7, 2.15, 1.6, "#ffffff", GREEN, 1.3)
    fitted_text(ax, 8.78, 3.85, "Observation probe", 1.95, fontsize=9, weight="bold", color=GREEN)
    fitted_text(ax, 8.78, 3.2, "exit, failed tests,\nassertions, stack, duration", 1.95, fontsize=7)
    arrow(ax, 7.25, 3.3, 7.7, 3.3)
    # feedback loop arrow back
    arrow(ax, 8.78, 2.6, 1.02, 2.0, color=GREEN, lw=1.1,
          ls=(0, (4, 3)), style="-|>")
    ax.text(4.5, 2.3, "repeat until failure reproduced or budget exhausted", ha="center",
            va="center", fontsize=7, style="italic", color=GREEN)
    # diagnose branch
    box(ax, 5.6, 0.35, 3.1, 1.5, LIGHTR, RED, 1.3)
    fitted_text(ax, 7.15, 1.4, "Diagnoser (LLM API, 1 call)", 2.9, fontsize=9, weight="bold", color=RED)
    fitted_text(ax, 7.15, 0.85, "category · root cause · evidence[] · confidence", 2.9, fontsize=7)
    arrow(ax, 8.4, 2.7, 7.15, 1.85, color=RED, lw=1.1)
    ax.text(8.85, 2.3, "on failure", ha="center", va="center", fontsize=7, color=RED)
    fig.savefig(os.path.join(FIGDIR, "overview.pdf"), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("[make_diagrams] overview.pdf")


def fig_motivating():
    fig, ax = plt.subplots(figsize=(6.6, 3.7))
    ax.set_xlim(0, 13.2)
    ax.set_ylim(0, 7.4)
    ax.axis("off")
    # (a) source
    box(ax, 0.1, 0.25, 3.5, 6.8, "#fbfbfb", GRAY, 0.8)
    fitted_text(ax, 1.85, 6.75, "(a) Test source (real)", 3.3, fontsize=8, weight="bold")
    src = [
        "class ExhaustingAGiven... {",
        "  @Test public void enums() {",
        "    assertThat(testResult(",
        "      Enums.class), isSuccessful());",
        "    assertEquals(defaultProperty-",
        "      TrialCount(), Enums.iterations);",
        "    assertEquals(EnumSet.of(...),",
        "      new HashSet<>(Enums.values",
        "      .subList(0, 2)));",
        "  }",
        "  static class Enums {",
        "    static int iterations;",
        "    static List values = ...;",
        "  }",
        "}",
    ]
    for i, line in enumerate(src):
        fitted_text(ax, 0.4, 6.55 - i * 0.42, line, 3.3, ha="left",
                    fontsize=6.6, fontfamily=MONO,
                    color="#222222" if "iterations" not in line else RED)
    # (b) double run
    box(ax, 3.85, 0.25, 3.5, 7.0, "#fbfbfb", GRAY, 0.8)
    fitted_text(ax, 5.6, 6.95, "(b) Same-JVM double run (T2)", 3.3, fontsize=8, weight="bold")
    box(ax, 4.05, 5.4, 3.1, 1.15, LIGHTG, GREEN)
    fitted_text(ax, 5.6, 6.18, "sub-run 1: PASS", 2.9, fontsize=8, weight="bold", color=GREEN)
    ax.text(5.6, 5.75, "iterations = 100", ha="center", va="center", fontsize=7)
    box(ax, 4.05, 4.0, 3.1, 1.15, LIGHTR, RED)
    fitted_text(ax, 5.6, 4.78, "sub-run 2: FAIL", 2.9, fontsize=8, weight="bold", color=RED)
    fitted_text(ax, 5.6, 4.35, "expected: 100 but was: 200", 2.9, fontsize=6.6, fontfamily=MONO)
    arrow(ax, 5.6, 5.4, 5.6, 5.2, color=GRAY)
    fitted_text(ax, 4.05, 3.25, "No rerun loop can see this:\nboth sub-runs live in one JVM,\nthe state leak is the bug.", 3.1, ha="left", fontsize=7)
    # (c) fix
    box(ax, 7.55, 0.25, 2.55, 7.0, "#fbfbfb", GRAY, 0.8)
    fitted_text(ax, 8.82, 6.95, "(c) Developer fix", 2.35, fontsize=8, weight="bold")
    fitted_text(ax, 7.75, 6.2, "assertEquals(...\n  Enums.values.subList(0, 2)));", 2.3, ha="left", fontsize=6.4, fontfamily=MONO)
    fitted_text(ax, 7.75, 5.2, "+ Enums.iterations = 0;", 2.3, ha="left", fontsize=6.4, fontfamily=MONO, color=GREEN, weight="bold")
    fitted_text(ax, 8.82, 4.2, "Fix confirms the mechanism:\nreset static state after\neach assertion.", 2.3, fontsize=7)
    # (d) trajectory
    box(ax, 10.3, 0.25, 2.75, 7.0, "#fbfbfb", GRAY, 0.8)
    fitted_text(ax, 11.67, 6.95, "(d) FlakeAgent trajectory", 2.55, fontsize=8, weight="bold")
    steps = [
        ("Step 0: 3 reruns", "all PASS", "#666666"),
        ("Hypothesis:", "\"static state leaks\nacross runs\"", BLUE),
        ("Pick T2 (runs=2)", "same-JVM double run", ORANGE),
        ("sub-run 2 FAILS", "expected:100 was:200", RED),
        ("Diagnose: NIO", "evidence = assertion\nline the fix touches", GREEN),
    ]
    y = 6.05
    for title, sub, color in steps:
        fitted_text(ax, 10.45, y, title, 2.55, ha="left", fontsize=7.4, weight="bold", color=color)
        fitted_text(ax, 10.45, y - 0.42, sub, 2.55, ha="left", fontsize=6.6, color="#333333")
        y -= 1.16
        if y > 1.3:
            arrow(ax, 11.67, y + 0.55, 11.67, y + 0.3, color="#999999")
    fitted_text(ax, 10.45, 0.55, "Total: 2 LLM calls,\n4 executions", 2.55, ha="left", fontsize=7, style="italic")
    fig.savefig(os.path.join(FIGDIR, "motivating_example.pdf"), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("[make_diagrams] motivating_example.pdf")


def fig_case_timeline():
    fig, ax = plt.subplots(figsize=(6.8, 2.6))
    ax.set_xlim(0, 13.2)
    ax.set_ylim(0, 4.2)
    ax.axis("off")
    # time axis
    arrow(ax, 0.5, 0.55, 12.7, 0.55, color=GRAY, lw=1.4)
    for x, t in [(0.5, "t=0"), (4.4, "~12 s"), (8.4, "~22 s"), (12.2, "~31 s")]:
        ax.text(x, 0.12, t, ha="center", va="center", fontsize=7, color=GRAY)
    # Step 0
    box(ax, 0.6, 1.05, 3.3, 2.85, LIGHT, BLUE)
    fitted_text(ax, 2.25, 3.55, "Step 0 — baseline (no LLM)", 3.1, fontsize=8, weight="bold", color=BLUE)
    ax.text(2.25, 2.95, "3 isolated reruns", ha="center", va="center", fontsize=7.5)
    ax.text(2.25, 2.5, "T1 → PASS, PASS, PASS", ha="center", va="center", fontfamily=MONO, fontsize=6.6)
    fitted_text(ax, 2.25, 1.7, "no failure log exists —\nthe bug never shows up\non a rerun", 3.0, fontsize=7, color="#444444")
    arrow(ax, 3.9, 2.45, 4.45, 2.45, color=BLUE)
    # Round 1
    box(ax, 4.45, 1.05, 3.6, 2.85, "#ffffff", ORANGE, 1.2)
    fitted_text(ax, 6.25, 3.55, "Round 1 — plan (1 LLM call)", 3.4, fontsize=8, weight="bold", color=ORANGE)
    fitted_text(ax, 6.25, 2.9, "hypothesis: \"static iteration\ncounters and value lists never\nreset; 2nd JVM run sees doubles\"", 3.4, fontsize=6.8)
    ax.text(6.25, 1.8, "strategy: T2, runs=2", ha="center", va="center", fontfamily=MONO, fontsize=7)
    fitted_text(ax, 6.25, 1.32, "sub-run 1 PASS → sub-run 2 FAIL\n(expected:<100> but was:<200>)", 3.4, fontsize=6.6, color=RED)
    arrow(ax, 8.05, 2.45, 8.6, 2.45, color=ORANGE)
    # Diagnose
    box(ax, 8.6, 1.05, 3.6, 2.85, LIGHTR, RED, 1.2)
    fitted_text(ax, 10.4, 3.55, "Diagnose (1 LLM call)", 3.4, fontsize=8, weight="bold", color=RED)
    ax.text(10.4, 2.95, "category: NIO (conf 0.98)", ha="center", va="center", fontfamily=MONO, fontsize=7)
    fitted_text(ax, 10.4, 2.35, "root cause: static accumulator\nnever reset across executions", 3.4, fontsize=6.8)
    fitted_text(ax, 10.4, 1.5, "evidence: counter site L83–90 +\nassertion L460 (fix adds reset there)", 3.4, fontsize=6.8, color=GREEN)
    fig.savefig(os.path.join(FIGDIR, "case_timeline.pdf"), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("[make_diagrams] case_timeline.pdf")


if __name__ == "__main__":
    fig_overview()
    fig_motivating()
    fig_case_timeline()
    print("[make_diagrams] done")
