# Kochi live ingestion presentation

Open http://127.0.0.1:5173/#live-ingestion with the backend and frontend running.
The station panel loads independently of Karnataka lake selection.

1. Show the chlorophyll-a and water-temperature readings and their observation times.
2. Click **Refresh readings**. The backend requests the public INCOIS source pages,
   parses their numerical chart series, verifies names/units/timestamps, and returns JSON.
   Requests within 60 seconds reuse the most recent attempt to avoid excessive source requests.
3. Show the history charts and expand **Latest 10 source readings**.
4. Open the official source links to demonstrate provenance.

The browser checks every five minutes while the page is open. This is ingestion
of recent published observations, not a promise that the buoy updates immediately.
A refresh can return the same observations. Data older than 24 hours are labelled
SOURCE DELAYED. If fetching fails, saved readings remain labelled CACHED with an
error notice. Their original observation and retrieval timestamps are preserved.

Endpoint: `GET /live-stations/kochi` (frontend proxy: `/api/live-stations/kochi`).
No API credentials are required. The last successful response is stored in
`outputs/incois_kochi_live_cache.json`; retain this file for the presentation.
The numerical feed is embedded in official public chart pages, not a documented
stable JSON API. Source format changes fail closed and require parser maintenance.

The initial successful ingestion returned 258 chlorophyll-a observations and 260
water-temperature observations, ending 2026-09-25 12:30 UTC (18:00 IST), with gaps.
Chlorophyll-a was 1.67 µg/L and water temperature was 27.054 °C at that time.
No source quality flags accompany these chart series. The station is coastal
Kochi, not a Karnataka lake, and these data do not enable the lake prediction model.

Checks: `python -m unittest discover -s tests -p 'test_live_coastal.py' -v`
and `npm run build --prefix frontend`.
