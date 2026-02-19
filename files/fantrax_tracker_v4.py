"""
Fantrax Player Ownership Tracker v4
===================================

Improvements over v3:
- Config file support (config.yaml) - no more hardcoding secrets
- Fixed roster fetching using public API + fallback to internal
- Owner/team name mapping for your league's 6-year history
- Better error messages and auth validation
- Per-player caching to avoid re-fetching

Usage:
    # First time: copy config.yaml.example to config.yaml and fill in values
    cp config.yaml.example config.yaml
    
    # Then run:
    python fantrax_tracker_v4.py
    
    # Or override config with CLI args:
    python fantrax_tracker_v4.py --jsessionid "node0abc..."
    
    # Force refresh cached player data:
    python fantrax_tracker_v4.py --refresh
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import re
import sys
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# =============================================================================
# CONSTANTS
# =============================================================================

BASE_URL = "https://www.fantrax.com/fxea/general"
INTERNAL_API_URL = "https://www.fantrax.com/fxpa/req"

# =============================================================================
# OWNER / TEAM NAME MAPPING (Your league's 6-year history)
# =============================================================================

OWNERS = {
    "MattZujewski": {
        "real_name": "Matthew Zujewski",
        "teams": {
            2026: "Top Gunnar",
            2025: "Quentin Pasquantino",
            2024: "My Team is Better Than Reed's",
            2023: "The Juice is Loose",
            2022: "Purple Hayes",
            2021: "Jung Gunnars",
        }
    },
    "lpburns": {
        "real_name": "Liam Burns",
        "teams": {
            2026: "Boot & Raleigh",
            2025: "Boot & Raleigh",
            2024: "Everybody Loves Ramon",
            2023: "Soto's Johto League Champions",
            2022: "Sohto League Champions",
            2021: "Sohto League Champions",
        }
    },
    "sfgiant": {
        "real_name": "Jason Bartolini",
        "teams": {
            2026: "Gho-Strider",
            2025: "Gho-Strider",
            2024: "Waiting for Cespedes",
            2023: "Waiting for Cespedes",
            2022: "The Riley Reid's",
            2021: "The J-Rod Squad",
        }
    },
    "Jpapula": {
        "real_name": "Jordan Papula",
        "teams": {
            2026: "Mojo Dojo Casas House",
            2025: "Mojo Dojo Casas House",
            2024: "Bay of Puigs",
            2023: "Bay of Puigs",
            2022: "The Phamtom Menace",
            2021: "Attack of the Crons",
        }
    },
    "trentradding": {
        "real_name": "Trent Radding",
        "teams": {
            2026: "Partially Torked",
            2025: "A Few Jung Men",
            2024: "A Few Jung Men",
            2023: "Championship or Bust (2021)",
            2022: "Fully Torked",
            2021: "Turner Burners",
            2020: "Team CarmenCiardiello",
        }
    },
    "Jgchope": {
        "real_name": "Jose Garcia-Chope",
        "teams": {
            2026: "Rates & Carrolls",
            2025: "Rates & Carrolls",
            2024: "Shark(are)nado",
            2023: "Shark(are)nado",
            2022: "Shark(are)nado",
            2021: "The KamikOzzie's",
        }
    },
    "rheim": {
        "real_name": "Reed Heim",
        "teams": {
            2026: "Reed's Trading Post",
            2025: "Heimlich Maneuver",
            2024: "Lil' Tikes",
            2023: "Lil' Tikes",
            2022: "If You Give a Mouse a Mookie",
            2021: "Heimlich Maneuver",
        }
    },
    "owenhern": {
        "real_name": "Owen Hern",
        "teams": {
            2026: "The Juan-Binary Murderers' Row",
            2025: "The New Murderers' Row",
            2024: "DJ LeMachine",
            2023: "DJ LeMachine",
            2022: "DJ LeMachine",
            2021: "DJ LeMachine",
        }
    },
    "esoraci": {
        "real_name": "Evan Soraci",
        "teams": {
            2026: "The Roman Empire",
            2025: "The Kirby Superstars",
            2024: "The 430 Million Dollar Man",
            2023: "The Wuhan BatEaters",
            2022: "Power Troutage",
            2021: "The Kirby Superstars",
        }
    },
    "Beim": {
        "real_name": "Alex Beim",
        "teams": {
            2026: "The Undisputed ERA",
            2025: "Hold Me Closer, Ohtani Dancer",
            2024: "Acuña Matata",
            2023: "The Cole Train",
            2022: "The Manbolorians",
            2021: "Hold Me Closer, Ohtani Dancer",
        }
    },
    "Jookuh": {
        "real_name": "Jack Dunne",
        "teams": {
            2026: "Wallace & deGromit",
            2025: "The Wire Nation",
            2024: "Richmond Mazers",
            2023: "Richmond Mazers",
            2022: "Petey Blinders",
            2021: "Booze Cruz",
        }
    },
    "dturls55": {
        "real_name": "David Turley",
        "teams": {
            2026: "Yoshi's Riland",
            2025: "Yoshi's Riland",
            2024: "Seage(r) Miller Band",
            2023: "Lux Luthors",
            2022: "Ranger Things",
            2021: "Ward Of The Rings",
            2020: "Kershawshank Redemption",
        }
    },
}

# Build reverse lookup: team name -> owner info
def _normalize_apostrophes(s: str) -> str:
    """Replace Unicode smart-quote apostrophes with ASCII ' for matching."""
    return s.replace('\u2019', "'").replace('\u2018', "'").replace('\u02bc', "'")


def _build_team_to_owner() -> Dict[str, Dict]:
    lookup = {}
    for username, data in OWNERS.items():
        for year, team_name in data["teams"].items():
            owner_info = {
                "username": username,
                "real_name": data["real_name"],
                "season": year,
                "team_name": team_name,
            }
            # Store under original, lowercased, and smart-quote variants
            for variant in {
                team_name,
                team_name.lower().strip(),
                _normalize_apostrophes(team_name),
                _normalize_apostrophes(team_name).lower().strip(),
            }:
                lookup[variant] = owner_info
    return lookup

TEAM_TO_OWNER = _build_team_to_owner()


def get_owner_from_team_name(team_name: str) -> Dict[str, Any]:
    """Get owner info from a team name (handles renames across years and smart quotes)."""
    if not team_name:
        return {"username": "Unknown", "real_name": "Unknown"}

    # Try exact match, then smart-quote-normalized, then lowercased
    for candidate in (
        team_name,
        _normalize_apostrophes(team_name),
        team_name.lower().strip(),
        _normalize_apostrophes(team_name).lower().strip(),
    ):
        if candidate in TEAM_TO_OWNER:
            return TEAM_TO_OWNER[candidate]

    # Partial match fallback (substring)
    norm_input = _normalize_apostrophes(team_name).lower().strip()
    for key, val in TEAM_TO_OWNER.items():
        if norm_input in key.lower() or key.lower() in norm_input:
            return val

    return {"username": "Unknown", "real_name": "Unknown"}


# =============================================================================
# HELPERS
# =============================================================================

def utc_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def now_local_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slug_to_name(slug: str) -> str:
    """Convert a URL slug like 'eduardo-quintero' to 'Eduardo Quintero'."""
    if not slug:
        return ""
    parts = slug.split("-")
    return " ".join(p.upper() if len(p) <= 2 else p.capitalize() for p in parts)


def extract_player_name_from_profile(profile_data: Dict) -> str:
    """Extract player name from getPlayerProfile response via miscData.urlName."""
    try:
        for resp in profile_data.get("responses", []):
            url_name = resp.get("data", {}).get("miscData", {}).get("urlName", "")
            if url_name:
                return slug_to_name(url_name)
    except Exception:
        pass
    return ""


def strip_html(s: str) -> str:
    """Remove HTML tags from string."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_bold_text(html: str) -> Optional[str]:
    """Extract text from <b> tags."""
    match = re.search(r"<b>([^<]+)</b>", html)
    return match.group(1) if match else None


@dataclass
class Config:
    league_id: str
    jsessionid: str
    user_secret_id: str = ""
    extra_cookies: Dict[str, str] = field(default_factory=dict)
    request_delay: float = 0.5
    data_root: str = "fantrax_data"
    refresh: bool = False
    verbose: bool = False
    all_season_league_ids: Dict[int, str] = field(default_factory=dict)
    workers: int = 8  # threads for parallel player fetching


@dataclass
class RunDirs:
    root: Path
    input_dir: Path
    output_dir: Path
    logs_dir: Path
    raw_dir: Path
    cache_dir: Path


def load_config(config_path: Path, args: argparse.Namespace) -> Config:
    """Load config from file, with CLI args as overrides."""
    cfg = {}
    
    # Load from file if exists
    if config_path.exists():
        if HAS_YAML and config_path.suffix in ['.yaml', '.yml']:
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
        elif config_path.suffix == '.json':
            with open(config_path) as f:
                cfg = json.load(f)
    
    # all_season_league_ids: keys may be ints or strings in yaml
    raw_seasons = cfg.get('all_season_league_ids') or {}
    all_season_league_ids = {int(k): str(v) for k, v in raw_seasons.items()}

    # CLI args override file config
    return Config(
        league_id=args.league_id or cfg.get('league_id') or os.getenv('FANTRAX_LEAGUE_ID', ''),
        jsessionid=args.jsessionid or cfg.get('jsessionid') or os.getenv('FANTRAX_JSESSIONID', ''),
        user_secret_id=args.user_secret_id or cfg.get('user_secret_id') or os.getenv('FANTRAX_USER_SECRET_ID', ''),
        extra_cookies=cfg.get('extra_cookies') or {},
        request_delay=args.delay if args.delay is not None else cfg.get('request_delay', 0.5),
        data_root=args.data_root or cfg.get('data_root', 'fantrax_data'),
        refresh=args.refresh,
        verbose=args.verbose,
        all_season_league_ids=all_season_league_ids,
        workers=getattr(args, 'workers', 8) or 8,
    )


def setup_run_dirs(data_root: Path) -> RunDirs:
    """Create timestamped output directory structure."""
    run_name = f"run_{utc_stamp()}"
    root = data_root / run_name
    
    dirs = RunDirs(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        logs_dir=root / "logs",
        raw_dir=root / "raw_responses",
        cache_dir=data_root / "cache",
    )
    
    for d in [dirs.input_dir, dirs.output_dir, dirs.logs_dir, dirs.raw_dir, dirs.cache_dir]:
        d.mkdir(parents=True, exist_ok=True)
    
    # Create "latest" symlink
    latest = data_root / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(run_name)
    except Exception:
        pass  # Windows doesn't support symlinks without admin
    
    return dirs


def setup_logging(logs_dir: Path, verbose: bool) -> logging.Logger:
    """Configure logging to file and console."""
    logger = logging.getLogger("fantrax")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
    
    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    
    # File
    fh = logging.FileHandler(logs_dir / f"tracker_{utc_stamp()}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    
    return logger


# =============================================================================
# API CLIENT
# =============================================================================

class FantraxAuthError(Exception):
    """Raised when Fantrax returns NOT_LOGGED_IN."""
    pass


class FantraxAPI:
    """Fantrax API client with auth validation and response caching."""
    
    def __init__(self, config: Config, raw_dir: Path, logger: logging.Logger):
        self.config = config
        self.raw_dir = raw_dir
        self.logger = logger
        self.request_count = 0
        self._session = requests.Session()
    
    def _headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "content-type": "text/plain",
            "origin": "https://www.fantrax.com",
            "referer": f"https://www.fantrax.com/fantasy/league/{self.config.league_id}/team/roster",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }
    
    def _cookies(self) -> Dict[str, str]:
        cookies = dict(self.config.extra_cookies)
        if self.config.jsessionid:
            cookies["JSESSIONID"] = self.config.jsessionid
        return cookies
    
    def _save_raw(self, name: str, data: Any) -> Path:
        """Save raw response for debugging."""
        fname = self.raw_dir / f"{self.request_count:04d}_{name}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.logger.debug(f"Saved: {fname.name}")
        return fname
    
    def _check_auth(self, data: Dict, context: str) -> None:
        """Check for NOT_LOGGED_IN error in response."""
        def has_auth_error(obj: Any) -> bool:
            if isinstance(obj, dict):
                if obj.get("pageError", {}).get("code") == "WARNING_NOT_LOGGED_IN":
                    return True
                return any(has_auth_error(v) for v in obj.values())
            elif isinstance(obj, list):
                return any(has_auth_error(x) for x in obj)
            return False
        
        if has_auth_error(data):
            raise FantraxAuthError(
                f"Session expired (context: {context}). "
                "Get a fresh JSESSIONID from Chrome DevTools -> Application -> Cookies -> fantrax.com"
            )
    
    def _sleep(self) -> None:
        if self.config.request_delay > 0:
            time.sleep(self.config.request_delay)
    
    def internal_request(self, msgs: List[Dict], save_as: str = None) -> Dict:
        """Make request to internal /fxpa API."""
        url = f"{INTERNAL_API_URL}?leagueId={self.config.league_id}"
        
        payload = {
            "uiv": 3,
            "refUrl": f"https://www.fantrax.com/fantasy/league/{self.config.league_id}/home",
            "dt": 2,
            "at": 0,
            "av": "0.0",
            "tz": "America/New_York",
            "v": "182.0.1",
            "msgs": msgs,
        }
        
        self.request_count += 1
        method = msgs[0].get("method", "unknown") if msgs else "unknown"
        self.logger.debug(f"Request #{self.request_count}: {method}")
        
        resp = self._session.post(
            url,
            headers=self._headers(),
            cookies=self._cookies(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        
        self._check_auth(data, method)
        
        if save_as:
            self._save_raw(save_as, data)
        
        self._sleep()
        return data
    
    def public_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make request to public /fxea API."""
        url = f"{BASE_URL}/{endpoint}"
        
        self.request_count += 1
        self.logger.debug(f"Request #{self.request_count}: {endpoint}")
        
        resp = self._session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        
        self._sleep()
        return resp.json()
    
    # --- High-level methods ---
    
    def get_fantasy_teams(self) -> List[Dict]:
        """Get list of fantasy teams."""
        msgs = [{"method": "getFantasyTeams", "data": {}}]
        data = self.internal_request(msgs, save_as="fantasy_teams")
        
        teams = []
        for resp in data.get("responses", []):
            d = resp.get("data", {})
            if isinstance(d.get("fantasyTeams"), list):
                teams.extend(d["fantasyTeams"])
        return teams
    
    def get_team_rosters_public(self) -> Dict:
        """Get rosters via public API (requires valid session or userSecretId)."""
        params = {"leagueId": self.config.league_id}
        if self.config.user_secret_id:
            params["userSecretId"] = self.config.user_secret_id
        
        try:
            data = self.public_request("getTeamRosters", params)
            self._save_raw("team_rosters_public", data)
            return data
        except Exception as e:
            self.logger.warning(f"Public roster API failed: {e}")
            return {}
    
    def get_league_info(self) -> Dict:
        """Get league info including player pool."""
        params = {"leagueId": self.config.league_id}
        try:
            data = self.public_request("getLeagueInfo", params)
            self._save_raw("league_info", data)
            return data
        except Exception as e:
            self.logger.warning(f"League info API failed: {e}")
            return {}
    
    def get_player_profile(self, player_id: str, save_as: str = None) -> Dict:
        """Get player profile including transactions."""
        msgs = [{"method": "getPlayerProfile", "data": {
            "playerId": player_id,
            "tab": "TRANSACTIONS_FANTASY"
        }}]
        return self.internal_request(msgs, save_as=save_as)


# =============================================================================
# PARSING
# =============================================================================

def parse_teams(teams_raw: List[Dict]) -> List[Dict]:
    """Parse team list into standardized format."""
    out = []
    for t in teams_raw:
        team_id = t.get("id") or t.get("teamId") or ""
        team_name = t.get("name") or t.get("teamName") or ""
        
        # Get owner from our mapping
        owner_info = get_owner_from_team_name(team_name)
        
        out.append({
            "team_id": str(team_id),
            "team_name": str(team_name),
            "short_name": t.get("shortName", ""),
            "owner_username": owner_info.get("username"),
            "owner_real_name": owner_info.get("real_name"),
        })
    return out


def parse_rosters_from_league_info(league_info: Dict, teams: List[Dict]) -> List[Dict]:
    """Extract roster from league info response."""
    players = []
    
    # Get rosters from league info
    rosters = league_info.get("rosters", {})
    for team_id, roster in rosters.items():
        team_name = next((t["team_name"] for t in teams if t["team_id"] == team_id), "")
        owner_info = get_owner_from_team_name(team_name)
        
        for player in roster.get("players", roster.get("rosterItems", [])):
            players.append({
                "player_id": player.get("id") or player.get("playerId"),
                "player_name": player.get("name") or player.get("playerName"),
                "team_id": team_id,
                "team_name": team_name,
                "owner_username": owner_info.get("username"),
                "owner_real_name": owner_info.get("real_name"),
            })
    
    return players


def parse_rosters_from_player_profiles(api: FantraxAPI, teams: List[Dict], cache_dir: Path, 
                                        refresh: bool, logger: logging.Logger) -> Tuple[List[Dict], List[Dict]]:
    """
    Build roster by fetching a sample player profile and getting teams from there,
    then use league info to get player list.
    
    Returns: (roster_list, player_transactions_list)
    """
    # First, get the list of players from getLeagueInfo
    logger.info("Fetching league info for player pool...")
    league_info = api.get_league_info()
    
    # The player pool is in league_info["players"]
    player_pool = league_info.get("players", {})
    
    if not player_pool:
        logger.warning("No player pool in league info, using cached data or hardcoded fallback")
        return [], []
    
    # Extract rostered players
    players = []
    for player_id, player_data in player_pool.items():
        # Players with a teamId are rostered
        team_id = player_data.get("teamId")
        if team_id:
            team_name = next((t["team_name"] for t in teams if t["team_id"] == team_id), "")
            owner_info = get_owner_from_team_name(team_name)
            
            players.append({
                "player_id": player_id,
                "player_name": player_data.get("name", "Unknown"),
                "position": player_data.get("position", ""),
                "team_id": team_id,
                "team_name": team_name,
                "owner_username": owner_info.get("username"),
                "owner_real_name": owner_info.get("real_name"),
            })
    
    logger.info(f"Found {len(players)} rostered players in league info")
    return players, []


def parse_transaction_table(profile_data: Dict) -> List[Dict]:
    """Parse transaction table from player profile response."""
    transactions = []
    
    try:
        for resp in profile_data.get("responses", []):
            data = resp.get("data", {})
            section = data.get("sectionContent", {})
            trans_section = section.get("TRANSACTIONS_FANTASY", {})
            tables = trans_section.get("tables", [])
            
            if not tables:
                continue
            
            for row in tables[0].get("rows", []):
                # Skip header rows
                if row.get("highlight"):
                    continue
                
                cells = row.get("cells", [])
                if len(cells) < 2:
                    continue
                
                date_str = cells[0].get("content", "")
                action_html = cells[1].get("content", "")
                details_html = cells[2].get("content", "") if len(cells) > 2 else ""
                
                # Parse action
                action_clean = strip_html(action_html)
                team_name = extract_bold_text(action_html)
                
                # Determine action type
                action_lower = action_clean.lower()
                if "kept by" in action_lower:
                    action_type = "KEPT"
                elif "claimed" in action_lower:
                    action_type = "CLAIMED"
                elif "dropped by" in action_lower:
                    action_type = "DROPPED"
                elif "traded" in action_lower:
                    action_type = "TRADED"
                elif "drafted" in action_lower:
                    action_type = "DRAFTED"
                else:
                    action_type = "UNKNOWN"
                
                # Extract salary if present
                salary = None
                salary_match = re.search(r'\$(\d+\.?\d*)', action_clean)
                if salary_match:
                    salary = float(salary_match.group(1))
                
                # Get owner from team name
                owner_info = get_owner_from_team_name(team_name or "")
                
                transactions.append({
                    "date": date_str,
                    "action_type": action_type,
                    "team_name": team_name,
                    "owner_username": owner_info.get("username"),
                    "owner_real_name": owner_info.get("real_name"),
                    "salary": salary,
                    "details": strip_html(details_html),
                    "action_raw": action_clean,
                })
    
    except Exception as e:
        pass
    
    return transactions


def build_player_journeys(player_id: str, player_name: str, transactions: List[Dict]) -> List[Dict]:
    """Build ownership journey from transaction history."""
    if not transactions:
        return []
    
    # Sort by date
    def parse_date(d):
        try:
            return datetime.strptime(d, "%b %d %Y")
        except:
            try:
                return datetime.strptime(d, "%b %d, %Y")
            except:
                return datetime.min
    
    sorted_txns = sorted(transactions, key=lambda x: parse_date(x.get("date", "")))
    
    journeys = []
    current = None
    
    for txn in sorted_txns:
        action = txn.get("action_type")
        team = txn.get("team_name")
        date = txn.get("date")
        
        if action in ["CLAIMED", "TRADED", "DRAFTED", "KEPT"]:
            # Close previous stint
            if current and current.get("end_date") is None:
                current["end_date"] = date
                journeys.append(current)
            
            # Start new stint
            current = {
                "player_id": player_id,
                "player_name": player_name,
                "team_name": team,
                "owner_username": txn.get("owner_username"),
                "owner_real_name": txn.get("owner_real_name"),
                "start_date": date,
                "end_date": None,
                "acquisition_type": action,
                "acquisition_salary": txn.get("salary"),
            }
        
        elif action == "DROPPED":
            if current and current.get("end_date") is None:
                current["end_date"] = date
                journeys.append(current)
                current = None
    
    # Add final open stint
    if current:
        journeys.append(current)
    
    return journeys


# =============================================================================
# MAIN COLLECTION
# =============================================================================

def collect_all(api: FantraxAPI, dirs: RunDirs, config: Config, logger: logging.Logger) -> Dict:
    """Collect all data from Fantrax."""
    
    collected = {
        "teams": [],
        "players": [],
        "transactions": [],
        "journeys": [],
        "errors": [],
    }
    
    # Step 1: Get teams
    logger.info("=" * 60)
    logger.info("STEP 1: Fetching fantasy teams")
    logger.info("=" * 60)
    
    teams_raw = api.get_fantasy_teams()
    if not teams_raw:
        raise RuntimeError("No teams returned. Session may be expired.")
    
    teams = parse_teams(teams_raw)
    collected["teams"] = teams
    logger.info(f"Found {len(teams)} teams")
    
    for t in teams:
        logger.info(f"  - {t['team_name']} ({t['owner_real_name']})")
    
    # Step 2: Get rosters via public getTeamRosters endpoint
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2: Fetching rosters")
    logger.info("=" * 60)

    rosters_data = api.get_team_rosters_public()
    rosters = rosters_data.get("rosters", {})

    if rosters:
        rostered = []
        for team_id, roster in rosters.items():
            team_name = roster.get("teamName", "")
            if not team_name:
                team_name = next((t["team_name"] for t in teams if t["team_id"] == team_id), "")
            owner_info = get_owner_from_team_name(team_name)
            for player in roster.get("rosterItems", []):
                pid = player.get("id")
                if pid:
                    rostered.append({
                        "player_id": pid,
                        "player_name": "",  # filled in during Step 3 from profile
                        "position": player.get("position", ""),
                        "roster_status": player.get("status", ""),
                        "team_id": team_id,
                        "team_name": team_name,
                        "owner_username": owner_info.get("username"),
                        "owner_real_name": owner_info.get("real_name"),
                    })
        collected["players"] = rostered
        logger.info(f"Found {len(rostered)} rostered players across {len(rosters)} teams")
    else:
        logger.warning("No rosters found from getTeamRosters")
    
    # Step 3: Fetch transactions for each player
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 3: Fetching player transactions")
    logger.info("=" * 60)
    
    all_transactions = []
    all_journeys = []
    errors = []

    players_to_fetch = collected["players"] or []
    total = len(players_to_fetch)

    # Thread-safe counter and lock for progress logging
    _counter_lock = threading.Lock()
    _done_count = [0]

    def fetch_player(player: Dict) -> Optional[Dict]:
        """Fetch + parse one player; returns result dict or None on error."""
        pid = player["player_id"]
        pname = player["player_name"]
        cache_path = dirs.cache_dir / f"player_{pid}.json"

        try:
            if cache_path.exists() and not config.refresh:
                with open(cache_path) as f:
                    profile_data = json.load(f)
                source = "cached"
            else:
                profile_data = api.get_player_profile(pid, save_as=f"player_{pid}")
                # Write cache (atomic via tmp file to avoid partial writes)
                tmp = cache_path.with_suffix(".tmp")
                with open(tmp, "w") as f:
                    json.dump(profile_data, f, indent=2)
                tmp.replace(cache_path)
                source = "fetched"
                # Respect rate limit — only when actually making a network call
                time.sleep(config.request_delay)

            resolved_name = pname or extract_player_name_from_profile(profile_data) or pid
            txns = parse_transaction_table(profile_data)
            for t in txns:
                t["player_id"] = pid
                t["player_name"] = resolved_name
            journeys = build_player_journeys(pid, resolved_name, txns)

            with _counter_lock:
                _done_count[0] += 1
                n = _done_count[0]
                if n % 25 == 0 or n == total:
                    logger.info(f"  Processed {n}/{total} players...")
                else:
                    logger.debug(f"  [{n}/{total}] {pid} ({source})")

            return {
                "player": player,
                "resolved_name": resolved_name,
                "transactions": txns,
                "journeys": journeys,
            }

        except FantraxAuthError:
            raise  # propagate auth errors immediately
        except Exception as e:
            logger.warning(f"Error processing player {pname or pid}: {e}")
            with _counter_lock:
                _done_count[0] += 1
            return {"player": player, "error": str(e)}

    workers = max(1, config.workers)
    logger.info(f"  Fetching {total} players with {workers} parallel threads...")

    # Use threads (I/O-bound; GIL not a bottleneck for network calls)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_player, p): p for p in players_to_fetch}
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
            except FantraxAuthError:
                # Cancel remaining futures and re-raise
                pool.shutdown(wait=False, cancel_futures=True)
                raise
            except Exception as e:
                p = futures[future]
                errors.append({"player_id": p["player_id"], "player_name": p.get("player_name", ""), "error": str(e)})
                continue

            if result is None:
                continue
            if "error" in result:
                p = result["player"]
                errors.append({"player_id": p["player_id"], "player_name": p.get("player_name", ""), "error": result["error"]})
            else:
                # Update the player name in-place on the original dict
                result["player"]["player_name"] = result["resolved_name"]
                all_transactions.extend(result["transactions"])
                all_journeys.extend(result["journeys"])

    collected["transactions"] = all_transactions
    collected["journeys"] = all_journeys
    collected["errors"].extend(errors)

    logger.info(f"Collected {len(all_transactions)} transactions, {len(all_journeys)} ownership stints")
    
    return collected


def export_all(collected: Dict, dirs: RunDirs, logger: logging.Logger) -> None:
    """Export collected data to CSV files."""
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 4: Exporting data")
    logger.info("=" * 60)
    
    output = dirs.output_dir
    
    # Teams
    teams_df = pd.DataFrame(collected["teams"])
    teams_df.to_csv(output / "teams.csv", index=False)
    logger.info(f"Exported {len(teams_df)} teams")
    
    # Current rosters
    players_df = pd.DataFrame(collected["players"])
    players_df.to_csv(output / "current_rosters.csv", index=False)
    logger.info(f"Exported {len(players_df)} rostered players")
    
    # Transactions
    txn_df = pd.DataFrame(collected["transactions"])
    txn_df.to_csv(output / "transaction_history.csv", index=False)
    logger.info(f"Exported {len(txn_df)} transactions")
    
    # Journeys
    journeys_df = pd.DataFrame(collected["journeys"])
    journeys_df.to_csv(output / "player_journeys.csv", index=False)
    logger.info(f"Exported {len(journeys_df)} ownership stints")
    
    # Owner mapping
    owner_records = []
    for username, data in OWNERS.items():
        for year, team_name in sorted(data["teams"].items(), reverse=True):
            owner_records.append({
                "username": username,
                "real_name": data["real_name"],
                "season": year,
                "team_name": team_name,
            })
    owner_df = pd.DataFrame(owner_records)
    owner_df.to_csv(output / "owner_team_mapping.csv", index=False)
    logger.info(f"Exported {len(owner_df)} owner mappings")
    
    # Errors
    if collected["errors"]:
        errors_df = pd.DataFrame(collected["errors"])
        errors_df.to_csv(output / "errors.csv", index=False)
        logger.warning(f"Exported {len(errors_df)} errors")
    
    # Raw data dump
    dump = {
        "teams": collected["teams"],
        "players_count": len(collected["players"]),
        "transactions_count": len(collected["transactions"]),
        "journeys_count": len(collected["journeys"]),
    }
    with open(output / "run_summary.json", "w") as f:
        json.dump(dump, f, indent=2)


# =============================================================================
# MULTI-SEASON ORCHESTRATION
# =============================================================================

def run_single_season(
    season: int,
    league_id: str,
    config: Config,
    data_root: Path,
    logger: logging.Logger,
) -> Optional[Path]:
    """
    Run a full collect+export cycle for one season/league_id.
    Returns the output directory path on success, None on failure.
    """
    season_logger = logging.getLogger(f"fantrax.season{season}")
    # Inherit handlers from parent logger
    season_logger.handlers = logger.handlers
    season_logger.setLevel(logger.level)

    season_logger.info("")
    season_logger.info("=" * 60)
    season_logger.info(f"SEASON {season}  |  league_id: {league_id}")
    season_logger.info("=" * 60)

    # Build a config copy with this season's league_id
    season_config = Config(
        league_id=league_id,
        jsessionid=config.jsessionid,
        user_secret_id=config.user_secret_id,
        extra_cookies=config.extra_cookies,
        request_delay=config.request_delay,
        data_root=config.data_root,
        refresh=config.refresh,
        verbose=config.verbose,
        all_season_league_ids=config.all_season_league_ids,
        workers=config.workers,
    )

    try:
        dirs = setup_run_dirs(data_root)
        api = FantraxAPI(season_config, dirs.raw_dir, season_logger)
        collected = collect_all(api, dirs, season_config, season_logger)
        export_all(collected, dirs, season_logger)
        season_logger.info(f"Season {season} complete → {dirs.root}")
        return dirs.root
    except FantraxAuthError as e:
        season_logger.error(f"Auth error for season {season}: {e}")
        return None
    except Exception as e:
        season_logger.exception(f"Failed season {season}: {e}")
        return None


def collect_all_seasons(
    seasons: List[int],
    config: Config,
    data_root: Path,
    logger: logging.Logger,
    parallel_seasons: bool = False,
) -> Dict[int, Optional[Path]]:
    """
    Run collection for multiple seasons.

    parallel_seasons=False (default): run seasons sequentially.
      This is safer — avoids hitting Fantrax rate limits with concurrent
      full-season scrapes, each of which already uses threaded player fetching.

    parallel_seasons=True: run each season in its own thread simultaneously.
      Only use if you know your session can handle the load.
    """
    results: Dict[int, Optional[Path]] = {}

    if not parallel_seasons:
        for season in sorted(seasons):
            lid = config.all_season_league_ids.get(season)
            if not lid:
                logger.warning(f"No league_id for season {season} — skipping")
                results[season] = None
                continue
            results[season] = run_single_season(season, lid, config, data_root, logger)
    else:
        def _run(season: int) -> Tuple[int, Optional[Path]]:
            lid = config.all_season_league_ids.get(season)
            if not lid:
                logger.warning(f"No league_id for season {season} — skipping")
                return season, None
            return season, run_single_season(season, lid, config, data_root, logger)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(seasons)) as pool:
            futs = {pool.submit(_run, s): s for s in sorted(seasons)}
            for fut in concurrent.futures.as_completed(futs):
                season, path = fut.result()
                results[season] = path

    return results


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fantrax Ownership Tracker v4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fantrax_tracker_v4.py                         # Current season (config.yaml)
  python fantrax_tracker_v4.py --jsessionid X         # Override session
  python fantrax_tracker_v4.py --refresh               # Re-fetch cached data
  python fantrax_tracker_v4.py --all-seasons           # Run all seasons from config
  python fantrax_tracker_v4.py --seasons 2024 2025     # Run specific seasons
  python fantrax_tracker_v4.py --all-seasons --workers 12  # More parallel threads
        """
    )

    p.add_argument("--config", default="config.yaml", help="Config file path")
    p.add_argument("--league-id", help="Fantrax league ID (overrides config, current season only)")
    p.add_argument("--jsessionid", help="JSESSIONID cookie value")
    p.add_argument("--user-secret-id", help="User Secret ID (from Fantrax profile)")
    p.add_argument("--data-root", help="Output folder")
    p.add_argument("--delay", type=float, help="Request delay in seconds")
    p.add_argument("--refresh", action="store_true", help="Re-fetch cached player data")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    # Multi-season flags
    p.add_argument(
        "--all-seasons",
        action="store_true",
        help="Run collection for ALL seasons defined in config.yaml (all_season_league_ids)",
    )
    p.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        metavar="YEAR",
        help="Run collection for specific season year(s), e.g. --seasons 2024 2025",
    )

    # Parallelism
    p.add_argument(
        "--workers",
        type=int,
        default=8,
        metavar="N",
        help="Number of parallel threads for player profile fetching (default: 8)",
    )

    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Load config
    config_path = Path(args.config)
    config = load_config(config_path, args)

    # Validate auth
    if not config.jsessionid:
        print("ERROR: Missing jsessionid. Set in config.yaml or use --jsessionid", file=sys.stderr)
        print("\nTo get your JSESSIONID:", file=sys.stderr)
        print("  1. Open Chrome and log into Fantrax", file=sys.stderr)
        print("  2. Open DevTools (F12) -> Application -> Cookies -> fantrax.com", file=sys.stderr)
        print("  3. Copy the JSESSIONID value", file=sys.stderr)
        return 1

    data_root = Path(config.data_root)

    # ── Multi-season mode ─────────────────────────────────────────────────────
    if args.all_seasons or args.seasons:
        if args.seasons:
            seasons_to_run = list(args.seasons)
        else:
            seasons_to_run = sorted(config.all_season_league_ids.keys())

        if not seasons_to_run:
            print(
                "ERROR: No seasons found. Add 'all_season_league_ids' to config.yaml or use --seasons.",
                file=sys.stderr,
            )
            return 1

        # Set up a shared logger (logs go to data_root/multi_season.log)
        data_root.mkdir(parents=True, exist_ok=True)
        log_path = data_root / f"multi_season_{utc_stamp()}.log"
        logger = logging.getLogger("fantrax.multi")
        logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
        logger.handlers.clear()
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if args.verbose else logging.INFO)
        ch.setFormatter(fmt)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(ch)
        logger.addHandler(fh)

        logger.info("=" * 60)
        logger.info("FANTRAX OWNERSHIP TRACKER v4 — MULTI-SEASON")
        logger.info("=" * 60)
        logger.info(f"Seasons to collect: {sorted(seasons_to_run)}")
        logger.info(f"Player fetch workers: {config.workers}")
        logger.info(f"Seasons run: sequentially (safer for rate limits)")

        results = collect_all_seasons(
            seasons=seasons_to_run,
            config=config,
            data_root=data_root,
            logger=logger,
            parallel_seasons=False,  # sequential seasons, parallel players within each
        )

        logger.info("")
        logger.info("=" * 60)
        logger.info("MULTI-SEASON SUMMARY")
        logger.info("=" * 60)
        ok = [s for s, p in results.items() if p is not None]
        fail = [s for s, p in results.items() if p is None]
        for season in sorted(results):
            status = "✓" if results[season] else "✗ FAILED"
            logger.info(f"  {season}: {status}  {results[season] or ''}")

        logger.info(f"\nSucceeded: {len(ok)}/{len(seasons_to_run)} seasons")
        if fail:
            logger.warning(f"Failed:    {fail}")
            return 1
        return 0

    # ── Single-season mode (default) ─────────────────────────────────────────
    if not config.league_id:
        print("ERROR: Missing league_id. Set in config.yaml or use --league-id", file=sys.stderr)
        return 1

    dirs = setup_run_dirs(data_root)
    logger = setup_logging(dirs.logs_dir, config.verbose)

    # Save config snapshot (without secrets)
    config_snapshot = {
        "league_id": config.league_id,
        "data_root": config.data_root,
        "request_delay": config.request_delay,
        "workers": config.workers,
        "refresh": config.refresh,
        "start_time": now_local_iso(),
    }
    with open(dirs.input_dir / "config.json", "w") as f:
        json.dump(config_snapshot, f, indent=2)

    logger.info("=" * 60)
    logger.info("FANTRAX OWNERSHIP TRACKER v4")
    logger.info("=" * 60)
    logger.info(f"League: {config.league_id}")
    logger.info(f"Output: {dirs.root}")
    logger.info(f"Workers: {config.workers} threads")

    api = FantraxAPI(config, dirs.raw_dir, logger)

    try:
        collected = collect_all(api, dirs, config, logger)
        export_all(collected, dirs, logger)

        logger.info("")
        logger.info("=" * 60)
        logger.info("COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Output: {dirs.root}")
        return 0

    except FantraxAuthError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"Failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
