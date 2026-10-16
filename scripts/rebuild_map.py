from pathlib import Path
import re

INDEX = Path("index.html")
text = INDEX.read_text(encoding="utf-8")
start = text.index('const COL=')
end = text.index('function setView(view)', start)

new_map = r'''const COL={CONFIRMED:"#1f7a3d","STRONGLY CORROBORATED":"#18794e",CORROBORATED:"#2563a6",REPORTED:"#b7791f",DEVELOPING:"#9a6700",CLAIM:"#b42318"};

/* MAP V2: deliberately independent from the old mixed GeoJSON/base-map pipeline. */
const MAP_CENTER=[13.817438300695837,38.79537860244431];
const MAP_ZOOM=8;
const map=L.map("map",{zoomControl:false,preferCanvas:true,worldCopyJump:false}).setView(MAP_CENTER,MAP_ZOOM);
L.control.zoom({position:"bottomright"}).addTo(map);
const osm=L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{
  subdomains:"abc",maxZoom:19,crossOrigin:true,attribution:"© OpenStreetMap contributors"
}).addTo(map);

let events=[];
let gradeOn={CONFIRMED:1,"STRONGLY CORROBORATED":1,CORROBORATED:1,REPORTED:1,DEVELOPING:1,CLAIM:1};
let credOn={STRONG:1,MODERATE:1,LIMITED:1};
let layer=L.layerGroup().addTo(map),markers={};
let forecastData=null;
let referenceLayer=null;

function el(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e}
function sourceLabel(s){if(s.platform==="reddit")return "Reddit";if(s.platform==="gdelt")return "GDELT";return s.outlet||"Source"}
function isApiKeyError(value){return /api[\s_-]*key.{0,50}(required|missing|not provided)|(?:required|missing).{0,50}api[\s_-]*key/i.test(String(value||""))}
function visible(e){return !!gradeOn[e.grade] && (e.sources||[]).some(s=>credOn[s.credibility_label||"LIMITED"]&&!isApiKeyError(s.title)&&!isApiKeyError(s.outlet))}

const mapStatus=L.control({position:"topright"});
mapStatus.onAdd=function(){
  const box=L.DomUtil.create("div","map-status");
  box.innerHTML='<b>MAP V2</b><span id="mapStatusText">Basemap ready · reference layer not loaded</span>';
  L.DomEvent.disableClickPropagation(box);return box;
};
mapStatus.addTo(map);

const mapControls=L.control({position:"topleft"});
mapControls.onAdd=function(){
  const wrap=L.DomUtil.create("div","map-controls");
  const home=el("button","","Tigray");
  home.onclick=()=>map.setView(MAP_CENTER,MAP_ZOOM);
  const fit=el("button","","Fit events");
  fit.onclick=()=>fitEventBounds();
  const ref=el("button","","Reference layer");
  ref.disabled=true;ref.title="Import the supplied Google My Maps KML/KMZ before enabling this layer.";
  wrap.append(home,fit,ref);L.DomEvent.disableClickPropagation(wrap);return wrap;
};
mapControls.addTo(map);

const legend=L.control({position:"bottomleft"});
legend.onAdd=function(){
 const box=L.DomUtil.create("div","map-legend");
 box.innerHTML='<strong>MAP KEY</strong><div><i class="legend-dot event"></i><span>Reported event</span></div><div><i class="legend-dot corroborated"></i><span>Corroborated / confirmed</span></div><div><i class="legend-dot claim"></i><span>Claim / developing</span></div><small>Event locations are plotted only when coordinates are present in the event record.</small>';
 L.DomEvent.disableClickPropagation(box);return box;
};
legend.addTo(map);

function fitEventBounds(){
 const pts=events.filter(e=>visible(e)&&Number.isFinite(Number(e.lat))&&Number.isFinite(Number(e.lon)));
 if(!pts.length){map.setView(MAP_CENTER,MAP_ZOOM);return}
 const b=L.latLngBounds(pts.map(e=>[Number(e.lat),Number(e.lon)]));
 map.fitBounds(b.pad(.12),{maxZoom:10,animate:false});
}

function addBaseMap(){
 // Intentionally empty. The previous mixed base_map.geojson implementation is removed.
 // The supplied Google My Maps layer will be imported here once its KML/KMZ is available.
 referenceLayer=null;
 const s=document.getElementById("mapStatusText");
 if(s)s.textContent="Basemap ready · reference layer awaiting import";
}

function draw(){
 layer.clearLayers();markers={};
 const list=document.getElementById("list");list.replaceChildren();
 events.filter(visible).forEach(e=>{
   if(e.lat!=null&&e.lon!=null){
     const color=COL[e.grade]||"#64748b";
     const m=L.circleMarker([Number(e.lat),Number(e.lon)],{radius:8,color,fillColor:color,fillOpacity:e.grade==="CLAIM"?.25:.82,weight:2,dashArray:e.grade==="CONFIRMED"?null:"3 3"}).addTo(layer);
     const source=(e.sources||[]).filter(s=>!isApiKeyError(s.title)&&!isApiKeyError(s.outlet)).map(sourceLabel).join(", ");
     m.bindPopup("<b>"+String(e.place||e.region||"Reported event")+"</b><br>"+String(e.summary||"")+"<br><small>"+(e.date||"")+" · "+(e.confidence??0)+"% evidence · "+source+"</small>");
     markers[e.key]=m;
   }
   const d=el("div","ev"),g=el("span","g "+String(e.grade||"").replaceAll(" ","-"),e.grade||"UNGRADED");
   const loc=e.place||e.region||"";const b=el("b","",loc?(e.date+" · "+loc):e.date||"");
   const score=el("span","badge",(e.confidence??0)+"%"),tier=el("span","badge",(e.source_tier||"D")+"-tier"+(e.best_source?" · "+e.best_source:""));
   d.append(g,b,score,tier,el("p","",e.summary||""));
   if(e.evidence_explanation){const x=el("div","src",e.evidence_explanation);d.append(x)}
   list.append(d);
 });
 const stats=document.getElementById("stats");stats.replaceChildren();
 const total=events.length,early=events.filter(e=>["CLAIM","DEVELOPING"].includes(e.grade)).length;
 [[total,"EVENTS"],[early,"EARLY REPORTS"]].forEach(x=>{const d=el("div","stat");d.append(el("b","",String(x[0])),el("span","",x[1]));stats.append(d)});
}
'''

text = text[:start] + new_map + text[end:]
# Remove the old base-map network request from the data bootstrap. Events/status/forecast remain.
text = text.replace('fetch("data/base_map.geojson?"+Date.now()).then(r=>r.ok?r.json():null).catch(()=>null),\n ', '')
text = text.replace(']).then(([base,j,s,f])=>{\n if(base && base.features) addBaseMap(base);', ']).then(([j,s,f])=>{\n addBaseMap();')
# Add dedicated V2 styles.
style_marker='[hidden]{display:none!important}'
v2_css='''[hidden]{display:none!important}.map-controls{display:flex;gap:5px;padding:6px;background:#0b1624ed;border:1px solid #38516d;border-radius:10px;box-shadow:0 7px 20px #0005}.map-controls button{background:#15283c;color:#e3edf8;border:1px solid #38516d;border-radius:7px;padding:7px 10px;font-weight:700;font-size:11px;cursor:pointer}.map-controls button:hover:not(:disabled){background:#204464;border-color:#65b8f3}.map-controls button:disabled{opacity:.45;cursor:not-allowed}.map-status{display:flex;flex-direction:column;gap:2px;padding:8px 10px;background:#0b1624ed;border:1px solid #38516d;border-radius:10px;color:#dce9f8;box-shadow:0 7px 20px #0005;font-size:11px}.map-status b{font-size:9px;letter-spacing:.12em;color:#70c5ff}.map-status span{color:#9fb2c7}.map-legend .legend-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;background:#64748b}.map-legend .legend-dot.corroborated{background:#18794e}.map-legend .legend-dot.claim{background:#b42318}'''
if v2_css not in text:
    text=text.replace(style_marker,v2_css+style_marker)
INDEX.write_text(text,encoding="utf-8")
print("rebuilt map implementation")
