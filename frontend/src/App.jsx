import { API } from "./api";
import { useEffect, useRef, useState } from "react";
import HistoricalSnapshot from "./HistoricalSnapshot";
import HistoricalPrediction from "./HistoricalPrediction";
import LakeMap from "./LakeMap";


const EXAMPLE_LAKES = [
  "Ulsoor Lake",
  "Varthur Lake",
  "Bellandur Lake",
  "Kukkarahalli Lake",
  "Karanjikere",
  "Gattigere Palya (Sompura) Lake",
  "Chikkegowdanapalya Lake",
  "Bettahalli lake",
  "Srinivasapura Lake",
];

function Icon({ name, size = 18 }) {
  const shared = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };
  const paths = {
    water: <><path d="M3 8c2.4 0 2.4-2 4.8-2s2.4 2 4.8 2 2.4-2 4.8-2 2.4 2 4.8 2"/><path d="M3 13c2.4 0 2.4-2 4.8-2s2.4 2 4.8 2 2.4-2 4.8-2 2.4 2 4.8 2"/><path d="M3 18c2.4 0 2.4-2 4.8-2s2.4 2 4.8 2 2.4-2 4.8-2 2.4 2 4.8 2"/></>,
    search: <><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 5 5"/></>,
    arrow: <><path d="M7 17 17 7"/><path d="M7 7h10v10"/></>,
    satellite: <><path d="m13.5 6.5 4-4 4 4-4 4zM2.5 17.5l4-4 4 4-4 4z"/><path d="m8 14 6-6M5 11l-2-2 3-3 2 2M13 19l2 2 3-3-2-2"/></>,
    leaf: <><path d="M20 4c-8 0-14 3-14 10a6 6 0 0 0 6 6c7 0 10-6 8-16Z"/><path d="M4 21c3-5 7-8 12-11"/></>,
    pin: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
    check: <><path d="m5 12 4 4L19 6"/></>,
  };
  return <svg {...shared}>{paths[name]}</svg>;
}

function SearchResult({ item, onSelect, disabled }) {
  return (
    <button
      className="catalog-result"
      type="button"
      onClick={() => onSelect(item)}
      disabled={disabled}
    >
      <span className="catalog-result-icon"><Icon name="water" size={17}/></span>
      <span className="catalog-result-copy">
        <b>{item.name}</b>
        <small>{[item.district, item.taluk, item.state].filter(Boolean).join(" · ")}</small>
      </span>
      {item.area_ha != null && Number.isFinite(Number(item.area_ha)) && (
        <span className="result-area">{Number(item.area_ha).toFixed(1)} ha</span>
      )}
      <Icon name="arrow" size={15}/>
    </button>
  );
}

function WeatherContextTable({ weather }) {
  const rows = weather?.rows || [];
  if (!rows.length) return null;
  const number = (value, unit) => value == null || !Number.isFinite(Number(value))
    ? "—"
    : `${Number(value).toFixed(1)} ${unit}`;

  return (
    <div className="weather-context-table">
      <div className="weather-context-heading">
        <b>Daily weather context</b>
        <span>Nearby gridded data · not lake-water measurements</span>
      </div>
      <div className="weather-table-scroll">
        <table>
          <thead><tr><th>Date</th><th>Air temp.</th><th>Rainfall</th><th>Wind</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.date}>
                <td>{row.date ? new Date(`${row.date}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" }) : "—"}</td>
                <td>{number(row.air_temperature_c, "°C")}</td>
                <td>{number(row.rainfall_mm, "mm")}</td>
                <td>{number(row.wind_speed_ms, "m/s")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>{weather.source || "Open-Meteo"} · informational context only; values are not model inputs.</p>
    </div>
  );
}

function App() {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState([]);
  const [searchMessage, setSearchMessage] = useState("");
  const [searchState, setSearchState] = useState("idle");
  const [searchTerm, setSearchTerm] = useState("");
  const [nextOffset, setNextOffset] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [catalogCount, setCatalogCount] = useState(null);
  const [selected, setSelected] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [analysisMode, setAnalysisMode] = useState("live");
  const [demoResult, setDemoResult] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState("");
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [coverageError, setCoverageError] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const [selecting, setSelecting] = useState(false);
  const [satellitePreview, setSatellitePreview] = useState(null);
  const [satellitePreviewLoading, setSatellitePreviewLoading] = useState(false);
  const [satellitePreviewError, setSatellitePreviewError] = useState("");
  const searchSequence = useRef(0);
  const selectionSequence = useRef(0);
  const analysisSequence = useRef(0);

  useEffect(() => () => {
    if (satellitePreview) URL.revokeObjectURL(satellitePreview);
  }, [satellitePreview]);

  useEffect(() => {
    fetch(`${API}/lakes/catalog/status`)
      .then((response) => response.ok ? response.json() : null)
      .then((data) => {
        if (Number.isInteger(data?.source_named_records)) setCatalogCount(data.source_named_records);
      })
      .catch(() => {});
  }, []);

  const searchWaterBodies = async (searchText) => {
    const term = searchText.trim();
    if (term.length < 2) {
      setSearchState("error");
      setSearchMessage("Enter at least two characters to search Karnataka water bodies.");
      setItems([]);
      setNextOffset(null);
      return;
    }

    const sequence = ++searchSequence.current;
    selectionSequence.current += 1;
    setSearchState("loading");
    setSearchTerm(term);
    setNextOffset(null);
    setLoadingMore(false);
    setSearchMessage("");
    setItems([]);
    setSelected(null);
    setCoverage(null);
    setPrediction(null);
    setDemoResult(null);
    setAnalysisError("");
    setAnalysisLoading(false);
    setSatellitePreview(null);
    setSatellitePreviewError("");
    setCoverageError("");
    setCoverageLoading(false);
    setSelectionError("");

    try {
      const response = await fetch(`${API}/water-bodies/search?q=${encodeURIComponent(term)}`);
      const data = await response.json();
      if (sequence !== searchSequence.current) return;
      if (!response.ok) throw new Error(data.detail || "The Karnataka catalogue is temporarily unavailable.");

      const found = data.items || [];
      setItems(found);
      setNextOffset(data.has_more ? data.next_offset : null);
      setSearchState(found.length ? "results" : "empty");
      setSearchMessage(found.length
        ? `Showing ${found.length} matching water bod${found.length === 1 ? "y" : "ies"}${data.has_more ? " · more available" : ""}`
        : (data.message || "Water body not found in the Karnataka catalogue."));
    } catch (error) {
      if (sequence !== searchSequence.current) return;
      setSearchState("error");
      setSearchMessage(error.message || "The Karnataka catalogue is temporarily unavailable.");
    }
  };

  const loadMoreResults = async () => {
    if (nextOffset == null || loadingMore) return;
    const sequence = searchSequence.current;
    setLoadingMore(true);
    try {
      const response = await fetch(`${API}/water-bodies/search?q=${encodeURIComponent(searchTerm)}&offset=${nextOffset}`);
      const data = await response.json();
      if (sequence !== searchSequence.current) return;
      if (!response.ok) throw new Error(data.detail || "More catalogue results are temporarily unavailable.");
      const more = data.items || [];
      const seen = new Set(items.map((item) => item.id));
      const merged = [...items, ...more.filter((item) => !seen.has(item.id))];
      setItems(merged);
      setSearchMessage(`Showing ${merged.length} matching water bodies${data.has_more ? " · more available" : ""}`);
      setNextOffset(data.has_more ? data.next_offset : null);
    } catch (error) {
      if (sequence === searchSequence.current) {
        setSearchMessage(error.message || "More catalogue results are temporarily unavailable.");
      }
    } finally {
      if (sequence === searchSequence.current) setLoadingMore(false);
    }
  };

  const submitSearch = (event) => {
    event.preventDefault();
    void searchWaterBodies(query);
  };

  const searchExample = (name) => {
    setQuery(name);
    void searchWaterBodies(name);
  };

  const loadSatellitePreview = async () => {
    if (!selected?.id) return;
    const sequence = selectionSequence.current;
    setSatellitePreviewLoading(true);
    setSatellitePreviewError("");
    try {
      const response = await fetch(`${API}/water-bodies/${encodeURIComponent(selected.id)}/satellite/preview`);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "The satellite preview could not be loaded.");
      }
      const url = URL.createObjectURL(await response.blob());
      if (sequence !== selectionSequence.current) {
        URL.revokeObjectURL(url);
        return;
      }
      setSatellitePreview(url);
    } catch (error) {
      if (sequence === selectionSequence.current) {
        setSatellitePreviewError(error.message || "The satellite preview could not be loaded.");
      }
    } finally {
      if (sequence === selectionSequence.current) setSatellitePreviewLoading(false);
    }
  };

  const runAnalysis = async () => {
    if (!selected?.id || (analysisMode === "live" && !coverage)) return;
    const sequence = selectionSequence.current;
    const runSequence = ++analysisSequence.current;
    const mode = analysisMode;
    setAnalysisLoading(true);
    setAnalysisError("");
    setPrediction(null);
    setDemoResult(null);
    try {
      const response = await fetch(`${API}/water-bodies/${encodeURIComponent(selected.id)}/prediction?mode=${mode}`, {
        cache: "no-store",
      });
      const data = await response.json();
      if (sequence !== selectionSequence.current || runSequence !== analysisSequence.current) return;
      if (!response.ok) throw new Error(data.detail || "The analysis service is temporarily unavailable.");
      if (mode === "demo") {
        if (data.mode !== "demo" || data.simulated !== true || !Number.isFinite(Number(data.fused_probability))) {
          throw new Error("The practice service did not return a valid result.");
        }
        setDemoResult(data);
      } else {
        setCoverage(data);
        setPrediction(data.prediction || null);
        if (!data.prediction) {
          setAnalysisError(data.data_status?.model_input_readiness || data.data_status?.reason || "Required model inputs are unavailable.");
        }
      }
    } catch (error) {
      if (sequence === selectionSequence.current && runSequence === analysisSequence.current) {
        setAnalysisError(error.message || "The analysis service is temporarily unavailable.");
      }
    } finally {
      if (sequence === selectionSequence.current && runSequence === analysisSequence.current) setAnalysisLoading(false);
    }
  };

  const changeAnalysisMode = (mode) => {
    analysisSequence.current += 1;
    setAnalysisMode(mode);
    setAnalysisLoading(false);
    setAnalysisError("");
    setPrediction(null);
    setDemoResult(null);
  };

  const selectWaterBody = async (item) => {
    const sequence = ++selectionSequence.current;
    setSelecting(true);
    setSelectionError("");
    setCoverage(null);
    setPrediction(null);
    setDemoResult(null);
    setAnalysisError("");
    setAnalysisLoading(false);
    setSatellitePreview(null);
    setSatellitePreviewError("");
    setCoverageError("");
    setCoverageLoading(true);
    setSelected({ ...item, detailsLoading: true });

    try {
      const response = await fetch(`${API}/water-bodies/${encodeURIComponent(item.id)}`);
      const data = await response.json();
      if (sequence !== selectionSequence.current) return;
      if (!response.ok) throw new Error(data.detail || "Water-body details are unavailable.");

      setSelected({
        ...item,
        ...(data.water_body || {}),
        ...(data.location || {}),
        model_status: data.model_status || item.model_status,
        data_status: data.data_status,
        map_view: data.map_view,
        detailsLoading: false,
      });
      setSelecting(false);

      try {
        const coverageResponse = await fetch(`${API}/water-bodies/${encodeURIComponent(item.id)}/coverage`);
        const coverageData = await coverageResponse.json();
        if (sequence !== selectionSequence.current) return;
        if (!coverageResponse.ok) {
          throw new Error(coverageData.detail || "Current source coverage is unavailable.");
        }
        setCoverage(coverageData);
      } catch (error) {
        if (sequence !== selectionSequence.current) return;
        setCoverageError(error.message || "Current source coverage is unavailable.");
      }
    } catch (error) {
      if (sequence !== selectionSequence.current) return;
      setSelected(null);
      setSelectionError(error.message || "Water-body details are unavailable.");
    } finally {
      if (sequence === selectionSequence.current) {
        setSelecting(false);
        setCoverageLoading(false);
      }
    }
  };

  const selectedModelStatus = typeof selected?.model_status === "string"
    ? selected.model_status
    : selected?.model_status?.status;
  const selectedStatus = selectedModelStatus === "data_model_validation_required"
    ? "Data/model validation required"
    : selectedModelStatus === "validated_prototype"
      ? "Validated prototype"
      : "Model status unavailable";
  const canRunAnalysis = Boolean(
    coverage?.model_status?.validated_for_water_body
    && coverage?.environment_sources?.model_inputs_complete
    && coverage?.satellite_source?.scene_metadata_available
    && coverage?.satellite_source?.model_ingestion_ready
  );
  const canRunSelectedMode = analysisMode === "demo"
    ? Boolean(selected?.id && !selected.detailsLoading)
    : canRunAnalysis;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top">
          <span className="brand-mark"><Icon name="water" size={22}/></span>
          <span>ALGAE<span className="brand-light">WATCH</span><small>EARLY WARNING SYSTEM</small></span>
        </a>
        <div className="sidebar-label">KARNATAKA</div>
        <a className="nav-item" href="#historical-prediction"><Icon name="water"/>Historical prediction</a>
        <a className="nav-item active" href="#lake-search"><Icon name="search"/>Find a water body</a>
        <a className="nav-item" href="#historical-data"><Icon name="satellite"/>Historical data</a>
        <a className="nav-item" href="#forecast"><Icon name="water"/>Bloom risk forecast</a>
        <a className="nav-item" href="#data-status"><Icon name="leaf"/>Data availability</a>
        <div className="sidebar-bottom">
          <span className="live-indicator"/>
          <span>Karnataka water-body catalogue</span>
          <small>Research prototype · predictions require lake-specific validation</small>
        </div>
      </aside>

      <main id="top" className="main-area">
        <header className="topbar">
          <div className="crumb">AlgaeWatch <span>/</span> <b>Karnataka water bodies</b></div>
          <div className="top-meta"><span className="status-pill"><i/> Research prototype</span></div>
        </header>

        <section className="page-content">
          <HistoricalPrediction />
          <section className="hero-row karnataka-hero" id="lake-search">
            <div>
              <p className="eyebrow"><span/> KARNATAKA LAKE EARLY WARNING</p>
              <h1>Find a lake or water body</h1>
              <p className="subhead">Search named water bodies from Karnataka’s official K-GIS layer.</p>
            </div>
            <div className="catalog-source-chip">
              <span className="lake-chip-icon"><Icon name="pin" size={19}/></span>
              <span><b>Karnataka, India</b><small>{catalogCount == null ? "K-GIS named water-body inventory" : `${catalogCount.toLocaleString("en-IN")} named catalogue records`}</small></span>
            </div>
          </section>

          <section className="research-panel lake-search-panel" aria-labelledby="search-heading">
            <div className="section-title">
              <div><p className="eyebrow">WATER-BODY SEARCH</p><h2 id="search-heading">Search Karnataka lakes</h2></div>
              <span className="window-pill">K-GIS · ALL LISTED SIZES</span>
            </div>
            <form className="catalog-search-form" onSubmit={submitSearch}>
              <label htmlFor="lake-search-input">Lake or water-body name</label>
              <div className="lake-search-input-row">
                <span className="search-input-icon"><Icon name="search" size={17}/></span>
                <input
                  id="lake-search-input"
                  minLength={2}
                  maxLength={80}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="e.g. Ulsoor Lake"
                  autoComplete="off"
                />
                <button className="run-button" disabled={searchState === "loading" || query.trim().length < 2}>
                  {searchState === "loading" ? <><span className="spinner"/>Searching</> : <>Search lakes <Icon name="arrow" size={15}/></>}
                </button>
              </div>
            </form>

            <div className="lake-examples" aria-label="Example Karnataka lakes">
              <span>Try</span>
              {EXAMPLE_LAKES.map((name) => (
                <button key={name} type="button" onClick={() => searchExample(name)} disabled={searchState === "loading"}>{name}</button>
              ))}
            </div>
            <p className="catalog-scope-note">Searches the full named K-GIS catalogue, including small urban lakes. These are example searches, not the complete list. Catalogue membership does not mean model validation.</p>

            {searchMessage && (
              <p className={`catalog-status ${searchState === "error" || searchState === "empty" ? "status-error" : ""}`} aria-live="polite">
                {searchMessage}
              </p>
            )}
            {items.length > 0 && (
              <div className="catalog-results lake-results" aria-label="Karnataka water-body search results">
                {items.map((item) => (
                  <SearchResult key={item.id} item={item} onSelect={selectWaterBody} disabled={selecting}/>
                ))}
              </div>
            )}
            {nextOffset != null && (
              <button className="catalog-load-more" type="button" onClick={loadMoreResults} disabled={loadingMore}>
                {loadingMore ? "Loading more…" : "Show more lakes"}
              </button>
            )}
            {selectionError && <div className="error-banner"><b>Water-body details unavailable</b><span>{selectionError}</span></div>}
          </section>

          {selected && (
            <>
              <section className="selected-water-body" aria-labelledby="selected-name">
                <div className="selected-heading">
                  <span className="selected-icon"><Icon name="water" size={20}/></span>
                  <div>
                    <p className="eyebrow">SELECTED WATER BODY</p>
                    <h2 id="selected-name">{selected.name}</h2>
                    <p>{[selected.district, selected.taluk, selected.state || "Karnataka"].filter(Boolean).join(" · ")}</p>
                  </div>
                  {(selecting || coverageLoading) && <span className="inline-loading"><span className="spinner spinner-dark"/>{selecting ? "Resolving location" : "Checking data sources"}</span>}
                </div>
                {!selecting && (
                  <div className="selected-meta">
                    <span><b>Location</b><small>{selected.location_resolved ? "Resolved from catalogue" : "Location data unavailable"}</small></span>
                    <span><b>Boundary</b><small>{selected.boundary_available ? "Available" : "Not available"}</small></span>
                    {Number.isFinite(Number(selected.area_ha)) && <span><b>Area</b><small>{Number(selected.area_ha).toFixed(1)} ha</small></span>}
                    <span><b>Model status</b><small className="validation-text">{selectedStatus}</small></span>
                  </div>
                )}
              </section>

              {!selected.detailsLoading && <LakeMap name={selected.name} mapView={selected.map_view} />}

              {!selected.detailsLoading && <HistoricalSnapshot key={selected.id} waterBodyId={selected.id} lakeName={selected.name} />}

              <section id="forecast" className="forecast-section">
                <div className="section-title">
                  <div><p className="eyebrow">FIVE-DAY MODEL HORIZON</p><h2>{analysisMode === "demo" ? "Practice Analysis" : "5-Day Bloom Risk Forecast"}</h2></div>
                  <span className="window-pill">{coverage?.forecast_horizon_days || 5}-DAY HORIZON</span>
                </div>
                <div className="analysis-mode-control" role="group" aria-label="Analysis mode">
                  <span>Analysis mode</span>
                  <button type="button" className={analysisMode === "live" ? "active" : ""} aria-pressed={analysisMode === "live"} onClick={() => changeAnalysisMode("live")}>Live</button>
                  <button type="button" className={analysisMode === "demo" ? "active demo-active" : ""} aria-pressed={analysisMode === "demo"} onClick={() => changeAnalysisMode("demo")}>Practice Analysis</button>
                </div>
                {analysisMode === "demo" ? (
                  <article className="forecast-unavailable demo-forecast">
                    <div className="forecast-value" aria-label={demoResult ? `Practice analysis result ${Number(demoResult.fused_probability * 100).toFixed(1)} percent` : "Practice analysis not run"}>
                      {demoResult ? `${Number(demoResult.fused_probability * 100).toFixed(1)}%` : "—"}
                    </div>
                    <div className="forecast-explanation">
                      <span className="demo-badge">PRACTICE RUN</span>
                      <h3>{demoResult ? "Model analysis complete" : "Run a practice analysis"}</h3>
                      <p><strong>Rehearsal result from example inputs. Not based on current measurements for this lake.</strong></p>
                      {demoResult && <p className="demo-component-scores">CNN {Number(demoResult.cnn_probability * 100).toFixed(1)}% · LSTM {Number(demoResult.lstm_probability * 100).toFixed(1)}% · 50/50 fusion · {demoResult.horizon_days}-day horizon</p>}
                    </div>
                    <button className="run-button analysis-button" type="button" onClick={runAnalysis} disabled={!canRunSelectedMode || analysisLoading} aria-describedby="analysis-limitation">
                      {analysisLoading ? <><span className="spinner"/>Running</> : demoResult ? "Run practice again" : "Run Practice Analysis"}
                    </button>
                    <p id="analysis-limitation" className="analysis-limitation">{analysisError || "Practice result only. Current lake measurements and model validation are needed for a live forecast."}</p>
                  </article>
                ) : (
                  <article className="forecast-unavailable">
                    <div className="forecast-value" aria-label={prediction ? `Model-estimated bloom risk ${prediction.percent.toFixed(1)} percent` : "Bloom risk probability unavailable"}>
                      {prediction ? `${prediction.percent.toFixed(1)}%` : "—"}
                    </div>
                    <div className="forecast-explanation">
                      <h3>{prediction ? "Model estimate available" : "Prediction unavailable for this water body"}</h3>
                      <p>{prediction ? "Five-day model estimate from the configured lake-specific input window." : coverage?.data_status?.reason || "Required satellite and in-lake environmental inputs are not currently available for a validated Karnataka prediction."}</p>
                      <span className="forecast-label">Model-estimated bloom risk probability</span>
                    </div>
                    <button className="run-button analysis-button" type="button" onClick={runAnalysis} disabled={!canRunSelectedMode || analysisLoading} aria-describedby="analysis-limitation">
                      {analysisLoading ? <><span className="spinner"/>Running</> : prediction ? "Run again" : "Run analysis"}
                    </button>
                    <p id="analysis-limitation" className="analysis-limitation">{analysisError || (!canRunAnalysis ? `${selectedStatus}. The analysis runs after lake validation and compatible data are available.` : "Research prototype. Not a confirmed toxic-HAB observation or public-health threshold.")}</p>
                    {!canRunAnalysis && <a className="historical-analysis-jump" href="#historical-data">View dated satellite and weather analysis, where available</a>}
                  </article>
                )}
              </section>

              <section id="data-status" className="data-status-section">
                <div className="section-title">
                  <div><p className="eyebrow">{analysisMode === "demo" ? "PRACTICE MODEL INPUTS" : "DATA AVAILABILITY"}</p><h2>{analysisMode === "demo" ? "Practice environmental inputs" : "Supporting inputs"}</h2></div>
                  <span className="window-pill">{analysisMode === "demo" ? "PRACTICE INPUTS" : coverageLoading ? "CHECKING SOURCES" : coverageError ? "SOURCE STATUS UNAVAILABLE" : "SOURCE STATUS"}</span>
                </div>
                {analysisMode === "demo" ? (
                  <div className="demo-inputs-panel">
                    <p><strong>Practice inputs.</strong> These example values and the raster are generated for this rehearsal. They are not current lake observations.</p>
                    {demoResult ? (
                      <>
                        <div className="weather-table-scroll">
                          <table className="demo-input-table">
                            <thead><tr>
                              <th>Date</th>
                              <th>Chlorophyll-a <small>Practice only</small></th>
                              <th>SST <small>Practice only</small></th>
                              <th>Rainfall <small>Practice only</small></th>
                              <th>Wind speed <small>Practice only</small></th>
                              <th>Imputed flag <small>Practice only</small></th>
                            </tr></thead>
                            <tbody>{demoResult.demo_inputs.environmental_rows.map((row) => (
                              <tr key={row.date}><td>{row.date}</td><td>{Number(row.chlorophyll_a).toFixed(2)}</td><td>{Number(row.sst).toFixed(2)}</td><td>{Number(row.rainfall).toFixed(2)}</td><td>{Number(row.wind_speed).toFixed(2)}</td><td>{row.chlorophyll_imputed}</td></tr>
                            ))}</tbody>
                          </table>
                        </div>
                        <div className="demo-raster-note"><Icon name="satellite"/><span><b>Practice four-band raster · B2 / B3 / B4 / B8</b><small>128×128 · existing model scaling and clipping · Practice only</small></span></div>
                      </>
                    ) : <p>Run Practice Analysis to generate and display the seven-day example sequence and four-band raster description.</p>}
                  </div>
                ) : (
                  <>
                {coverageError && <div className="error-banner coverage-error"><b>Data coverage unavailable</b><span>{coverageError}</span></div>}
                <div className="availability-grid">
                  <article className="availability-card">
                    <span className="availability-icon"><Icon name="satellite"/></span>
                    <div><b>Satellite scene metadata</b><small>{coverage?.satellite_source?.message || "No recent Sentinel-2 scene metadata is available. The archived model imagery is Vembanad-only."}</small></div>
                    <span className={`availability-state ${coverage?.satellite_source?.scene_metadata_available ? "context-only" : "unavailable"}`}>{coverage?.satellite_source?.scene_metadata_available ? "Metadata only" : "Unavailable"}</span>
                    {coverage?.satellite_source?.scene_metadata_available && (
                      <div className="satellite-preview-action">
                        {coverage.satellite_source.observation_date && <span>Observation · {coverage.satellite_source.observation_date}</span>}
                        {coverage.satellite_source.scene_cloud_cover_percent != null && (
                          <span>Scene-wide cloud cover · {Number(coverage.satellite_source.scene_cloud_cover_percent).toFixed(1)}% · not lake-specific</span>
                        )}
                        {coverage.satellite_source.scene_catalog_url && (
                          <a className="scene-source-link" href={coverage.satellite_source.scene_catalog_url} target="_blank" rel="noreferrer">Open Copernicus source record</a>
                        )}
                        {coverage.satellite_source.preview_available ? (
                          <button className="preview-button" type="button" onClick={loadSatellitePreview} disabled={satellitePreviewLoading}>
                            {satellitePreviewLoading ? "Loading image…" : satellitePreview ? "Refresh image" : "Load latest image"}
                          </button>
                        ) : (
                          <p className="preview-note">This current CDSE preview requires backend credentials. Downloaded historical images, where available, are shown in the separate snapshot above.</p>
                        )}
                        {satellitePreviewError && <p className="preview-error" role="alert">{satellitePreviewError}</p>}
                        {satellitePreview && (
                          <figure>
                            <img src={satellitePreview} alt={`Sentinel-2 true-colour preview of ${selected.name}`} />
                            <figcaption>True-colour preview · display only · not used by the model</figcaption>
                          </figure>
                        )}
                      </div>
                    )}
                  </article>
                  <article className="availability-card">
                    <span className="availability-icon"><Icon name="leaf"/></span>
                    <div>
                      <b>Chlorophyll-a and water temperature</b>
                      <small>{coverage?.environment_sources?.model_features?.chlorophyll_a?.use || "No confirmed current per-lake source is configured."} {coverage?.environment_sources?.model_features?.sst?.use || "In-lake SST is also unavailable."}</small>
                      <p className="research-source-note">Open research candidates, not retrieved for this lake: CLMS water quality (100 m, 10-day) and lake-surface temperature (~1 km, 10-day). Coverage is unverified; neither is a trained-model input.</p>
                      <div className="research-source-links">
                        <a href="https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/water-bodies/lake-water-quality/lwq-nrt_global_100m_10daily_v2.html" target="_blank" rel="noreferrer">CLMS lake water quality</a>
                        <a href="https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/temperature-and-reflectance/lake-surface-water-temperature/lswt-nrt_global_1km_10daily_v1.html" target="_blank" rel="noreferrer">CLMS lake temperature</a>
                      </div>
                    </div>
                    <span className="availability-state unavailable">Model inputs missing</span>
                  </article>
                  <article className="availability-card">
                    <span className="availability-icon weather-icon"><Icon name="water"/></span>
                    <div><b>Rainfall and wind</b><small>{coverage?.environment_sources?.weather_context?.available
                      ? `${coverage.environment_sources.weather_context.source} returned ${coverage.environment_sources.weather_context.rows.length} daily context records. These gridded values are not substituted into the trained model.`
                      : coverage?.environment_sources?.weather_context?.message || "Open-Meteo weather context is not currently available."}</small></div>
                    <span className={`availability-state ${coverage?.environment_sources?.weather_context?.available ? "context-only" : "unavailable"}`}>{coverage?.environment_sources?.weather_context?.available ? "Context only" : "Unavailable"}</span>
                  </article>
                </div>
                <WeatherContextTable weather={coverage?.environment_sources?.weather_context} />
                  </>
                )}
              </section>
            </>
          )}

          {!selected && (
            <section className="forecast-empty" aria-labelledby="empty-heading">
              <span className="empty-water-icon"><Icon name="water" size={22}/></span>
              <div><h2 id="empty-heading">Select a water body to view its data status</h2><p>Live forecasts require validated inputs. Practice Analysis runs the saved model on example inputs.</p></div>
            </section>
          )}

          <details className="model-details">
            <summary>Model and data notes</summary>
            <div className="model-details-body">
              <p>The existing CNN/LSTM was developed with Vembanad Lake data in Kerala. It is not validated for Karnataka lakes. Catalogue selection resolves location metadata; it does not make a water body eligible for a prediction.</p>
              <p>The inspected Vembanad export path uses Sentinel-2 surface-reflectance bands B2, B3, B4, B8 in that order, cropped to the Vembanad rectangle at 10 m. The bulk export code applies no SCL cloud mask; the inference code also applies no cloud mask. It resizes to 128×128, divides by 10,000, then clips values to [0, 2]. Upstream scene/date selection criteria are not recorded. These inputs do not validate the model for Karnataka lakes.</p>
              <p>Copernicus CLMS has open 10-day lake-water-quality and lake-surface-temperature products, but their cadence, spatial coverage, and source-unit compatibility have not been verified for this model. They are not currently used as model inputs.</p>
              <p>Model estimates use chlorophyll-threshold proxy labels, not confirmed toxic-HAB observations, and are research outputs rather than health advisories.</p>
            </div>
          </details>

          <footer className="app-footer">
            <span>ALGAEWATCH · KARNATAKA</span>
            <span>Live results require validation · Practice runs use example inputs</span>
          </footer>
        </section>
      </main>
    </div>
  );
}

export default App;
