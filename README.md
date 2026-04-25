# CipherSlice

CipherSlice is a Streamlit-based 3D printing control plane for:

- mesh upload and print optimization
- blueprint review and reconstruction guidance
- approval-gated release
- SD card, manual download, and secure connector delivery paths

## Run locally

From `C:\Users\Owner\OneDrive\Desktop\3D_slicer`:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.port 8501
```

Then open:

```text
http://localhost:8501
```

## Best demo flow

For a school or club demo:

1. Choose `Friend` or `Best Friend`
2. Choose `SD card export` as the delivery strategy
3. Use `Reliable Print Mode`
4. Upload a real `.stl` or `.obj`
5. Review recommendations, edit overrides if needed, and approve the plan
6. Export the artifact and move it to the printer workflow

## Delivery modes

- `Secure local connector`
  Best long-term path. Requires a slicer backend plus a local `CipherBridge` or supported relay.

- `SD card export`
  Best club demo path. Practical for offline printers and locked-down school desktops.

- `Manual download only`
  Best fallback path for review, demos, or unsupported environments.

## Real-world integrations

### 1. Slicer backend

To enable real production slicing, set:

```text
CIPHERSLICE_SLICER_PATH
```

Point it to a local slicer executable such as a PrusaSlicer-style CLI path.

### 2. Local printer connector

To enable secure handoff, set:

```text
CIPHERSLICE_CONNECTOR_URL
```

Point it to a local `CipherBridge`-style service or supported printer relay.

### 3. Optional live AI worker runtime

CipherSlice can also run the four internal workers as real model-backed summaries instead of only using built-in deterministic copy.

Enable that path with:

```text
CIPHERSLICE_ENABLE_LIVE_MODELS=true
OPENAI_API_KEY=...
```

Optional runtime tuning:

```text
CIPHERSLICE_AGENT_MODEL=gpt-5.4
CIPHERSLICE_AGENT_REASONING=medium
CIPHERSLICE_AGENT_TIMEOUT_SEC=20
```

This runtime is intentionally optional:

- if it is configured, CipherSlice can generate cleaner live role summaries for the user-facing review flow
- if it is not configured, CipherSlice falls back to the built-in planning engine
- the slicer backend still remains the source of truth for final printer-valid G-code

## Internal architecture plan

CipherSlice is moving toward a four-role orchestration model:

1. `Inspector`
   Validates intake quality, geometry, scale, fit, and reconstruction readiness.

2. `Calibrator`
   Converts printer, material, and job intent into a safe print strategy.

3. `G-Code Architect`
   Prepares the slicer-ready manufacturing plan and final artifact handoff.

4. `Cipher Vault`
   Hashes, encrypts, gates release, and controls delivery packaging.

### How this works with a real slicer

CipherSlice should not invent raw production toolpaths by language reasoning alone.

The intended stack is:

- `Human`
  chooses goals, reviews the plan, and approves release

- `CipherSlice`
  validates, recommends, organizes, and packages the job

- `Slicer backend`
  generates the real printer-valid G-code

### Safe slicer handoff contract

Before a slicer runs, CipherSlice now prepares a structured handoff contract that includes:

- source file
- part label
- printer
- filament
- build volume
- part size
- G-code flavor
- layer height
- infill
- wall loops
- print speed
- nozzle and bed temperatures
- support / adhesion state
- delivery mode
- confidence
- release gate status
- artifact hash

This is the bridge between the AI-guided planning layer and the deterministic slicer layer.

### UI policy

The user-facing site should stay clean:

- show concise review summaries
- show editable plan sections
- show warnings and blockers clearly
- hide verbose model prompts and internal orchestration details
- keep live worker failures behind a simple status message instead of spilling raw API/debug text into the main workflow

The README and backend code can carry the deeper orchestration details without turning the front end into a developer console.

## Deploy suggestion

The easiest public deployment path is Streamlit Community Cloud:

1. Push this folder to a GitHub repository
2. Go to Streamlit Community Cloud
3. Create an app from the repo
4. Select `app.py` as the entrypoint

Official docs:

- [Prep and deploy on Community Cloud](https://docs.streamlit.io/streamlit-community-cloud/get-started/deploy-an-app)
- [Deploy your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
