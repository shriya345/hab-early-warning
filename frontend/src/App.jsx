
import { useState } from "react";

function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const runPrediction = async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(
        "/api/predict/vembanad"
      );

      if (!response.ok) {
        throw new Error(
          `Request failed with status ${response.status}`
        );
      }

      const data = await response.json();
      setResult(data);

    } catch (err) {
      setError(err.message);

    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        fontFamily: "Arial, sans-serif",
        padding: "2rem",
        maxWidth: "700px",
        margin: "0 auto",
      }}
    >
      <h1>HAB Early-Warning System</h1>
      <h2>Vembanad Lake</h2>

      <p>
        CNN + LSTM Harmful Algal Bloom Risk Prediction
      </p>

      <button
        onClick={runPrediction}
        disabled={loading}
      >
        {loading
          ? "Running prediction..."
          : "Get Bloom Risk Prediction"}
      </button>

      {error && (
        <p style={{ color: "red" }}>
          Error: {error}
        </p>
      )}

      {result && (
        <div style={{ marginTop: "2rem" }}>
          <h2>Prediction Result</h2>

          <p>
            <strong>Lake:</strong>{" "}
            {result.lake}
          </p>

          <p>
            <strong>Prediction Date:</strong>{" "}
            {result.prediction_date}
          </p>

          <p>
            <strong>Forecast Date:</strong>{" "}
            {result.forecast_date}
          </p>

          <p>
            <strong>CNN Probability:</strong>{" "}
            {(result.cnn_probability * 100).toFixed(1)}%
          </p>

          <p>
            <strong>LSTM Probability:</strong>{" "}
            {(result.lstm_probability * 100).toFixed(1)}%
          </p>

          <p>
            <strong>Final 5-Day Bloom Risk:</strong>{" "}
            {result.bloom_risk_percent.toFixed(1)}%
          </p>
        </div>
      )}
    </div>
  );
}

export default App;
