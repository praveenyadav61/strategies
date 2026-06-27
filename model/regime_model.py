import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
import matplotlib.pyplot as plt
import seaborn as sns
import os


def load_feature_matrix(filepath: str) -> pd.DataFrame:
    """Loads the feature matrix from a CSV file."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"Feature matrix not found at {filepath}. "
            "Please run pipeline_mr.py first to generate it."
        )
    df = pd.read_csv(filepath, index_col='Date', parse_dates=True)
    return df


def preprocess_and_reduce(
    features_df: pd.DataFrame,
    n_pca_variance: float = 0.85
) -> tuple[pd.DataFrame, PCA, StandardScaler]:
    """
    Scales features and applies PCA for dimensionality reduction.
    """
    # Exclude original price data and volume from the feature set for scaling
    feature_cols = features_df.columns.drop(['Open', 'High', 'Low', 'Close', 'Volume'], errors='ignore')
    features = features_df[feature_cols].copy()

    # Handle any potential NaNs that might have slipped through
    features.dropna(inplace=True)

    # Scale features
    scaler = StandardScaler()
    scaled_features = scaler.fit_transform(features)

    # Apply PCA
    pca = PCA(n_components=n_pca_variance)
    pca_features = pca.fit_transform(scaled_features)

    print(f"PCA retained {pca.n_components_} components, "
          f"explaining {np.sum(pca.explained_variance_ratio_)*100:.2f}% of the variance.")

    # Return as a DataFrame to keep the index
    pca_df = pd.DataFrame(pca_features, index=features.index)
    return pca_df, pca, scaler


def fit_gmm_model(
    data: pd.DataFrame,
    n_components: int = 3
) -> tuple[GaussianMixture, np.ndarray, np.ndarray]:
    """
    Initializes and fits a Gaussian Mixture Model.
    """
    gmm = GaussianMixture(n_components=n_components, random_state=42, covariance_type='full')
    gmm.fit(data)
    
    labels = gmm.predict(data)
    probabilities = gmm.predict_proba(data)
    
    return gmm, labels, probabilities


def map_regime_labels(
    df_with_labels: pd.DataFrame,
    original_features_df: pd.DataFrame
) -> tuple[pd.DataFrame, dict]:
    """
    Maps numerical GMM clusters to human-readable regime labels based on
    volatility and trend profiles.
    """
    # Align indices before merging
    aligned_features = original_features_df.loc[df_with_labels.index]
    
    # Add the GMM labels to the aligned feature dataframe for analysis
    analysis_df = aligned_features.copy()
    analysis_df['gmm_cluster'] = df_with_labels['gmm_cluster']

    # Group by cluster and calculate mean of key indicators
    # Using long-term trend (dist_ema_200) and volatility (natr_14)
    regime_profiles = analysis_df.groupby('gmm_cluster')[['dist_ema_200', 'natr_14']].mean()
    
    # Logic to map clusters to regimes
    # Risk-On: Highest trend (price well above long-term average)
    # Risk-Off: Lowest trend (price well below long-term average)
    # Neutral: In-between
    risk_on_cluster = regime_profiles['dist_ema_200'].idxmax()
    risk_off_cluster = regime_profiles['dist_ema_200'].idxmin()
    
    label_map = {
        risk_on_cluster: 'Risk-On',
        risk_off_cluster: 'Risk-Off'
    }
    
    # Find the neutral cluster
    neutral_cluster = [c for c in range(3) if c not in [risk_on_cluster, risk_off_cluster]][0]
    label_map[neutral_cluster] = 'Neutral'
    
    print("Regime Profiles (Cluster Means):")
    print(regime_profiles)
    print("\nInferred Label Mapping:")
    print(label_map)

    df_with_labels['gmm_regime'] = df_with_labels['gmm_cluster'].map(label_map)
    return df_with_labels, label_map


def enforce_regime_transitions(df: pd.DataFrame, raw_label_col: str) -> pd.DataFrame:
    """
    Enforces a Markovian state machine rule: no direct jumps between
    Risk-On and Risk-Off. Forces such transitions to Neutral.
    """
    df_smoothed = df.copy()
    
    # Numerical mapping for easier logic
    state_map = {'Risk-Off': 0, 'Neutral': 1, 'Risk-On': 2}
    inv_state_map = {v: k for k, v in state_map.items()}
    
    # Create a numeric column for raw and smoothed regimes
    df_smoothed['numeric_regime'] = df_smoothed[raw_label_col].map(state_map)
    df_smoothed['smoothed_numeric_regime'] = df_smoothed['numeric_regime'].copy()
    
    smoothed_regimes = df_smoothed['smoothed_numeric_regime'].values
    
    for i in range(1, len(smoothed_regimes)):
        prev_state = smoothed_regimes[i-1]
        current_state = smoothed_regimes[i]
        
        # Check for invalid transitions (e.g., |2 - 0| = 2 > 1)
        if abs(current_state - prev_state) > 1:
            # Force the transition to be Neutral
            smoothed_regimes[i] = 1 # Neutral state
            
    df_smoothed['smoothed_numeric_regime'] = smoothed_regimes
    df_smoothed['smoothed_regime'] = df_smoothed['smoothed_numeric_regime'].map(inv_state_map)
    
    return df_smoothed


def plot_regimes(df: pd.DataFrame, ticker_name: str = "Nifty 50"):
    """
    Plots the close price with background colored by the smoothed regime.
    """
    sns.set(style='darkgrid')
    fig, ax = plt.subplots(figsize=(15, 8))

    # Define colors for regimes
    regime_colors = {
        'Risk-On': 'lightgreen',
        'Neutral': 'lightgray',
        'Risk-Off': 'lightcoral'
    }

    # Plot the close price
    ax.plot(df.index, df['Close'], label=f'{ticker_name} Close', color='navy', linewidth=1.5)

    # Add colored background for regimes
    for regime, color in regime_colors.items():
        # Find contiguous blocks for each regime
        for i, g in (df['smoothed_regime'] == regime).cumsum().groupby((df['smoothed_regime'] != regime).cumsum()):
            if g.all():
                start_date = g.index[0]
                end_date = g.index[-1]
                ax.axvspan(start_date, end_date, color=color, alpha=0.4)

    # Create custom legend patches
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=color, edgecolor='grey', alpha=0.4, label=regime)
                       for regime, color in regime_colors.items()]
    
    ax.legend(handles=legend_elements, loc='upper left')
    ax.set_title(f'{ticker_name} Market Regimes', fontsize=16, fontweight='bold')
    ax.set_ylabel('Close Price')
    ax.set_xlabel('Date')
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    # Configuration
    N_COMPONENTS = 3
    PCA_VARIANCE_THRESHOLD = 0.85

    script_dir = os.path.dirname(os.path.abspath(__file__))
    INPUT_FILE = os.path.join(script_dir, "nsei_regime_features.csv")

    # 1. Load Data
    print(f"Loading feature matrix from {INPUT_FILE}...")
    full_df = load_feature_matrix(INPUT_FILE)
    
    # Keep original close prices for plotting
    close_prices = full_df[['Close']].copy()

    # 2. Preprocess and Reduce Dimensionality
    print("Preprocessing data and applying PCA...")
    # Select only engineered features for the model
    feature_cols = [col for col in full_df.columns if col not in ['Open', 'High', 'Low', 'Close', 'Volume']]
    features_for_model = full_df[feature_cols]
    
    pca_df, pca_model, scaler = preprocess_and_reduce(
        features_for_model,
        n_pca_variance=PCA_VARIANCE_THRESHOLD
    )

    # 3. GMM Clustering
    print(f"Fitting Gaussian Mixture Model with {N_COMPONENTS} components...")
    gmm_model, gmm_labels, gmm_probs = fit_gmm_model(pca_df, n_components=N_COMPONENTS)

    # Combine results into a single DataFrame
    results_df = close_prices.loc[pca_df.index].copy()
    results_df['gmm_cluster'] = gmm_labels
    for i in range(N_COMPONENTS):
        results_df[f'prob_cluster_{i}'] = gmm_probs[:, i]

    # 4. Map Labels
    print("Mapping GMM clusters to regime labels...")
    results_df, label_mapping = map_regime_labels(results_df, full_df)

    # 5. Smooth Transitions
    print("Enforcing Markovian state transitions...")
    smoothed_results_df = enforce_regime_transitions(results_df, raw_label_col='gmm_regime')

    # Display regime distribution
    print("\nSmoothed Regime Distribution:")
    print(smoothed_results_df['smoothed_regime'].value_counts(normalize=True).mul(100).round(2).astype(str) + '%')
    # smoothed_results_df.to_csv(os.path.join(script_dir, "nsei_regime_results.csv"), index=True)
    # 6. Visualize Results
    print("Generating regime plot...")
    plot_regimes(smoothed_results_df, ticker_name="Nifty 50")

    print("\nScript finished successfully.")