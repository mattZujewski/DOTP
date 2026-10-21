"""Team renames verified against saved season-specific Fantrax team IDs."""
import json
from pathlib import Path

TEAM_ALIASES = json.loads(Path(__file__).with_name("team_aliases.json").read_text())["teams"]


def normalized_name(name):
    return name.replace("\u2019", "'").replace("\u2018", "'").lower().strip()


def owner_aliases():
    return {normalized_name(row["team_name"]): row for row in TEAM_ALIASES}
