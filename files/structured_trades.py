"""Use explicit Fantrax trade assets instead of inferring players from prose."""
from collections import Counter
from datetime import datetime, timezone


def classify_assets(asset_types, assets_by_owner):
    types = set(t for values in asset_types.values() for t in values)
    if any(len(values) > 1 for values in asset_types.values()):
        label = "Mixed"
    else:
        label = {frozenset({"player"}): "Player-for-Player",
                 frozenset({"player", "pick"}): "Player-for-Pick",
                 frozenset({"player", "budget"}): "Player-for-FAAB",
                 frozenset({"pick"}): "Pick-for-Pick",
                 frozenset({"pick", "budget"}): "Pick-for-FAAB"}.get(frozenset(types), "Other")
    counts = sorted((len(v["sent"]) for v in assets_by_owner.values() if v["sent"]), reverse=True)
    subtype = "-for-".join(map(str, counts)) if label == "Player-for-Player" and len(counts) > 1 else ""
    return label, subtype


def build_pick_results(trades, drafts, player_index):
    by_slot = {}
    by_recipient_round = {}
    completed = {s["year"] for s in drafts["seasons"]}
    for season in drafts["seasons"]:
        for pick in season["picks"]:
            key = (pick["draft_year"], pick["round"], pick["pick_in_round"])
            if key in by_slot:
                raise ValueError("Duplicate draft slot")
            by_slot[key] = pick
            if pick.get("player_id"):
                by_recipient_round.setdefault((pick["draft_year"], pick["round"], pick["owner_name"]), []).append(pick)

    def enriched(pick):
        status = player_index.get(pick["player_id"], {})
        return {**{k: pick[k] for k in ("player_name", "player_id", "draft_year", "round", "pick_in_round", "overall_pick")},
                "drafting_owner": pick["owner_name"], "drafting_team": pick["team_name"],
                "current_owner": status.get("current_owner"), "still_rostered": bool(status.get("current_owner")),
                "owner_changes": status.get("owner_changes", 0), "total_stints": status.get("total_stints", 0)}

    results = []
    for trade in trades:
        for asset in trade["pick_assets"]:
            year, rnd, slot = asset["pick_year"], asset["pick_round"], asset["pick_in_round"]
            exact = by_slot.get((year, rnd, slot)) if slot else None
            candidates = by_recipient_round.get((year, rnd, asset["receiving_owner"]), [])
            if year not in completed:
                status = "pending"
            elif exact and exact.get("player_id"):
                status = "matched"
            elif slot:
                status = "unknown"  # A blank exact slot must not match a different player's slot.
            elif candidates:
                status = "ambiguous"  # Recipient/round alone does not identify the original pick.
            else:
                status = "unknown"
            results.append({**asset, "is_deleted": asset["original_holder"].lower() == "*deleted*",
                            "event_id": trade["event_id"], "all_parties": trade["parties"],
                            "trade_date": trade["date_iso"], "trade_type_label": trade["trade_type_label"],
                            "result_status": status, "match_basis": "Exact year, round, and pick number" if status == "matched" else None,
                            "drafted_player": enriched(exact) if status == "matched" else None,
                            "ambiguous_candidates": [enriched(p) for p in candidates] if status == "ambiguous" else []})
    counts = dict(Counter(p["result_status"] for p in results))
    print(f"      Structured traded picks: {len(results)}; statuses: {counts}")
    return {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(), "total_pick_refs": len(results),
                     "status_counts": counts, "matching_rule": "Only explicit draft-slot numbers are confirmed matches"},
            "pick_results": results}
