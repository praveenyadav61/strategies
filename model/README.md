# Market Regime Detection Model

This folder contains a machine learning pipeline designed to detect and classify different market regimes using historical price data. The model uses an unsupervised learning approach to segment market conditions into distinct states: **Risk-On**, **Risk-Off**, and **Neutral**. Understanding the current market regime can help algorithmic trading strategies adapt their parameters dynamically.

## Architecture & Workflow

The architecture is built as a two-stage pipeline:
1.  **Data Ingestion & Feature Engineering (`pipeline_mr.py`)**: Raw OHLCV data is downloaded, and various technical indicators and statistical features are engineered to capture trend, momentum, and volatility.
2.  **Modeling & Classification (`regime_model.py`)**: The engineered features are scaled, dimensionally reduced, and clustered to identify the hidden market regimes.

### Step-by-Step Execution:
1.  **Download**: Historical data for selected indices/ETFs (like Nifty 50) is fetched using `yfinance`.
2.  **Feature Creation**: Technical indicators like RSI, ADX, NATR, and Garman-Klass Volatility are calculated. Relative distances to various Exponential Moving Averages (EMAs) are computed to capture trends.
3.  **Dimensionality Reduction**: Principal Component Analysis (PCA) is applied to the scaled features to reduce noise and multicollinearity while retaining 85% of the variance.
4.  **Clustering**: A Gaussian Mixture Model (GMM) with 3 components is fitted to the PCA-transformed data.
5.  **Regime Mapping**: The resulting mathematical clusters are mapped to human-readable labels based on their underlying characteristics (e.g., the cluster with the highest distance above the 200-EMA is labeled "Risk-On").
6.  **Transition Smoothing**: A logical smoothing layer is applied to enforce realistic Markovian state transitions, preventing abrupt direct jumps between "Risk-On" and "Risk-Off" without passing through a "Neutral" state.

## Model Details

*   **Model Type**: Unsupervised Machine Learning (Clustering).
*   **Core Algorithms**:
    *   **PCA (Principal Component Analysis)**: Used for feature extraction and dimensionality reduction.
    *   **GMM (Gaussian Mixture Model)**: A probabilistic model that assumes the data is generated from a mixture of a finite number of Gaussian distributions with unknown parameters. It excels at soft clustering, providing probabilities for each data point belonging to each regime.
*   **Features Engineered**:
    *   *Trend*: Distance from price to 10, 21, 50, and 200-period EMAs; Spreads between EMAs.
    *   *Momentum*: RSI (7, 14, 28 periods), Average Directional Index (ADX - 14 periods).
    *   *Volatility*: Normalized Average True Range (NATR) for 5, 14, 21 periods; Garman-Klass Volatility (21 periods).
    *   *Volume*: Z-scores of volume over 5 and 20 periods.
    *   *Rate of Change*: 1-day and 5-day differences for key metrics to capture sequence tracking and momentum shifts.

## File Structure

*   **`pipeline_mr.py`**: The data engineering pipeline. Downloads market data and constructs the complex feature matrix. Outputs data to `nsei_regime_features.csv`.
*   **`regime_model.py`**: The core machine learning script. Loads the feature matrix, scales the data, trains the PCA and GMM models, smooths the output transitions, and visualizes the regimes on a price chart. It outputs the final classifications to `nsei_regime_results.csv`.
*   **`order.py`**: A simple utility data class representing a financial order (`symbol`, `side`, `price`, `quantity`, `date`). While part of the broader trading ecosystem, it is not directly consumed by the regime classification pipeline.

## Usage

1.  First, run the data pipeline to generate the necessary features:
    ```bash
    python pipeline_mr.py
    ```
2.  Next, train the model and generate regime classifications and visualizations:
    ```bash
    python regime_model.py
    ```

## New Supervised Forecasting Pipeline

The implementation-plan version lives under `market_regime/`. It keeps the older
PCA/GMM files intact and builds a modular, auditable supervised pipeline with
5 trader-style labels:

* `STRONG_RISK_OFF`
* `RISK_OFF`
* `NEUTRAL`
* `RISK_ON`
* `STRONG_RISK_ON`

Install the model-specific dependencies when needed:

```bash
pip install -r requirements.txt
```

Run the full pipeline from the repository root:

```bash
python model/market_regime/run_pipeline.py
```

Main outputs:

* `market_regime/data/raw/nifty_indices_raw.csv`
* `market_regime/data/features/features_base.csv`
* `market_regime/data/features/features_support_resistance.csv`
* `market_regime/data/features/features_trendline.csv`
* `market_regime/data/features/features_breakouts.csv`
* `market_regime/data/labels/regime_labels.csv`
* `market_regime/data/labels/ground_truth_validation.csv`
* `market_regime/data/features/model_dataset.csv`
* `market_regime/data/models/model_5d.pkl`
* `market_regime/data/models/model_10d.pkl`
* `market_regime/data/models/feature_importance.csv`
* `market_regime/data/models/shap_values.csv` when `shap` is installed, otherwise `shap_status.txt`
* `market_regime/data/models/transition_matrix.csv`
* `market_regime/data/models/transition_heatmap.png`
* `market_regime/data/models/regime_duration_report.csv`
* `market_regime/data/diagnostics/regime_distribution.csv`
* `market_regime/data/diagnostics/regime_score_distribution.csv`
* `market_regime/data/diagnostics/feature_audit.csv`
* `market_regime/data/evaluation/evaluation_summary.csv`
* `market_regime/data/predictions/raw_probabilities.csv`
* `market_regime/data/predictions/final_regime_forecast.csv`

`ground_truth.csv` is used for validation only. The training labels are generated
by the configurable trader label engine in `market_regime/src/label_engine.py`.
The refactor in `Market Regime Model Refactor.docx` is implemented phase-wise
except for breadth features and walk-forward validation, which are intentionally
skipped for now.
