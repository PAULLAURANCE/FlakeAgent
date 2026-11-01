# -*- coding: utf-8 -*-
"""make_tables: generate paper/tables/*.tex from data/summary/*.csv.
Run inside WSL after analyze.py. The section tex files \input these.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
import llm_client

HERE = os.path.dirname(os.path.abspath(__file__))
SUMMARY = os.path.join(HERE, "..", "data", "summary")
TABLES = os.path.join(HERE, "..", "..", "paper", "tables")
CAT_LABEL = {"od": "OD", "td": "TD", "nio": "NIO", "id": "ID"}
CATS = ["od", "td", "nio", "id"]

MODEL_LABEL = {
    "ds-flash": "DeepSeek-V4.1-Flash", "ds-pro": "DeepSeek-V4-Pro",
    "gemini38": "Gemini-3.8-Flash", "grok47": "Grok-4.7",
    "sol": "GPT-5.6", "astra": "GPT-6-Astra",
}
PROVIDER = {"ds-flash": "DeepSeek", "ds-pro": "DeepSeek", "gemini38": "Google",
            "grok47": "xAI", "sol": "OpenAI", "astra": "OpenAI"}
ROLE = {"ds-flash": "main", "ds-pro": "50-test subset", "gemini38": "50-test subset",
        "grok47": "50-test subset", "sol": "50-test subset", "astra": "50-test subset"}


def read(name):
    with open(os.path.join(SUMMARY, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(num, den):
    return "%.1f" % (100.0 * num / den) if den else "--"


def bold_best(row_cells):
    """Bold max, underline second max among numeric cells; returns formatted strings."""
    vals = []
    for c in row_cells:
        try:
            vals.append(float(c))
        except ValueError:
            vals.append(None)
    best = max(v for v in vals if v is not None) if any(v is not None for v in vals) else None
    second = None
    if best is not None:
        rest = sorted(set(v for v in vals if v is not None and v < best), reverse=True)
        second = rest[0] if rest else None
    out = []
    for c, v in zip(row_cells, vals):
        if v is None:
            out.append(c)
        elif v == best:
            out.append("\\textbf{%s}" % c)
        elif v == second:
            out.append("\\underline{%s}" % c)
        else:
            out.append(c)
    return out


def write(name, body):
    os.makedirs(TABLES, exist_ok=True)
    with open(os.path.join(TABLES, name), "w", encoding="utf-8") as f:
        f.write(body)


# ---------------- benchmark ----------------
def bench():
    rows = read("gate_summary.csv")
    lines = []
    for r in rows:
        if r["category"] == "total":
            label = "\\textbf{Total}"
        else:
            label = CAT_LABEL.get(r["category"], r["category"]) + \
                (" & & & & &" if False else "")
        lines.append("%s & %s & %s & %s & %s & %s\\\\" % (
            label, r["selected"], r["projects"], r["built"], r["passed"], r["rate"]))
    write("benchmark.tex", "\n".join(lines))


# ---------------- main results ----------------
METHODS = [("agent_ds-flash", "FlakeAgent"), ("naive", "NaiveRerun"),
           ("random", "RandomStr."), ("shuffle", "OrderShuffle"),
           ("sleepscan", "SleepScan"), ("singleshot", "SingleShot")]


def main_results():
    rates = {r["method"]: r for r in read("repro_rates.csv")}
    def row_cells(label, key):
        cells = []
        for m, _ in METHODS:
            r = rates.get(m)
            if not r:
                cells.append("--")
            elif key == "overall":
                cells.append(r["overall_rate"])
            else:
                cells.append(pct(int(r[key + "_repro"]), int(r[key + "_n"])))
        return bold_best(cells)
    rows_out = ["Overall & " + " & ".join(row_cells("Overall", "overall")) + "\\\\"]
    for c in CATS:
        rows_out.append(CAT_LABEL[c] + " & " + " & ".join(row_cells(c, c)) + "\\\\")
    write("main_results.tex", "\n".join(rows_out))


# ---------------- diagnosis ----------------
def diagnosis():
    rows = read("diagnosis.csv")
    by_cat = {c: [r for r in rows if r["gt"] == c] for c in CATS}
    lines = []
    for c in CATS + ["all"]:
        pool = by_cat[c] if c != "all" else rows
        if not pool:
            lines.append("%s & 0 & -- & -- & -- & --\\\\" % (CAT_LABEL[c] if c != "all" else "Overall"))
            continue
        n = len(pool)
        acc = sum(int(r["cat_correct"]) for r in pool)
        coarse = sum(int(r["coarse_correct"]) for r in pool)
        m = sum(int(r["ev_matched"]) for r in pool)
        t = sum(int(r["ev_total"]) for r in pool)
        hit = sum(int(r["fix_hit"]) for r in pool)
        label = CAT_LABEL[c] if c != "all" else "Overall"
        lines.append("%s & %d & %s & %s & %s & %s\\\\" % (
            label, n, pct(acc, n), pct(coarse, n), pct(m, t), pct(hit, n)))
    write("diagnosis.tex", "\n".join(lines))


# ---------------- ablation ----------------
ABLATIONS = [("agent_ds-flash", "FlakeAgent (main)"), ("agent_ds-flash_noreflection", "$-$reflection"),
             ("agent_ds-flash_space4", "$-$space4"), ("agent_ds-flash_nosource", "$-$source"),
             ("agent_ds-flash_warm", "Warm")]


def ablation():
    rates = {r["method"]: r for r in read("repro_rates.csv")}
    diag = read("diagnosis.csv")
    cost = read("cost.csv")
    lines = []
    for key, label in ABLATIONS:
        r = rates.get(key)
        repro = r["overall_rate"] if r else "--"
        pool = [d for d in diag if d["method"] == key]
        acc = pct(sum(int(d["cat_correct"]) for d in pool), len(pool)) if pool else "--"
        m = sum(int(d["ev_matched"]) for d in pool)
        t = sum(int(d["ev_total"]) for d in pool)
        prec = pct(m, t) if pool else "--"
        hit = pct(sum(int(d["fix_hit"]) for d in pool), len(pool)) if pool else "--"
        cs = [float(x["cost_usd"]) for x in cost if x["method"] == key]
        usd = "%.3f" % (sum(cs) / len(cs)) if cs else "--"
        if key == "agent_ds-flash_warm":
            repro = "n/a"
        lines.append("%s & %s & %s & %s & %s & %s\\\\" % (label, repro, acc, prec, hit, usd))
    write("ablation.tex", "\n".join(lines))


# ---------------- cost ----------------
def cost():
    cost = [r for r in read("cost.csv") if r["method"] == "agent_ds-flash"]
    metrics = [
        ("LLM calls per test", "llm_calls", "%d"),
        ("Executions per test", "executions", "%d"),
        ("Input tokens per test", "tokens_in", "%d"),
        ("Output tokens per test", "tokens_out", "%d"),
        ("Cost per test (USD)", "cost_usd", "%.3f"),
        ("Wall-clock per test (min)", "wallclock_s", "%.1f"),
    ]
    lines = []
    for label, key, fmt in metrics:
        vals = sorted(float(r[key]) for r in cost if r.get(key))
        if key == "wallclock_s":
            vals = [v / 60.0 for v in vals]
        if not vals:
            lines.append("%s & -- & -- & -- & --\\\\" % label)
            continue
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        mean = sum(vals) / n
        p90 = vals[min(n - 1, int(0.9 * n))]
        lines.append("%s & %s & %s & %s & %s\\\\" % (
            label, fmt % med, fmt % mean, fmt % p90, fmt % sum(vals)))
    # cost per reproduction (total cost / number of reproduced tests)
    repro = [r for r in read("atr.csv") if r["method"] == "agent_ds-flash" and r["reproduced"] == "1"]
    total_cost = sum(float(r["cost_usd"]) for r in cost)
    lines.append("Cost per reproduction (USD) & -- & -- & -- & %.3f\\\\"
                 % (total_cost / len(repro)) if repro else
                 "Cost per reproduction (USD) & -- & -- & -- & --\\\\")
    write("cost.tex", "\n".join(lines))


# ---------------- models results ----------------
def models_results():
    rates = {r["method"]: r for r in read("repro_rates.csv")}
    diag = read("diagnosis.csv")
    cost = read("cost.csv")
    lines = []
    for key in ["ds-flash", "ds-pro", "gemini38", "grok47", "sol", "astra"]:
        r = rates.get("agent_%s" % key)
        repro = r["overall_rate"] if r else "--"
        pool = [d for d in diag if d["method"] == "agent_%s" % key]
        acc = pct(sum(int(d["cat_correct"]) for d in pool), len(pool)) if pool else "--"
        m = sum(int(d["ev_matched"]) for d in pool)
        t = sum(int(d["ev_total"]) for d in pool)
        prec = pct(m, t) if pool else "--"
        hit = pct(sum(int(d["fix_hit"]) for d in pool), len(pool)) if pool else "--"
        cs = [float(x["cost_usd"]) for x in cost if x["method"] == "agent_%s" % key]
        usd = "%.3f" % (sum(cs) / len(cs)) if cs else "--"
        lines.append("%s & %s & %s & %s & %s & %s\\\\" % (
            MODEL_LABEL[key], repro, acc, prec, hit, usd))
    write("models_results.tex", "\n".join(lines))


# ---------------- model prices ----------------
def model_prices():
    lines = []
    for key in ["ds-flash", "ds-pro", "gemini38", "grok47", "sol", "astra"]:
        pin, pout = llm_client.PRICES[key]
        lines.append("%s & %s & %s & %.2f & %.2f & %s\\\\" % (
            key, MODEL_LABEL[key], PROVIDER[key], pin, pout, ROLE[key]))
    write("models.tex", "\n".join(lines))


if __name__ == "__main__":
    bench()
    main_results()
    diagnosis()
    ablation()
    cost()
    models_results()
    model_prices()
    print("[make_tables] wrote 7 table files to paper/tables/")
