#!/usr/bin/env python3
"""Add storm-centered high-resolution zoom assets without touching originals.

The primary collection remains authoritative for frame selection and timing.
This tool reads those records, downloads higher-resolution source imagery into
an additive ``zoom`` directory, and writes a sidecar metadata file consumed by
the viewer.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import pathlib
import re
import struct

import pull_storm_images as base


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "storm_image_pairs"
DATA = OUT / "data"
MANIFEST = OUT / "manifest.csv"

HIMAWARI_LEVEL = 20
HIMAWARI_TILE_SIZE = 550
HIMAWARI_FULL_SIZE = HIMAWARI_LEVEL * HIMAWARI_TILE_SIZE
HIMAWARI_TILE_URL = (
    "https://himawari.asia/img/D531106/{level}d/{tile_size}/"
    "{year}/{month}/{day}/{clock}_{x}_{y}.png"
)
EPIC_SOURCE_SIZE = 2048
ZOOM_OUTPUT_SIZE = 1600
DEFAULT_HALF_SPAN_DEGREES = 10.0


def png_header(value):
    """Return (width, height, bit depth, color type) from PNG bytes or a file."""
    if isinstance(value, pathlib.Path):
        with value.open("rb") as handle:
            value = handle.read(29)
    if len(value) < 29 or value[:8] != b"\x89PNG\r\n\x1a\n" or value[12:16] != b"IHDR":
        raise RuntimeError("Response is not a valid PNG")
    width, height = struct.unpack(">II", value[16:24])
    return width, height, value[24], value[25]


def download_new_png(
    url, destination, expected_size, require_color=True, allow_placeholder=False
):
    """Download a PNG idempotently, optionally skipping archive placeholders."""
    destination = pathlib.Path(destination)
    if destination.exists():
        dimensions = png_header(destination)
        if dimensions[:2] != expected_size:
            raise RuntimeError(f"Existing file has unexpected dimensions: {destination}: {dimensions[:2]}")
        if require_color and dimensions[3] not in {2, 3, 6}:
            if allow_placeholder:
                return None
            raise RuntimeError(f"Existing file is a placeholder rather than color imagery: {destination}")
        return destination

    body, content_type = base.request_bytes(url)
    if "image/png" not in content_type:
        raise RuntimeError(f"Unexpected content type {content_type!r} for {url}")
    dimensions = png_header(body)
    if dimensions[:2] != expected_size:
        raise RuntimeError(f"Unexpected PNG dimensions {dimensions[:2]} for {url}")
    if require_color and dimensions[3] not in {2, 3, 6}:
        if allow_placeholder:
            return None
        raise RuntimeError(f"NICT returned its non-color placeholder for {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(body)
    temporary.replace(destination)
    return destination


def relative(path):
    return pathlib.Path(path).relative_to(OUT).as_posix()


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


def projected_square(project, lat, lon, half_span, full_size):
    """Create a square pixel crop containing a geographic box around a point."""
    center_x, center_y = project(lat, lon)
    samples = []
    for sample_lat in (lat - half_span, lat, lat + half_span):
        for sample_lon in (lon - half_span, lon, lon + half_span):
            samples.append(project(sample_lat, sample_lon))
    radius = max(
        max(abs(x - center_x) for x, _ in samples),
        max(abs(y - center_y) for _, y in samples),
    )
    size = int(math.ceil(radius * 2))
    if size % 2:
        size += 1
    left = int(math.floor(center_x - size / 2))
    top = int(math.floor(center_y - size / 2))
    left = max(0, min(left, full_size - size))
    top = max(0, min(top, full_size - size))
    return {
        "left": left,
        "top": top,
        "size": size,
        "center_x": round(center_x, 3),
        "center_y": round(center_y, 3),
    }


def write_epic_crop_svg(path, source_name, crop):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{ZOOM_OUTPUT_SIZE}" height="{ZOOM_OUTPUT_SIZE}" viewBox="{crop["left"]} {crop["top"]} {crop["size"]} {crop["size"]}">
<rect x="{crop["left"]}" y="{crop["top"]}" width="{crop["size"]}" height="{crop["size"]}" fill="black"/>
<image href="{html.escape(source_name)}" x="0" y="0" width="{EPIC_SOURCE_SIZE}" height="{EPIC_SOURCE_SIZE}" preserveAspectRatio="none"/>
</svg>
'''
    base.write_text_if_changed(path, svg)


def write_himawari_crop_svg(path, tile_entries, crop):
    images = []
    for entry in tile_entries:
        images.append(
            f'<image href="{html.escape(entry["svg_href"])}" '
            f'x="{entry["x"] * HIMAWARI_TILE_SIZE}" y="{entry["y"] * HIMAWARI_TILE_SIZE}" '
            f'width="{HIMAWARI_TILE_SIZE}" height="{HIMAWARI_TILE_SIZE}" preserveAspectRatio="none"/>'
        )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{crop["size"]}" height="{crop["size"]}" viewBox="{crop["left"]} {crop["top"]} {crop["size"]} {crop["size"]}">
<rect x="{crop["left"]}" y="{crop["top"]}" width="{crop["size"]}" height="{crop["size"]}" fill="black"/>
{''.join(images)}
</svg>
'''
    base.write_text_if_changed(path, svg)


def write_zoom_comparison_svg(
    path, storm, frame, epic_name, himawari_name, epic_capture, himawari_capture,
    lat, lon, half_span, markers,
):
    title = f"{storm} — frame {frame} · storm zoom"
    span = half_span * 2
    label = f"{storm}  {lat:.1f}°, {lon:.1f}°"
    annotations = ""
    if markers:
        annotations = base.marker(425, 490, label) + base.marker(1275, 490, label)
    view_label = "red marker: nearest IBTrACS point" if markers else "marker-free view"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1700" height="970" viewBox="0 0 1700 970" data-render-version="2">
<rect width="1700" height="970" fill="#07111d"/>
<text x="25" y="38" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="white">{html.escape(title)}</text>
<text x="25" y="70" font-family="Arial,sans-serif" font-size="19" fill="#b9cad9">EPIC {html.escape(epic_capture)} · Himawari {html.escape(himawari_capture)} · {span:g}° storm-centered window · {view_label}</text>
<image href="{html.escape(epic_name)}" x="25" y="90" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
<image href="{html.escape(himawari_name)}" x="875" y="90" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
{annotations}
<text x="425" y="930" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NASA DSCOVR EPIC · 2048px source</text>
<text x="1275" y="930" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NICT Himawari · 20d high resolution</text>
</svg>
'''
    base.write_text_if_changed(path, svg)


def write_epic_zoom_comparison_svg(
    path, storm, frame, epic_name, epic_capture, lat, lon, half_span, markers,
):
    title = f"{storm} — frame {frame} · storm zoom"
    span = half_span * 2
    label = f"{storm}  {lat:.1f}°, {lon:.1f}°"
    annotations = base.marker(450, 505, label) if markers else ""
    view_label = "red marker: nearest IBTrACS point" if markers else "marker-free view"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="990" viewBox="0 0 900 990" data-render-version="1">
<rect width="900" height="990" fill="#07111d"/>
<text x="50" y="38" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="white">{html.escape(title)}</text>
<text x="50" y="72" font-family="Arial,sans-serif" font-size="18" fill="#b9cad9">EPIC {html.escape(epic_capture)} · {span:g}° storm-centered window · {view_label}</text>
<image href="{html.escape(epic_name)}" x="50" y="105" width="800" height="800" preserveAspectRatio="xMidYMid meet"/>
{annotations}
<text x="450" y="950" text-anchor="middle" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="white">NASA DSCOVR EPIC · 2048px source</text>
</svg>
'''
    base.write_text_if_changed(path, svg)


def load_manifest(storm):
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        records = [row for row in csv.DictReader(handle) if row["storm"].casefold() == storm.casefold()]
    if not records:
        raise RuntimeError(f"No frames for {storm!r} in {MANIFEST}")
    return sorted(records, key=lambda row: int(row["frame"]))


def manifest_storms():
    """Return named storms in their manifest order."""
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        names = [row["storm"] for row in csv.DictReader(handle)]
    return list(dict.fromkeys(names))


def load_zoom_metadata():
    metadata_path = DATA / "zoom_frames.json"
    metadata = {"version": 1, "storms": {}}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.setdefault("version", 1)
        metadata.setdefault("storms", {})
    return metadata_path, metadata


def has_complete_zoom_metadata(metadata, storm):
    expected = {int(row["frame"]) for row in load_manifest(storm)}
    actual = {
        int(frame["frame"])
        for frame in metadata.get("storms", {}).get(storm, {}).get("frames", [])
    }
    return actual == expected


def enrich_frame(record, half_span):
    storm = record["storm"]
    frame = int(record["frame"])
    lat = float(record["track_lat"])
    lon = float(record["track_lon"])
    epic_center_lat = float(record["epic_centroid_lat"])
    epic_center_lon = float(record["epic_centroid_lon"])
    epic_capture = record["epic_capture_utc"]
    himawari_capture = record["himawari_capture_utc"]

    storm_folder = OUT / "images" / record["season_group"] / base.slug(storm)
    zoom_folder = storm_folder / "zoom"
    tile_folder = zoom_folder / "source_tiles" / f"{frame:02d}"
    zoom_folder.mkdir(parents=True, exist_ok=True)

    epic_url = record["epic_url"].replace("/jpg/", "/png/").removesuffix(".jpg") + ".png"
    epic_stamp = epic_capture.replace("-", "").replace(":", "")
    epic_source = zoom_folder / f"{frame:02d}_epic_{epic_stamp}_2048.png"
    download_new_png(epic_url, epic_source, (EPIC_SOURCE_SIZE, EPIC_SOURCE_SIZE))
    epic_position = embedded_epic_position(epic_source)

    epic_project = lambda sample_lat, sample_lon: base.epic_xy(
        sample_lat, sample_lon, epic_center_lat, epic_center_lon, EPIC_SOURCE_SIZE,
        epic_position,
    )
    epic_crop = projected_square(epic_project, lat, lon, half_span, EPIC_SOURCE_SIZE)
    epic_zoom_svg = zoom_folder / f"{frame:02d}_epic_zoom.svg"
    write_epic_crop_svg(epic_zoom_svg, epic_source.name, epic_crop)
    epic_zoom = base.render_svg(epic_zoom_svg, ZOOM_OUTPUT_SIZE, ZOOM_OUTPUT_SIZE)

    tile_entries = []
    placeholder_tiles = []
    comparison_svg = zoom_folder / f"{frame:02d}_comparison_zoom.svg"
    clean_svg = zoom_folder / f"{frame:02d}_comparison_zoom_clean.svg"
    himawari_crop = None
    himawari_zoom = None
    comparison_size = (900, 990)
    if himawari_capture:
        himawari_project = lambda sample_lat, sample_lon: base.himawari_xy(
            sample_lat, sample_lon, HIMAWARI_FULL_SIZE
        )
        himawari_crop = projected_square(
            himawari_project, lat, lon, half_span, HIMAWARI_FULL_SIZE
        )
        first_x = max(0, himawari_crop["left"] // HIMAWARI_TILE_SIZE)
        last_x = min(
            HIMAWARI_LEVEL - 1,
            (himawari_crop["left"] + himawari_crop["size"] - 1) // HIMAWARI_TILE_SIZE,
        )
        first_y = max(0, himawari_crop["top"] // HIMAWARI_TILE_SIZE)
        last_y = min(
            HIMAWARI_LEVEL - 1,
            (himawari_crop["top"] + himawari_crop["size"] - 1) // HIMAWARI_TILE_SIZE,
        )
        capture_date, capture_clock = himawari_capture.split("T")
        clock = capture_clock.replace(":", "").removesuffix("Z")
        year, month, day = capture_date.split("-")
        himawari_stamp = himawari_capture.replace("-", "").replace(":", "")
        for y in range(first_y, last_y + 1):
            for x in range(first_x, last_x + 1):
                url = HIMAWARI_TILE_URL.format(
                    level=HIMAWARI_LEVEL, tile_size=HIMAWARI_TILE_SIZE,
                    year=year, month=month, day=day, clock=clock, x=x, y=y,
                )
                destination = tile_folder / f"{himawari_stamp}_{x}_{y}.png"
                downloaded = download_new_png(
                    url, destination, (HIMAWARI_TILE_SIZE, HIMAWARI_TILE_SIZE),
                    allow_placeholder=True,
                )
                if downloaded is None:
                    placeholder_tiles.append({"x": x, "y": y, "url": url})
                    continue
                tile_entries.append({
                    "x": x,
                    "y": y,
                    "file": relative(destination),
                    "url": url,
                    "svg_href": destination.relative_to(zoom_folder).as_posix(),
                })

        himawari_zoom_svg = zoom_folder / f"{frame:02d}_himawari_zoom.svg"
        write_himawari_crop_svg(himawari_zoom_svg, tile_entries, himawari_crop)
        himawari_zoom = base.render_svg(
            himawari_zoom_svg, himawari_crop["size"], himawari_crop["size"]
        )
        write_zoom_comparison_svg(
            comparison_svg, storm, frame, epic_zoom.name, himawari_zoom.name,
            epic_capture, himawari_capture, lat, lon, half_span, True,
        )
        write_zoom_comparison_svg(
            clean_svg, storm, frame, epic_zoom.name, himawari_zoom.name,
            epic_capture, himawari_capture, lat, lon, half_span, False,
        )
        comparison_size = (1700, 970)
    else:
        write_epic_zoom_comparison_svg(
            comparison_svg, storm, frame, epic_zoom.name, epic_capture,
            lat, lon, half_span, True,
        )
        write_epic_zoom_comparison_svg(
            clean_svg, storm, frame, epic_zoom.name, epic_capture,
            lat, lon, half_span, False,
        )
    comparison = base.render_svg(comparison_svg, *comparison_size)
    clean_comparison = base.render_svg(clean_svg, *comparison_size)

    return {
        "frame": frame,
        "center_lat": lat,
        "center_lon": lon,
        "half_span_degrees": half_span,
        "epic_capture_utc": epic_capture,
        "epic_source_file": relative(epic_source),
        "epic_source_url": epic_url,
        "epic_source_dimensions": [EPIC_SOURCE_SIZE, EPIC_SOURCE_SIZE],
        "epic_dscovr_j2000_position": epic_position,
        "epic_crop_bounds_px": epic_crop,
        "epic_zoom_file": relative(epic_zoom),
        "epic_zoom_dimensions": [ZOOM_OUTPUT_SIZE, ZOOM_OUTPUT_SIZE],
        "himawari_capture_utc": himawari_capture,
        "himawari_tile_level": HIMAWARI_LEVEL if himawari_capture else None,
        "himawari_tile_size": HIMAWARI_TILE_SIZE if himawari_capture else None,
        "himawari_full_disk_dimensions": (
            [HIMAWARI_FULL_SIZE, HIMAWARI_FULL_SIZE] if himawari_capture else None
        ),
        "himawari_crop_bounds_px": himawari_crop,
        "himawari_zoom_file": relative(himawari_zoom) if himawari_zoom else "",
        "himawari_zoom_dimensions": (
            [himawari_crop["size"], himawari_crop["size"]] if himawari_crop else None
        ),
        "himawari_tiles": [
            {key: entry[key] for key in ("x", "y", "file", "url")} for entry in tile_entries
        ],
        "himawari_placeholder_tiles": placeholder_tiles,
        "comparison": relative(comparison),
        "clean_comparison": relative(clean_comparison),
        "coverage": "epic_himawari" if himawari_capture else "epic_only",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument(
        "--storm", help="Existing storm to enrich (default: Mitchell)"
    )
    targets.add_argument(
        "--all-missing", action="store_true",
        help="Enrich every storm without a complete set of zoom metadata",
    )
    parser.add_argument(
        "--half-span-degrees", type=float, default=DEFAULT_HALF_SPAN_DEGREES,
        help="Degrees from the track point to each side of the zoom window",
    )
    args = parser.parse_args()
    if not 2 <= args.half_span_degrees <= 25:
        parser.error("--half-span-degrees must be between 2 and 25")

    metadata_path, metadata = load_zoom_metadata()
    if args.all_missing:
        storms = [
            storm for storm in manifest_storms()
            if not has_complete_zoom_metadata(metadata, storm)
        ]
    else:
        storms = [args.storm or "Mitchell"]

    if not storms:
        print("Every named storm already has complete zoom metadata.", flush=True)

    total_frames = 0
    for storm in storms:
        records = load_manifest(storm)
        frames = []
        for record in records:
            print(f'Building {record["storm"]} zoom frame {record["frame"]}...', flush=True)
            frames.append(enrich_frame(record, args.half_span_degrees))

        canonical_name = records[0]["storm"]
        metadata["storms"][canonical_name] = {
            "half_span_degrees": args.half_span_degrees,
            "frames": frames,
        }
        base.write_text_if_changed(
            metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        )
        total_frames += len(frames)
        print(
            f"Added {len(frames)} zoom frames for {canonical_name}: {metadata_path}",
            flush=True,
        )

    base.render_existing_index()
    print(
        f"Zoom enrichment complete for {len(storms)} storm(s), "
        f"{total_frames} frame(s); rebuilt {OUT / 'index.html'}",
        flush=True,
    )


if __name__ == "__main__":
    main()
