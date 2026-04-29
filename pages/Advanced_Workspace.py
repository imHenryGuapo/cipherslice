import streamlit as st


st.set_page_config(
    page_title="CipherSlice Advanced Workspace",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def jump_to_guided(target: str | None = None) -> None:
    if target:
        st.session_state["review_workspace_target"] = target
    st.session_state["experience_mode"] = "Advanced"
    st.switch_page("app.py")


st.session_state["experience_mode"] = "Advanced"
active_job = st.session_state.get("active_job")

st.title("Advanced Workspace")
st.caption(
    "The expert lane for tuning, comparison, and release decisions. This page keeps the same live CipherSlice job underneath, but gives advanced users a cleaner place to work."
)

top_col1, top_col2 = st.columns([1.2, 0.8], gap="large")
with top_col1:
    with st.container(border=True):
        st.markdown("### Why this page exists")
        st.write(
            "Advanced users usually want fewer beginner explanations and faster access to deeper tuning. This workspace gives them a more direct launch point without forking the job into a second app."
        )
        st.write(
            "The same shared plan still powers review, comparison, and release. You are changing the work surface, not making a duplicate project."
        )
with top_col2:
    with st.container(border=True):
        st.markdown("### Quick navigation")
        if st.button("Open Advanced Builder", use_container_width=True, type="primary"):
            jump_to_guided()
        if st.button("Back to Guided Setup", use_container_width=True):
            st.session_state["experience_mode"] = "Beginner"
            st.switch_page("app.py")

if not active_job:
    empty_col1, empty_col2 = st.columns(2, gap="medium")
    with empty_col1:
        with st.container(border=True):
            st.markdown("### No active job yet")
            st.write(
                "Build a job from the main app first, then come back here to work in the advanced lane."
            )
            st.write(
                "Fastest path: upload the model, choose printer and material, then continue into tuning and release."
            )
    with empty_col2:
        with st.container(border=True):
            st.markdown("### Best next move")
            st.write(
                "Start in Guided Setup to create the live plan, then return here once CipherSlice has something real to tune."
            )
            if st.button("Go to Guided Setup", use_container_width=True):
                st.session_state["experience_mode"] = "Beginner"
                st.switch_page("app.py")
else:
    metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4, gap="medium")
    metric_col1.metric("Active file", active_job.get("filename", "Unknown"))
    metric_col2.metric("Workflow", active_job.get("mode", "Unknown"))
    metric_col3.metric("Printer", active_job.get("printer", "Unknown"))
    metric_col4.metric("Material", active_job.get("filament", "Unknown"))

    summary_col1, summary_col2 = st.columns([1.1, 0.9], gap="large")
    with summary_col1:
        with st.container(border=True):
            st.markdown("### Job summary")
            st.write(f"**Quality profile:** {active_job.get('quality_profile', 'Unknown')}")
            st.write(f"**Print goal:** {active_job.get('print_goal', 'Unknown')}")
            st.write(f"**Support strategy:** {active_job.get('support_strategy', 'Unknown')}")
            st.write(f"**Adhesion strategy:** {active_job.get('adhesion_strategy', 'Unknown')}")
            st.write(f"**Delivery path:** {active_job.get('delivery_mode', 'Unknown')}")
    with summary_col2:
        with st.container(border=True):
            st.markdown("### Recommended use")
            st.write(
                "Use this page when you want to jump quickly into tuning, compare different plan directions, or open the final release surface without working through the full beginner rhythm."
            )

    st.markdown("### Open a focused review area")
    jump_col1, jump_col2, jump_col3, jump_col4, jump_col5 = st.columns(5, gap="medium")
    with jump_col1:
        if st.button("Overview", use_container_width=True):
            jump_to_guided("Overview")
    with jump_col2:
        if st.button("Fit + 3D", use_container_width=True):
            jump_to_guided("Fit + 3D")
    with jump_col3:
        if st.button("Tuning", use_container_width=True, type="primary"):
            jump_to_guided("Tuning")
    with jump_col4:
        if st.button("Compare", use_container_width=True):
            jump_to_guided("Compare")
    with jump_col5:
        if st.button("Release", use_container_width=True):
            jump_to_guided("Release")

    lower_col1, lower_col2 = st.columns(2, gap="large")
    with lower_col1:
        with st.container(border=True):
            st.markdown("### What this page will grow into")
            st.write("The next level of this workspace is to move deeper tuning and compare controls here directly, instead of sending advanced users back into the guided review page.")
            st.write("That keeps CipherSlice calm for beginners and faster for expert users.")
    with lower_col2:
        with st.container(border=True):
            st.markdown("### Prusa backend readiness")
            st.write(
                "Once the UI split is stable, this is the best place to expose backend-aware controls, slicer profile selection, and advanced print package diagnostics."
            )
