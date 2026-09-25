import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

export default function LakeMap({ name, mapView }) {
  const container = useRef(null);
  const center = mapView?.center;
  const hasCenter = Number.isFinite(center?.latitude) && Number.isFinite(center?.longitude);
  const hasBoundary = Boolean(mapView?.boundary);

  useEffect(() => {
    if (!container.current || (!hasCenter && !hasBoundary)) return undefined;

    const map = L.map(container.current, {
      scrollWheelZoom: false,
      zoomControl: true,
    });
    L.tileLayer(TILE_URL, {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);

    let fittedBoundary = false;
    if (hasBoundary) {
      try {
        const boundary = L.geoJSON(mapView.boundary, {
          style: {
            color: "#147c70",
            weight: 3,
            fillColor: "#21a595",
            fillOpacity: 0.22,
          },
        }).addTo(map);
        if (boundary.getBounds().isValid()) {
          map.fitBounds(boundary.getBounds(), { padding: [28, 28], maxZoom: 16 });
          fittedBoundary = true;
        }
      } catch {
        // A valid source point still provides a useful location map.
      }
    }
    if (!fittedBoundary && hasCenter) {
      map.setView([center.latitude, center.longitude], 14);
      L.circleMarker([center.latitude, center.longitude], {
        radius: 8,
        color: "#fff",
        weight: 3,
        fillColor: "#147c70",
        fillOpacity: 1,
      }).addTo(map);
    }
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
    requestAnimationFrame(() => map.invalidateSize());
    return () => map.remove();
  }, [mapView, hasCenter, hasBoundary, center]);

  return (
    <section className="lake-map-section" aria-labelledby="lake-map-heading">
      <div className="lake-map-heading">
        <div>
          <p className="eyebrow">AUTO-RESOLVED LOCATION</p>
          <h2 id="lake-map-heading">{name} on the map</h2>
          <p>{hasBoundary ? "K-GIS lake boundary" : hasCenter ? "K-GIS lake location" : "Location unavailable in this catalogue record"}</p>
        </div>
        {hasBoundary && <span className="map-boundary-key"><i/> Lake boundary</span>}
      </div>
      {(hasCenter || hasBoundary) ? (
        <div ref={container} className="lake-map" role="region" aria-label={`Map centered on ${name}${hasBoundary ? " with its K-GIS boundary" : ""}`} />
      ) : (
        <p className="lake-map-unavailable">K-GIS does not provide a usable point or boundary for this record.</p>
      )}
      <div className="lake-map-footer">
        <span>Location and boundary: <a href={mapView?.source_url} target="_blank" rel="noreferrer">Karnataka K-GIS</a></span>
        <span>Scroll wheel zoom is off; use the map controls to zoom.</span>
      </div>
    </section>
  );
}
