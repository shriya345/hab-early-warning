# HAB Early-Warning System

Final-year CSE project for Harmful Algal Bloom early-warning prediction in Vembanad Lake.

## Ryder / Integration Track

Current implementation includes:

- Input schema validation
- Satellite/environmental date alignment
- No-future-image leakage check
- Provisional chlorophyll-a-based bloom labels
- 5-day-ahead target creation
- Chronological train/test split
- Random Forest baseline model
- Accuracy, precision, recall, F1 and confusion matrix

## Important

Current baseline metrics were generated using mock data only to verify that the software pipeline works.

They are not scientific project results.

Real project inputs will later be supplied as:

### Satellite
`data/sentinel2/sentinel_index.csv`

Columns:

`date,image_path,cloud_percentage`

### Environmental
`data/environmental/processed/environmental_dataset.csv`

Columns:

`date,lat,lon,chlorophyll_a,sst,rainfall,wind_speed`


## 5-Day Bloom Probability and Risk Level

The Random Forest baseline also produces a model-estimated probability
of bloom occurrence five days ahead using `predict_proba()`.

Prototype risk categories are currently:

- LOW: probability < 30%
- MEDIUM: probability >= 30% and < 60%
- HIGH: probability >= 60%

These risk thresholds are PROVISIONAL operational thresholds for
prototype demonstration only. They are not scientifically validated
HAB thresholds.

Once sufficient real labeled HAB data is available, probability and
alert thresholds will be evaluated and calibrated using chronological
validation and appropriate classification metrics such as precision,
recall, F1-score, ROC-AUC and/or Precision-Recall analysis.

Current mock-data probabilities and evaluation metrics are used only
to verify that the end-to-end forecasting pipeline functions correctly.
