import { API } from "./api";
import { useState } from 'react';

export default function HistoricalPrediction() {
  const [result, setResult] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState('');
  async function run() {
    setLoading(true); setError('');
    try {
      const response = await fetch(`${API}/historical-predictions/vembanad`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Historical model run failed.');
      setResult(data);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }
  return <section id="historical-prediction" className="archive-prediction">
    <div className="section-title"><div><p className="eyebrow">ARCHIVED DATA · SAVED CNN + LSTM</p><h2>Historical bloom-risk prediction</h2></div><span className="window-pill">5-DAY FORECAST WINDOW</span></div>
    <div className="archive-prediction-card">
      <div className="archive-prediction-heading"><div><h3>Vembanad Lake, Kerala</h3><p>Sentinel-2 image: 22 February 2024<br/>Environmental sequence: 16–22 February 2024<br/>Forecast target: 27 February 2024</p></div><button className="run-button" onClick={run} disabled={loading}>{loading ? 'Running saved models…' : result ? 'Run historical prediction again' : 'Run historical prediction'}</button></div>
      <p className="archive-source-note">Uses the project’s archived satellite raster and environmental dataset, including its recorded chlorophyll imputation flags. This dated estimate applies to Vembanad, independently of the Karnataka lake selected below.</p>
      {error && <p role="alert" className="coastal-error">{error}</p>}
      {result && <div aria-live="polite">
        <div className="archive-probabilities">
          <div className="archive-fused"><small>Fused bloom-risk estimate</small><strong>{result.bloom_risk_percent.toFixed(2)}%</strong><span>Target date · {result.forecast_target_date}</span></div>
          <div><small>CNN probability</small><strong>{(result.cnn_probability * 100).toFixed(2)}%</strong><span>Archived B2 / B3 / B4 / B8</span></div>
          <div><small>LSTM probability</small><strong>{(result.lstm_probability * 100).toFixed(2)}%</strong><span>Seven archived environmental rows</span></div>
        </div>
        <p className="archive-source-note">50% CNN + 50% LSTM · {result.imputed_chlorophyll_days} of 7 chlorophyll values marked imputed in the source archive.</p>
        <details><summary>View the seven model input rows</summary><div className="weather-table-scroll"><table><thead><tr><th>Date</th>{result.environmental_features.map(f => <th key={f}>{f}</th>)}</tr></thead><tbody>{result.environmental_rows.map(r => <tr key={r.date}><td>{r.date}</td>{result.environmental_features.map(f => <td key={f}>{r[f].toFixed(f === 'chlorophyll_imputed' ? 0 : 4)}</td>)}</tr>)}</tbody></table></div><p>Values shown in the original archived training feature units.</p></details>
        <p className="archive-result-note">{result.note}</p>
      </div>}
    </div>
  </section>;
}
