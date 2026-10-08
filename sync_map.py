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



def abgr_to_rgba(value):
    """Convert KML AABBGGRR colors to CSS/GeoJSON color + opacity."""
    value=(value or "").strip().lstrip("#")
    if len(value)==6:
        value="ff"+value
    if len(value)!=8 or not all(ch in "0123456789abcdefABCDEF" for ch in value):
        return None, None
    a,b,g,r=value[0:2],value[2:4],value[4:6],value[6:8]
    return f"#{r}{g}{b}", int(a,16)/255


def parse_styles(root):
    styles={}
    for st in root.findall(".//k:Style", NS):
        sid=st.get("id")
        if not sid: continue
        icon=st.find("k:IconStyle",NS)
        line=st.find("k:LineStyle",NS)
        poly=st.find("k:PolyStyle",NS)
        out={}
        if line is not None:
            color=abgr_to_rgba(text(line,"color"))
            if color[0]: out.update(strokeColor=color[0],strokeOpacity=color[1])
            width=text(line,"width")
            if width:
                try: out["strokeWeight"]=float(width)
                except ValueError: pass
        if poly is not None:
            color=abgr_to_rgba(text(poly,"color"))
            if color[0]: out.update(fillColor=color[0],fillOpacity=color[1])
            fill=text(poly,"fill")
            if fill=="0": out["fillOpacity"]=0
        if icon is not None:
            scale=text(icon,"scale")
            if scale:
                try: out["iconScale"]=float(scale)*5
                except ValueError: pass
            color=abgr_to_rgba(text(icon,"color"))
            if color[0]: out.update(fillColor=color[0],fillOpacity=color[1])
        styles[sid]=out
    for sm in root.findall(".//k:StyleMap", NS):
        sid=sm.get("id")
        if not sid: continue
        chosen=""
        for pair in sm.findall("k:Pair",NS):
            if text(pair,"key")=="normal":
                chosen=text(pair,"styleUrl").lstrip("#")
                break
        if chosen in styles: styles[sid]=dict(styles[chosen])
    return styles

def placemarks(root,styles):
    features = []
    for pm in root.findall(".//k:Placemark", NS):
        g = geometry(pm)
        if not g:
            continue
        style_id=text(pm,"styleUrl").lstrip("#")
        props = {
            "name": text(pm, "name"),
            "description": text(pm, "description"),
            "styleUrl": text(pm, "styleUrl"),
        }
        if style_id in styles:
            props.update(styles[style_id])
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
        styles = parse_styles(root)
        fc = {"type": "FeatureCollection", "features": placemarks(root, styles)}
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
        # If this is the first run, create an empty valid layer so the workflow's
        # git-add step still succeeds. A later successful run will replace it.
        OUT.parent.mkdir(parents=True, exist_ok=True)
        if not OUT.exists():
            OUT.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        print(f"WARNING: could not refresh Google My Maps layer: {exc}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
