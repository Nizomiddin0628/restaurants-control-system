"""
AI Kotib diagrammalari. AI rasm chizmaydi — u faqat diagramma «tavsifini» (tur, sarlavha, yorliqlar, raqamlar)
make_chart asbobi orqali beradi; server uni matplotlib bilan PNG'ga aylantiradi (Telegram va saytga yuboriladi).
Hech qanday kod bajarilmaydi — faqat tekshirilgan raqamlar chiziladi.
"""
from __future__ import annotations

import base64
import io
import logging

log = logging.getLogger("ai")
KINDS = ("bar", "hbar", "line", "pie")
PALETTE = ["#2563EB", "#F97316", "#10B981", "#A855F7", "#EF4444", "#0EA5E9", "#EAB308", "#64748B"]
MAX_POINTS = 31
MAX_SERIES = 4


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def short(v: float, unit: str = "") -> str:
    a = abs(v)
    if a >= 1e9:
        s = f"{v / 1e9:.1f} mlrd"
    elif a >= 1e6:
        s = f"{v / 1e6:.1f} mln"
    elif a >= 1e4:
        s = f"{v / 1e3:.0f} ming"
    elif a == int(a):
        s = f"{int(v)}"
    else:
        s = f"{v:.1f}"
    s = s.replace(".0 ", " ").replace(".", ",")
    return f"{s} {unit}" if unit else s


def validate(spec: dict) -> dict:
    """AI bergan tavsifni tozalash: tur, ≤31 nuqta, ≤4 seriya, faqat raqamlar."""
    kind = str(spec.get("kind") or "bar").lower()
    kind = kind if kind in KINDS else "bar"
    labels = [str(x)[:28] for x in (spec.get("labels") or [])][:MAX_POINTS]
    series = []
    for s in (spec.get("series") or [])[:MAX_SERIES]:
        vals = [_num(v) for v in (s.get("values") or [])][: len(labels)]
        if vals:
            series.append({"name": str(s.get("name") or "")[:40], "values": vals + [0.0] * (len(labels) - len(vals))})
    if not labels or not series:
        raise ValueError("labels va series bo'sh bo'lmasin")
    if kind == "pie":
        series = series[:1]
    return {"kind": kind, "title": str(spec.get("title") or "")[:90], "unit": str(spec.get("unit") or "")[:12],
            "labels": labels, "series": series}


def render(spec: dict) -> bytes:
    """Tavsif → PNG (1000×620). Xato bo'lsa ValueError."""
    import os
    import tempfile
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "restopos-mpl"))   # server foydalanuvchisida uy papkasi bo'lmasa ham
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    s = validate(spec)
    kind, labels, series, unit = s["kind"], s["labels"], s["series"], s["unit"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#CBD5E1", "axes.labelcolor": "#334155", "xtick.color": "#475569", "ytick.color": "#475569"})
    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=100)
    fig.patch.set_facecolor("white")
    fmt = FuncFormatter(lambda v, _p: short(v))
    n = len(series)
    if kind == "pie":
        vals = [max(0.0, v) for v in series[0]["values"]]
        if not sum(vals):
            raise ValueError("bo'sh doira")
        wedges, _t, auto = ax.pie(vals, labels=None, colors=(PALETTE * 4)[: len(vals)], startangle=90, counterclock=False,
                                  autopct=lambda p: f"{p:.0f}%" if p >= 4 else "", pctdistance=0.78,
                                  wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 2})
        for a in auto:
            a.set_color("white")
            a.set_fontweight("bold")
        ax.legend(wedges, [f"{lab} — {short(v, unit)}" for lab, v in zip(labels, vals, strict=False)], loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
        ax.set_aspect("equal")
    elif kind == "hbar":
        idx = list(range(len(labels)))[::-1]
        h = 0.8 / n
        for i, se in enumerate(series):
            ys = [y + (i - (n - 1) / 2) * h for y in idx]
            bars = ax.barh(ys, se["values"], height=h * 0.92, color=PALETTE[i % len(PALETTE)], label=se["name"] or None)
            if len(labels) <= 15:
                ax.bar_label(bars, labels=[short(v) for v in se["values"]], padding=4, fontsize=10, color="#334155")
        ax.set_yticks(idx, labels)
        ax.xaxis.set_major_formatter(fmt)
        ax.grid(axis="x", color="#E2E8F0")
        ax.set_axisbelow(True)
    elif kind == "line":
        x = list(range(len(labels)))
        for i, se in enumerate(series):
            c = PALETTE[i % len(PALETTE)]
            ax.plot(x, se["values"], color=c, linewidth=2.6, marker="o" if len(x) <= 16 else None, markersize=5, label=se["name"] or None)
            if n == 1:
                ax.fill_between(x, se["values"], color=c, alpha=0.08)
        step = max(1, len(labels) // 12)
        ax.set_xticks(x[::step], labels[::step], rotation=0 if len(labels) <= 8 else 35, ha="center" if len(labels) <= 8 else "right")
        ax.yaxis.set_major_formatter(fmt)
        ax.grid(axis="y", color="#E2E8F0")
        ax.set_axisbelow(True)
    else:
        x = list(range(len(labels)))
        w = 0.8 / n
        for i, se in enumerate(series):
            xs = [v + (i - (n - 1) / 2) * w for v in x]
            bars = ax.bar(xs, se["values"], width=w * 0.92, color=PALETTE[i % len(PALETTE)], label=se["name"] or None)
            if len(labels) * n <= 16:
                ax.bar_label(bars, labels=[short(v) for v in se["values"]], padding=3, fontsize=10, color="#334155")
        ax.set_xticks(x, labels, rotation=0 if len(labels) <= 7 else 35, ha="center" if len(labels) <= 7 else "right")
        ax.yaxis.set_major_formatter(fmt)
        ax.grid(axis="y", color="#E2E8F0")
        ax.set_axisbelow(True)
    if kind != "pie" and (n > 1 or any(se["name"] for se in series)):
        ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, 1.02), ncol=min(n, 4))
    if s["title"]:
        fig.suptitle(s["title"] + (f"  ({unit})" if unit and kind != "pie" else ""), x=0.02, ha="left", fontsize=16, fontweight="bold", color="#0F172A")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()
