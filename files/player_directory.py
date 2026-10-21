"""Canonical names from Fantrax's public MLB player ID directory."""


def player_names(directory):
    if not isinstance(directory, dict) or not directory:
        raise ValueError("Empty or invalid player directory")
    names = {}
    for pid, info in directory.items():
        if not isinstance(info, dict) or info.get("fantraxId") != pid or not info.get("name"):
            raise ValueError("Malformed player directory entry")
        parts = info["name"].split(",", 1)
        names[pid] = f"{parts[1].strip()} {parts[0].strip()}" if len(parts) == 2 else parts[0].strip()
    return names
