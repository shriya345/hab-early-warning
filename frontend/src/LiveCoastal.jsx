import { API } from "./api";
import { useEffect, useRef, useState } from "react";

const dateLabel = (value) => new Date(value).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });

function HistoryChart({ series }) {
  const values = series.records;
  const start = Date.parse(values[0].time), end = Date.parse(values.at(-1).time);
  const low = Math.min(...values.map(r => r.value)), high = Math.max(...values.map(r => r.value));
  const points = values.map(r => ({ x: 40 + (Date.parse(r.time) - start) / (end - start || 1) * 510, y: 125 - (r.value - low) / (high - low || 1) * 100, time: r.time, value: r.value }));
  return <figure className="coastal-chart">
    <svg viewBox="0 0 570 155" role="img" aria-label={`${series.name} history; gaps longer than one hour are not connected`}>
      <line x1="40" y1="125" x2="550" y2="125" stroke="#dbe8e1" />
      <text x="2" y="29">{high.toFixed(1)}</text><text x="2" y="129">{low.toFixed(1)}</text>
      {points.map((p, i) => <g key={p.time}>
        {i > 0 && Date.parse(p.time) - Date.parse(points[i - 1].time) <= 3600000 && <line x1={points[i - 1].x} y1={points[i - 1].y} x2={p.x} y2={p.y} stroke="#267f70" strokeWidth="1.5" />}
        <circle cx={p.x} cy={p.y} r="2" fill="#267f70"><title>{dateLabel(p.time)} IST: {p.value} {series.unit}</title></circle>
      </g>)}
    </svg>
    <figcaption>{dateLabel(values[0].time)} — {dateLabel(values.at(-1).time)} IST · {series.count} readings · {series.gaps_over_60_minutes} gaps over 1 hour</figcaption>
  </figure>;
}

export default function LiveCoastal() {
  const [data, setData] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const busy = useRef(false);
  async function refresh() {
    if (busy.current) return;
    busy.current = true; setLoading(true); setError("");
    const request = new AbortController();
    const timeout = setTimeout(() => request.abort(), 45000);
    try {
      const response = await fetch(`${API}/live-stations/kochi`, { signal: request.signal });
      if (!response.ok) throw new Error("The station service could not be reached.");
      const result = await response.json();
      if (!result.available) throw new Error(result.error || "No station readings are available.");
      setData(result); setError(result.error || "");
    } catch (e) { setError(e.name === "AbortError" ? "The refresh timed out. Try again shortly." : e.message); }
    finally { clearTimeout(timeout); busy.current = false; setLoading(false); }
  }
  useEffect(() => { refresh(); const timer = setInterval(refresh, 300000); return () => { clearInterval(timer); }; }, []);
  return <section className="coastal-section" id="live-ingestion" aria-labelledby="coastal-heading">
    <div className="section-title"><div><p className="eyebrow">LIVE DATA INGESTION · INCOIS</p><h2 id="coastal-heading">Kochi coastal water monitoring</h2></div><button className="coastal-refresh" onClick={refresh} disabled={loading}>{loading ? "Fetching readings…" : "Refresh readings"}</button></div>
    <p className="coastal-intro">Real chlorophyll-a and water-temperature readings from the Kochi coastal buoy, Kerala. The feed is checked every 5 minutes; source observations may arrive later.</p>
    <div role="status" aria-live="polite" className="coastal-status">{loading ? "Connecting to INCOIS…" : data ? `Last successful retrieval: ${dateLabel(data.retrieved_at)} IST` : "Waiting for source readings"}{data && " · Backend requests are cached for up to 60 seconds."}</div>
    {error && <p className="coastal-error" role="alert">{error} {data ? "Previously retrieved readings remain below; check their observation times." : "Use Refresh readings to retry."}</p>}
    {data && <><div className="coastal-grid">{Object.entries(data.series).map(([key, series]) => <article className="coastal-card" key={key}>
      <div className="coastal-card-heading"><h3>{series.name}</h3><span>{error || data.cached ? "CACHED" : series.delayed ? "SOURCE DELAYED" : "RECENT OBSERVATION"}</span></div>
      <p className="coastal-value">{series.latest.value.toFixed(2)} <small>{series.unit}</small></p>
      <p className="coastal-observed">Observed {dateLabel(series.latest.time)} IST · {series.age_hours} hours old</p>
      <HistoryChart series={series} />
      <details><summary>Latest 10 source readings</summary><table><thead><tr><th>Observation time (IST)</th><th>{series.unit}</th></tr></thead><tbody>{series.records.slice(-10).reverse().map(r => <tr key={r.time}><td>{dateLabel(r.time)}</td><td>{r.value}</td></tr>)}</tbody></table></details>
      <a href={series.source_url} target="_blank" rel="noreferrer">View official INCOIS source</a>
    </article>)}</div><p className="coastal-footnote">Coastal station readings; not measurements for the selected Karnataka lake. Source quality flags are not supplied in this chart feed. Bloom forecasting requires separate model validation.</p></>}
  </section>;
}
