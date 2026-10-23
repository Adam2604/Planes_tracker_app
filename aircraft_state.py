"""Aircraft state updates shared by the receiver and hardware-free tests."""
import uuid


def update_plane(planes, models, icao, data, now, update_last_seen=True):
    if icao not in planes:
        planes[icao] = {
            "icao": icao, "track_id": uuid.uuid4().hex,
            "first_seen": now, "last_seen": now,
            "model": models.get(icao, "Nieznany model"),
            "dist": None, "min_dist": None, "max_dist": None,
            "speed": None, "max_speed": 0, "category": 0, "route": [],
            "spoof_score": 0, "is_spoofed": False, "rejected_jumps": 0,
        }
    plane = planes[icao]
    plane.update(data)
    if update_last_seen:
        plane["last_seen"] = now
    if "lat" in data and "lon" in data:
        plane["route"].append([data["lat"], data["lon"]])
    if data.get("dist") is not None:
        for field, reducer in (("min_dist", min), ("max_dist", max)):
            plane[field] = data["dist"] if plane[field] is None else reducer(plane[field], data["dist"])
    if data.get("speed") is not None:
        plane["max_speed"] = max(plane["max_speed"], data["speed"])
    return plane
