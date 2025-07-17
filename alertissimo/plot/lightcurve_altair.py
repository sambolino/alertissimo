import altair as alt
import pandas as pd
import streamlit as st


def plot_lightcurve(lc, mag_field="magpsf", time_field="mjd"):
    """
    Plots an interactive lightcurve using Altair.

    Parameters:
    - lc: dict containing ALeRCE-format lightcurve (with "detections" key)
    - mag_field: string, the magnitude field to plot (default "magpsf")
    - time_field: string, the time field to plot on x-axis (default "mjd")
    """
    if lc and "detections" in lc and lc["detections"]:
        df = pd.DataFrame(lc["detections"])
        if df.empty or mag_field not in df or time_field not in df:
            st.info("No valid data to plot.")
            return

        # Drop rows with NaNs in important columns
        df = df[[time_field, mag_field]].dropna()

        # Normalize mag_field to 1.2× the range for better y-axis fit
        mag_min, mag_max = df[mag_field].min(), df[mag_field].max()
        buffer = (mag_max - mag_min) * 0.1
        ydomain = [mag_max + buffer, mag_min - buffer]  # invert y-axis

        chart = alt.Chart(df).mark_circle(size=60).encode(
            x=alt.X(f"{time_field}:Q", title="MJD", scale=alt.Scale(zero=False)),
            y=alt.Y(f"{mag_field}:Q", title=mag_field, scale=alt.Scale(domain=ydomain)),
            tooltip=[time_field, mag_field],
        ).interactive()

        st.altair_chart(chart, use_container_width=True)

    else:
        st.info("No detections to plot.")

