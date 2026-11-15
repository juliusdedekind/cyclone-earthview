#!/usr/bin/env python3
"""Pull and pair NASA EPIC and NICT Himawari images for 2025-26 cyclones.

The script uses only the Python standard library.  Storm names/windows are the
named systems listed in the linked season-effect tables.  Positions and winds
come from NOAA/NCEI IBTrACS.  For each storm, three observations are selected
around peak intensity; the closest usable EPIC view is paired to the nearest
10-minute Himawari full-disk image for Australian/South Pacific cyclones.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import math
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "storm_image_pairs"
DATA = OUT / "data"
IMAGES = OUT / "images"
WIKI_PANELS = OUT / "wiki_panels"

IBTRACS_URL = (
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-"
    "climate-stewardship-ibtracs/v04r01/access/csv/"
    "ibtracs.last3years.list.v04r01.csv"
)
EPIC_API = "https://epic.gsfc.nasa.gov/api/natural/date/{date}"
EPIC_ARCHIVE = (
    "https://epic.gsfc.nasa.gov/archive/natural/{year}/{month}/{day}/jpg/{name}.jpg"
)
HIMAWARI_ARCHIVE = (
    "https://himawari.asia/img/D531106/1d/550/"
    "{year}/{month}/{day}/{clock}_0_0.png"
)

WIKI_AU = "https://en.wikipedia.org/wiki/2025%E2%80%9326_Australian_region_cyclone_season"
WIKI_SP = "https://en.wikipedia.org/wiki/2025%E2%80%9326_South_Pacific_cyclone_season"
WIKI_ATL = "https://en.wikipedia.org/wiki/2026_Atlantic_hurricane_season"
WIKI_EPAC = "https://en.wikipedia.org/wiki/2026_Pacific_hurricane_season"


def storm(group, basin, name, start, end, wiki):
    return {
        "group": group,
        "basin": basin,
        "name": name,
        "start": dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc),
        "end": dt.datetime.fromisoformat(end).replace(
            hour=23, minute=59, second=59, tzinfo=dt.timezone.utc
        ),
        "wiki": wiki,
    }


# Named-storm windows from the season-effect tables, inclusive.
STORMS = [
    storm("australian_region_2025-26", "Australian region", "Fina", "2025-11-15", "2025-11-25", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Bakung", "2025-12-10", "2025-12-17", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Grant", "2025-12-15", "2025-12-27", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Hayley", "2025-12-27", "2025-12-30", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Iggy", "2025-12-31", "2026-01-01", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Jenna", "2026-01-03", "2026-01-08", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Koji", "2026-01-07", "2026-01-11", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Luana", "2026-01-21", "2026-01-25", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Mitchell", "2026-01-29", "2026-02-09", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Narelle", "2026-03-15", "2026-03-27", WIKI_AU),
    storm("australian_region_2025-26", "Australian region", "Maila", "2026-04-01", "2026-04-11", WIKI_AU),
    storm("south_pacific_2025-26", "South Pacific", "Urmil", "2026-02-26", "2026-03-01", WIKI_SP),
    storm("south_pacific_2025-26", "South Pacific", "Vaianu", "2026-04-03", "2026-04-09", WIKI_SP),
    storm("atlantic_2026", "North Atlantic", "Arthur", "2026-06-17", "2026-06-18", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Bertha", "2026-07-19", "2026-07-23", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Cristobal", "2026-08-12", "2026-08-13", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Dolly", "2026-08-27", "2026-08-28", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Edouard", "2026-08-31", "2026-09-03", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Fay", "2026-09-19", "2026-09-29", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Gonzalo", "2026-09-25", "2026-09-26", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Hanna", "2026-09-28", "2026-09-30", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Isaias", "2026-10-06", "2026-10-10", WIKI_ATL),
    storm("atlantic_2026", "North Atlantic", "Josephine", "2026-10-21", "2026-10-22", WIKI_ATL),
]

# "Areas affected" from each linked Wikipedia season-effects table, preserved
# in the table's listed order and presented in the UI as the source's path.
WIKIPEDIA_PATHS = {
    "Fina": ["Timor-Leste", "Indonesia (Lesser Sunda Islands)", "Tiwi Islands", "Northern Territory", "Kimberley"],
    "Bakung": ["Indonesia (Sumatra)"],
    "Grant": ["Indonesia (Java)", "Christmas Island", "Cocos (Keeling) Islands", "South-West Indian Ocean crossover"],
    "Hayley": ["Indonesia (Lesser Sunda Islands)", "Western Australia (Kimberley and Rowley Shoals)", "Northern Territory"],
    "Iggy": ["Indonesia (Sumatra and Java)", "Christmas Island"],
    "Jenna": ["Cocos (Keeling) Islands", "South-West Indian Ocean crossover"],
    "Koji": ["Papua New Guinea", "Coral Sea Islands", "Queensland"],
    "Luana": ["Indonesia (Lesser Sunda Islands)", "Western Top End", "Ashmore and Cartier Islands", "Western Australia (Kimberley, Pilbara and Goldfields–Esperance)"],
    "Mitchell": ["Northern Territory", "Western Australia"],
    "Narelle": ["Solomon Islands", "Papua New Guinea", "Coral Sea Islands", "Queensland (Cape York Peninsula)", "Northern Territory", "Western Australia"],
    "Maila": ["Solomon Islands", "Papua New Guinea"],
    "Urmil": ["Vanuatu", "New Caledonia", "Fiji", "Tonga", "Kermadec Islands"],
    "Vaianu": ["Tonga", "Fiji", "New Zealand"],
    "Arthur": ["Veracruz", "Northern Mexico", "United States Gulf Coast"],
    "Bertha": ["United States Gulf Coast"],
    "Cristobal": ["No affected areas listed"],
    "Dolly": ["Antilles"],
    "Edouard": ["Coastal Louisiana", "East Texas"],
    "Fay": ["No affected areas listed"],
    "Gonzalo": ["Cape Verde", "The Gambia"],
    "Hanna": ["No affected areas listed"],
    "Isaias": ["Eastern Mexico", "Alabama", "Mississippi", "Florida Panhandle"],
    "Josephine": ["United States East Coast", "Atlantic Canada"],
}

for storm_spec in STORMS:
    storm_spec["path"] = WIKIPEDIA_PATHS[storm_spec["name"]]

# Extra useful views beyond the three around peak intensity. Entries append to
# the existing numbered sequence so previously collected assets remain stable.
# Arthur's June 18 additions are post-track remnant views: the marker
# intentionally uses the final IBTrACS fix rather than inventing a position.
EXTRA_EPIC_FRAMES = {
    "BAKUNG": [
        {
            "capture": "2025-12-16 05:55:51",
            "note": "Additional late-lifecycle EPIC and Himawari view selected to extend Bakung's day-by-day coverage.",
            "is_remnant": False,
        },
        {
            "capture": "2025-12-17 05:37:09",
            "note": "Additional late-lifecycle EPIC and Himawari view selected to extend Bakung's day-by-day coverage.",
            "is_remnant": False,
        },
    ],
    "BERTHA": [
        {
            "capture": "2026-07-23 18:36:26",
            "note": "Additional July 23 EPIC view; concurrent East Pacific Hurricane Fausto is marked in gold.",
            "is_remnant": False,
        },
        {
            "capture": "2026-07-23 19:41:54",
            "note": "Additional July 23 EPIC view; concurrent East Pacific Hurricane Fausto is marked in gold.",
            "is_remnant": False,
        },
    ],
    "ARTHUR": [
        {
            "capture": "2026-06-18 17:30:56",
            "note": "Post-track remnant view; marker and wind use Arthur's final IBTrACS fix at 00:00 UTC.",
            "is_remnant": True,
        },
        {
            "capture": "2026-06-18 18:36:23",
            "note": "Post-track remnant view; marker and wind use Arthur's final IBTrACS fix at 00:00 UTC.",
            "is_remnant": True,
        },
    ]
}

# Independently named systems visible in another storm's selected EPIC frame.
# Keys are (primary storm, frame number); values are the IBTrACS names.
COINCIDENT_MARKERS = {
    ("BERTHA", 2): "FAUSTO",
    ("BERTHA", 3): "FAUSTO",
    ("BERTHA", 4): "FAUSTO",
    ("BERTHA", 5): "FAUSTO",
}

# Multiple independently named systems visible alongside Edouard. These use
# additive enriched comparison assets so the original Edouard frames remain on
# disk unchanged. Lowell is beyond EPIC's usable limb in frame 3.
VISIBLE_COMPANION_MARKERS = {
    ("EDOUARD", 1): ["MARIE", "KARINA", "LOWELL"],
    ("EDOUARD", 2): ["MARIE", "KARINA", "LOWELL"],
    ("EDOUARD", 3): ["MARIE", "KARINA"],
}
COMPANION_MARKER_STYLES = {
    "MARIE": ("#ffd23f", "gold"),
    "KARINA": ("#ff66cc", "magenta"),
    "LOWELL": ("#6be585", "green"),
}
WIKIPEDIA_COMPANION_SPECS = [
    {"group": "associated_2026_pacific", "basin": "Eastern Pacific", "name": name.title(), "wiki": WIKI_EPAC}
    for name in ("MARIE", "KARINA", "LOWELL")
]
ASSOCIATED_WIKIPEDIA_PANELS = {
    "EDOUARD": ["Marie", "Karina", "Lowell"],
}


USER_AGENT = "storm-image-pairing/1.0 (research; NASA EPIC + NICT Himawari)"
EPIC_RADIUS_SCALE_KM = 582_500.0


def request_bytes(url, attempts=4):
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
                return body, content_type
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed after {attempts} attempts: {url}: {last}")


def download(url, destination, expected_type=None):
    destination = pathlib.Path(destination)
    if destination.exists() and destination.stat().st_size > 1000:
        return destination
    body, content_type = request_bytes(url)
    if expected_type and expected_type not in content_type:
        raise RuntimeError(f"Unexpected content type {content_type!r} for {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(body)
    temporary.replace(destination)
    return destination


def parse_time(value):
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=dt.timezone.utc
    )


def iso_z(value):
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(value):
    return value.lower().replace(" ", "_").replace("-", "_")


def wind(row):
    values = []
    for key in ("WMO_WIND", "USA_WIND", "BOM_WIND", "TOKYO_WIND", "REUNION_WIND"):
        try:
            values.append(float(row.get(key, "")))
        except (TypeError, ValueError):
            pass
    return max(values) if values else 0.0


def angular_distance(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(((lon2 - lon1 + 180) % 360) - 180)
    cosine = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def nearest_track(rows, when):
    return min(rows, key=lambda row: abs((row["_time"] - when).total_seconds()))


def choose_track_targets(rows, active_start, active_end):
    named = [row for row in rows if row.get("NATURE") in {"TS", "SS"}]
    if len(named) >= 3:
        rows = named
    peak = max(rows, key=lambda row: (wind(row), row["_time"]))
    start = max(active_start, rows[0]["_time"])
    end = min(active_end, rows[-1]["_time"])
    desired = [max(start, peak["_time"] - dt.timedelta(hours=24)), peak["_time"], min(end, peak["_time"] + dt.timedelta(hours=24))]
    chosen = []
    for target in desired:
        options = sorted(rows, key=lambda row: abs((row["_time"] - target).total_seconds()))
        row = next((candidate for candidate in options if candidate["ISO_TIME"] not in {r["ISO_TIME"] for r in chosen}), options[0])
        chosen.append(row)
    if len({row["ISO_TIME"] for row in chosen}) < 3:
        indexes = [0, len(rows) // 2, len(rows) - 1]
        chosen = [rows[index] for index in indexes]
    return sorted(chosen, key=lambda row: row["_time"])


def load_epic_metadata(date, cache):
    key = date.isoformat()
    if key not in cache:
        body, _ = request_bytes(EPIC_API.format(date=key))
        cache[key] = json.loads(body.decode("utf-8"))
    return cache[key]


def select_epic_image(target_row, track_rows, active_start, active_end, cache, used):
    target_time = target_row["_time"]
    candidates = []
    for offset in (-1, 0, 1):
        day = (target_time + dt.timedelta(days=offset)).date()
        for item in load_epic_metadata(day, cache):
            capture = parse_time(item["date"])
            if capture < active_start or capture > active_end:
                continue
            row = nearest_track(track_rows, capture)
            center = item["centroid_coordinates"]
            distance = angular_distance(
                float(row["LAT"]), float(row["LON"]), float(center["lat"]), float(center["lon"])
            )
            hours = abs((capture - target_time).total_seconds()) / 3600
            score = hours + distance / 8.0
            if item["image"] in used:
                score += 1000
            candidates.append((distance > 83, score, distance, capture, item, row))
    if not candidates:
        raise RuntimeError(f"No EPIC metadata candidates around {iso_z(target_time)}")
    _, _, distance, capture, item, row = min(candidates, key=lambda candidate: candidate[:2])
    used.add(item["image"])
    return {
        "item": item,
        "capture": capture,
        "track": row,
        "view_angle": distance,
    }


def round_ten_minutes(value):
    epoch = int(value.timestamp())
    return dt.datetime.fromtimestamp(((epoch + 300) // 600) * 600, tz=dt.timezone.utc)


def fetch_himawari(capture, destination):
    rounded = round_ten_minutes(capture)
    for minutes in (0, -10, 10, -20, 20, -30, 30):
        candidate = rounded + dt.timedelta(minutes=minutes)
        url = HIMAWARI_ARCHIVE.format(
            year=candidate.strftime("%Y"),
            month=candidate.strftime("%m"),
            day=candidate.strftime("%d"),
            clock=candidate.strftime("%H%M%S"),
        )
        try:
            download(url, destination, "image/png")
            return candidate, url
        except RuntimeError:
            if pathlib.Path(destination).exists():
                pathlib.Path(destination).unlink()
    raise RuntimeError(f"No Himawari frame within 30 minutes of {iso_z(capture)}")


def epic_xy(lat, lon, center_lat, center_lon, size=1080.0, dscovr_position=None):
    latitude = math.radians(lat)
    center_phi = math.radians(center_lat)
    delta = math.radians(((lon - center_lon + 180) % 360) - 180)
    if dscovr_position:
        distance = math.sqrt(sum(float(dscovr_position[axis]) ** 2 for axis in ("x", "y", "z")))
        radius = size * EPIC_RADIUS_SCALE_KM / distance
    else:
        radius = size * 0.465
    x = size / 2 + radius * math.cos(latitude) * math.sin(delta)
    y_proj = math.cos(center_phi) * math.sin(latitude) - math.sin(center_phi) * math.cos(latitude) * math.cos(delta)
    y = size / 2 - radius * y_proj
    return x, y


def embedded_epic_position(path):
    """Read DSCOVR position metadata embedded near the start of EPIC imagery."""
    text = pathlib.Path(path).read_bytes()[:4096].decode("latin-1", errors="ignore")
    match = re.search(
        r"dscovr_j2000_position'\s*:\s*\{\s*'x'\s*:\s*([-+0-9.]+),\s*"
        r"'y'\s*:\s*([-+0-9.]+),\s*'z'\s*:\s*([-+0-9.]+)",
        text,
    )
    if not match:
        raise RuntimeError(f"Could not read DSCOVR position metadata from {path}")
    return dict(zip(("x", "y", "z"), map(float, match.groups())))


def himawari_xy(lat, lon, size=550.0):
    # This is the forward transform used by NICT's own Himawari tile viewer.
    margin_left = margin_right = 0.0045
    left = math.radians(((lon + 180 - 140.7) % 360) - 180)
    top = math.radians(((lat + 90) % 180) - 90)
    radius = size * (1.0 - margin_left - margin_right) / 2.0
    e2 = 0.00669438003
    n = radius / math.sqrt(1.0 - e2 * math.sin(top) ** 2)
    theta = 0.1535
    f = 6.613
    vrad = math.radians(81.3025)
    left = max(-vrad, min(vrad, left))
    top = max(-vrad, min(vrad, top))
    z = radius * f - n * math.cos(top) * math.cos(left)
    x = n * math.cos(top) * math.sin(left)
    y = (n * (1.0 - e2)) * math.sin(top)
    px = size / 2 * math.atan(x / z) / theta + size / 2
    py = size / 2 - size / 2 * math.atan(y / z) / theta
    return px, py


def write_text_if_changed(path, content):
    path = pathlib.Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8")


def marker(x, y, label, color="#ff2b2b", label_x=None, label_y=None):
    safe = html.escape(label)
    label_x = min(1590, max(8, x + 16)) if label_x is None else label_x
    label_y = min(910, max(32, y - 16)) if label_y is None else label_y
    width = max(86, 9 * len(label) + 12)
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="none" stroke="{color}" stroke-width="4" stroke-opacity="0.9"/>'
        f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{label_x:.1f}" y2="{label_y:.1f}" stroke="{color}" stroke-width="3" stroke-opacity="0.8"/>'
        f'<rect x="{label_x:.1f}" y="{label_y - 22:.1f}" width="{width}" height="28" rx="5" fill="#101820" fill-opacity="0.62"/>'
        f'<text x="{label_x + 6:.1f}" y="{label_y - 3:.1f}" font-family="Arial,sans-serif" font-size="16" font-weight="700" fill="white">{safe}</text>'
    )


def write_pair_svg(
    path, title, epic_name, hima_name, epic_capture, hima_capture, row, epic_center,
    epic_position=None,
):
    lat, lon = float(row["LAT"]), float(row["LON"])
    ex, ey = epic_xy(
        lat, lon, float(epic_center["lat"]), float(epic_center["lon"]),
        dscovr_position=epic_position,
    )
    hx, hy = himawari_xy(lat, lon)
    ex = 25 + ex * 800 / 1080
    ey = 90 + ey * 800 / 1080
    hx = 875 + hx * 800 / 550
    hy = 90 + hy * 800 / 550
    label = f'{title.split(" — ")[0]}  {lat:.1f}°, {lon:.1f}°'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1700" height="970" viewBox="0 0 1700 970">
<rect width="1700" height="970" fill="#07111d"/>
<text x="25" y="38" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="white">{html.escape(title)}</text>
<text x="25" y="70" font-family="Arial,sans-serif" font-size="19" fill="#b9cad9">EPIC {iso_z(epic_capture)} · Himawari {iso_z(hima_capture)} · red marker: nearest IBTrACS point</text>
<image href="{html.escape(epic_name)}" x="25" y="90" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
<image href="{html.escape(hima_name)}" x="875" y="90" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
{marker(ex, ey, label)}
{marker(hx, hy, label)}
<text x="425" y="930" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NASA DSCOVR EPIC</text>
<text x="1275" y="930" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NICT Himawari full disk</text>
</svg>
'''
    write_text_if_changed(path, svg)


def write_epic_svg(
    path, title, epic_name, epic_capture, row, epic_center, secondary=None,
    epic_position=None,
):
    lat, lon = float(row["LAT"]), float(row["LON"])
    ex, ey = epic_xy(
        lat, lon, float(epic_center["lat"]), float(epic_center["lon"]),
        dscovr_position=epic_position,
    )
    ex = 50 + ex * 800 / 1080
    ey = 105 + ey * 800 / 1080
    label = f'{title.split(" — ")[0]}  {lat:.1f}°, {lon:.1f}°'
    secondary_marker = ""
    marker_legend = "red marker: nearest IBTrACS point"
    if secondary:
        secondary_row = secondary["track"]
        secondary_lat, secondary_lon = float(secondary_row["LAT"]), float(secondary_row["LON"])
        sx, sy = epic_xy(
            secondary_lat, secondary_lon, float(epic_center["lat"]), float(epic_center["lon"]),
            dscovr_position=epic_position,
        )
        sx = 50 + sx * 800 / 1080
        sy = 105 + sy * 800 / 1080
        secondary_label = f'{secondary["name"]}  {secondary_lat:.1f}°, {secondary_lon:.1f}°'
        secondary_marker = marker(sx, sy, secondary_label, "#ffd23f")
        marker_legend = f'red: {title.split(" — ")[0]} · gold: {secondary["name"]} · nearest IBTrACS points'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="990" viewBox="0 0 900 990">
<rect width="900" height="990" fill="#07111d"/>
<text x="50" y="38" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="white">{html.escape(title)}</text>
<text x="50" y="72" font-family="Arial,sans-serif" font-size="19" fill="#b9cad9">EPIC {iso_z(epic_capture)} · {html.escape(marker_legend)}</text>
<image href="{html.escape(epic_name)}" x="50" y="105" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
{marker(ex, ey, label)}
{secondary_marker}
<text x="450" y="950" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NASA DSCOVR EPIC</text>
</svg>
'''
    write_text_if_changed(path, svg)


def write_multi_epic_svg(
    path, title, epic_name, epic_capture, row, epic_center, companions,
    epic_position=None,
):
    """Create an additive EPIC annotation variant with multiple named systems."""
    lat, lon = float(row["LAT"]), float(row["LON"])
    ex, ey = epic_xy(
        lat, lon, float(epic_center["lat"]), float(epic_center["lon"]),
        dscovr_position=epic_position,
    )
    ex = 50 + ex * 800 / 1080
    ey = 105 + ey * 800 / 1080
    primary_label = f'{title.split(" — ")[0]}  {lat:.1f}°, {lon:.1f}°'
    annotations = [marker(ex, ey, primary_label)]
    legend = [f'red: {title.split(" — ")[0]}']
    label_offsets = {
        "MARIE": (18, 70),
        "KARINA": (18, 20),
        "LOWELL": (18, -40),
    }
    for companion in companions:
        companion_row = companion["track"]
        companion_lat = float(companion_row["LAT"])
        companion_lon = float(companion_row["LON"])
        cx, cy = epic_xy(
            companion_lat, companion_lon, float(epic_center["lat"]), float(epic_center["lon"]),
            dscovr_position=epic_position,
        )
        cx = 50 + cx * 800 / 1080
        cy = 105 + cy * 800 / 1080
        color, color_name = COMPANION_MARKER_STYLES[companion["name"].upper()]
        dx, dy = label_offsets[companion["name"].upper()]
        label = f'{companion["name"]}  {companion_lat:.1f}°, {companion_lon:.1f}°'
        annotations.append(marker(cx, cy, label, color, cx + dx, cy + dy))
        legend.append(f'{color_name}: {companion["name"]}')
    legend_text = " · ".join(legend) + " · nearest IBTrACS points"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="990" viewBox="0 0 900 990">
<rect width="900" height="990" fill="#07111d"/>
<text x="50" y="38" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="white">{html.escape(title)}</text>
<text x="50" y="68" font-family="Arial,sans-serif" font-size="18" fill="#b9cad9">EPIC {iso_z(epic_capture)} · multi-storm annotations</text>
<text x="50" y="92" font-family="Arial,sans-serif" font-size="14" fill="#b9cad9">{html.escape(legend_text)}</text>
<image href="{html.escape(epic_name)}" x="50" y="105" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
{''.join(annotations)}
<text x="450" y="950" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NASA DSCOVR EPIC</text>
</svg>
'''
    write_text_if_changed(path, svg)


def write_pair_clean_svg(path, title, epic_name, hima_name, epic_capture, hima_capture):
    """Create a marker-free paired view while retaining timestamps and provenance."""
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1700" height="970" viewBox="0 0 1700 970">
<rect width="1700" height="970" fill="#07111d"/>
<text x="25" y="38" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="white">{html.escape(title)}</text>
<text x="25" y="70" font-family="Arial,sans-serif" font-size="19" fill="#b9cad9">EPIC {iso_z(epic_capture)} · Himawari {iso_z(hima_capture)} · marker-free view</text>
<image href="{html.escape(epic_name)}" x="25" y="90" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
<image href="{html.escape(hima_name)}" x="875" y="90" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
<text x="425" y="930" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NASA DSCOVR EPIC</text>
<text x="1275" y="930" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NICT Himawari full disk</text>
</svg>
'''
    write_text_if_changed(path, svg)


def write_epic_clean_svg(path, title, epic_name, epic_capture):
    """Create a marker-free EPIC view while retaining timestamp and provenance."""
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="990" viewBox="0 0 900 990">
<rect width="900" height="990" fill="#07111d"/>
<text x="50" y="38" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="white">{html.escape(title)}</text>
<text x="50" y="72" font-family="Arial,sans-serif" font-size="19" fill="#b9cad9">EPIC {iso_z(epic_capture)} · marker-free view</text>
<image href="{html.escape(epic_name)}" x="50" y="105" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
<text x="450" y="950" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NASA DSCOVR EPIC</text>
</svg>
'''
    write_text_if_changed(path, svg)


def render_svg(svg_path, width, height):
    """Rasterize a comparison SVG with the locally installed Chrome."""
    png_path = svg_path.with_suffix(".png")
    if png_path.exists() and png_path.stat().st_mtime >= svg_path.stat().st_mtime:
        return png_path
    chrome_candidates = [
        pathlib.Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"),
        pathlib.Path("/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ]
    chrome = next((candidate for candidate in chrome_candidates if candidate.exists()), None)
    if chrome is None:
        raise RuntimeError("Chrome/Edge is required to rasterize comparison SVGs")
    win_svg = subprocess.check_output(["wslpath", "-w", str(svg_path.resolve())], text=True).strip()
    win_png = subprocess.check_output(["wslpath", "-w", str(png_path.resolve())], text=True).strip()
    result = subprocess.run(
        [
            str(chrome), "--headless", "--disable-gpu", "--hide-scrollbars",
            "--allow-file-access-from-files", f"--window-size={width},{height}",
            f"--screenshot={win_png}", f"file:///{win_svg}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode or not png_path.exists():
        raise RuntimeError(f"Could not render {svg_path}: {result.stderr.strip()}")
    return png_path


def clean_html_text(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = html.unescape(fragment).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in fragment.splitlines()]
    return "\n".join(line for line in lines if line)


def high_resolution_wikimedia_url(source, width=1280):
    source = html.unescape(source)
    if source.startswith("//"):
        source = "https:" + source
    source = source.split("?", 1)[0]
    return re.sub(r"/\d+px-", f"/{width}px-", source)


def collect_wikipedia_panels():
    """Extract each matching small storm infobox and its high-resolution assets."""
    WIKI_PANELS.mkdir(parents=True, exist_ok=True)
    panel_specs = [*STORMS, *WIKIPEDIA_COMPANION_SPECS]
    page_html = {}
    for spec in panel_specs:
        if spec["wiki"] in page_html:
            continue
        url = spec["wiki"] + ("&" if "?" in spec["wiki"] else "?") + "useskin=vector-2022"
        body, _ = request_bytes(url)
        page_html[spec["wiki"]] = body.decode("utf-8")

    panels = {}
    download_jobs = []
    for spec in panel_specs:
        page = page_html[spec["wiki"]]
        headings = []
        for match in re.finditer(r"<h3\b([^>]*)>(.*?)</h3>", page, re.S | re.I):
            heading_text = clean_html_text(match.group(2))
            if re.search(rf"\b{re.escape(spec['name'])}\b", heading_text, re.I):
                headings.append((match, heading_text))
        if not headings:
            print(f"No Wikipedia inset heading found for {spec['name']}", flush=True)
            continue
        heading_match, heading_text = headings[0]
        next_heading = re.search(r"<h3\b", page[heading_match.end():], re.I)
        end = heading_match.end() + next_heading.start() if next_heading else len(page)
        section = page[heading_match.end():end]
        table_match = re.search(r'<table class="infobox"[^>]*>(.*?)</table>', section, re.S | re.I)
        if not table_match:
            print(f"No Wikipedia inset table found for {spec['name']}", flush=True)
            continue
        table = table_match.group(1)
        subheader = re.search(
            r'<td[^>]*class="infobox-subheader"[^>]*style="([^"]*)"[^>]*>(.*?)</td>',
            table, re.S | re.I,
        )
        if not subheader:
            print(f"No Wikipedia inset intensity header found for {spec['name']}", flush=True)
            continue
        style, intensity = subheader.groups()
        background_match = re.search(r"background(?:-color)?\s*:\s*([^;]+)", style, re.I)
        background = background_match.group(1).strip() if background_match else "#4DFFFF"

        def table_value(label):
            match = re.search(
                rf'<th[^>]*>\s*{re.escape(label)}\s*</th>\s*<td[^>]*>(.*?)</td>',
                table, re.S | re.I,
            )
            return clean_html_text(match.group(1)) if match else ""

        images = re.findall(
            r'<a href="([^"]+)" class="mw-file-description"[^>]*>\s*<img\b[^>]*src="([^"]+)"[^>]*>',
            table, re.S | re.I,
        )
        if len(images) < 2:
            print(f"Wikipedia inset for {spec['name']} lacks two image assets", flush=True)
            continue

        folder = WIKI_PANELS / spec["group"] / slug(spec["name"])
        folder.mkdir(parents=True, exist_ok=True)
        local_assets = []
        source_links = []
        high_res_urls = []
        for asset_kind, (file_page, thumb) in zip(("satellite", "track"), images[:2]):
            high_res = high_resolution_wikimedia_url(thumb)
            suffix = pathlib.PurePosixPath(urllib.parse.urlparse(high_res).path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                suffix = ".png"
            destination = folder / f"{asset_kind}{suffix}"
            download_jobs.append((high_res, destination, "image/"))
            local_assets.append(destination.relative_to(OUT).as_posix())
            source_links.append(urllib.parse.urljoin(spec["wiki"], html.unescape(file_page)))
            high_res_urls.append(high_res)

        id_match = re.search(r'\bid="([^"]+)"', heading_match.group(1))
        article_anchor = id_match.group(1) if id_match else heading_text.replace(" ", "_")
        panels[spec["name"]] = {
            "storm": spec["name"],
            "heading": heading_text,
            "intensity": clean_html_text(intensity),
            "header_color": background,
            "duration": table_value("Duration"),
            "peak_intensity": table_value("Peak intensity"),
            "satellite_file": local_assets[0],
            "track_file": local_assets[1],
            "satellite_source": source_links[0],
            "track_source": source_links[1],
            "satellite_download_url": high_res_urls[0],
            "track_download_url": high_res_urls[1],
            "article_source": spec["wiki"] + "#" + article_anchor,
        }

    print(f"Downloading {len(download_jobs)} high-resolution Wikipedia inset assets...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(download, *job) for job in download_jobs]
        for future in as_completed(futures):
            future.result()
    write_text_if_changed(
        DATA / "wiki_panels.json", json.dumps(panels, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"Extracted {len(panels)} matching Wikipedia storm insets", flush=True)
    return panels


def format_date_range(start, end):
    if start.year != end.year:
        return f"{start.strftime('%B')} {start.day}, {start.year}–{end.strftime('%B')} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start.strftime('%B')} {start.day}–{end.strftime('%B')} {end.day}, {end.year}"
    return f"{start.strftime('%B')} {start.day}–{end.day}, {end.year}"


def output_relative(path):
    """Return a collection-relative path, tolerating Windows path casing."""
    value = pathlib.Path(path)
    try:
        return value.relative_to(OUT).as_posix()
    except ValueError:
        parts = pathlib.PurePosixPath(str(value).replace("\\", "/")).parts
        lowered = [part.casefold() for part in parts]
        try:
            index = lowered.index("storm_image_pairs")
        except ValueError as exc:
            raise RuntimeError(f"Path is outside the collection: {path}") from exc
        return pathlib.PurePosixPath(*parts[index + 1:]).as_posix()


def write_index(records, wikipedia_panels):
    zoom_by_key = {}
    zoom_metadata_path = DATA / "zoom_frames.json"
    if zoom_metadata_path.exists():
        zoom_metadata = json.loads(zoom_metadata_path.read_text(encoding="utf-8"))
        for storm_name, storm_zoom in zoom_metadata.get("storms", {}).items():
            for frame_zoom in storm_zoom.get("frames", []):
                zoom_by_key[(storm_name.casefold(), int(frame_zoom["frame"]))] = frame_zoom
    by_storm = {}
    for record in records:
        by_storm.setdefault((record["season_group"], record["storm"]), []).append(record)
    group_titles = {
        "australian_region_2025-26": "2025–26 Australian region",
        "south_pacific_2025-26": "2025–26 South Pacific",
        "atlantic_2026": "2026 Atlantic",
    }
    interface_data = []
    for spec in STORMS:
        frames = []
        for item in sorted(by_storm[(spec["group"], spec["name"])], key=lambda row: int(row["frame"])):
            frame_number = int(item["frame"])
            zoom = zoom_by_key.get((spec["name"].casefold(), frame_number))
            frames.append({
                "number": frame_number,
                "comparison": output_relative(item["comparison_file"]),
                "clean_comparison": output_relative(item["clean_comparison_file"]),
                "epic_file": output_relative(item["epic_file"]),
                "epic_url": item["epic_url"],
                "epic_capture": item["epic_capture_utc"],
                "himawari_file": output_relative(item["himawari_file"]) if item["himawari_file"] else "",
                "himawari_url": item["himawari_url"],
                "himawari_capture": item["himawari_capture_utc"],
                "track_time": item["track_time_utc"],
                "lat": float(item["track_lat"]),
                "lon": float(item["track_lon"]),
                "wind_kt": int(item["track_wind_kt"]),
                "note": item.get("observation_note", ""),
                "coincident": {
                    "name": item["coincident_storm"],
                    "track_time": item["coincident_track_time_utc"],
                    "lat": float(item["coincident_track_lat"]),
                    "lon": float(item["coincident_track_lon"]),
                    "wind_kt": int(item["coincident_track_wind_kt"]),
                } if item.get("coincident_storm") else None,
                "companions": json.loads(item.get("visible_companions_json") or "[]"),
                "zoom": {
                    "comparison": zoom["comparison"],
                    "clean_comparison": zoom["clean_comparison"],
                    "epic_file": zoom["epic_source_file"],
                    "epic_zoom_file": zoom["epic_zoom_file"],
                    "epic_url": zoom["epic_source_url"],
                    "himawari_file": zoom["himawari_zoom_file"],
                    "himawari_url": (
                        zoom["himawari_tiles"][0]["url"] if zoom["himawari_tiles"] else ""
                    ),
                    "metadata_file": "data/zoom_frames.json",
                    "half_span_degrees": zoom["half_span_degrees"],
                    "himawari_level": zoom["himawari_tile_level"],
                    "coverage": zoom.get("coverage", "epic_himawari"),
                } if zoom else None,
            })
        interface_data.append({
            "id": slug(spec["name"]),
            "name": spec["name"],
            "basin": spec["basin"],
            "season_group": spec["group"],
            "season_title": group_titles[spec["group"]],
            "date_range": format_date_range(spec["start"], spec["end"]),
            "active_start": spec["start"].date().isoformat(),
            "active_end": spec["end"].date().isoformat(),
            "path": spec["path"],
            "wikipedia_url": spec["wiki"],
            "wikipedia_panel": wikipedia_panels.get(spec["name"]),
            "companion_panels": {
                name: wikipedia_panels[name]
                for name in ASSOCIATED_WIKIPEDIA_PANELS.get(spec["name"].upper(), [])
                if name in wikipedia_panels
            },
            "frames": frames,
        })
    data_json = json.dumps(interface_data, ensure_ascii=False).replace("</", "<\\/")
    page = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Storm Frame Explorer · EPIC + Himawari</title>
<style>
:root{--bg:#07111d;--panel:#0c1a29;--panel2:#102235;--line:#243e56;--text:#edf6ff;--muted:#9db2c6;--cyan:#58d6f7;--blue:#6fa8ff;--red:#ff595e;--radius:16px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 75% -20%,#153b59 0,transparent 38%),var(--bg);color:var(--text);font:15px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
button,input{font:inherit}button,a{color:inherit}.topbar{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid var(--line);background:rgba(7,17,29,.9);backdrop-filter:blur(14px);position:sticky;top:0;z-index:10}
.brand{display:flex;align-items:center;gap:12px}.brand-mark{width:38px;height:38px;border:1px solid #4b7b9e;border-radius:50%;background:radial-gradient(circle at 36% 34%,#9eefff 0 3%,#287da8 4% 13%,#123c5b 14% 25%,transparent 26%),linear-gradient(145deg,#163b56,#07111d);box-shadow:0 0 24px #48c8ff33}.brand strong{display:block;font-size:16px;letter-spacing:.02em}.brand small,.collection-count{color:var(--muted)}
.shell{display:grid;grid-template-columns:285px minmax(0,1fr);max-width:1640px;margin:0 auto;min-height:calc(100vh - 72px)}aside{border-right:1px solid var(--line);padding:24px 18px 40px;position:sticky;top:72px;height:calc(100vh - 72px);overflow:auto}.search{width:100%;border:1px solid var(--line);border-radius:11px;background:#081522;color:var(--text);padding:11px 13px;outline:none}.search:focus{border-color:var(--cyan);box-shadow:0 0 0 3px #58d6f722}.nav-group{margin:22px 0 8px}.nav-group h2{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#7794ad;margin:0 10px 7px}.storm-nav{display:block;width:100%;border:0;border-left:2px solid transparent;background:transparent;text-align:left;padding:9px 10px;border-radius:0 9px 9px 0;color:#b8c9d8;cursor:pointer}.storm-nav:hover{background:#10243a;color:white}.storm-nav.active{border-left-color:var(--cyan);background:#12304a;color:white;font-weight:700}.empty-nav{padding:14px 10px;color:var(--muted)}
main{padding:38px clamp(22px,4vw,64px) 64px;min-width:0}.eyebrow{color:var(--cyan);font-size:12px;text-transform:uppercase;letter-spacing:.13em;font-weight:800}.storm-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;margin:6px 0 22px}.storm-heading h1{font-size:clamp(36px,5vw,66px);line-height:.96;letter-spacing:-.04em;margin:0}.badges{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.badge{border:1px solid var(--line);background:#0d2031;border-radius:999px;padding:6px 10px;color:#c6d9e8;font-size:13px}.wiki-link{display:inline-flex;align-items:center;gap:8px;text-decoration:none;color:#07111d;background:var(--cyan);padding:10px 14px;border-radius:10px;font-weight:800;white-space:nowrap}.wiki-link:hover{background:#8ae8ff}
.path-panel{border:1px solid var(--line);background:linear-gradient(135deg,#0e2235,#0a1725);border-radius:var(--radius);padding:17px 19px;margin-bottom:24px}.path-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px}.path-head strong{font-size:13px;text-transform:uppercase;letter-spacing:.08em}.path-note{font-size:12px;color:var(--muted)}.path{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.path-segment{display:inline-flex;align-items:center;gap:8px;max-width:100%}.path-stop{padding:7px 10px;border:1px solid #36546d;background:#122b40;border-radius:8px}.path-arrow{color:#5f829d;font-weight:800}
.viewer{border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;background:#050b12;box-shadow:0 28px 80px #0006}.stage{position:relative;min-height:320px;display:grid;place-items:center;background:linear-gradient(135deg,#020507,#0b1722)}.stage.loading:after{content:"Loading frame…";position:absolute;color:var(--muted)}.stage img{position:relative;z-index:1;display:block;width:100%;max-height:min(69vh,900px);object-fit:contain}.stage-control{position:absolute;z-index:3;top:50%;transform:translateY(-50%);width:48px;height:64px;border:1px solid #ffffff33;background:#06111ccc;border-radius:12px;color:white;font-size:28px;cursor:pointer;backdrop-filter:blur(8px)}.stage-control:hover{background:#14314a}.stage-control.prev{left:14px}.stage-control.next{right:14px}.frame-pill{position:absolute;z-index:3;right:14px;top:14px;background:#06111cdd;border:1px solid #ffffff2b;border-radius:999px;padding:7px 11px;font-weight:800}.open-image{position:absolute;z-index:3;right:84px;top:14px;background:#06111cdd;border:1px solid #ffffff2b;border-radius:9px;padding:7px 10px;text-decoration:none}.viewer-footer{padding:16px;background:var(--panel);border-top:1px solid var(--line)}.filmstrip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.thumb{display:grid;grid-template-columns:96px 1fr;gap:10px;align-items:center;border:1px solid var(--line);background:#0a1724;color:var(--text);padding:7px;border-radius:11px;text-align:left;cursor:pointer;min-width:0}.thumb:hover{border-color:#54738d}.thumb.active{border-color:var(--cyan);box-shadow:0 0 0 2px #58d6f71f}.thumb img{width:96px;height:58px;object-fit:cover;border-radius:7px;background:black}.thumb strong,.thumb small{display:block}.thumb small{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.details{display:grid;grid-template-columns:1.5fr 1fr;gap:16px;margin-top:18px}.detail-card{border:1px solid var(--line);background:var(--panel);border-radius:var(--radius);padding:18px}.detail-card h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:#a9bed0;margin:0 0 14px}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.fact span{display:block;color:var(--muted);font-size:12px}.fact strong{display:block;font-size:16px;margin-top:2px}.source-links{display:flex;flex-wrap:wrap;gap:8px}.source-links a{border:1px solid var(--line);background:#10243a;border-radius:9px;padding:8px 10px;text-decoration:none}.source-links a:hover{border-color:var(--cyan)}.method-note{color:var(--muted);font-size:13px;margin:18px 2px 0}.keyboard{border:1px solid var(--line);border-radius:6px;padding:1px 6px;color:#c8d9e8;background:#0b1927}
.filmstrip{display:flex;overflow-x:auto}.thumb{flex:1 0 210px}.frame-note{margin:0 0 12px;padding:10px 12px;border:1px solid #a8792d;background:#3d2a0d;color:#ffe4a8;border-radius:9px;font-size:13px}.frame-note[hidden]{display:none}
.viewer-tools{display:flex;flex-direction:column;align-items:flex-end;gap:8px;margin:0 0 10px}.marker-toggle{display:inline-flex;align-items:center;gap:8px;border:1px solid #3d607a;background:#10283b;color:#eaf7ff;border-radius:999px;padding:7px 11px;cursor:pointer;font-weight:800}.marker-toggle:hover:not(:disabled){border-color:var(--cyan)}.marker-toggle:disabled{cursor:not-allowed;opacity:.58}.marker-toggle-dot{width:10px;height:10px;border-radius:50%;background:#ff3b3f;box-shadow:0 0 0 3px #ff3b3f33}.marker-toggle.off{color:#9db2c6;background:#0a1724}.marker-toggle.off .marker-toggle-dot{background:#637688;box-shadow:none}.marker-toggle .keyboard{margin-left:2px;font-size:10px}.zoom-toggle .zoom-toggle-dot{background:#6fa8ff;box-shadow:0 0 0 3px #6fa8ff33}.zoom-toggle.zoomed .zoom-toggle-dot{background:var(--cyan);box-shadow:0 0 0 3px #58d6f733}
.storm-layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:24px;align-items:start}.storm-content{min-width:0}.wiki-reference{position:sticky;top:96px;min-width:0}.wiki-reference[hidden]{display:none}.wiki-rail-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 10px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.09em;font-weight:800}.wiki-rail-head a{color:var(--cyan);text-decoration:none;text-transform:none;letter-spacing:0}.wiki-card{overflow:hidden;border:1px solid #aab4be;background:#f4f6f8;color:#111b25;border-radius:4px;box-shadow:0 18px 45px #0005}.wiki-intensity{padding:10px 12px;text-align:center;font-size:19px;font-weight:800;line-height:1.15}.wiki-media{display:grid;gap:10px;padding:12px}.wiki-media a{display:grid;place-items:center;min-height:120px;background:#e8edf1;border:1px solid #cbd3da;overflow:hidden}.wiki-media img{display:block;width:100%;max-height:270px;object-fit:contain}.wiki-media .track-image{max-height:210px}.wiki-facts{margin:0;padding:4px 14px 14px}.wiki-facts>div{display:grid;grid-template-columns:92px 1fr;gap:10px;padding:9px 0;border-top:1px solid #c8d0d7}.wiki-facts dt{font-weight:800}.wiki-facts dd{margin:0;white-space:pre-line}.wiki-attribution{padding:10px 14px;border-top:1px solid #c8d0d7;background:#e9edf1;color:#485866;font-size:11px}.wiki-attribution a{color:#235c87}.wiki-heading{padding:10px 14px 0;font-weight:800;font-size:15px}
.companion-insets{margin-top:22px}.companion-insets[hidden]{display:none}.companion-stack{display:grid;gap:8px}.companion-card{overflow:hidden;border:1px solid #8797a5;background:#f4f6f8;color:#111b25;border-radius:5px}.companion-card summary{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:9px;padding:10px 11px;cursor:pointer;font-weight:800;list-style:none}.companion-card summary::-webkit-details-marker{display:none}.companion-card summary:after{content:"+";grid-column:3;color:#526574}.companion-card[open] summary:after{content:"−"}.companion-dot{width:10px;height:10px;border-radius:50%;box-shadow:0 0 0 2px #172535}.companion-summary-text{min-width:0}.companion-summary-text small{display:block;color:#526574;font-size:10px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.companion-body{border-top:1px solid #b8c2cb;padding:9px}.companion-media{display:grid;grid-template-columns:1fr 1fr;gap:7px}.companion-media a{display:grid;place-items:center;background:#e2e7eb;border:1px solid #c6ced5;min-height:92px}.companion-media img{display:block;width:100%;height:110px;object-fit:contain}.companion-facts{margin:8px 0 0;font-size:11px}.companion-facts div{padding:5px 0;border-top:1px solid #c7cfd6}.companion-source{display:inline-block;margin-top:7px;color:#235c87;font-size:11px;font-weight:800;text-decoration:none}
@media(max-width:1320px){.storm-layout{grid-template-columns:1fr}.wiki-reference{position:static;max-width:680px}.wiki-media{grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);align-items:center}.wiki-media img{max-height:360px}}
@media(max-width:1050px){.shell{grid-template-columns:230px minmax(0,1fr)}.filmstrip{grid-template-columns:1fr}.thumb{grid-template-columns:72px 1fr}.thumb img{width:72px;height:44px}.details{grid-template-columns:1fr}.facts{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.topbar{padding:0 16px}.collection-count{display:none}.shell{display:block}aside{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:16px}.nav-scroll{display:flex;gap:7px;overflow:auto;padding-top:12px}.nav-group{display:contents}.nav-group h2{display:none}.storm-nav{width:auto;white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:7px 11px}.storm-nav.active{border-color:var(--cyan)}main{padding:26px 16px 48px}.storm-heading{display:block}.wiki-link{margin-top:18px}.path-head{display:block}.path-note{display:block;margin-top:4px}.facts{grid-template-columns:1fr 1fr}.stage-control{width:40px;height:52px}.filmstrip{display:flex;overflow:auto}.thumb{min-width:220px}.wiki-media{grid-template-columns:1fr}.wiki-reference{max-width:none}}
</style>
</head>
<body>
<header class="topbar"><div class="brand"><span class="brand-mark" aria-hidden="true"></span><div><strong>Storm Frame Explorer</strong><small>EPIC + Himawari evidence set</small></div></div><div class="collection-count">__SYSTEM_COUNT__ named systems · __OBS_COUNT__ observations</div></header>
<div class="shell">
<aside aria-label="Storm directory"><input id="storm-search" class="search" type="search" placeholder="Find a named storm…" aria-label="Find a named storm"><nav id="storm-nav" class="nav-scroll"></nav></aside>
<main id="main-content">
<div id="season" class="eyebrow"></div>
<div class="storm-heading"><div><h1 id="storm-name"></h1><div class="badges"><span id="basin" class="badge"></span><span id="date-range" class="badge"></span></div></div><a id="wiki-link" class="wiki-link" target="_blank" rel="noreferrer">Wikipedia source ↗</a></div>
<div class="storm-layout">
<div class="storm-content">
<section class="path-panel" aria-labelledby="path-title"><div class="path-head"><strong id="path-title">Wikipedia path / areas affected</strong><span class="path-note">Source-table order; not a precise chronology</span></div><div id="path" class="path"></div></section>
<section class="viewer" aria-label="Storm frame viewer"><div id="stage" class="stage"><a id="open-image" class="open-image" target="_blank">Open PNG ↗</a><span id="frame-pill" class="frame-pill"></span><button id="prev-frame" class="stage-control prev" aria-label="Previous frame">‹</button><img id="stage-image" alt=""><button id="next-frame" class="stage-control next" aria-label="Next frame">›</button></div><div class="viewer-footer"><div class="viewer-tools"><button id="marker-toggle" class="marker-toggle" type="button" aria-pressed="true"><span class="marker-toggle-dot" aria-hidden="true"></span><span id="marker-toggle-label">Markers on</span><span class="keyboard">M</span></button><button id="zoom-toggle" class="marker-toggle zoom-toggle off" type="button" aria-pressed="false"><span class="marker-toggle-dot zoom-toggle-dot" aria-hidden="true"></span><span id="zoom-toggle-label">Storm zoom</span><span class="keyboard">Z</span></button></div><div id="frame-note" class="frame-note" hidden></div><div id="filmstrip" class="filmstrip"></div></div></section>
<section class="details"><div class="detail-card"><h2>Selected observation</h2><div class="facts"><div class="fact"><span>EPIC capture</span><strong id="epic-time"></strong></div><div class="fact"><span>Himawari capture</span><strong id="hima-time"></strong></div><div class="fact"><span>Nearest track point</span><strong id="track-position"></strong></div><div class="fact"><span>Track time</span><strong id="track-time"></strong></div><div class="fact"><span>Wind at track point</span><strong id="track-wind"></strong></div><div class="fact"><span>Frame</span><strong id="frame-number"></strong></div></div></div><div class="detail-card"><h2>Source files</h2><div id="source-links" class="source-links"></div></div></section>
<p class="method-note">Use <span class="keyboard">←</span> <span class="keyboard">→</span> to change frames, <span class="keyboard">M</span> to toggle all markers, and <span class="keyboard">Z</span> to switch between full disks and available storm-centered zooms. Markers and zoom centers use the nearest NOAA IBTrACS track point; Wikipedia supplies the named-system range and affected-area path. Atlantic systems have EPIC frames only because Himawari does not cover the Atlantic.</p>
</div>
<section id="wiki-panel" class="wiki-reference" hidden aria-label="Wikipedia storm inset">
<div class="wiki-rail-head"><span>Wikipedia storm inset</span><a id="wiki-panel-source" target="_blank" rel="noreferrer">Source ↗</a></div>
<div class="wiki-card"><div id="wiki-intensity" class="wiki-intensity"></div><div id="wiki-heading" class="wiki-heading"></div><div class="wiki-media"><a id="wiki-satellite-link" target="_blank" rel="noreferrer"><img id="wiki-satellite" alt=""></a><a id="wiki-track-link" target="_blank" rel="noreferrer"><img id="wiki-track" class="track-image" alt=""></a></div><dl class="wiki-facts"><div><dt>Duration</dt><dd id="wiki-duration"></dd></div><div><dt>Peak intensity</dt><dd id="wiki-peak"></dd></div></dl><div class="wiki-attribution">Higher-resolution Wikimedia assets. Select an image for its file page, attribution, and license.</div></div>
<div id="companion-insets" class="companion-insets" hidden><div class="wiki-rail-head"><span>Also visible in this frame</span></div><div id="companion-list" class="companion-stack"></div></div>
</section>
</div>
<noscript>This viewer requires JavaScript. The original files and manifest remain available in this folder.</noscript>
</main>
</div>
<script id="storm-data" type="application/json">__STORM_DATA__</script>
<script>
const storms=JSON.parse(document.getElementById('storm-data').textContent);let stormIndex=0,frameIndex=0,markersVisible=true,zoomVisible=false;try{markersVisible=localStorage.getItem('stormMarkersVisible')!=='false';zoomVisible=localStorage.getItem('stormZoomVisible')==='true'}catch(error){}const params=new URLSearchParams(location.search),markerParam=params.get('markers'),viewParam=params.get('view');if(markerParam==='off')markersVisible=false;if(markerParam==='on')markersVisible=true;if(viewParam==='zoom')zoomVisible=true;if(viewParam==='full')zoomVisible=false;
const $=id=>document.getElementById(id);const els={nav:$('storm-nav'),search:$('storm-search'),season:$('season'),name:$('storm-name'),basin:$('basin'),range:$('date-range'),wiki:$('wiki-link'),path:$('path'),stage:$('stage'),image:$('stage-image'),pill:$('frame-pill'),open:$('open-image'),film:$('filmstrip'),note:$('frame-note'),epic:$('epic-time'),hima:$('hima-time'),pos:$('track-position'),trackTime:$('track-time'),wind:$('track-wind'),frame:$('frame-number'),sources:$('source-links'),markerToggle:$('marker-toggle'),markerToggleLabel:$('marker-toggle-label'),zoomToggle:$('zoom-toggle'),zoomToggleLabel:$('zoom-toggle-label'),wikiPanel:$('wiki-panel'),wikiPanelSource:$('wiki-panel-source'),wikiIntensity:$('wiki-intensity'),wikiHeading:$('wiki-heading'),wikiSatellite:$('wiki-satellite'),wikiSatelliteLink:$('wiki-satellite-link'),wikiTrack:$('wiki-track'),wikiTrackLink:$('wiki-track-link'),wikiDuration:$('wiki-duration'),wikiPeak:$('wiki-peak'),companionInsets:$('companion-insets'),companionList:$('companion-list')};
const shortTime=value=>value?new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'UTC'}).format(new Date(value))+' UTC':'Not available';
function renderNav(query=''){const q=query.trim().toLowerCase();els.nav.innerHTML='';const groups=[...new Set(storms.map(s=>s.season_title))];let shown=0;for(const group of groups){const matches=storms.map((s,i)=>({s,i})).filter(x=>x.s.season_title===group&&x.s.name.toLowerCase().includes(q));if(!matches.length)continue;const wrap=document.createElement('div');wrap.className='nav-group';wrap.innerHTML=`<h2>${group}</h2>`;for(const {s,i} of matches){const b=document.createElement('button');b.className='storm-nav'+(i===stormIndex?' active':'');b.textContent=s.name;b.dataset.index=i;b.onclick=()=>showStorm(i,true);wrap.appendChild(b);shown++}els.nav.appendChild(wrap)}if(!shown)els.nav.innerHTML='<div class="empty-nav">No matching storms.</div>'}
function pathMarkup(stops){return stops.map((stop,i)=>`<span class="path-segment">${i?'<span class="path-arrow" aria-hidden="true">→</span>':''}<span class="path-stop">${stop}</span></span>`).join('')}
function contrastColor(value){const match=(value||'').match(/^#?([0-9a-f]{6})$/i);if(!match)return'#07111d';const n=parseInt(match[1],16),r=(n>>16)&255,g=(n>>8)&255,b=n&255;return(r*299+g*587+b*114)/1000>150?'#07111d':'#fff'}
function renderWikipediaPanel(s){const p=s.wikipedia_panel;els.wikiPanel.hidden=!p;if(!p)return;els.wikiPanelSource.href=p.article_source;els.wikiIntensity.textContent=p.intensity;els.wikiIntensity.style.background=p.header_color;els.wikiIntensity.style.color=contrastColor(p.header_color);els.wikiHeading.textContent=`${s.name} · source inset`;els.wikiSatellite.src=p.satellite_file;els.wikiSatellite.alt=`${s.name} satellite image from its Wikipedia inset`;els.wikiSatelliteLink.href=p.satellite_source;els.wikiTrack.src=p.track_file;els.wikiTrack.alt=`${s.name} track map from its Wikipedia inset`;els.wikiTrackLink.href=p.track_source;els.wikiDuration.textContent=p.duration;els.wikiPeak.textContent=p.peak_intensity}
function renderCompanionPanels(s,f){els.companionList.innerHTML='';const companions=f.companions||[];let shown=0;companions.forEach((c,i)=>{const p=(s.companion_panels||{})[c.name];if(!p)return;const card=document.createElement('details');card.className='companion-card';card.open=i===0;card.innerHTML=`<summary><span class="companion-dot" style="background:${c.color}"></span><span class="companion-summary-text">${c.name}<small>${p.intensity}</small></span></summary><div class="companion-body"><div class="companion-media"><a href="${p.satellite_source}" target="_blank" rel="noreferrer"><img src="${p.satellite_file}" alt="${c.name} satellite image from Wikipedia inset" loading="lazy"></a><a href="${p.track_source}" target="_blank" rel="noreferrer"><img src="${p.track_file}" alt="${c.name} track map from Wikipedia inset" loading="lazy"></a></div><div class="companion-facts"><div><strong>Frame fix:</strong> ${Math.abs(c.lat).toFixed(1)}°${c.lat<0?'S':'N'}, ${Math.abs(c.lon).toFixed(1)}°${c.lon<0?'W':'E'} · ${c.wind_kt} kt</div><div><strong>Duration:</strong> ${p.duration}</div><div><strong>Peak:</strong> ${p.peak_intensity}</div></div><a class="companion-source" href="${p.article_source}" target="_blank" rel="noreferrer">Wikipedia source ↗</a></div>`;els.companionList.appendChild(card);shown++});els.companionInsets.hidden=!shown}
function syncMarkerToggle(){els.markerToggle.setAttribute('aria-pressed',String(markersVisible));els.markerToggle.classList.toggle('off',!markersVisible);els.markerToggleLabel.textContent=markersVisible?'Markers on':'Markers off';els.markerToggle.setAttribute('aria-label',markersVisible?'Hide markers on all storm frames':'Show markers on all storm frames')}
function toggleMarkers(){markersVisible=!markersVisible;try{localStorage.setItem('stormMarkersVisible',String(markersVisible))}catch(error){}syncMarkerToggle();renderFrame()}
function syncZoomToggle(f){const available=Boolean(f&&f.zoom),active=available&&zoomVisible;els.zoomToggle.disabled=!available;els.zoomToggle.setAttribute('aria-pressed',String(active));els.zoomToggle.classList.toggle('off',!active);els.zoomToggle.classList.toggle('zoomed',active);els.zoomToggleLabel.textContent=available?(active?'Full disks':'Storm zoom'):'Zoom unavailable';els.zoomToggle.setAttribute('aria-label',available?(active?'Show full-disk satellite comparison':'Show storm-centered satellite zoom'):'Storm zoom is not available for this observation')}
function toggleZoom(){const f=storms[stormIndex].frames[frameIndex];if(!f.zoom)return;zoomVisible=!zoomVisible;try{localStorage.setItem('stormZoomVisible',String(zoomVisible))}catch(error){}renderFrame()}
function showStorm(index,updateHash=false){stormIndex=(index+storms.length)%storms.length;frameIndex=0;const s=storms[stormIndex];els.season.textContent=s.season_title;els.name.textContent=s.name;els.basin.textContent=s.basin;els.range.textContent=s.date_range;els.wiki.href=s.wikipedia_url;els.wiki.setAttribute('aria-label',`Open Wikipedia source for ${s.name}`);els.path.innerHTML=pathMarkup(s.path);renderWikipediaPanel(s);renderFrame();renderNav(els.search.value);if(updateHash)history.replaceState(null,'','#'+s.id);document.title=`${s.name} · Storm Frame Explorer`}
function renderFrame(){const s=storms[stormIndex],f=s.frames[frameIndex],zoomActive=zoomVisible&&Boolean(f.zoom),view=zoomActive?f.zoom:f,displayImage=markersVisible?view.comparison:view.clean_comparison;renderCompanionPanels(s,f);syncZoomToggle(f);els.stage.classList.add('loading');els.image.onload=()=>els.stage.classList.remove('loading');els.image.src=displayImage;els.image.alt=`${s.name}, observation ${f.number}: ${markersVisible?'annotated':'marker-free'} ${zoomActive?'storm-centered zoom':'full-disk'} satellite comparison`;els.open.href=displayImage;els.pill.textContent=`${f.number} / ${s.frames.length}`;els.note.hidden=!f.note;els.note.textContent=f.note||'';els.epic.textContent=shortTime(f.epic_capture);els.hima.textContent=f.himawari_capture?shortTime(f.himawari_capture):'Outside coverage';els.pos.textContent=`${Math.abs(f.lat).toFixed(1)}°${f.lat<0?'S':'N'}, ${Math.abs(f.lon).toFixed(1)}°${f.lon<0?'W':'E'}`;els.trackTime.textContent=shortTime(f.track_time);els.wind.textContent=`${f.wind_kt} kt`;els.frame.textContent=`Observation ${f.number} of ${s.frames.length}`;els.sources.innerHTML=zoomActive?`<a href="${f.zoom.epic_file}" target="_blank">EPIC 2048px source ↗</a><a href="${f.zoom.epic_zoom_file}" target="_blank">EPIC zoom crop ↗</a>${f.zoom.himawari_file?`<a href="${f.zoom.himawari_file}" target="_blank">Himawari 20d zoom ↗</a>`:''}<a href="${f.zoom.epic_url}" target="_blank" rel="noreferrer">EPIC PNG archive ↗</a>${f.zoom.himawari_url?`<a href="${f.zoom.himawari_url}" target="_blank" rel="noreferrer">Himawari source tile ↗</a>`:''}<a href="${f.zoom.metadata_file}" target="_blank">Zoom provenance ↗</a>`:`<a href="${f.epic_file}" target="_blank">EPIC original ↗</a>${f.himawari_file?`<a href="${f.himawari_file}" target="_blank">Himawari original ↗</a>`:''}<a href="${f.epic_url}" target="_blank" rel="noreferrer">EPIC archive ↗</a>${f.himawari_url?`<a href="${f.himawari_url}" target="_blank" rel="noreferrer">Himawari archive ↗</a>`:''}`;els.film.innerHTML='';s.frames.forEach((item,i)=>{const itemView=zoomVisible&&item.zoom?item.zoom:item,b=document.createElement('button');b.className='thumb'+(i===frameIndex?' active':'');b.setAttribute('aria-label',`Show ${s.name} observation ${item.number}`);b.innerHTML=`<img src="${markersVisible?itemView.comparison:itemView.clean_comparison}" alt="" loading="lazy"><span><strong>Observation ${item.number}</strong><small>${shortTime(item.epic_capture)}</small></span>`;b.onclick=()=>{frameIndex=i;renderFrame()};els.film.appendChild(b)})}
function stepFrame(delta){const total=storms[stormIndex].frames.length;frameIndex=(frameIndex+delta+total)%total;renderFrame()}
$('prev-frame').onclick=()=>stepFrame(-1);$('next-frame').onclick=()=>stepFrame(1);els.markerToggle.onclick=toggleMarkers;els.zoomToggle.onclick=toggleZoom;els.search.addEventListener('input',e=>renderNav(e.target.value));window.addEventListener('keydown',e=>{if(e.target.matches('input,button,a'))return;if(e.key==='ArrowLeft')stepFrame(-1);if(e.key==='ArrowRight')stepFrame(1);if(e.key.toLowerCase()==='m')toggleMarkers();if(e.key.toLowerCase()==='z')toggleZoom()});window.addEventListener('hashchange',()=>{const id=decodeURIComponent(location.hash.slice(1));const i=storms.findIndex(s=>s.id===id);if(i>=0)showStorm(i,false)});
syncMarkerToggle();const initial=storms.findIndex(s=>s.id===decodeURIComponent(location.hash.slice(1)));showStorm(initial>=0?initial:0,false);
</script>
</body></html>'''.replace("__STORM_DATA__", data_json).replace("__SYSTEM_COUNT__", str(len(interface_data))).replace("__OBS_COUNT__", str(len(records)))
    write_text_if_changed(OUT / "index.html", page)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)
    ibtracs_path = DATA / "ibtracs.last3years.list.v04r01.csv"
    print("Downloading/loading IBTrACS...", flush=True)
    download(IBTRACS_URL, ibtracs_path, "text/csv")

    companion_names = {name for names in VISIBLE_COMPANION_MARKERS.values() for name in names}
    requested = (
        {item["name"].upper() for item in STORMS}
        | set(COINCIDENT_MARKERS.values())
        | companion_names
    )
    all_tracks = {name: [] for name in requested}
    with ibtracs_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        next(reader)  # units row
        for row in reader:
            name = row["NAME"].upper()
            if name not in requested or not row["ISO_TIME"].startswith(("2025", "2026")):
                continue
            row["_time"] = parse_time(row["ISO_TIME"])
            all_tracks[name].append(row)

    epic_cache = {}
    selections = []
    for spec in STORMS:
        name = spec["name"].upper()
        rows = [row for row in all_tracks[name] if spec["start"] <= row["_time"] <= spec["end"]]
        if not rows:
            raise RuntimeError(f"No IBTrACS rows for {spec['name']}")
        targets = choose_track_targets(rows, spec["start"], spec["end"])
        used = set()
        for frame, target in enumerate(targets, 1):
            chosen = select_epic_image(target, rows, spec["start"], spec["end"], epic_cache, used)
            selections.append({
                "spec": spec, "frame": frame, "observation_note": "", "is_remnant": False, **chosen
            })
        for extra_number, extra in enumerate(EXTRA_EPIC_FRAMES.get(name, []), len(targets) + 1):
            capture = parse_time(extra["capture"])
            metadata = load_epic_metadata(capture.date(), epic_cache)
            item = min(metadata, key=lambda candidate: abs((parse_time(candidate["date"]) - capture).total_seconds()))
            actual_capture = parse_time(item["date"])
            row = nearest_track(rows, actual_capture)
            center = item["centroid_coordinates"]
            distance = angular_distance(
                float(row["LAT"]), float(row["LON"]), float(center["lat"]), float(center["lon"])
            )
            selections.append({
                "spec": spec,
                "frame": extra_number,
                "observation_note": extra["note"],
                "is_remnant": extra.get("is_remnant", False),
                "item": item,
                "capture": actual_capture,
                "track": row,
                "view_angle": distance,
            })
        selected_count = len(targets) + len(EXTRA_EPIC_FRAMES.get(name, []))
        print(f"Selected {selected_count} EPIC views for {spec['name']}", flush=True)

    for selected in selections:
        key = (selected["spec"]["name"].upper(), selected["frame"])
        secondary_name = COINCIDENT_MARKERS.get(key)
        selected["secondary"] = None
        selected["companions"] = []
        if secondary_name:
            secondary_row = nearest_track(all_tracks[secondary_name], selected["capture"])
            gap_hours = abs((secondary_row["_time"] - selected["capture"]).total_seconds()) / 3600
            if gap_hours > 6:
                raise RuntimeError(f"No contemporaneous {secondary_name} fix for {key}")
            selected["secondary"] = {
                "name": secondary_name.title(),
                "track": secondary_row,
            }
            secondary_type = "Hurricane" if wind(secondary_row) >= 64 else "Tropical Storm"
            selected["observation_note"] = (
                f"Concurrent East Pacific {secondary_type} {secondary_name.title()} is marked in gold; "
                "both markers use their nearest IBTrACS fixes."
            )
        for companion_name in VISIBLE_COMPANION_MARKERS.get(key, []):
            companion_row = nearest_track(all_tracks[companion_name], selected["capture"])
            gap_hours = abs((companion_row["_time"] - selected["capture"]).total_seconds()) / 3600
            if gap_hours > 6:
                raise RuntimeError(f"No contemporaneous {companion_name} fix for {key}")
            center = selected["item"]["centroid_coordinates"]
            view_angle = angular_distance(
                float(companion_row["LAT"]), float(companion_row["LON"]),
                float(center["lat"]), float(center["lon"]),
            )
            if view_angle > 83:
                raise RuntimeError(f"{companion_name} is beyond EPIC's usable limb for {key}: {view_angle:.1f}°")
            color, color_name = COMPANION_MARKER_STYLES[companion_name]
            selected["companions"].append({
                "name": companion_name.title(),
                "track": companion_row,
                "view_angle": view_angle,
                "color": color,
                "color_name": color_name,
            })
        if selected["companions"]:
            labels = ", ".join(
                f'{item["name"]} in {item["color_name"]}' for item in selected["companions"]
            )
            selected["observation_note"] = (
                f"Other Pacific systems visible in this EPIC frame: {labels}; "
                "all markers use their nearest IBTrACS fixes."
            )

    download_jobs = []
    for selected in selections:
        spec, item, frame = selected["spec"], selected["item"], selected["frame"]
        folder = IMAGES / spec["group"] / slug(spec["name"])
        folder.mkdir(parents=True, exist_ok=True)
        stamp = selected["capture"].strftime("%Y%m%dT%H%M%SZ")
        epic_path = folder / f"{frame:02d}_epic_{stamp}.jpg"
        capture = selected["capture"]
        epic_url = EPIC_ARCHIVE.format(
            year=capture.strftime("%Y"), month=capture.strftime("%m"), day=capture.strftime("%d"), name=item["image"]
        )
        selected["folder"] = folder
        selected["epic_path"] = epic_path
        selected["epic_url"] = epic_url
        download_jobs.append((epic_url, epic_path, "image/jpeg"))

    print(f"Downloading {len(download_jobs)} EPIC source images...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(download, *job) for job in download_jobs]
        for future in as_completed(futures):
            future.result()

    southern = [selected for selected in selections if selected["spec"]["group"] != "atlantic_2026"]
    print(f"Downloading {len(southern)} matching Himawari source images...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {}
        for selected in southern:
            provisional = round_ten_minutes(selected["capture"])
            path = selected["folder"] / f'{selected["frame"]:02d}_himawari_{provisional.strftime("%Y%m%dT%H%M%SZ")}.png'
            future_map[pool.submit(fetch_himawari, selected["capture"], path)] = (selected, path)
        for future in as_completed(future_map):
            selected, provisional_path = future_map[future]
            hima_capture, hima_url = future.result()
            actual_path = selected["folder"] / f'{selected["frame"]:02d}_himawari_{hima_capture.strftime("%Y%m%dT%H%M%SZ")}.png'
            if provisional_path != actual_path:
                provisional_path.replace(actual_path)
            selected["hima_capture"] = hima_capture
            selected["hima_url"] = hima_url
            selected["hima_path"] = actual_path

    records = []
    for selected in selections:
        spec, row, item = selected["spec"], selected["track"], selected["item"]
        title_name = f'{spec["name"]} remnant' if selected["is_remnant"] else spec["name"]
        title = f'{title_name} — frame {selected["frame"]}'
        comparison_svg = selected["folder"] / f'{selected["frame"]:02d}_comparison.svg'
        if selected["companions"]:
            comparison_svg = selected["folder"] / f'{selected["frame"]:02d}_comparison_enriched.svg'
            write_multi_epic_svg(
                comparison_svg, title, selected["epic_path"].name, selected["capture"], row,
                item["centroid_coordinates"], selected["companions"],
                item.get("dscovr_j2000_position"),
            )
            comparison = render_svg(comparison_svg, 900, 990)
            hima_capture = hima_url = hima_path = ""
        elif spec["group"] == "atlantic_2026":
            write_epic_svg(
                comparison_svg, title, selected["epic_path"].name, selected["capture"], row,
                item["centroid_coordinates"], selected["secondary"],
                item.get("dscovr_j2000_position"),
            )
            comparison = render_svg(comparison_svg, 900, 990)
            hima_capture = hima_url = hima_path = ""
        else:
            write_pair_svg(
                comparison_svg, title, selected["epic_path"].name, selected["hima_path"].name,
                selected["capture"], selected["hima_capture"], row, item["centroid_coordinates"],
                item.get("dscovr_j2000_position"),
            )
            comparison = render_svg(comparison_svg, 1700, 970)
            hima_capture = iso_z(selected["hima_capture"])
            hima_url = selected["hima_url"]
            hima_path = str(selected["hima_path"])
        clean_comparison_svg = selected["folder"] / f'{selected["frame"]:02d}_comparison_clean.svg'
        if spec["group"] == "atlantic_2026":
            write_epic_clean_svg(
                clean_comparison_svg, title, selected["epic_path"].name, selected["capture"]
            )
            clean_comparison = render_svg(clean_comparison_svg, 900, 990)
        else:
            write_pair_clean_svg(
                clean_comparison_svg, title, selected["epic_path"].name, selected["hima_path"].name,
                selected["capture"], selected["hima_capture"],
            )
            clean_comparison = render_svg(clean_comparison_svg, 1700, 970)
        records.append({
            "season_group": spec["group"],
            "basin": spec["basin"],
            "storm": spec["name"],
            "active_window_utc": f'{spec["start"].date().isoformat()}/{spec["end"].date().isoformat()}',
            "frame": selected["frame"],
            "ibtracs_sid": row["SID"],
            "track_time_utc": iso_z(row["_time"]),
            "track_lat": row["LAT"],
            "track_lon": row["LON"],
            "track_wind_kt": f"{wind(row):.0f}",
            "epic_capture_utc": iso_z(selected["capture"]),
            "epic_view_angle_deg": f'{selected["view_angle"]:.1f}',
            "epic_centroid_lat": item["centroid_coordinates"]["lat"],
            "epic_centroid_lon": item["centroid_coordinates"]["lon"],
            "epic_file": str(selected["epic_path"]),
            "epic_url": selected["epic_url"],
            "himawari_capture_utc": hima_capture,
            "himawari_file": hima_path,
            "himawari_url": hima_url,
            "comparison_file": str(comparison),
            "comparison_svg_file": str(comparison_svg),
            "clean_comparison_file": str(clean_comparison),
            "clean_comparison_svg_file": str(clean_comparison_svg),
            "observation_note": selected["observation_note"],
            "coincident_storm": selected["secondary"]["name"] if selected["secondary"] else "",
            "coincident_sid": selected["secondary"]["track"]["SID"] if selected["secondary"] else "",
            "coincident_track_time_utc": iso_z(selected["secondary"]["track"]["_time"]) if selected["secondary"] else "",
            "coincident_track_lat": selected["secondary"]["track"]["LAT"] if selected["secondary"] else "",
            "coincident_track_lon": selected["secondary"]["track"]["LON"] if selected["secondary"] else "",
            "coincident_track_wind_kt": f'{wind(selected["secondary"]["track"]):.0f}' if selected["secondary"] else "",
            "visible_companions_json": json.dumps([
                {
                    "name": companion["name"],
                    "sid": companion["track"]["SID"],
                    "track_time": iso_z(companion["track"]["_time"]),
                    "lat": float(companion["track"]["LAT"]),
                    "lon": float(companion["track"]["LON"]),
                    "wind_kt": int(wind(companion["track"])),
                    "view_angle_deg": round(companion["view_angle"], 1),
                    "color": companion["color"],
                    "color_name": companion["color_name"],
                }
                for companion in selected["companions"]
            ], ensure_ascii=False, separators=(",", ":")),
            "wikipedia_path": " → ".join(spec["path"]),
            "name_source": spec["wiki"],
            "track_source": IBTRACS_URL,
        })
        expected_count = 3 + len(EXTRA_EPIC_FRAMES.get(spec["name"].upper(), []))
        if selected["frame"] == expected_count:
            print(f"Rendered viewer frames for {spec['name']}", flush=True)

    fields = list(records[0])
    with (OUT / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    with (OUT / "named_storms.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["season_group", "basin", "storm", "active_start", "active_end", "wikipedia_path", "name_source"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for spec in STORMS:
            writer.writerow({
                "season_group": spec["group"], "basin": spec["basin"], "storm": spec["name"],
                "active_start": spec["start"].date(), "active_end": spec["end"].date(),
                "wikipedia_path": " → ".join(spec["path"]), "name_source": spec["wiki"],
            })
    wikipedia_panels = collect_wikipedia_panels()
    write_index(records, wikipedia_panels)
    print(f"Done: {len(STORMS)} storms, {len(records)} selected observations", flush=True)


def render_existing_index():
    """Rebuild only the viewer from existing manifests and sidecar metadata."""
    manifest_path = OUT / "manifest.csv"
    panels_path = DATA / "wiki_panels.json"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    wikipedia_panels = json.loads(panels_path.read_text(encoding="utf-8"))
    write_index(records, wikipedia_panels)
    print(f"Rebuilt viewer only: {OUT / 'index.html'}", flush=True)


def repair_epic_markers(storm_name):
    """Repair simple EPIC-only marker frames using per-capture disk scale."""
    manifest_path = OUT / "manifest.csv"
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        records = [
            row for row in csv.DictReader(handle)
            if row["storm"].casefold() == storm_name.casefold()
        ]
    if not records:
        raise RuntimeError(f"No manifest frames found for {storm_name!r}")
    for record in records:
        if record["himawari_file"] or record.get("coincident_storm") or record.get("visible_companions_json") not in {"", "[]"}:
            raise RuntimeError(
                f"Targeted repair currently supports simple EPIC-only frames: {storm_name} frame {record['frame']}"
            )
        epic_path = OUT / output_relative(record["epic_file"])
        comparison_svg = OUT / output_relative(record["comparison_svg_file"])
        epic_position = embedded_epic_position(epic_path)
        row = {"LAT": record["track_lat"], "LON": record["track_lon"]}
        epic_center = {
            "lat": float(record["epic_centroid_lat"]),
            "lon": float(record["epic_centroid_lon"]),
        }
        title = f'{record["storm"]} — frame {record["frame"]}'
        epic_capture = dt.datetime.fromisoformat(
            record["epic_capture_utc"].replace("Z", "+00:00")
        )
        write_epic_svg(
            comparison_svg, title, epic_path.name, epic_capture,
            row, epic_center, epic_position=epic_position,
        )
        render_svg(comparison_svg, 900, 990)
        print(f'Repaired {record["storm"]} marker frame {record["frame"]}', flush=True)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--render-index-only", action="store_true",
        help="Rebuild index.html from existing manifests without downloading or regenerating data",
    )
    actions.add_argument(
        "--repair-epic-markers", metavar="STORM",
        help="Repair existing simple EPIC-only markers using the capture-specific disk scale",
    )
    args = parser.parse_args()
    if args.render_index_only:
        render_existing_index()
    elif args.repair_epic_markers:
        repair_epic_markers(args.repair_epic_markers)
    else:
        main()


if __name__ == "__main__":
    cli()
