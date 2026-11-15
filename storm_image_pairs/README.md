# Storm Frame Explorer

Open `index.html` to review the collected storm imagery. The interface presents one named storm at a time and gathers its selected observations into a single viewer.

## Collection

- 23 named systems
- 75 selected observations
- 75 original NASA DSCOVR EPIC JPEGs
- 41 original NICT Himawari full-disk PNGs for Australian-region and South Pacific cyclones
- 75 standard annotated comparison PNGs, plus 3 additive Edouard multi-storm variants
- 75 marker-free comparison PNGs used by the global annotation toggle
- 75 additive storm-centered zoom comparisons across all 23 systems, each with annotated and marker-free variants
- 75 NASA EPIC 2048px PNG sources and 960 NICT Himawari 20d color source tiles for the zoom collection
- 23 primary Wikipedia storm insets and 3 associated Pacific-storm insets, with 52 local 1280px satellite and track assets

The named systems are:

- 2025–26 Australian region: Fina, Bakung, Grant, Hayley, Iggy, Jenna, Koji, Luana, Mitchell, Narelle, and Maila
- 2025–26 South Pacific: Urmil and Vaianu
- 2026 Atlantic: Arthur, Bertha, Cristobal, Dolly, Edouard, Fay, Gonzalo, Hanna, Isaias, and Josephine

## Enriched viewer metadata

Each storm view includes:

- named storm and basin
- Wikipedia-listed active date range
- Wikipedia-listed affected-area path, preserved in the source table's order
- direct link to the relevant Wikipedia season page
- a Wikipedia inset reference rail with the storm's intensity band, higher-resolution satellite image, track map, duration, and peak intensity
- frame-specific companion-storm insets when another named system is visibly corroborated in the EPIC image
- filmstrip and previous/next controls; Arthur, Bakung, and Bertha have five frames, while the other storms have three
- a persistent **Markers on/off** control that switches the main image and all thumbnails for every storm; the `M` key provides the same toggle
- an independent **Full disks/Storm zoom** control for every frame; the `Z` key provides the same toggle
- UTC capture times, nearest track point, wind, and position
- links to the untouched local originals and their online archives

The path display is an affected-area summary, not a claim that every place is listed in precise track chronology. Exact frame coordinates and winds come from IBTrACS.

EPIC marker projection uses each image's embedded DSCOVR position to scale the apparent Earth disk for that capture. This prevents high-latitude markers from being pushed too far toward the limb as the spacecraft–Earth distance changes.

Arthur observations 4 and 5 are June 18 post-track remnant views. Their markers and wind values deliberately use Arthur's final IBTrACS fix at 00:00 UTC; the viewer labels this distinction explicitly.

Bakung observations 4 and 5 add paired EPIC/Himawari views from December 16 and 17, extending its day-by-day sequence without replacing or renumbering its original three observations.

Bertha observations 2–5 also contain East Pacific Hurricane Fausto. Bertha is marked in red and Fausto in gold, with independent nearest-time IBTrACS positions recorded in the manifest. Observations 4 and 5 are additional EPIC views from July 23 at 18:36 and 19:41 UTC. Bertha observation 1 remains single-marked because the Pacific systems were beyond EPIC's visible limb at that capture time.

Edouard observations 1–3 use additive `comparison_enriched` variants while retaining their original comparison files. Marie is marked in gold and Karina in magenta on all three frames; Lowell is marked in green on frames 1 and 2, but is omitted from frame 3 because it is beyond EPIC's usable limb. The viewer supplies frame-specific Wikipedia inset cards for each visible companion.

All 75 observations have additive storm-centered zooms. Each frame uses its existing observation time and IBTrACS fix with a newly downloaded 2048px NASA EPIC PNG. The 41 Australian-region and South Pacific frames also use the highest-resolution NICT Himawari `20d/550` tiles intersecting a 20° storm-centered window; the 34 Atlantic frames are EPIC-only because the basin is outside Himawari coverage. Two unavailable edge-of-disk Himawari placeholder tiles are recorded in the metadata and rendered as black outside the visible disk. Raw color tiles, native-resolution Himawari crops, 1600px EPIC zoom crops, comparison variants, and source URLs are retained separately in each storm's `zoom/` directory. The original full-disk assets and primary manifest are unchanged.

## Files

- `index.html` — self-contained storm viewer and embedded metadata
- `manifest.csv` — one record per selected observation, including image provenance and Wikipedia enrichment
- `named_storms.csv` — one record per named system
- `images/` — originals, annotated and marker-free comparisons, and retained SVG masters
- `wiki_panels/` — local higher-resolution satellite and track assets extracted from the matching Wikipedia insets
- `data/wiki_panels.json` — extracted inset metadata, article anchors, and Wikimedia attribution/file-page links
- `data/zoom_frames.json` — additive per-frame zoom geometry, local files, tile coordinates, and source URLs
- `data/ibtracs.last3years.list.v04r01.csv` — downloaded NOAA/NCEI track data
- `../tools/pull_storm_images.py` — reproducible collection and interface builder
- `../tools/pull_storm_zooms.py` — additive high-resolution zoom collector for one storm or every incomplete storm
- `viewer_fina.png`, `viewer_bakung.png`, `viewer_arthur.png`, `viewer_bertha.png`, `viewer_edouard.png`, `viewer_edouard_markers_off.png`, and `viewer_hanna.png` — interface previews

## Sources

- NASA EPIC: <https://epic.gsfc.nasa.gov/>
- NICT Himawari: <https://himawari8.nict.go.jp/>
- NICT historical image archive: <https://himawari.asia/>
- NOAA/NCEI IBTrACS v04r01: <https://www.ncei.noaa.gov/products/international-best-track-archive>
- Australian-region season: <https://en.wikipedia.org/wiki/2025%E2%80%9326_Australian_region_cyclone_season>
- South Pacific season: <https://en.wikipedia.org/wiki/2025%E2%80%9326_South_Pacific_cyclone_season>
- Atlantic season: <https://en.wikipedia.org/wiki/2026_Atlantic_hurricane_season>
- Pacific season: <https://en.wikipedia.org/wiki/2026_Pacific_hurricane_season>

All times in the viewer and manifest are UTC.
Each inset image links to its Wikimedia file page, where its creator, attribution, and license are recorded.
