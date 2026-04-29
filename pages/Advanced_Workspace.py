import streamlit as st


st.set_page_config(
    page_title="CipherSlice Advanced Print Lab",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .advanced-hero {
        background: rgba(8, 24, 38, 0.9);
        border: 1px solid rgba(104, 241, 193, 0.18);
        border-radius: 20px;
        padding: 1.15rem 1.2rem;
        margin-bottom: 1rem;
    }
    .advanced-kicker {
        color: #7ce0bf;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-size: 0.78rem;
        margin-bottom: 0.25rem;
    }
    .advanced-title {
        color: #f4f8fb;
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }
    .advanced-copy {
        color: #abc0cf;
        line-height: 1.55;
    }
    .advanced-note {
        border-radius: 16px;
        padding: 0.85rem 0.95rem;
        border: 1px solid rgba(104, 144, 177, 0.16);
        background: rgba(9, 19, 31, 0.75);
        color: #abc0cf;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.session_state["experience_mode"] = "Advanced"
active_job = st.session_state.get("active_job")

ADVANCED_PRINTERS = [
    "Bambu X1 Carbon",
    "Bambu P1S",
    "Bambu P1P",
    "Prusa MK4S",
    "Creality K1 Max",
    "Custom / Large Format",
]
ADVANCED_MATERIALS = [
    "PLA",
    "PLA Silk",
    "PLA Wood",
    "PETG",
    "PETG-GF",
    "ABS",
    "ASA",
    "TPU",
    "Nylon",
    "CF Nylon",
]
ADVANCED_QUALITY = ["Balanced production", "Draft / fast iteration", "Detail / cosmetic"]
ADVANCED_GOALS = ["Balanced everyday part", "Functional strength", "Visual prototype"]
ADVANCED_SUPPORT = ["Auto", "Always on", "Disabled"]
ADVANCED_ADHESION = ["Auto", "Brim", "Raft", "Skirt"]
ADVANCED_DELIVERY = ["Secure local connector", "SD card export", "Manual download only"]


def open_guided_setup() -> None:
    st.session_state.pop("advanced_direct_build", None)
    st.session_state["experience_mode"] = "Beginner"
    st.switch_page("app.py")


def open_advanced_builder() -> None:
    st.session_state["advanced_direct_build"] = True
    st.session_state["experience_mode"] = "Advanced"
    st.switch_page("app.py")


st.markdown(
    """
    <div class="advanced-hero">
        <div class="advanced-kicker">Expert lane</div>
        <div class="advanced-title">Advanced Print Lab</div>
        <div class="advanced-copy">
            This is the focused expert workspace. It uses the same shared CipherSlice job underneath, but keeps
            advanced tuning, compare, and release work out of the calmer beginner flow.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

top_col1, top_col2 = st.columns([1.15, 0.85], gap="large")
with top_col1:
    with st.container(border=True):
        st.markdown("### Why this page exists")
        st.write(
            "Advanced users usually want less hand-holding and quicker access to tuning, comparison, and release decisions. This workspace provides that without forking the project into a second app."
        )
with top_col2:
    with st.container(border=True):
        st.markdown("### Navigation")
        if st.button("Open Shared Build Flow", use_container_width=True, type="primary"):
            open_advanced_builder()
        if st.button("Back to Guided Setup", use_container_width=True):
            open_guided_setup()

section = st.radio(
    "Advanced areas",
    ["Overview", "Start Build", "Compare", "Release"],
    horizontal=True,
    index=1 if not active_job else 0,
)

if not active_job:
    if section == "Start Build":
        with st.container(border=True):
            st.markdown("### Upload a file here")
            st.write(
                "You can start from Advanced Print Lab too. Upload a real print file here, then tune it directly on this page without being pushed back into the guided flow."
            )
            advanced_upload = st.file_uploader(
                "Upload STL, OBJ, or 3MF",
                type=["stl", "obj", "3mf"],
                key="advanced_workspace_upload",
            )
            if advanced_upload is not None:
                st.session_state["advanced_pending_upload"] = {
                    "name": advanced_upload.name,
                    "type": getattr(advanced_upload, "type", ""),
                    "bytes": advanced_upload.getvalue(),
                }
            staged_payload = st.session_state.get("advanced_pending_upload")
            if staged_payload:
                staged_name = str(staged_payload.get("name", "advanced_upload.stl"))
                st.markdown(
                    f'<div class="advanced-note">Loaded <strong>{staged_name}</strong> in Advanced Print Lab. The expert controls below are now ready to tune.</div>',
                    unsafe_allow_html=True,
                )
                st.markdown("### Expert tuning controls")
                top_row1, top_row2 = st.columns(2, gap="medium")
                with top_row1:
                    st.selectbox("Target printer", ADVANCED_PRINTERS, key="advanced_lab_printer")
                    st.selectbox("Filament type", ADVANCED_MATERIALS, key="advanced_lab_material")
                    st.selectbox("Quality profile", ADVANCED_QUALITY, key="advanced_lab_quality")
                    st.selectbox("Print goal", ADVANCED_GOALS, key="advanced_lab_goal")
                    st.selectbox("Support strategy", ADVANCED_SUPPORT, key="advanced_lab_support")
                with top_row2:
                    st.selectbox("Build plate adhesion", ADVANCED_ADHESION, key="advanced_lab_adhesion")
                    st.selectbox("Delivery mode", ADVANCED_DELIVERY, key="advanced_lab_delivery")
                    st.number_input("Layer height (mm)", min_value=0.08, max_value=0.6, value=0.20, step=0.02, format="%.2f", key="advanced_lab_layer")
                    st.number_input("Wall loops", min_value=1, max_value=10, value=3, step=1, key="advanced_lab_walls")
                    st.number_input("Infill (%)", min_value=0, max_value=100, value=20, step=1, key="advanced_lab_infill")

                st.markdown("### Fine tuning")
                fine_col1, fine_col2, fine_col3 = st.columns(3, gap="medium")
                with fine_col1:
                    st.number_input("Nozzle temperature (degC)", min_value=150, max_value=320, value=220, step=1, key="advanced_lab_nozzle")
                    st.number_input("Bed temperature (degC)", min_value=0, max_value=130, value=60, step=1, key="advanced_lab_bed")
                    st.number_input("Print speed (mm/s)", min_value=10, max_value=400, value=95, step=5, key="advanced_lab_speed")
                with fine_col2:
                    st.number_input("Outer wall speed (mm/s)", min_value=10, max_value=300, value=55, step=5, key="advanced_lab_outer")
                    st.number_input("Inner wall speed (mm/s)", min_value=10, max_value=300, value=80, step=5, key="advanced_lab_inner")
                    st.number_input("Travel speed (mm/s)", min_value=20, max_value=500, value=180, step=5, key="advanced_lab_travel")
                with fine_col3:
                    st.number_input("First-layer speed (mm/s)", min_value=5, max_value=100, value=20, step=1, key="advanced_lab_first_speed")
                    st.number_input("Brim width (mm)", min_value=0.0, max_value=20.0, value=4.0, step=0.5, format="%.1f", key="advanced_lab_brim")
                    st.selectbox("Seam position", ["Rear", "Aligned", "Nearest", "Random"], key="advanced_lab_seam")

                action_col1, action_col2 = st.columns(2, gap="medium")
                with action_col1:
                    if st.button("Open Full Build Tools", use_container_width=True, type="primary", key="advanced_continue_shared"):
                        open_advanced_builder()
                with action_col2:
                    if st.button("Clear This Upload", use_container_width=True, key="advanced_clear_upload"):
                        st.session_state.pop("advanced_pending_upload", None)
                        for cleanup_key in [
                            "advanced_lab_printer",
                            "advanced_lab_material",
                            "advanced_lab_quality",
                            "advanced_lab_goal",
                            "advanced_lab_support",
                            "advanced_lab_adhesion",
                            "advanced_lab_delivery",
                            "advanced_lab_layer",
                            "advanced_lab_walls",
                            "advanced_lab_infill",
                            "advanced_lab_nozzle",
                            "advanced_lab_bed",
                            "advanced_lab_speed",
                            "advanced_lab_outer",
                            "advanced_lab_inner",
                            "advanced_lab_travel",
                            "advanced_lab_first_speed",
                            "advanced_lab_brim",
                            "advanced_lab_seam",
                        ]:
                            st.session_state.pop(cleanup_key, None)
                        st.rerun()
        with st.container(border=True):
            st.markdown("### Best next step")
            st.write(
                "Once the file is loaded, keep tuning it here. If you want the full shared builder later, open it only when you are ready."
            )
    else:
        with st.container(border=True):
            st.markdown("### No active job yet")
            st.write(
                "There is no live job loaded yet. Start in `Start Build` on this page or go back to the guided setup to create the active plan."
            )
else:
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4, gap="medium")
    metric_col1.metric("Active file", active_job.get("filename", "Unknown"))
    metric_col2.metric("Workflow", active_job.get("mode", "Unknown"))
    metric_col3.metric("Printer", active_job.get("printer", "Unknown"))
    metric_col4.metric("Material", active_job.get("filament", "Unknown"))

    if section == "Overview":
        overview_col1, overview_col2 = st.columns([1.1, 0.9], gap="large")
        with overview_col1:
            with st.container(border=True):
                st.markdown("### Job summary")
                st.write(f"**Quality profile:** {active_job.get('quality_profile', 'Unknown')}")
                st.write(f"**Print goal:** {active_job.get('print_goal', 'Unknown')}")
                st.write(f"**Support strategy:** {active_job.get('support_strategy', 'Unknown')}")
                st.write(f"**Adhesion strategy:** {active_job.get('adhesion_strategy', 'Unknown')}")
                st.write(f"**Delivery path:** {active_job.get('delivery_mode', 'Unknown')}")
        with overview_col2:
            with st.container(border=True):
                st.markdown("### Best use")
                st.write(
                    "Use this page when you want faster access to the live job without walking through the full beginner rhythm again."
                )

    elif section == "Start Build":
        with st.container(border=True):
            st.markdown("### Continue the advanced build")
            st.write(
                "Your live job is already loaded. Open the shared build flow to adjust printer, material, tuning, and plan details in Advanced mode."
            )
            if st.button("Open Shared Build Flow", use_container_width=True, type="primary", key="advanced_open_builder_repeat"):
                open_advanced_builder()

    elif section == "Compare":
        with st.container(border=True):
            st.markdown("### Compare workspace")
            snapshot_bank = list(st.session_state.get("plan_snapshots", []))
            st.write(
                "Use the shared build flow to compare plan snapshots and saved tuning directions. This page keeps the advanced lane calm while the detailed compare tools stay tied to the active job."
            )
            st.caption(f"Saved snapshot count in this session: {len(snapshot_bank)}")
            if st.button("Open compare tools", use_container_width=True, type="primary", key="advanced_compare_jump"):
                st.session_state["review_workspace_target"] = "Compare"
                open_advanced_builder()

    elif section == "Release":
        with st.container(border=True):
            st.markdown("### Release workspace")
            st.write(
                "Use this area when you are ready to review output truthfulness, approval state, and handoff packaging. The final release controls still live in the shared build flow so they stay tied to the active plan."
            )
            approval_key = active_job.get("approval_key")
            if approval_key:
                st.caption(
                    f"Approval status right now: {'Approved' if st.session_state.get(approval_key, False) else 'Awaiting human approval'}"
                )
            if st.button("Open release tools", use_container_width=True, type="primary", key="advanced_release_jump"):
                st.session_state["review_workspace_target"] = "Release"
                open_advanced_builder()
