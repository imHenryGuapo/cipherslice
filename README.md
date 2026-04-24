# CipherSlice

CipherSlice is a Streamlit-based 3D printing control plane for:

- mesh upload and print optimization
- blueprint review and reconstruction guidance
- approval-gated release
- SD card, manual download, and secure connector delivery paths

## Run locally

From `C:\Users\Owner\OneDrive\Documents\GitHub\cipherslice`:

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
  Controlled end-to-end handoff. Requires a slicer backend plus a local `CipherBridge` or supported relay.

- `SD card export`
  Recommended club demo path. Practical for offline printers and locked-down school desktops.

- `Manual download only`
  Best fallback path for review, demos, or unsupported environments.

## Internal agent model

CipherSlice uses a four-part internal orchestration model:

- `Inspector`
  Reviews the upload for manufacturability, scale, and geometry risk.

- `Calibrator`
  Chooses print settings around printer, filament, print goal, and reliability.

- `G-Code Architect`
  Prepares the slicing plan and the artifact path.

- `Cipher Vault`
  Handles delivery logic, release gating, and secure artifact framing.

This framing is mostly for demos, judging, and technical explanation. The consumer-facing UI is intentionally simpler so the product feels more like click, drop, review, and go.

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

## Deploy suggestion

The easiest public deployment path is Streamlit Community Cloud:

1. Push this folder to a GitHub repository
2. Go to Streamlit Community Cloud
3. Create an app from the repo
4. Select `app.py` as the entrypoint

Official docs:

- [Prep and deploy on Community Cloud](https://docs.streamlit.io/streamlit-community-cloud/get-started/deploy-an-app)
- [Deploy your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
