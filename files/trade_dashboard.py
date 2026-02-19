"""
Trade Dashboard — Ducks on the Pond Dynasty League
===================================================

Generates 7 charts + an HTML report from the latest Fantrax tracker run.

Usage:
    python trade_dashboard.py
    python trade_dashboard.py --data-root fantrax_data --output-dir trade_dashboard_output
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import seaborn as sns
    import networkx as nx
except ImportError as e:
    sys.exit(
        f"Missing visualization library: {e}\n"
        "Install with: pip install matplotlib seaborn networkx"
    )

# =============================================================================
# CONSTANTS
# =============================================================================

COLORS = {
    "KEPT": "#4e9af1",
    "CLAIMED": "#f4a261",
    "TRADED": "#e76f51",
    "DRAFTED": "#2a9d8f",
}

MONTH_ORDER = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

sns.set_theme(style="whitegrid", font_scale=1.1)


# =============================================================================
# DATA LOADING
# =============================================================================

def find_latest_run(data_root: str) -> Path:
    root = Path(data_root)
    latest = root / "latest"
    if latest.exists() or latest.is_symlink():
        target = latest.resolve()
        return target / "output"
    runs = sorted(d for d in root.iterdir() if d.is_dir() and d.name.startswith("run_"))
    if not runs:
        sys.exit(f"No run directories found in {data_root}")
    return runs[-1] / "output"


def load_data(data_root: str) -> Dict[str, pd.DataFrame]:
    out_dir = find_latest_run(data_root)
    print(f"Loading data from: {out_dir}")
    return {
        "transactions": pd.read_csv(out_dir / "transaction_history.csv"),
        "teams": pd.read_csv(out_dir / "teams.csv"),
        "rosters": pd.read_csv(out_dir / "current_rosters.csv"),
        "journeys": pd.read_csv(out_dir / "player_journeys.csv"),
        "owner_mapping": pd.read_csv(out_dir / "owner_team_mapping.csv"),
    }


# =============================================================================
# HELPERS
# =============================================================================

def normalize_quotes(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return text.replace("\u2018", "'").replace("\u2019", "'")


def build_team_to_owner_lookup(owner_mapping_df: pd.DataFrame) -> Dict[str, str]:
    lookup = {}
    for _, row in owner_mapping_df.iterrows():
        key = normalize_quotes(str(row["team_name"]))
        lookup[key] = str(row["real_name"])
    return lookup


def extract_trade_partners(details: str, all_team_names_sorted: List[str]) -> Set[str]:
    """Return set of team names that participated in this trade event."""
    details_norm = normalize_quotes(details)
    found = set()
    if "trades away" in details_norm:
        for team in all_team_names_sorted:
            if re.search(re.escape(team) + r"\s+trades away", details_norm):
                found.add(team)
    else:
        for team in all_team_names_sorted:
            if re.search(re.escape(team) + r"\s+to\s+", details_norm):
                found.add(team)
    return found


def build_trade_events(transactions_df: pd.DataFrame) -> pd.DataFrame:
    trades = transactions_df[transactions_df["action_type"] == "TRADED"].copy()
    trades["details"] = trades["details"].fillna("").apply(normalize_quotes)
    unique = trades.drop_duplicates(subset=["date", "details"])

    # Parse year/month from date strings like "Sep 29 2025"
    def parse_year(d):
        try:
            return pd.to_datetime(d, format="%b %d %Y").year
        except Exception:
            try:
                return pd.to_datetime(d).year
            except Exception:
                return None

    def parse_month(d):
        try:
            return pd.to_datetime(d, format="%b %d %Y").month
        except Exception:
            try:
                return pd.to_datetime(d).month
            except Exception:
                return None

    unique = unique.copy()
    unique["year"] = unique["date"].apply(parse_year)
    unique["month_num"] = unique["date"].apply(parse_month)
    unique["month"] = unique["month_num"].apply(
        lambda m: MONTH_ORDER[m - 1] if pd.notna(m) else None
    )
    return unique.reset_index(drop=True)


def resolve_partners_to_owners(
    partner_teams: Set[str],
    team_to_owner: Dict[str, str]
) -> Set[str]:
    owners = set()
    for t in partner_teams:
        owner = team_to_owner.get(normalize_quotes(t))
        if owner:
            owners.add(owner)
    return owners


def build_trade_pairs_df(
    trade_events_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
) -> pd.DataFrame:
    pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)

    for _, row in trade_events_df.iterrows():
        teams = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        if len(owners) < 2:
            continue
        for a, b in combinations(sorted(owners), 2):
            pair_counts[(a, b)] += 1

    records = [{"party_a": a, "party_b": b, "count": c}
               for (a, b), c in pair_counts.items()]
    return pd.DataFrame(records)


def save_png(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.name}")


# =============================================================================
# CHART 1: Trades Per Owner
# =============================================================================

def plot_trades_per_owner(
    trade_events_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
    output_path: Path,
) -> None:
    owner_counts: Dict[str, int] = defaultdict(int)
    for _, row in trade_events_df.iterrows():
        teams = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        for o in owners:
            owner_counts[o] += 1

    df = pd.DataFrame(list(owner_counts.items()), columns=["owner", "trades"]).sort_values(
        "trades", ascending=True
    )

    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.barh(df["owner"], df["trades"], color="#4472C4", edgecolor="white")
    for bar in bars:
        ax.text(
            bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
            str(int(bar.get_width())), va="center", ha="left", fontsize=10
        )
    ax.set_xlabel("Number of Trade Events")
    ax.set_title("Trade Participation by Owner (All Seasons)", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlim(0, df["trades"].max() * 1.15)
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 2: Trade Partner Matrix
# =============================================================================

def plot_trade_partner_matrix(
    trade_pairs_df: pd.DataFrame,
    output_path: Path,
) -> None:
    if trade_pairs_df.empty:
        print("  Skipping trade partner matrix — no pair data.")
        return

    owners = sorted(set(trade_pairs_df["party_a"]) | set(trade_pairs_df["party_b"]))
    matrix = pd.DataFrame(0, index=owners, columns=owners)
    for _, row in trade_pairs_df.iterrows():
        matrix.loc[row["party_a"], row["party_b"]] = row["count"]
        matrix.loc[row["party_b"], row["party_a"]] = row["count"]

    import numpy as np
    mask = np.triu(np.ones_like(matrix, dtype=bool))

    fig, ax = plt.subplots(figsize=(14, 12))
    sns.heatmap(
        matrix, mask=mask, annot=True, fmt="d", cmap="YlOrRd",
        linewidths=0.5, linecolor="#ddd", ax=ax,
        annot_kws={"size": 9},
        cbar_kws={"label": "Trade Count"},
    )
    ax.set_title("Trade Partner Matrix — How Often Each Pair Has Traded",
                 fontsize=13, fontweight="bold", pad=14)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=40, ha="right", fontsize=9)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=9)
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 3: Trade Network
# =============================================================================

def plot_trade_network(
    trade_pairs_df: pd.DataFrame,
    output_path: Path,
) -> None:
    if trade_pairs_df.empty:
        print("  Skipping trade network — no pair data.")
        return

    G = nx.Graph()
    for _, row in trade_pairs_df.iterrows():
        G.add_edge(row["party_a"], row["party_b"], weight=row["count"])

    total_trades = defaultdict(int)
    for _, row in trade_pairs_df.iterrows():
        total_trades[row["party_a"]] += row["count"]
        total_trades[row["party_b"]] += row["count"]

    node_sizes = [total_trades.get(n, 1) * 180 for n in G.nodes()]
    edge_widths = [G[u][v]["weight"] * 0.6 for u, v in G.edges()]

    cmap = plt.cm.get_cmap("tab20", len(G.nodes()))
    node_colors = [cmap(i) for i, _ in enumerate(G.nodes())]

    pos = nx.spring_layout(G, seed=42, k=2.8, weight="weight")

    fig, ax = plt.subplots(figsize=(16, 12))
    ax.set_facecolor("#f8f9fa")

    nx.draw_networkx_nodes(G, pos, node_size=node_sizes, node_color=node_colors,
                           alpha=0.9, ax=ax)
    nx.draw_networkx_edges(G, pos, width=edge_widths, alpha=0.55,
                           edge_color="#555", ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=8.5, font_weight="bold", ax=ax)

    # Edge labels for significant edges
    edge_labels = {(u, v): G[u][v]["weight"] for u, v in G.edges()
                   if G[u][v]["weight"] >= 5}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels,
                                 font_size=7.5, ax=ax)

    ax.set_title("Trade Network — Owner-to-Owner Trade Relationships",
                 fontsize=14, fontweight="bold", pad=14)
    ax.axis("off")
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 4: Trade Activity Timeline (Monthly)
# =============================================================================

def plot_trade_activity_timeline(trade_events_df: pd.DataFrame, output_path: Path) -> None:
    df = trade_events_df.dropna(subset=["year", "month_num"]).copy()
    df["year_month"] = pd.to_datetime(
        df["year"].astype(int).astype(str) + "-" + df["month_num"].astype(int).astype(str).str.zfill(2)
    )
    monthly = df.groupby("year_month").size().reset_index(name="count")
    monthly = monthly.sort_values("year_month")

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(monthly["year_month"], monthly["count"], color="#4472C4", linewidth=2)
    ax.fill_between(monthly["year_month"], monthly["count"],
                    alpha=0.25, color="#4472C4")
    ax.set_xlabel("Month")
    ax.set_ylabel("Trade Events")
    ax.set_title("Trade Activity Over Time (Monthly)", fontsize=14,
                 fontweight="bold", pad=12)
    ax.xaxis.set_major_formatter(
        matplotlib.dates.DateFormatter("%b '%y")
    )
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 5: Trade Activity Heatmap (Year × Month)
# =============================================================================

def plot_trade_activity_heatmap(trade_events_df: pd.DataFrame, output_path: Path) -> None:
    df = trade_events_df.dropna(subset=["year", "month_num"]).copy()
    df["year"] = df["year"].astype(int)
    df["month_num"] = df["month_num"].astype(int)
    pivot = df.groupby(["year", "month_num"]).size().unstack(fill_value=0)
    pivot.columns = [MONTH_ORDER[c - 1] for c in pivot.columns]
    # Ensure all months present
    for m in MONTH_ORDER:
        if m not in pivot.columns:
            pivot[m] = 0
    pivot = pivot[MONTH_ORDER]

    fig, ax = plt.subplots(figsize=(14, 5))
    sns.heatmap(pivot, annot=True, fmt="d", cmap="YlOrRd",
                linewidths=0.5, linecolor="#ddd", ax=ax,
                cbar_kws={"label": "Trade Events"})
    ax.set_title("Trade Activity Heatmap by Year and Month",
                 fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("")
    ax.set_ylabel("Season")
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 6: 2-Team vs 3-Team Trade Breakdown
# =============================================================================

def plot_multi_team_trade_breakdown(
    trade_events_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
    output_path: Path,
) -> None:
    records = []
    for _, row in trade_events_df.iterrows():
        if pd.isna(row.get("year")):
            continue
        teams = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        n = len(owners)
        records.append({"year": int(row["year"]), "parties": n})

    if not records:
        print("  Skipping multi-team breakdown — no data.")
        return

    df = pd.DataFrame(records)
    df["type"] = df["parties"].apply(lambda n: "3-Team" if n >= 3 else "2-Team")
    pivot = df.groupby(["year", "type"]).size().unstack(fill_value=0)
    for col in ["2-Team", "3-Team"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot = pivot[["2-Team", "3-Team"]]

    fig, ax = plt.subplots(figsize=(10, 6))
    pivot.plot(kind="bar", stacked=True, ax=ax,
               color=["#4472C4", "#ED7D31"], edgecolor="white", width=0.6)
    ax.set_xlabel("Season")
    ax.set_ylabel("Trade Events")
    ax.set_title("2-Team vs 3-Team Trades Per Season",
                 fontsize=14, fontweight="bold", pad=12)
    ax.legend(title="Trade Type")
    plt.setp(ax.get_xticklabels(), rotation=0)
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 7: Trade Volume by Season (Per Owner)
# =============================================================================

def plot_trade_volume_by_season(
    trade_events_df: pd.DataFrame,
    all_team_names_sorted: List[str],
    team_to_owner: Dict[str, str],
    output_path: Path,
) -> None:
    records = []
    for _, row in trade_events_df.iterrows():
        if pd.isna(row.get("year")):
            continue
        teams = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        for o in owners:
            records.append({"owner": o, "year": int(row["year"])})

    if not records:
        print("  Skipping trade volume by season — no data.")
        return

    df = pd.DataFrame(records)
    pivot = df.groupby(["owner", "year"]).size().unstack(fill_value=0)
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]

    fig, ax = plt.subplots(figsize=(16, 7))
    pivot.plot(kind="bar", ax=ax, colormap="tab10", edgecolor="white", width=0.75)
    ax.set_xlabel("Owner")
    ax.set_ylabel("Trade Events")
    ax.set_title("Trade Volume Per Owner by Season",
                 fontsize=14, fontweight="bold", pad=12)
    ax.legend(title="Season", bbox_to_anchor=(1.01, 1), loc="upper left")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# HTML REPORT
# =============================================================================

def _img_to_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def generate_html_report(
    chart_paths: List[Path],
    output_path: Path,
    summary_stats: Dict,
) -> None:
    chart_info = [
        ("Trade Participation by Owner",
         "Total trade events each owner participated in across all seasons."),
        ("Trade Partner Matrix",
         "How many times each pair of owners has traded with each other (lower triangle)."),
        ("Trade Network",
         "Visual graph of owner trade relationships. Node size = total trade volume. "
         "Edge thickness = number of trades between that pair. Labels appear on edges with 5+ trades."),
        ("Trade Activity Timeline",
         "Monthly trade volume across all seasons. Spikes often align with trade deadlines and offseasons."),
        ("Trade Activity Heatmap",
         "Year × Month heatmap of trade events. Darker = more trades."),
        ("2-Team vs 3-Team Trades Per Season",
         "Breakdown of trade complexity by season."),
        ("Trade Volume Per Owner by Season",
         "How each owner's trade activity has changed year over year."),
    ]

    stats_html = "".join(
        f"<div class='stat'><span class='label'>{k}</span><span class='value'>{v}</span></div>"
        for k, v in summary_stats.items()
    )

    sections = []
    for i, path in enumerate(chart_paths):
        if not path.exists():
            continue
        title, desc = chart_info[i] if i < len(chart_info) else (path.stem, "")
        b64 = _img_to_b64(path)
        sections.append(f"""
        <section>
            <h2>{title}</h2>
            <p class="desc">{desc}</p>
            <img src="data:image/png;base64,{b64}" alt="{title}" />
        </section>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Ducks on the Pond — Trade Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f0f2f5; margin: 0; padding: 20px; color: #222; }}
  h1 {{ text-align: center; color: #1a1a2e; margin-bottom: 4px; }}
  .subtitle {{ text-align: center; color: #666; margin-bottom: 24px; font-size: 0.95rem; }}
  .summary {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: center;
              background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 30px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .stat {{ display: flex; flex-direction: column; align-items: center;
           background: #f8f9ff; border-radius: 8px; padding: 12px 20px; min-width: 140px; }}
  .stat .label {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat .value {{ font-size: 1.4rem; font-weight: 700; color: #4472C4; }}
  section {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px;
             box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  section h2 {{ margin-top: 0; color: #1a1a2e; font-size: 1.2rem; }}
  p.desc {{ color: #555; font-size: 0.9rem; margin-bottom: 16px; }}
  img {{ max-width: 100%; border-radius: 6px; display: block; margin: auto; }}
</style>
</head>
<body>
<h1>🦆 Ducks on the Pond Dynasty — Trade Dashboard</h1>
<p class="subtitle">All seasons tracked • Grouped by owner</p>
<div class="summary">{stats_html}</div>
{"".join(sections)}
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"  Saved: {output_path.name}")


# =============================================================================
# MAIN
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fantrax Trade Dashboard")
    p.add_argument("--data-root", default="fantrax_data", help="Path to fantrax_data folder")
    p.add_argument("--output-dir", default="trade_dashboard_output", help="Output folder for charts")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    data = load_data(args.data_root)
    txns = data["transactions"]
    owner_mapping = data["owner_mapping"]

    # Build lookups
    team_to_owner = build_team_to_owner_lookup(owner_mapping)
    all_team_names_sorted = sorted(
        set(normalize_quotes(t) for t in txns["team_name"].dropna().unique()),
        key=len, reverse=True
    )

    # Build trade events (deduplicated)
    trade_events = build_trade_events(txns)
    print(f"Unique trade events: {len(trade_events)}")

    # Build trade pairs
    trade_pairs = build_trade_pairs_df(trade_events, all_team_names_sorted, team_to_owner)

    # Summary stats
    owner_counts: Dict[str, int] = defaultdict(int)
    for _, row in trade_events.iterrows():
        teams = extract_trade_partners(row["details"], all_team_names_sorted)
        owners = resolve_partners_to_owners(teams, team_to_owner)
        for o in owners:
            owner_counts[o] += 1

    top_trader = max(owner_counts, key=owner_counts.get) if owner_counts else "N/A"
    top_pair = ("N/A", "N/A", 0)
    if not trade_pairs.empty:
        idx = trade_pairs["count"].idxmax()
        row = trade_pairs.loc[idx]
        top_pair = (row["party_a"], row["party_b"], int(row["count"]))

    summary_stats = {
        "Total Trade Events": len(trade_events),
        "Most Active Trader": f"{top_trader} ({owner_counts.get(top_trader, 0)})",
        "Top Trade Pair": f"{top_pair[0]} ↔ {top_pair[1]} ({top_pair[2]})",
        "3-Way Trades": sum(
            1 for _, r in trade_events.iterrows()
            if len(resolve_partners_to_owners(
                extract_trade_partners(r["details"], all_team_names_sorted), team_to_owner
            )) >= 3
        ),
    }

    # Generate charts
    chart_paths = []

    print("\nGenerating chart 1/7: trades_per_owner...")
    p1 = out_dir / "01_trades_per_owner.png"
    plot_trades_per_owner(trade_events, all_team_names_sorted, team_to_owner, p1)
    chart_paths.append(p1)

    print("Generating chart 2/7: trade_partner_matrix...")
    p2 = out_dir / "02_trade_partner_matrix.png"
    plot_trade_partner_matrix(trade_pairs, p2)
    chart_paths.append(p2)

    print("Generating chart 3/7: trade_network...")
    p3 = out_dir / "03_trade_network.png"
    plot_trade_network(trade_pairs, p3)
    chart_paths.append(p3)

    print("Generating chart 4/7: trade_activity_timeline...")
    p4 = out_dir / "04_trade_activity_timeline.png"
    plot_trade_activity_timeline(trade_events, p4)
    chart_paths.append(p4)

    print("Generating chart 5/7: trade_activity_heatmap...")
    p5 = out_dir / "05_trade_activity_heatmap.png"
    plot_trade_activity_heatmap(trade_events, p5)
    chart_paths.append(p5)

    print("Generating chart 6/7: multi_team_trade_breakdown...")
    p6 = out_dir / "06_multi_team_trade_breakdown.png"
    plot_multi_team_trade_breakdown(trade_events, all_team_names_sorted, team_to_owner, p6)
    chart_paths.append(p6)

    print("Generating chart 7/7: trade_volume_by_season...")
    p7 = out_dir / "07_trade_volume_by_season.png"
    plot_trade_volume_by_season(trade_events, all_team_names_sorted, team_to_owner, p7)
    chart_paths.append(p7)

    print("\nGenerating HTML report...")
    generate_html_report(chart_paths, out_dir / "trade_dashboard.html", summary_stats)

    print(f"\n✓ Trade dashboard complete → {out_dir}/")
    print(f"  Open: {out_dir}/trade_dashboard.html")


if __name__ == "__main__":
    main()
