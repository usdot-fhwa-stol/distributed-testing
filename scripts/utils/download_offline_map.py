#!/usr/bin/env python3
"""Download imagery tiles from an ArcGIS REST MapServer around a lat/lon and save
them as a local .mbtiles file, for offline use in SIMDIS's Map Editor (Driver =
MBTiles) with no network access required afterward.

The output file lives on disk wherever --output points -- run this from the host
(pointed at a path under distributed-testing/) or from inside a dt-simdis
container with distributed-testing bind-mounted, and it survives independently
of any container's lifecycle.

Example (TFHRC, ~2km radius, zoom 10-18, via Virginia's VBMP imagery):
python3 download_offline_map.py \
    --lat 38.9519791 \
    --lon -77.1483513 \
    --radius-km 2 \
    --min-zoom 10 \
    --max-zoom 18 \
    --url "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VBMP_Imagery/MostRecentImagery_WGS/MapServer" \
    --output tfhrc.mbtiles

Then in SIMDIS: Map Editor -> Load New Layer -> Driver=MBTiles -> File=tfhrc.mbtiles.
"""

import argparse
import math
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from shapely.affinity import scale
from shapely.geometry import Point

DEFAULT_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer"

KM_PER_DEGREE_LAT = 111.32


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return (minLon, minLat, maxLon, maxLat) for a radius_km buffer around (lat, lon)."""
    km_per_degree_lon = KM_PER_DEGREE_LAT * math.cos(math.radians(lat))
    radius_deg_lat = radius_km / KM_PER_DEGREE_LAT
    radius_deg_lon = radius_km / km_per_degree_lon
    # A degree of longitude covers fewer km than a degree of latitude away from the
    # equator, so scale a unit circle into an ellipse with the correct lat/lon radii
    # rather than buffering directly with a single (isotropic) distance.
    circle = Point(lon, lat).buffer(1.0)
    ellipse = scale(circle, xfact=radius_deg_lon, yfact=radius_deg_lat, origin=(lon, lat))
    return ellipse.bounds


def deg2tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2**zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, xtile)), max(0, min(n - 1, ytile))


def tiles_for_zoom(bbox: tuple[float, float, float, float], zoom: int):
    minlon, minlat, maxlon, maxlat = bbox
    x0, y0 = deg2tile(maxlat, minlon, zoom)  # top-left
    x1, y1 = deg2tile(minlat, maxlon, zoom)  # bottom-right
    for x in range(min(x0, x1), max(x0, x1) + 1):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            yield x, y


def init_mbtiles(path: Path, name: str, fmt: str, bbox: tuple, minzoom: int, maxzoom: int) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)"
    )
    metadata = {
        "name": name,
        "type": "baselayer",
        "version": "1.1",
        "description": f"Downloaded via download_offline_map.py from {name}",
        "format": fmt,
        "bounds": ",".join(str(v) for v in bbox),
        "minzoom": str(minzoom),
        "maxzoom": str(maxzoom),
    }
    conn.executemany("INSERT INTO metadata (name, value) VALUES (?, ?)", metadata.items())
    conn.commit()
    return conn


def fetch_tile(session: requests.Session, base_url: str, z: int, x: int, y: int, retries: int = 3):
    url = f"{base_url}/tile/{z}/{y}/{x}"
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200 and resp.content:
                return z, x, y, resp.content
            if resp.status_code == 404:
                return z, x, y, None  # no imagery for this tile, not an error
        except requests.RequestException:
            pass
        time.sleep(0.5 * attempt)
    return z, x, y, None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, required=True, help="Center latitude in degrees")
    parser.add_argument("--lon", type=float, required=True, help="Center longitude in degrees")
    parser.add_argument("--radius-km", type=float, default=2.0, help="Radius around the center to cover (default 2km)")
    parser.add_argument("--min-zoom", type=int, default=10, help="Minimum zoom level to fetch (default 10)")
    parser.add_argument("--max-zoom", type=int, default=18, help="Maximum zoom level to fetch (default 18; 19-20 for full 3-6in GSD where available, much larger download)")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"ArcGIS REST MapServer base URL (default: Esri World Imagery, {DEFAULT_URL})")
    parser.add_argument("--output", required=True, help="Output .mbtiles file path")
    parser.add_argument("--name", default=None, help="Layer name stored in the mbtiles metadata (default: derived from --output)")
    parser.add_argument("--format", default="jpg", choices=["jpg", "png"], help="Tile image format (default jpg)")
    parser.add_argument("--threads", type=int, default=8, help="Parallel download threads (default 8)")
    args = parser.parse_args()

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    layer_name = args.name or output_path.stem

    bbox = bounding_box(args.lat, args.lon, args.radius_km)
    print(f"Bounding box (minLon, minLat, maxLon, maxLat): {bbox}")

    all_tiles = []
    for z in range(args.min_zoom, args.max_zoom + 1):
        zoom_tiles = list(tiles_for_zoom(bbox, z))
        print(f"  zoom {z}: {len(zoom_tiles)} tiles")
        all_tiles.extend((z, x, y) for x, y in zoom_tiles)

    print(f"Total tiles to fetch: {len(all_tiles)}")
    if not all_tiles:
        print("Nothing to do.", file=sys.stderr)
        sys.exit(1)

    conn = init_mbtiles(output_path, layer_name, args.format, bbox, args.min_zoom, args.max_zoom)
    session = requests.Session()

    fetched = skipped = failed = 0
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(fetch_tile, session, args.url, z, x, y) for z, x, y in all_tiles]
        for i, future in enumerate(as_completed(futures), 1):
            z, x, y, data = future.result()
            if data is None:
                skipped += 1
            else:
                # MBTiles uses TMS row numbering, which is flipped from the XYZ
                # convention used to request tiles from the ArcGIS REST endpoint.
                tms_y = (2**z - 1) - y
                conn.execute(
                    "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                    (z, x, tms_y, data),
                )
                fetched += 1
            if i % 200 == 0 or i == len(all_tiles):
                conn.commit()
                print(f"  {i}/{len(all_tiles)} done ({fetched} fetched, {skipped} empty, {failed} failed)")

    conn.commit()
    conn.close()
    print(f"Saved {fetched} tiles to {output_path} ({output_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
