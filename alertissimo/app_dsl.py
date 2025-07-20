import streamlit as st
from dotenv import load_dotenv
from alertissimo.core.orchestrator import run_ir
from alertissimo.plot.lightcurve_altair import plot_lightcurve
from alertissimo.core.schema import WorkflowIR
from alertissimo.dsl.dsl_parser_validator import parse_dsl_script, validate_capabilities, DSLParseError, load_broker_registry_from_yaml

load_dotenv()

st.title("Alertissimo Visualizer (DSL Demo)")
st.markdown("Paste DSL script, validate it, and run as an orchestrated IR.")

dsl_input = st.text_area("📜 DSL Script", height=300, placeholder="e.g.\nfind object_id=ZTF23abc sources=[fink, alerce]\nlightcurve source=fink")

if st.button("🔍 Validate and Run"):
    try:
        st.info("Parsing DSL script...")
        steps = parse_dsl_script(dsl_input)
        st.success("✅ DSL parsed successfully")

        st.info("Validating broker capabilities...")

        #broker_yaml_dir = Path("alertissimo/core/brokers/registry")
        #broker_names = [p.stem for p in broker_yaml_dir.glob("*.yaml")]

        broker_registry = load_broker_registry_from_yaml()
        #broker_registry = load_broker_registry(["fink", "alerce", "lasair", "antares"])
        
        all_errors = []
        for step in steps:
            step_errors = validate_capabilities(step, broker_registry)
            if step_errors:
                all_errors.extend(step_errors)

        if all_errors:
            st.error("❌ Capability validation failed:")
            for err in all_errors:
                st.markdown(f"- {err}")
        else:
            st.success("✅ Capability validation passed")

            # Wrap in WorkflowIR
            ir = WorkflowIR(
                name="From DSL",
                filter=[s for s in steps if s.__class__.__name__ == "FilterCondition"],
                classify=[s for s in steps if s.__class__.__name__ == "Classifier"],
                enrich=[s for s in steps if "Step" in s.__class__.__name__],
                act=[s for s in steps if s.__class__.__name__ == "ActStep"],
                findobject=next((s for s in steps if s.__class__.__name__ == "FindObject"), None),
                confirm=next((s for s in steps if s.__class__.__name__ == "ConfirmationRule"), None),
                score=[s for s in steps if s.__class__.__name__ == "ScoringRule"],
            )

            st.info("Running orchestrator...")
            results = run_ir(ir)
            st.success("🎉 Pipeline finished!")

            st.subheader("Confirmed Objects")
            for broker, snapshot in results.object_snapshots.items():
                st.json({broker: str(snapshot)})

            st.subheader("Object dictionaries")
            for broker, snapshot in results.find_results.items():
                st.json({broker: str(snapshot)})

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

