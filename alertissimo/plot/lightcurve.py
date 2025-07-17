import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from typing import Optional

def plot_lightcurve(lc: dict, title:Optional[str] = none):
    """
    Plots a normalized magpsf lightcurve from a lightcurve dict as returned by ALeRCE or other brokers.
    Assumes detections are under lc["detections"].
    """

    if not lc or "detections" not in lc or not lc["detections"]:
        st.warning("⚠️ No valid detections to plot.")
        return

    df = pd.DataFrame(lc["detections"])

    if df.empty or "mjd" not in df or "magpsf" not in df:
        st.warning("⚠️ Incomplete data for plotting.")
        return

    # Normalize magpsf for plotting (invert mag scale: higher = brighter)
    mags = df["magpsf"]
    mag_min, mag_max = mags.min(), mags.max()
    padding = (mag_max - mag_min) * 0.2 if mag_max > mag_min else 1.0
    y_min = mag_max + padding
    y_max = mag_min - padding

    # Plot
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(df["mjd"], df["magpsf"], marker="o", linestyle="-", color="tab:blue")
    ax.set_xlabel("MJD")
    ax.set_ylabel("magpsf")
    ax.set_title(title)
    ax.set_ylim(y_min, y_max)  # invert y-axis
    ax.grid(True)

    st.pyplot(fig)

