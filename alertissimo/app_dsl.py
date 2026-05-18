import sys
import subprocess

# Check if setuptools is installed
try:
    import setuptools
    print(f"setuptools version: {setuptools.__version__}")
    print(f"setuptools location: {setuptools.__file__}")
except ImportError as e:
    print(f"setuptools not found: {e}")
    # Try to install it
    subprocess.check_call([sys.executable, "-m", "pip", "install", "setuptools"])
    import setuptools
    print("setuptools installed successfully")

# Now try importing pkg_resources
try:
    import pkg_resources
    print("pkg_resources imported successfully")
    print(f"pkg_resources location: {pkg_resources.__file__}")
except ImportError as e:
    print(f"pkg_resources not found: {e}")

# Finally try antares_client
import antares_client
print("antares_client imported successfully")

import streamlit as st
from dotenv import load_dotenv
from alertissimo.core.orchestrator import run_ir
from alertissimo.plot.lightcurve_altair import plot_lightcurve
from alertissimo.core.schema import WorkflowIR
from alertissimo.dsl.dsl_parser_validator import parse_dsl_script, validate_capabilities, DSLParseError
import pandas as pd
from typing import Any, Dict

def find_summary(obj: Any) -> Dict[str, Any]:
    """Recursively search for the 'summary' dictionary in nested structures"""
    if isinstance(obj, dict):
        if 'summary' in obj:
            return obj['summary']
        for value in obj.values():
            result = find_summary(value)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_summary(item)
            if result is not None:
                return result
    return None

def display_broker_object(obj: Any, broker_name: str):
    st.subheader(f"{broker_name.upper()} Object")

    if isinstance(obj, list):
        if not obj:
            st.info("No objects returned.")
            return
        for i, entry in enumerate(obj):
            with st.expander(f"Result {i + 1}", expanded=i == 0):
                display_broker_object(entry, broker_name)
        return

    if not isinstance(obj, dict):
        st.warning("Unsupported object type")
        st.json(obj)
        return

    # Optional highlights
    with st.container():
        object_id = obj.get("objectId") or obj.get("i:objectId")
        if object_id:
            st.markdown(f"🔭 **Object ID**: `{object_id}`")

        ra, dec = obj.get("i:ra"), obj.get("i:dec")
        if ra and dec:
            st.markdown(f"📍 **RA / Dec**: `{ra}`, `{dec}`")

        if "firstmjd" in obj and "lastmjd" in obj:
            st.markdown(f"🕒 **First / Last MJD**: `{obj['firstmjd']}` → `{obj['lastmjd']}`")

    """Display the summary dictionary in a DataFrame if found"""
    summary = find_summary(obj)

    if summary is None:
        st.warning("No 'summary' section found in the data")
        return

    # Flatten the summary dictionary to simple types
    flat = {k: v for k, v in summary.items()
            if isinstance(v, (str, int, float, bool, type(None)))}

    if not flat:
        st.warning("Summary found but contains no displayable data")
        return

    st.markdown("### Summary")
    st.dataframe(
        pd.DataFrame(flat.items(), columns=["Key", "Value"]),
        use_container_width=True
    )

    # Full nested view
    st.markdown("### Full Object (Nested)")
    st.json(obj, expanded=False)


st.title("Alertissimo Visualizer (DSL Demo)")
st.markdown("Paste DSL script, validate it, and run as an orchestrated IR.")

dsl_input = st.text_area("📜 DSL Script", height=300, placeholder="e.g.\nfind object_id=ZTF23abc sources=[fink, alerce]\nlightcurve source=fink")

if st.button("🔍 Validate and Run"):
    try:
        st.info("Parsing DSL script...")
        steps = parse_dsl_script(dsl_input)

        # debug of steps
        #st.write("=== DEBUG ===")
        #st.write(f"steps type: {type(steps)}")
        #st.write(f"steps length: {len(steps)}")
        #for i, step in enumerate(steps):
        #    st.write(f"steps[{i}] type: {type(step)}")
        #    if isinstance(step, list):
        #        st.write(f"  → list with {len(step)} items")
        #        for j, sub in enumerate(step):
        #            st.write(f"    steps[{i}][{j}] type: {type(sub)}")
        

        st.success("✅ DSL parsed successfully")

        st.info("Validating broker capabilities...")

        all_errors = []
        for step in steps:
            step_errors = validate_capabilities(step)
            if step_errors:
                all_errors.extend(step_errors)

        if all_errors:
            st.error("❌ Capability validation failed:")
            for err in all_errors:
                st.markdown(f"- {err}")
        else:
            st.success("✅ Capability validation passed")

            st.subheader("Parsed DSL Steps")

            # Wrap in WorkflowIR
            ir = WorkflowIR(
                name="DSL Workflow",
                steps=steps
            )

            st.info("Running orchestrator...")
            results = run_ir(ir)
            st.success("🎉 Pipeline finished!")

            st.subheader("Confirmed Objects")
            for broker, snapshot in results.object_snapshots.items():
                st.write(f"**{broker}**: alert {'✅ confirmed' if snapshot else '❌ not confirmed'}")

            st.subheader("Object dictionaries")
            for broker, snapshot in results.find_results.items():
                display_broker_object(snapshot, broker)

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
                    st.json(matches)

            st.subheader("Kafka Monitoring")
            for broker, res in results.kafka_results.items():
                st.write(f"**{broker}**: {'✅ Monitored' if res else '❌ Not monitored'}")

    except DSLParseError as e:
        st.error(f"DSL Parse Error: {e}")
    except Exception as e:
        st.exception(e)
