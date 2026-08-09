import streamlit as st
from dotenv import load_dotenv
from alertissimo.core.orchestrator import run_ir
from alertissimo.core.smbbh_ir import smbbh_ir
from alertissimo.plot.lightcurve_altair import plot_lightcurve

load_dotenv()

st.title("Alertissimo Visualizer (Demo)")
st.markdown("Run the SMBBH pipeline and explore results.")

if st.button("Run Pipeline"):
    with st.spinner("Running pipeline..."):
        results = run_ir(smbbh_ir)

    st.success("Pipeline finished!")

    st.subheader("Confirmed Objects")
    for broker, snapshot in results.object_snapshots.items():
        #st.json({broker: str(snapshot)[:200] + "..."})  # Preview stringified
        st.json({broker: str(snapshot)})  # Preview stringified

    st.subheader("Light Curves")
    for broker, lc in results.lightcurves.items():
        if lc and "detections" in lc and lc["detections"]:
            st.subheader(f"📈 Lightcurve from {broker}")
            plot_lightcurve(lc)
        else:
            st.info("No detections found in lightcurve.")

    st.subheader("Crossmatches")
    for broker, matches in results.crossmatch_results.items():
        st.write(f"**{broker}**: {len(matches)} match(es)")
        if matches:
            st.json(matches)  # show sample
            #st.json(matches[:3])  # show sample

    st.subheader("Kafka Monitoring")
    for broker, res in results.kafka_results.items():
        st.write(f"**{broker}**: {'✅ Monitored' if res else '❌ Not monitored'}")

