import { API } from "./api";
import { useEffect, useState } from "react";



function formatNumber(value, digits = 1) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
}

export default function HistoricalSnapshot({ waterBodyId, lakeName }) {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setSnapshot(null);
    setLoading(true);
    setError("");
    setAnalysis(null);
    setAnalysisError("");
    fetch(`${API}/water-bodies/${encodeURIComponent(waterBodyId)}/historical`)
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Historical data could not be loaded.");
        return data;
      })
      .then((data) => { if (!cancelled) setSnapshot(data); })
      .catch((reason) => { if (!cancelled) setError(reason.message || "Historical data could not be loaded."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [waterBodyId]);

  async function runHistoricalAnalysis() {
    setAnalysisLoading(true);
    setAnalysisError("");
    try {
      const response = await fetch(`${API}/water-bodies/${encodeURIComponent(waterBodyId)}/historical/analysis`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Historical analysis could not be loaded.");
      setAnalysis(data);
    } catch (reason) {
      setAnalysisError(reason.message || "Historical analysis could not be loaded.");
    } finally {
      setAnalysisLoading(false);
    }
  }

  const satellite = snapshot?.satellite;
  const weather = snapshot?.weather;
  const sclWaterPercent = satellite?.scl_water_fraction == null
    ? null
    : satellite.scl_water_fraction * 100;

  return (
    <section id="historical-data" className="historical-section" aria-labelledby="historical-heading">
      <div className="section-title">
        <div>
          <p className="eyebrow">DOWNLOADED OBSERVATIONS</p>
          <h2 id="historical-heading">Historical data snapshot</h2>
        </div>
        <span className="window-pill">{loading ? "LOADING" : snapshot?.available ? "HISTORICAL · REAL DATA" : "NO SNAPSHOT"}</span>
      </div>

      {loading && <p className="historical-placeholder">Loading saved observations for {lakeName}…</p>}
      {!loading && error && <div className="error-banner historical-error"><b>Historical data unavailable</b><span>{error}</span></div>}
      {!loading && !error && snapshot && !snapshot.available && (
        <p className="historical-placeholder">{snapshot.message} The current acquisition pilot includes nine featured Karnataka lakes.</p>
      )}
      {!loading && !error && snapshot?.available && (
        <div className="historical-card">
          <div className="historical-intro">
            <div>
              <span className="historical-date-badge">SATELLITE · {snapshot.scene_date}</span>
              <h3>{snapshot.lake_name}</h3>
              <p>Real Sentinel-2 pixels and historical ERA5 weather. These dated records are for exploration and are not a live bloom prediction.</p>
            </div>
            <div className="historical-metrics" aria-label="Historical satellite data summary">
              <span><b>{satellite.valid_four_band_polygon_pixels.toLocaleString("en-IN")}</b><small>four-band polygon pixels</small></span>
              <span><b>{sclWaterPercent == null ? "—" : `${formatNumber(sclWaterPercent, 1)}%`}</b><small>classified as water</small></span>
              <span><b>{weather.rows.length}</b><small>daily weather rows</small></span>
            </div>
          </div>

          <div className="historical-grid">
            <figure className="historical-image">
              <img src={`${API}${satellite.image_url}`} alt={`Historical Sentinel-2 true-colour crop inside the K-GIS boundary of ${snapshot.lake_name} on ${snapshot.scene_date}`} />
              <figcaption>Sentinel-2 L2A true colour · {snapshot.scene_date} · display stretch only</figcaption>
            </figure>
            <div className="historical-details">
              <h4>Satellite acquisition</h4>
              <dl>
                <div><dt>Band order</dt><dd>{satellite.band_order.join(" / ")}</dd></div>
                <div><dt>Source resolution</dt><dd>{satellite.resolution_metres} m</dd></div>
                <div><dt>Scene-wide cloud cover</dt><dd>{formatNumber(snapshot.scene_footprint_cloud_percent, 2)}%</dd></div>
                <div><dt>Lake SCL water pixels</dt><dd>{satellite.scl_water_pixels.toLocaleString("en-IN")}</dd></div>
              </dl>
              <p className="historical-quality">{satellite.scl_water_pixels === 0
                ? "No pixels in this scene were classified as water inside the lake boundary. Inspect this crop before using it for lake analysis."
                : "Water classification is a satellite quality indicator, not a measured chlorophyll value."}</p>
              <p className="historical-raw-note">Raw four-band values need model-format review before inference.</p>
              <div className="historical-links">
                <a href={satellite.source_url} target="_blank" rel="noreferrer">Satellite source record</a>
                <a href={`${API}${satellite.raster_download_url}`} download>Download four-band GeoTIFF</a>
              </div>
            </div>
          </div>

          <div className="historical-weather">
            <div className="historical-weather-heading">
              <div><h4>Historical rainfall and wind</h4><p>ERA5 gridded estimates near the lake · {weather.rows[0]?.date} to {weather.rows.at(-1)?.date}</p></div>
              <a href={weather.source_url} target="_blank" rel="noreferrer">Weather source</a>
            </div>
            <div className="weather-table-scroll">
              <table>
                <thead><tr><th>Date</th><th>Rain</th><th>Precipitation</th><th>Mean wind</th><th>Max wind</th></tr></thead>
                <tbody>{weather.rows.map((row) => (
                  <tr key={row.date}>
                    <td>{row.date}</td>
                    <td>{formatNumber(row.rain_sum)} mm</td>
                    <td>{formatNumber(row.precipitation_sum)} mm</td>
                    <td>{formatNumber(row.wind_speed_10m_mean, 2)} m/s</td>
                    <td>{formatNumber(row.wind_speed_10m_max, 2)} m/s</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <p>Rainfall and wind are historical weather estimates. Daily lake chlorophyll-a and lake surface temperature were not obtained.</p>
          </div>

          <div className="historical-analysis">
            <div className="historical-analysis-heading">
              <div>
                <h4>Analyze this observation</h4>
                <p>Calculate a dated summary from the saved four-band raster and the seven preceding weather days.</p>
              </div>
              <button type="button" disabled={analysisLoading} onClick={runHistoricalAnalysis}>
                {analysisLoading ? "Analyzing…" : analysis ? "Run again" : "Run historical analysis"}
              </button>
            </div>
            {analysisError && <div className="error-banner historical-error"><b>Analysis unavailable</b><span>{analysisError}</span></div>}
            {analysis && (
              <div className="historical-analysis-result" aria-live="polite">
                <div className="historical-analysis-result-title">
                  <strong>Historical observation · {analysis.observation_date}</strong>
                  <span>NO BLOOM FORECAST</span>
                </div>
                <div className="historical-analysis-stats">
                  <div><small>Water-classified pixels</small><b>{analysis.satellite.scl_water_pixels.toLocaleString("en-IN")}</b><span>{analysis.satellite.scl_water_fraction == null ? "—" : `${formatNumber(analysis.satellite.scl_water_fraction * 100)}%`} of lake boundary pixels</span></div>
                  <div><small>Rainfall · prior 7 days</small><b>{formatNumber(analysis.weather.rainfall_total_mm)} mm</b><span>{analysis.weather.start_date} to {analysis.weather.end_date}</span></div>
                  <div><small>Mean wind · prior 7 days</small><b>{formatNumber(analysis.weather.mean_wind_speed_mps, 2)} m/s</b><span>ERA5 gridded estimate</span></div>
                </div>
                <h5>Median satellite reflectance inside lake boundary</h5>
                <div className="historical-band-list">
                  {analysis.satellite.band_order.map((band) => (
                    <span key={band}><small>{band}</small><b>{formatNumber(analysis.satellite.median_surface_reflectance_inside_boundary[band], 4)}</b></span>
                  ))}
                </div>
                {analysis.satellite.scl_water_pixels === 0 && <p className="historical-analysis-caution">No pixels were classified as water in this scene; interpret the boundary-wide reflectance with caution.</p>}
                <p className="historical-analysis-note">{analysis.satellite.reflectance_note} {analysis.interpretation}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
