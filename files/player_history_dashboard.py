"""
Player History Dashboard — Ducks on the Pond Dynasty League
============================================================

Generates 6 charts + an HTML report from the latest Fantrax tracker run.

Usage:
    python player_history_dashboard.py
    python player_history_dashboard.py --data-root fantrax_data --output-dir player_history_output
    python player_history_dashboard.py --top-n 15
"""

from __future__ import annotations

import argparse
import base64
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

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

ACQ_COLORS = {
    "KEPT": "#4e9af1",
    "CLAIMED": "#f4a261",
    "TRADED": "#e76f51",
    "DRAFTED": "#2a9d8f",
}

STATUS_COLORS = {
    "ACTIVE": "#2a9d8f",
    "INJURED_RESERVE": "#e63946",
    "MINORS": "#457b9d",
    "RESERVE": "#f4a261",
}

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


def resolve_owner(team_name: str, team_to_owner: Dict[str, str],
                  owner_real_name_col: Optional[str] = None) -> str:
    if owner_real_name_col:
        return owner_real_name_col
    return team_to_owner.get(normalize_quotes(str(team_name)), "Unknown")


def save_png(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.name}")


# =============================================================================
# ANALYTICS FUNCTIONS
# =============================================================================

def compute_player_team_counts(journeys_df: pd.DataFrame) -> pd.DataFrame:
    """Count distinct teams and total stints per player."""
    grouped = journeys_df.groupby("player_name").agg(
        distinct_teams=("team_name", "nunique"),
        total_stints=("team_name", "count"),
    ).reset_index()
    return grouped.sort_values("distinct_teams", ascending=False).reset_index(drop=True)


def compute_owner_player_throughput(
    journeys_df: pd.DataFrame, team_to_owner: Dict[str, str]
) -> pd.DataFrame:
    """Count unique players ever rostered per owner."""
    df = journeys_df.copy()
    df["_owner"] = df.apply(
        lambda r: resolve_owner(r["team_name"], team_to_owner,
                                r.get("owner_real_name")),
        axis=1
    )
    grouped = df.groupby("_owner")["player_name"].nunique().reset_index()
    grouped.columns = ["owner", "unique_players"]
    return grouped.sort_values("unique_players", ascending=False).reset_index(drop=True)


def compute_player_tenure_stats(journeys_df: pd.DataFrame) -> pd.DataFrame:
    """Compute tenure in days for completed ownership stints."""
    df = journeys_df.dropna(subset=["end_date"]).copy()

    def parse_date(d):
        if not isinstance(d, str):
            return pd.NaT
        for fmt in ("%b %d %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return pd.to_datetime(d, format=fmt)
            except Exception:
                pass
        try:
            return pd.to_datetime(d)
        except Exception:
            return pd.NaT

    df["_start"] = df["start_date"].apply(parse_date)
    df["_end"] = df["end_date"].apply(parse_date)
    df["tenure_days"] = (df["_end"] - df["_start"]).dt.days
    df = df[df["tenure_days"] >= 0]
    return df[["player_name", "team_name", "owner_real_name",
               "acquisition_type", "tenure_days"]].reset_index(drop=True)


def build_player_ownership_network(
    journeys_df: pd.DataFrame,
    team_to_owner: Dict[str, str],
    min_players: int = 3,
) -> nx.DiGraph:
    """Build directed graph of player movement between owners."""
    df = journeys_df.copy()
    df["_owner"] = df.apply(
        lambda r: resolve_owner(r["team_name"], team_to_owner,
                                r.get("owner_real_name")),
        axis=1
    )

    def parse_date(d):
        if not isinstance(d, str):
            return pd.NaT
        for fmt in ("%b %d %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return pd.to_datetime(d, format=fmt)
            except Exception:
                pass
        try:
            return pd.to_datetime(d)
        except Exception:
            return pd.NaT

    df["_start_dt"] = df["start_date"].apply(parse_date)
    df = df.dropna(subset=["_start_dt"])
    df = df.sort_values(["player_id", "_start_dt"])

    edge_counts: Dict[tuple, int] = defaultdict(int)
    for player_id, group in df.groupby("player_id"):
        owners_seq = group["_owner"].tolist()
        for i in range(len(owners_seq) - 1):
            src = owners_seq[i]
            dst = owners_seq[i + 1]
            if src != dst and src != "Unknown" and dst != "Unknown":
                edge_counts[(src, dst)] += 1

    G = nx.DiGraph()
    for (src, dst), weight in edge_counts.items():
        if weight >= min_players:
            G.add_edge(src, dst, weight=weight)
    return G


# =============================================================================
# CHART 1: Most Traveled Players
# =============================================================================

def plot_most_traveled_players(
    player_team_counts_df: pd.DataFrame,
    top_n: int,
    output_path: Path,
) -> None:
    df = player_team_counts_df.head(top_n).sort_values("distinct_teams", ascending=True)

    fig, ax = plt.subplots(figsize=(11, max(6, top_n * 0.55)))
    y_pos = range(len(df))

    bars = ax.barh(list(y_pos), df["distinct_teams"], color="#e07b39",
                   edgecolor="white", label="Distinct Teams", zorder=3)
    ax.scatter(df["total_stints"], list(y_pos), color="#1a1a2e",
               zorder=5, s=60, marker="D", label="Total Stints (incl. re-acquisitions)")

    for bar, stints in zip(bars, df["total_stints"]):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                str(int(bar.get_width())), va="center", ha="left", fontsize=9,
                color="#e07b39", fontweight="bold")

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(df["player_name"], fontsize=9)
    ax.set_xlabel("Count")
    ax.set_title(f"Top {top_n} Most Traveled Players (Distinct Teams Rostered)",
                 fontsize=13, fontweight="bold", pad=12)
    ax.legend(loc="lower right")
    ax.set_xlim(0, max(df["total_stints"].max(), df["distinct_teams"].max()) * 1.18)
    ax.grid(axis="x", alpha=0.4)
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 2: Owner Player Throughput
# =============================================================================

def plot_owner_player_throughput(
    owner_throughput_df: pd.DataFrame,
    output_path: Path,
) -> None:
    df = owner_throughput_df.sort_values("unique_players", ascending=True)

    palette = sns.color_palette("rocket_r", len(df))
    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.barh(df["owner"], df["unique_players"],
                   color=palette, edgecolor="white")

    for bar in bars:
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                str(int(bar.get_width())), va="center", ha="left", fontsize=10)

    ax.set_xlabel("Unique Players Ever Rostered")
    ax.set_title("Roster Turnover — Unique Players Ever Rostered Per Owner",
                 fontsize=13, fontweight="bold", pad=12)
    ax.text(0.5, -0.1,
            "Counts all distinct players ever on roster including short-term waiver claims",
            transform=ax.transAxes, ha="center", fontsize=8.5, color="#666")
    ax.set_xlim(0, df["unique_players"].max() * 1.15)
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 3: Player Ownership Flow Network
# =============================================================================

def plot_player_ownership_network(G: nx.DiGraph, output_path: Path) -> None:
    if G.number_of_nodes() == 0:
        print("  Skipping ownership network — no edges above threshold.")
        return

    # Node sizes by total in+out weight
    node_vol = {n: 0 for n in G.nodes()}
    for u, v, d in G.edges(data=True):
        node_vol[u] = node_vol.get(u, 0) + d["weight"]
        node_vol[v] = node_vol.get(v, 0) + d["weight"]

    node_sizes = [node_vol.get(n, 1) * 120 + 300 for n in G.nodes()]
    edge_widths = [G[u][v]["weight"] * 0.5 for u, v in G.edges()]

    cmap = plt.cm.get_cmap("tab20", len(G.nodes()))
    node_colors = [cmap(i) for i, _ in enumerate(G.nodes())]

    pos = nx.spring_layout(G, seed=42, k=3.0, weight="weight")

    fig, ax = plt.subplots(figsize=(15, 12))
    ax.set_facecolor("#f8f9fa")

    nx.draw_networkx_nodes(G, pos, node_size=node_sizes, node_color=node_colors,
                           alpha=0.9, ax=ax)
    nx.draw_networkx_edges(G, pos, width=edge_widths, alpha=0.55,
                           edge_color="#666", ax=ax,
                           arrows=True, arrowstyle="-|>", arrowsize=18,
                           connectionstyle="arc3,rad=0.08")
    nx.draw_networkx_labels(G, pos, font_size=8.5, font_weight="bold", ax=ax)

    edge_labels = {(u, v): G[u][v]["weight"] for u, v in G.edges()
                   if G[u][v]["weight"] >= 8}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels,
                                 font_size=7.5, ax=ax)

    ax.set_title("Player Ownership Flow Network (Owner → Owner)",
                 fontsize=14, fontweight="bold", pad=14)
    ax.text(0.5, -0.02,
            "Arrow direction = player movement from one owner to the next. "
            "Edge thickness = number of distinct players transferred.",
            transform=ax.transAxes, ha="center", fontsize=8.5, color="#555")
    ax.axis("off")
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 4: Acquisition Type Breakdown per Owner
# =============================================================================

def plot_acquisition_type_breakdown(
    journeys_df: pd.DataFrame,
    team_to_owner: Dict[str, str],
    output_path: Path,
) -> None:
    df = journeys_df.copy()
    df["_owner"] = df.apply(
        lambda r: resolve_owner(r["team_name"], team_to_owner,
                                r.get("owner_real_name")),
        axis=1
    )
    df = df[df["_owner"] != "Unknown"]
    pivot = df.groupby(["_owner", "acquisition_type"]).size().unstack(fill_value=0)

    acq_order = [c for c in ["KEPT", "CLAIMED", "TRADED", "DRAFTED"] if c in pivot.columns]
    pivot = pivot[acq_order]
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=True).index]

    colors = [ACQ_COLORS.get(c, "#aaa") for c in acq_order]

    fig, ax = plt.subplots(figsize=(11, 8))
    pivot.plot(kind="barh", stacked=True, ax=ax, color=colors, edgecolor="white", width=0.7)
    ax.set_xlabel("Roster Acquisitions")
    ax.set_title("How Each Owner Builds Their Roster (By Acquisition Type)",
                 fontsize=13, fontweight="bold", pad=12)
    ax.legend(title="Acquisition Type", bbox_to_anchor=(1.01, 1), loc="upper left")
    fig.tight_layout()
    save_png(fig, output_path)


# =============================================================================
# CHART 5: Current Roster Composition (Pie Grid)
# =============================================================================

def plot_current_roster_composition(rosters_df: pd.DataFrame, output_path: Path) -> None:
    teams = rosters_df["team_name"].unique()
    n_teams = len(teams)
    ncols = 4
    nrows = (n_teams + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(16, nrows * 3.5))
    axes_flat = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for i, team in enumerate(sorted(teams)):
        ax = axes_flat[i]
        team_df = rosters_df[rosters_df["team_name"] == team]
        counts = team_df["roster_status"].value_counts()
        labels = counts.index.tolist()
        colors = [STATUS_COLORS.get(l, "#ccc") for l in labels]
        ax.pie(counts.values, labels=None, colors=colors, autopct="%1.0f%%",
               startangle=90, pctdistance=0.75,
               wedgeprops={"edgecolor": "white", "linewidth": 1.2})
        short_name = team if len(team) <= 18 else team[:16] + "…"
        ax.set_title(short_name, fontsize=8.5, fontweight="bold")

    # Hide empty subplots
    for j in range(n_teams, len(axes_flat)):
        axes_flat[j].set_visible(False)

    # Shared legend
    patches = [mpatches.Patch(color=c, label=s) for s, c in STATUS_COLORS.items()]
    fig.legend(handles=patches, loc="lower center", ncol=4,
               bbox_to_anchor=(0.5, -0.01), frameon=False, fontsize=9)
    fig.suptitle("Current Roster Composition by Team (2026 Season)",
                 fontsize=14, fontweight="bold", y=1.01)
    fig.tight_layout(pad=2.0)
    save_png(fig, output_path)


# =============================================================================
# CHART 6: Player Tenure Distribution
# =============================================================================

def plot_player_tenure_distribution(tenure_df: pd.DataFrame, output_path: Path) -> None:
    if tenure_df.empty:
        print("  Skipping tenure distribution — no completed stints.")
        return

    df = tenure_df[tenure_df["tenure_days"] > 0]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    # Left: Histogram + KDE
    sns.histplot(data=df, x="tenure_days", bins=40, kde=True, color="#457b9d", ax=ax1)
    median_d = df["tenure_days"].median()
    mean_d = df["tenure_days"].mean()
    ax1.axvline(median_d, color="#e63946", linestyle="--", linewidth=1.5,
                label=f"Median: {median_d:.0f}d")
    ax1.axvline(mean_d, color="#f4a261", linestyle="--", linewidth=1.5,
                label=f"Mean: {mean_d:.0f}d")
    ax1.set_xlabel("Days on Roster")
    ax1.set_ylabel("Number of Stints")
    ax1.set_title("Distribution of Player Tenure (Days on Roster)",
                  fontsize=12, fontweight="bold")
    ax1.legend()

    # Right: Box plot by acquisition type
    acq_order = [t for t in ["DRAFTED", "CLAIMED", "TRADED", "KEPT"]
                 if t in df["acquisition_type"].unique()]
    palette = [ACQ_COLORS.get(t, "#aaa") for t in acq_order]
    sns.boxplot(data=df, x="acquisition_type", y="tenure_days",
                order=acq_order, palette=palette, ax=ax2,
                flierprops={"marker": ".", "markersize": 4})
    ax2.set_xlabel("How Player Was Acquired")
    ax2.set_ylabel("Days on Roster")
    ax2.set_title("Tenure by How Player Was Acquired",
                  fontsize=12, fontweight="bold")

    fig.suptitle("Player Tenure Analysis", fontsize=14, fontweight="bold", y=1.01)
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
        ("Most Traveled Players",
         "Top players by number of distinct teams they've been on. "
         "The diamond markers show total stints, including re-acquisitions by the same team."),
        ("Owner Player Throughput",
         "How many unique players have ever appeared on each owner's roster across all seasons. "
         "High counts reflect active waiver/trade activity."),
        ("Player Ownership Flow Network",
         "Directed graph showing how players move between owners. "
         "Arrow direction = player movement. Edge thickness = number of distinct players transferred. "
         "Only edges with 3+ player transfers shown."),
        ("Roster Building Style by Owner",
         "Stacked bar showing how each owner acquires their players — "
         "through keeping, claiming off waivers, trading, or drafting."),
        ("Current Roster Composition",
         "Pie charts showing the breakdown of roster slots by status for each team in 2026."),
        ("Player Tenure Distribution",
         "Left: distribution of how long players stay on any given roster (completed stints only). "
         "Right: tenure broken down by how the player was acquired."),
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
<title>Ducks on the Pond — Player History Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f0f2f5; margin: 0; padding: 20px; color: #222; }}
  h1 {{ text-align: center; color: #1a1a2e; margin-bottom: 4px; }}
  .subtitle {{ text-align: center; color: #666; margin-bottom: 24px; font-size: 0.95rem; }}
  .summary {{ display: flex; flex-wrap: wrap; gap: 12px; justify-content: center;
              background: #fff; border-radius: 12px; padding: 20px; margin-bottom: 30px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .stat {{ display: flex; flex-direction: column; align-items: center;
           background: #f8f9ff; border-radius: 8px; padding: 12px 20px; min-width: 160px; }}
  .stat .label {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat .value {{ font-size: 1.4rem; font-weight: 700; color: #e07b39; }}
  section {{ background: #fff; border-radius: 12px; padding: 24px; margin-bottom: 24px;
             box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  section h2 {{ margin-top: 0; color: #1a1a2e; font-size: 1.2rem; }}
  p.desc {{ color: #555; font-size: 0.9rem; margin-bottom: 16px; }}
  img {{ max-width: 100%; border-radius: 6px; display: block; margin: auto; }}
</style>
</head>
<body>
<h1>🦆 Ducks on the Pond Dynasty — Player History Dashboard</h1>
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
    p = argparse.ArgumentParser(description="Fantrax Player History Dashboard")
    p.add_argument("--data-root", default="fantrax_data")
    p.add_argument("--output-dir", default="player_history_output")
    p.add_argument("--top-n", type=int, default=10,
                   help="Number of players in top-N charts")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = load_data(args.data_root)
    journeys = data["journeys"]
    rosters = data["rosters"]
    owner_mapping = data["owner_mapping"]

    team_to_owner = build_team_to_owner_lookup(owner_mapping)

    # Analytics
    player_team_counts = compute_player_team_counts(journeys)
    owner_throughput = compute_owner_player_throughput(journeys, team_to_owner)
    tenure_df = compute_player_tenure_stats(journeys)
    flow_network = build_player_ownership_network(journeys, team_to_owner, min_players=3)

    # Summary stats
    top_traveler = player_team_counts.iloc[0] if len(player_team_counts) else None
    top_throughput = owner_throughput.iloc[0] if len(owner_throughput) else None
    total_unique_players = journeys["player_name"].nunique()
    med_tenure = int(tenure_df["tenure_days"].median()) if not tenure_df.empty else "N/A"

    summary_stats = {
        "Total Unique Players": total_unique_players,
        "Most Traveled Player": (
            f"{top_traveler['player_name']} ({int(top_traveler['distinct_teams'])} teams)"
            if top_traveler is not None else "N/A"
        ),
        "Highest Roster Turnover": (
            f"{top_throughput['owner']} ({int(top_throughput['unique_players'])} players)"
            if top_throughput is not None else "N/A"
        ),
        "Median Player Tenure": f"{med_tenure} days",
    }

    chart_paths = []

    print("\nGenerating chart 1/6: most_traveled_players...")
    p1 = out_dir / "01_most_traveled_players.png"
    plot_most_traveled_players(player_team_counts, args.top_n, p1)
    chart_paths.append(p1)

    print("Generating chart 2/6: owner_player_throughput...")
    p2 = out_dir / "02_owner_player_throughput.png"
    plot_owner_player_throughput(owner_throughput, p2)
    chart_paths.append(p2)

    print("Generating chart 3/6: player_ownership_network...")
    p3 = out_dir / "03_player_ownership_network.png"
    plot_player_ownership_network(flow_network, p3)
    chart_paths.append(p3)

    print("Generating chart 4/6: acquisition_type_breakdown...")
    p4 = out_dir / "04_acquisition_type_breakdown.png"
    plot_acquisition_type_breakdown(journeys, team_to_owner, p4)
    chart_paths.append(p4)

    print("Generating chart 5/6: roster_composition_current...")
    p5 = out_dir / "05_roster_composition_current.png"
    plot_current_roster_composition(rosters, p5)
    chart_paths.append(p5)

    print("Generating chart 6/6: player_tenure_distribution...")
    p6 = out_dir / "06_player_tenure_distribution.png"
    plot_player_tenure_distribution(tenure_df, p6)
    chart_paths.append(p6)

    print("\nGenerating HTML report...")
    generate_html_report(chart_paths, out_dir / "player_history_dashboard.html", summary_stats)

    print(f"\n✓ Player history dashboard complete → {out_dir}/")
    print(f"  Open: {out_dir}/player_history_dashboard.html")


if __name__ == "__main__":
    main()
