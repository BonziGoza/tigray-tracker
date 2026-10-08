#!/usr/bin/env python3
"""Fetch the public Google My Maps export and convert it to GeoJSON for Leaflet."""

import json
import os
import sys
import zipfile
import io
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

MAP_ID = "1q-M9x3Kshld2Ys36jDU0Y45TmvE7E0km"
KML_URL = f"https://www.google.com/maps/d/kml?forcekml=1&mid={MAP_ID}"
OUT = Path("data/base_map.geojson")
TIMEOUT = 30
NS = {"k": "http://www.opengis.net/kml/2.2"}


def text(node, tag):
    x = node.find(f"k:{tag}", NS)
    return (x.text or "").strip() if x is not None else ""


def coords(raw):
    out = []
    for part in raw.strip().split():
        bits = part.split(",")
        if len(bits) >= 2:
            try:
                out.append([float(bits[0]), float(bits[1])])
            except ValueError:
                pass
    return out


def geometry(el):
    point = el.find("k:Point/k:coordinates", NS)
    if point is not None:
        c = coords(point.text or "")
        return {"type": "Point", "coordinates": c[0]} if c else None

    line = el.find("k:LineString/k:coordinates", NS)
    if line is not None:
        c = coords(line.text or "")
        return {"type": "LineString", "coordinates": c} if len(c) >= 2 else None

    outer = el.find("k:Polygon/k:outerBoundaryIs/k:LinearRing/k:coordinates", NS)
    if outer is not None:
        c = coords(outer.text or "")
        return {"type": "Polygon", "coordinates": [c]} if len(c) >= 4 else None

    geoms = []
    multi = el.find("k:MultiGeometry", NS)
    if multi is not None:
        for child in list(multi):
            g = geometry(child)
            if g:
                geoms.append(g)
    if geoms:
        types = {g["type"] for g in geoms}
        if len(types) == 1:
            t = next(iter(types))
            return {"type": "Multi" + t, "coordinates": [g["coordinates"] for g in geoms]}
        return {"type": "GeometryCollection", "geometries": geoms}

    return None


def placemarks(root):
    features = []
    for pm in root.findall(".//k:Placemark", NS):
        g = geometry(pm)
        if not g:
            continue
        props = {
            "name": text(pm, "name"),
            "description": text(pm, "description"),
            "styleUrl": text(pm, "styleUrl"),
        }
        folder = pm
        parent_name = ""
        # KML export commonly keeps folder names outside the Placemark.
        # Walk the tree once more only when a folder name is useful.
        for parent in root.findall(".//k:Folder", NS):
            if pm in list(parent.findall("k:Placemark", NS)):
                parent_name = text(parent, "name")
                break
        if parent_name:
            props["folder"] = parent_name
        features.append({"type": "Feature", "properties": props, "geometry": g})
    return features


def main():
    try:
        r = requests.get(KML_URL, timeout=TIMEOUT, headers={"User-Agent": "Tigray-OSINT-Tracker/1.0"})
        r.raise_for_status()
        data = r.content

        # Google may return KMZ even without an explicit force-kml response.
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = [n for n in z.namelist() if n.lower().endswith(".kml")]
                if not names:
                    raise RuntimeError("Google export returned KMZ without a KML file")
                data = z.read(names[0])

        root = ET.fromstring(data)
        fc = {"type": "FeatureCollection", "features": placemarks(root)}
        OUT.parent.mkdir(parents=True, exist_ok=True)

        new = json.dumps(fc, ensure_ascii=False, separators=(",", ":")) + "\n"
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if new != old:
            OUT.write_text(new, encoding="utf-8")
            print(f"Google My Maps layer updated: {len(fc['features'])} features")
        else:
            print(f"Google My Maps layer unchanged: {len(fc['features'])} features")
    except Exception as exc:
        # Never break OSINT collection because the optional geographic layer failed.
        print(f"WARNING: could not refresh Google My Maps layer: {exc}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
