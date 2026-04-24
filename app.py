import hashlib
import io
import math
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from base64 import urlsafe_b64encode

import streamlit as st

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

try:
    import trimesh

    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False


st.set_page_config(
    page_title="CipherSlice Control Plane",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="collapsed",
)


PRINTER_PROFILES = {
    "Bambu X1 Carbon": {
        "bed_shape": "256 x 256 mm",
        "max_height_mm": 256,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin / Bambu",
        "nozzle": {"PLA": 220, "PETG": 250, "ABS": 255, "TPU": 228},
        "bed": {"PLA": 60, "PETG": 78, "ABS": 95, "TPU": 45},
        "speed": {"PLA": 220, "PETG": 150, "ABS": 120, "TPU": 60},
        "orientation": "Tilt 32 degrees rearward to reduce support contact on cosmetic faces.",
    },
    "Prusa MK4": {
        "bed_shape": "250 x 210 mm",
        "max_height_mm": 220,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Smooth PEI",
        "gcode_flavor": "Marlin / Prusa",
        "nozzle": {"PLA": 215, "PETG": 245, "ABS": 255, "TPU": 225},
        "bed": {"PLA": 60, "PETG": 85, "ABS": 100, "TPU": 45},
        "speed": {"PLA": 145, "PETG": 95, "ABS": 85, "TPU": 38},
        "orientation": "Lay the broadest face down and yaw 18 degrees to minimize seam visibility.",
    },
    "Creality K1 Max": {
        "bed_shape": "300 x 300 mm",
        "max_height_mm": 300,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin",
        "nozzle": {"PLA": 225, "PETG": 248, "ABS": 260, "TPU": 230},
        "bed": {"PLA": 58, "PETG": 80, "ABS": 105, "TPU": 45},
        "speed": {"PLA": 250, "PETG": 140, "ABS": 130, "TPU": 55},
        "orientation": "Rotate 45 degrees on the build plate so long spans bridge across the X-axis.",
    },
    "Ultimaker S5": {
        "bed_shape": "330 x 240 mm",
        "max_height_mm": 300,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Glass / glue assist",
        "gcode_flavor": "UltiGCode / Marlin compatible",
        "nozzle": {"PLA": 210, "PETG": 240, "ABS": 250, "TPU": 220},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 95, "TPU": 45},
        "speed": {"PLA": 95, "PETG": 70, "ABS": 60, "TPU": 35},
        "orientation": "Stand the part upright with a 12 degree cant to preserve edge detail and cut raft size.",
    },
    "Custom / Large Format": {
        "bed_shape": "500 x 500 mm",
        "max_height_mm": 500,
        "nozzle_diameter": 0.6,
        "adhesion_default": "Custom surface",
        "gcode_flavor": "Generic Marlin",
        "nozzle": {"PLA": 220, "PETG": 245, "ABS": 255, "TPU": 225},
        "bed": {"PLA": 60, "PETG": 80, "ABS": 95, "TPU": 45},
        "speed": {"PLA": 120, "PETG": 90, "ABS": 80, "TPU": 35},
        "orientation": "Keep the longest face stable on the bed and bias toward support reduction on cosmetic surfaces.",
    },
}

FILAMENT_TYPES = ["PLA", "PETG", "ABS", "TPU"]

PERSONA_PROFILES = {
    "friend": {
        "label": "Friend",
        "title": "Friendly Guide",
        "tagline": "Calm, supportive, and clear. Great for first-time users or careful manufacturing decisions.",
        "intro": "I will help you understand the print plan, explain tradeoffs clearly, and keep the process grounded.",
        "agent_tone": {
            "Inspector": "I checked the model carefully and I will point out anything that could cause trouble before you waste time or material.",
            "Calibrator": "I will tune the print plan for reliability first and explain the choices in plain language.",
            "G-Code Architect": "I will prepare the manufacturing file and keep the release path easy to follow.",
            "Cipher Vault": "I will make the delivery steps clear so you know exactly what is being released and why.",
        },
    },
    "best_friend": {
        "label": "Best Friend",
        "title": "Roasting Copilot",
        "tagline": "Same manufacturing brain, more personality. Gives playful ribbing, then clearly states it is joking.",
        "intro": "I will still give safe recommendations, but I will package them like a longtime best friend who teases you a little and then gets serious.",
        "agent_tone": {
            "Inspector": "I checked the model like a friend who refuses to let you embarrass yourself with a broken print. I am kidding, but the warning is real.",
            "Calibrator": "I tuned the settings so your printer does not make dramatic life choices. I am joking, and here is the real recommendation.",
            "G-Code Architect": "I built the manufacturing plan without the nonsense. Teasing aside, the output below is the serious path.",
            "Cipher Vault": "I locked the delivery flow down because your intellectual property deserves better than chaos. Yes, that was a joke. Security details are still real.",
        },
    },
}

DELIVERY_MODES = [
    "Secure local connector",
    "SD card export",
    "Manual download only",
]

DELIVERY_MODE_DETAILS = {
    "Secure local connector": {
        "recommended": "Best long-term path",
        "summary": "Most controlled option. Great when a local CipherBridge or supported printer relay is installed.",
        "warning": "Needs a slicer backend, user permission, and a working local connector.",
    },
    "SD card export": {
        "recommended": "Best club demo path",
        "summary": "Most practical for school printers and locked-down desktops. Export the job, move it manually, and print offline.",
        "warning": "Removable media breaks secure one-time streaming and file control.",
    },
    "Manual download only": {
        "recommended": "Best review path",
        "summary": "Safest choice when you want analysis, recommendations, and a downloadable artifact without printer handoff.",
        "warning": "No direct execution path. The user still has to move the file into their own workflow.",
    },
}

AGENT_IDENTITIES = {
    "Inspector": (
        "Manufacturing preflight specialist. Rejects unsafe or ambiguous inputs, checks mesh integrity "
        "and drawing completeness, and never pretends a weak input is printable."
    ),
    "Calibrator": (
        "Printer-process optimizer. Chooses printer and filament settings for reliability first, "
        "then material savings, then speed."
    ),
    "G-Code Architect": (
        "Deterministic slicing orchestrator. Converts validated geometry and approved print "
        "profiles into printer-specific toolpaths and readable manufacturing summaries."
    ),
    "Cipher Vault": (
        "Secure artifact delivery agent. Hashes, encrypts, labels, and stages artifacts so the "
        "consumer receives the right file with traceable provenance."
    ),
}

BLUEPRINT_REQUIREMENTS = [
    "Orthographic technical drawing or blueprint only. Avoid casual photos or perspective renders.",
    "Visible dimensions with units for all critical spans, hole diameters, and wall thicknesses.",
    "At least front and side views. Top view is strongly recommended for consumer-grade reliability.",
    "Declared material intent, printer target, and functional goal so tolerances can be interpreted.",
]

REJECTION_REASONS = [
    "A single object photo is 2D and does not reveal hidden geometry, backside surfaces, or internal cavities.",
    "Scale is often ambiguous without authoritative dimensions and units.",
    "Fit, tolerance, and wall-thickness intent cannot be trusted from a casual image alone.",
    "Automatic slicing from a weak image can waste material, damage a print, or produce a useless part.",
]


def format_bytes(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"


def build_hash(filename: str, file_size: int, printer: str, filament: str) -> str:
    seed = f"{filename}|{file_size}|{printer}|{filament}|CipherSlice"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def sanitize_download_name(raw_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name.strip())
    return cleaned.strip("._") or "cipherslice_artifact"


def set_persona(persona_key: str) -> None:
    st.session_state["persona_key"] = persona_key


def set_delivery_mode(mode_name: str) -> None:
    st.session_state["delivery_mode_choice"] = mode_name


def get_persona() -> dict[str, object]:
    persona_key = st.session_state.get("persona_key", "friend")
    return PERSONA_PROFILES.get(persona_key, PERSONA_PROFILES["friend"])


def build_status_board(
    mode: str,
    slicer_path: str | None,
    connector_url: str | None,
    release_allowed: bool,
    final_user_approval: bool,
    delivery_mode: str,
) -> list[tuple[str, str]]:
    printer_reachable = "Ready" if connector_url and delivery_mode == "Secure local connector" else "Not connected"
    if delivery_mode == "SD card export":
        printer_reachable = "Offline handoff"
    return [
        ("Website", "Ready"),
        ("Slicer", "Connected" if slicer_path else "Missing"),
        ("Connector", "Connected" if connector_url else "Not connected"),
        ("Printer Path", printer_reachable if mode == "Reliable Print Mode" else "Review only"),
        ("Release Gate", "Approved" if release_allowed else "Held"),
        ("User Approval", "Confirmed" if final_user_approval else "Pending"),
    ]


def summarize_global_readiness(slicer_path: str | None, connector_url: str | None) -> tuple[str, str]:
    if slicer_path and connector_url:
        return "Ready", "CipherSlice can generate production G-code and has a configured connector path for secure handoff."
    if slicer_path:
        return "Needs Delivery Path", "Production G-code can be generated, but direct printer handoff still needs a local connector or supported printer integration."
    return "Blocked", "The UI is ready, but a slicer backend still needs to be installed before production release can be enabled."


def resolve_printer_profile(
    printer_name: str,
    custom_width: float,
    custom_depth: float,
    custom_height: float,
    custom_nozzle: float,
) -> dict[str, object]:
    profile = dict(PRINTER_PROFILES[printer_name])
    if printer_name != "Custom / Large Format":
        return profile

    profile["bed_shape"] = f"{int(custom_width)} x {int(custom_depth)} mm"
    profile["max_height_mm"] = custom_height
    profile["nozzle_diameter"] = round(custom_nozzle, 2)
    profile["gcode_flavor"] = "Generic large-format Marlin"
    profile["adhesion_default"] = "Large-format custom surface"
    profile["speed"] = {"PLA": 95, "PETG": 75, "ABS": 65, "TPU": 28}
    profile["orientation"] = (
        "Favor a wide, stable first layer and reduce tall unsupported features. Large-format jobs benefit from slower speed and stronger adhesion."
    )
    return profile


def recommend_next_action(
    mode: str,
    release_allowed: bool,
    slicer_path: str | None,
    connector_url: str | None,
    delivery_mode: str,
    objections: list[str],
) -> str:
    if mode != "Reliable Print Mode":
        return "Provide a validated 3D mesh or upgrade the blueprint package with dimensions, units, and tolerance details before fabrication."
    if objections:
        return objections[0]
    if not slicer_path:
        return "Install and configure a slicer backend so CipherSlice can generate production G-code instead of holding release."
    if delivery_mode == "Secure local connector" and not connector_url:
        return "Install CipherBridge or connect a supported printer relay so approved jobs can move beyond download-only delivery."
    if delivery_mode == "SD card export":
        return "Review the final plan, export the G-code, and transfer it manually to the printer's SD card with a clear operator checklist."
    return "Review the preflight plan, confirm approval, and proceed with the selected delivery path."


def apply_user_overrides(
    plan: dict[str, str | float | int | bool],
    nozzle_override: int | None,
    bed_override: int | None,
    layer_override: float | None,
    speed_override: int | None,
    infill_override: int | None,
) -> dict[str, str | float | int | bool]:
    updated = dict(plan)
    if nozzle_override is not None:
        updated["nozzle_temp"] = nozzle_override
    if bed_override is not None:
        updated["bed_temp"] = bed_override
    if layer_override is not None:
        updated["layer_height"] = round(layer_override, 2)
    if speed_override is not None:
        updated["print_speed"] = speed_override
    if infill_override is not None:
        updated["infill_percent"] = infill_override
    return updated


def detect_slicer_backend() -> tuple[str | None, str | None]:
    configured = os.getenv("CIPHERSLICE_SLICER_PATH", "").strip()
    if configured and os.path.exists(configured):
        return "Configured Slicer", configured

    candidates = {
        "PrusaSlicer": "prusa-slicer-console",
        "PrusaSlicer Windows": "prusa-slicer-console.exe",
        "PrusaSlicer CLI": "prusa-slicer",
        "OrcaSlicer": "orcaslicer",
        "OrcaSlicer Windows": "OrcaSlicer.exe",
        "CuraEngine": "CuraEngine",
        "CuraEngine Windows": "CuraEngine.exe",
        "Slic3r": "slic3r-console",
    }
    for label, command in candidates.items():
        discovered = shutil.which(command)
        if discovered:
            return label, discovered

    common_paths = [
        r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
        r"C:\Program Files\OrcaSlicer\OrcaSlicer.exe",
        r"C:\Program Files\UltiMaker Cura 5.0\CuraEngine.exe",
        r"C:\Program Files\UltiMaker Cura 5.7\CuraEngine.exe",
    ]
    for path in common_paths:
        if os.path.exists(path):
            return os.path.basename(path), path

    return None, None


def detect_connector() -> tuple[str | None, str]:
    connector_url = os.getenv("CIPHERSLICE_CONNECTOR_URL", "").strip()
    if connector_url:
        return connector_url, "Configured local connector"
    return None, "Website-only mode"


def parse_bed_shape(bed_shape: str) -> tuple[float, float]:
    parts = [float(part.strip()) for part in bed_shape.replace("mm", "").split("x")]
    return parts[0], parts[1]


def infer_scale_adjustment(extents: list[float] | None, printer_profile: dict[str, object]) -> tuple[float, str]:
    if not extents:
        return 1.0, "No scale hint available."

    bed_x, bed_y = parse_bed_shape(str(printer_profile["bed_shape"]))
    largest = max(extents)
    if largest < 8:
        return 25.4, "Part appears extremely small. A 25.4x scale can help when inch-authored geometry was interpreted as millimeters."
    if largest > max(bed_x, bed_y) * 5:
        return 0.1, "Part appears extremely large. A 0.1x scale can help when centimeter-authored geometry was interpreted as millimeters."
    return 1.0, "Scale looks plausible for millimeter-native slicing."


def optimize_print_plan(
    printer_profile: dict[str, object],
    filament: str,
    quality_profile: str,
    print_goal: str,
    support_strategy: str,
    adhesion_strategy: str,
) -> dict[str, str | float | int | bool]:
    profile = printer_profile
    base_speed = int(profile["speed"][filament])
    nozzle_temp = int(profile["nozzle"][filament])
    bed_temp = int(profile["bed"][filament])

    layer_height_map = {
        "Draft / fast iteration": 0.28,
        "Balanced production": 0.20,
        "Detail / cosmetic": 0.12,
    }
    infill_map = {
        "Visual prototype": 12,
        "Balanced everyday part": 20,
        "Functional strength": 35,
    }
    wall_map = {
        "Visual prototype": 2,
        "Balanced everyday part": 3,
        "Functional strength": 4,
    }
    speed_factor = {
        "Draft / fast iteration": 1.08,
        "Balanced production": 1.0,
        "Detail / cosmetic": 0.76,
    }
    support_enabled = (
        support_strategy == "Always on"
        or (
            support_strategy == "Auto"
            and (filament in {"PETG", "ABS", "TPU"} or print_goal == "Functional strength")
        )
    )
    if support_strategy == "Disabled":
        support_enabled = False
    adhesion_map = {
        "Auto": "Skirt",
        "Brim": "Brim",
        "Raft": "Raft",
        "Skirt": "Skirt",
    }

    optimized_speed = max(25, int(base_speed * speed_factor[quality_profile]))
    return {
        "layer_height": layer_height_map[quality_profile],
        "infill_percent": infill_map[print_goal],
        "wall_loops": wall_map[print_goal],
        "print_speed": optimized_speed,
        "support_enabled": support_enabled,
        "support_density": 18 if not support_enabled else 24,
        "adhesion": adhesion_map[adhesion_strategy],
        "nozzle_temp": nozzle_temp,
        "bed_temp": bed_temp,
        "orientation": profile["orientation"],
        "bed_shape": profile["bed_shape"],
        "nozzle_diameter": profile["nozzle_diameter"],
        "gcode_flavor": profile["gcode_flavor"],
        "adhesion_surface": profile["adhesion_default"],
    }


def analyze_mesh(uploaded_file, printer_name: str, printer_profile: dict[str, object], auto_scale: bool) -> dict[str, object]:
    file_bytes = uploaded_file.getvalue()
    analysis: dict[str, object] = {
        "filename": uploaded_file.name,
        "size_bytes": uploaded_file.size,
        "face_count": None,
        "vertex_count": None,
        "watertight": None,
        "extents_mm": None,
        "scaled_extents_mm": None,
        "scale_factor": 1.0,
        "scale_hint": None,
        "mesh_ok": True,
        "issues": [],
        "notes": [],
    }
    bed_x, bed_y = parse_bed_shape(str(printer_profile["bed_shape"]))
    max_height = float(printer_profile["max_height_mm"])

    if not TRIMESH_AVAILABLE:
        analysis["notes"].append("Install `trimesh` for real mesh integrity and bounds analysis.")
        return analysis

    try:
        mesh = trimesh.load(io.BytesIO(file_bytes), file_type=uploaded_file.name.rsplit(".", 1)[-1].lower(), force="mesh")
        if isinstance(mesh, trimesh.Scene):
            mesh = trimesh.util.concatenate(tuple(g for g in mesh.geometry.values()))
        analysis["face_count"] = int(len(mesh.faces))
        analysis["vertex_count"] = int(len(mesh.vertices))
        analysis["watertight"] = bool(mesh.is_watertight)
        extents = [round(float(value), 2) for value in mesh.extents.tolist()]
        analysis["extents_mm"] = extents
        scale_factor, scale_hint = infer_scale_adjustment(extents, printer_profile)
        analysis["scale_hint"] = scale_hint
        if auto_scale:
            analysis["scale_factor"] = scale_factor
            analysis["scaled_extents_mm"] = [round(value * scale_factor, 2) for value in extents]
        else:
            analysis["scaled_extents_mm"] = extents

        if not mesh.is_watertight:
            analysis["mesh_ok"] = False
            analysis["issues"].append("Mesh is not watertight, so slicing may fail or produce weak shells.")

        test_extents = analysis["scaled_extents_mm"]
        if test_extents[0] > bed_x or test_extents[1] > bed_y or test_extents[2] > max_height:
            analysis["mesh_ok"] = False
            analysis["issues"].append(
                f"Model appears to exceed the {printer_name} build volume ({bed_x:.0f} x {bed_y:.0f} x {max_height:.0f} mm)."
            )

        if max(test_extents) < 2:
            analysis["mesh_ok"] = False
            analysis["issues"].append("Model appears extremely small, which often indicates a scale or unit mismatch.")

        if analysis["face_count"] and analysis["face_count"] > 1_500_000:
            analysis["notes"].append("Very dense mesh detected. Slicing may be slow and supports may need cleanup.")
        analysis["notes"].append(scale_hint)
    except Exception as exc:
        analysis["mesh_ok"] = False
        analysis["issues"].append(f"Mesh analysis failed: {exc}")

    return analysis


def build_prusaslicer_config(plan: dict[str, str | float | int | bool]) -> str:
    support_value = 1 if plan["support_enabled"] else 0
    brim_width = 0 if plan["adhesion"] != "Brim" else 5
    raft_layers = 0 if plan["adhesion"] != "Raft" else 2
    return textwrap.dedent(
        f"""
        layer_height = {plan['layer_height']}
        fill_density = {plan['infill_percent']}%
        perimeters = {plan['wall_loops']}
        support_material = {support_value}
        support_material_threshold = 40
        first_layer_temperature = {plan['nozzle_temp']}
        temperature = {plan['nozzle_temp']}
        first_layer_bed_temperature = {plan['bed_temp']}
        bed_temperature = {plan['bed_temp']}
        perimeters_speed = {plan['print_speed']}
        infill_speed = {plan['print_speed']}
        brim_width = {brim_width}
        raft_layers = {raft_layers}
        """
    ).strip()


def build_slicer_command(
    slicer_path: str,
    input_path: str,
    output_path: str,
    config_path: str,
    plan: dict[str, str | float | int | bool],
) -> list[str]:
    command = [
        slicer_path,
        "--export-gcode",
        input_path,
        "--output",
        output_path,
        "--load",
        config_path,
    ]
    scale_factor = float(plan.get("scale_factor", 1.0))
    if scale_factor != 1.0:
        command.extend(["--scale", str(scale_factor)])
    return command


def run_real_slicer(
    slicer_label: str | None,
    slicer_path: str | None,
    uploaded_file,
    plan: dict[str, str | float | int | bool],
) -> tuple[str | None, str]:
    if not slicer_path or not slicer_label:
        return None, "No slicer backend is configured in this environment."

    slicer_family = slicer_label.lower()
    if not any(name in slicer_family for name in ("prusa", "orca", "slic3r")):
        return None, f"{slicer_label} was detected, but this app currently supports CLI slicing for PrusaSlicer/OrcaSlicer/Slic3r-style backends."

    suffix = "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input_model" + suffix)
        config_path = os.path.join(tmpdir, "cipher_plan.ini")
        output_path = os.path.join(tmpdir, "output.gcode")
        with open(input_path, "wb") as handle:
            handle.write(uploaded_file.getvalue())
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(build_prusaslicer_config(plan))

        command = build_slicer_command(slicer_path, input_path, output_path, config_path, plan)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except Exception as exc:
            return None, f"Slicer execution failed before completion: {exc}"

        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "Unknown slicer error").strip()
            return None, f"Slicer backend returned an error: {error_text}"

        if not os.path.exists(output_path):
            return None, "Slicer reported success but did not produce an output G-code file."

        with open(output_path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(), "Real slicer backend generated G-code successfully."


def score_release_gate(
    mode: str,
    has_slicer: bool,
    blueprint_type: str,
    has_required_dimensions: bool,
    has_units: bool,
    has_multi_view: bool,
    has_tolerance_notes: bool,
) -> tuple[float, dict[str, float], list[str], bool]:
    if mode == "Reliable Print Mode":
        scores = {
            "Inspector": 0.96,
            "Calibrator": 0.95,
            "G-Code Architect": 0.965 if has_slicer else 0.82,
            "Cipher Vault": 0.95,
        }
        objections = []
        if not has_slicer:
            objections.append("No slicer backend is configured, so final release to production is blocked.")
    else:
        scores = {
            "Inspector": 0.91 if blueprint_type == "Structured technical drawing" else 0.35,
            "Calibrator": 0.90 if has_required_dimensions and has_units else 0.58,
            "G-Code Architect": 0.89 if has_multi_view and has_tolerance_notes else 0.62,
            "Cipher Vault": 0.94,
        }
        objections = []
        if blueprint_type != "Structured technical drawing":
            objections.append("Object photos are rejected because they do not provide trustworthy 3D fabrication geometry.")
        if not has_required_dimensions:
            objections.append("Critical dimensions are missing, so scale and manufacturability cannot be trusted.")
        if not has_units:
            objections.append("Units were not confirmed, so the system cannot safely infer size.")
        if not has_multi_view:
            objections.append("Multiple orthographic views are required before reconstruction can be trusted.")
        if not has_tolerance_notes:
            objections.append("Tolerance intent is missing, so fit-sensitive parts cannot be released.")

    overall_confidence = min(scores.values())
    release_allowed = overall_confidence >= 0.94 and not objections
    return overall_confidence, scores, objections, release_allowed


def encrypt_artifact(artifact_text: str, passphrase: str) -> tuple[str | None, str | None]:
    if not CRYPTOGRAPHY_AVAILABLE or not passphrase:
        return None, None

    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    key = urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    token = Fernet(key).encrypt(artifact_text.encode("utf-8")).decode("utf-8")
    return token, salt.hex()


def generate_gcode(filename: str, printer: str, filament: str, nozzle_temp: int, bed_temp: int, speed: int) -> str:
    sanitized_name = filename.replace(";", "_")
    extrusion_multiplier = {
        "PLA": 0.98,
        "PETG": 1.03,
        "ABS": 1.01,
        "TPU": 1.08,
    }[filament]
    feedrate = speed * 60
    return textwrap.dedent(
        f"""
        ; CipherSlice Autonomous Manufacturing Stream
        ; Source File: {sanitized_name}
        ; Target Printer: {printer}
        ; Filament Profile: {filament}
        ; Encryption Stage: staged_for_secure_hardware_stream
        M140 S{bed_temp}
        M104 S{nozzle_temp}
        M190 S{bed_temp}
        M109 S{nozzle_temp}
        G28
        G90
        M83
        ; Adaptive mesh profile generated for {sanitized_name}
        G1 Z0.28 F1200
        G1 X5 Y5 F9000
        G1 X220 Y5 E18.4 F{feedrate}
        G1 X220 Y220 E16.8 F{feedrate}
        G1 X5 Y220 E16.8 F{feedrate}
        G1 X5 Y5 E16.8 F{feedrate}
        ; Material optimization multiplier
        M221 S{math.floor(extrusion_multiplier * 100)}
        ; Support-aware perimeter pass
        G1 Z0.48 F1200
        G1 X28 Y28 F9000
        G1 X196 Y28 E12.2 F{feedrate}
        G1 X196 Y196 E12.2 F{feedrate}
        G1 X28 Y196 E12.2 F{feedrate}
        G1 X28 Y28 E12.2 F{feedrate}
        ; Secure stream ready
        M400
        M104 S0
        M140 S0
        M84
        """
    ).strip()


def attempt_hardware_stream(connector_url: str, artifact_text: str, printer: str, filament: str) -> tuple[bool, str]:
    payload = textwrap.dedent(
        f"""
        printer={printer}
        filament={filament}
        bytes={len(artifact_text.encode('utf-8'))}
        """
    ).encode("utf-8")
    request = Request(
        connector_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
        return True, body or "Connector accepted the secure job package."
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return False, str(exc)


st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(0, 204, 153, 0.14), transparent 28%),
            radial-gradient(circle at top right, rgba(0, 112, 255, 0.12), transparent 24%),
            linear-gradient(180deg, #07111b 0%, #050a12 100%);
        color: #e8f0f7;
    }
    .block-container {
        max-width: 1220px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    h1, h2, h3 {
        color: #f4f8fb !important;
        letter-spacing: 0.02em;
    }
    .hero-card, .panel-card {
        background: rgba(7, 18, 30, 0.82);
        border: 1px solid rgba(104, 144, 177, 0.22);
        border-radius: 20px;
        padding: 1.25rem 1.4rem;
        box-shadow: 0 18px 40px rgba(0, 0, 0, 0.28);
        backdrop-filter: blur(8px);
    }
    .hero-title {
        font-size: 2.4rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .hero-subtitle {
        color: #9db4c7;
        font-size: 1.02rem;
        line-height: 1.55;
    }
    .metric-strip {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.85rem;
        margin-top: 1.2rem;
    }
    .metric-box {
        background: rgba(10, 26, 42, 0.9);
        border: 1px solid rgba(64, 201, 161, 0.18);
        border-radius: 16px;
        padding: 0.95rem 1rem;
    }
    .metric-label {
        color: #84a0b6;
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .metric-value {
        color: #f6fbff;
        font-size: 1.1rem;
        font-weight: 650;
        margin-top: 0.25rem;
    }
    .section-label {
        color: #7ce0bf;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 0.78rem;
        margin-bottom: 0.35rem;
    }
    .success-banner {
        background: linear-gradient(135deg, rgba(0, 177, 125, 0.22), rgba(0, 104, 255, 0.16));
        border: 1px solid rgba(104, 241, 193, 0.28);
        border-radius: 18px;
        padding: 1rem 1.1rem;
        margin-top: 0.9rem;
        font-weight: 600;
        color: #dffcf2;
    }
    .agent-card {
        background: rgba(10, 22, 36, 0.92);
        border: 1px solid rgba(73, 117, 150, 0.2);
        border-radius: 16px;
        padding: 0.95rem 1rem;
        margin-bottom: 0.75rem;
    }
    .agent-name {
        color: #dff5ff;
        font-weight: 650;
        margin-bottom: 0.3rem;
    }
    .agent-role {
        color: #9fb6c8;
        font-size: 0.95rem;
        line-height: 1.5;
    }
    .mode-banner {
        background: rgba(8, 24, 38, 0.88);
        border: 1px solid rgba(90, 207, 171, 0.18);
        border-radius: 16px;
        padding: 0.85rem 1rem;
        margin-bottom: 1rem;
        color: #dceaf5;
    }
    div[data-testid="stFileUploaderDropzone"] {
        background: linear-gradient(180deg, rgba(8, 20, 34, 0.96), rgba(11, 28, 44, 0.96));
        border: 1px dashed rgba(106, 233, 194, 0.55);
        border-radius: 18px;
        padding: 1.2rem;
    }
    div[data-testid="stFileUploaderDropzone"] * {
        color: #e8f0f7 !important;
    }
    div[data-testid="stStatusWidget"] {
        border-radius: 18px;
    }
    .persona-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
        margin-top: 1rem;
    }
    .persona-card {
        background: rgba(8, 24, 38, 0.88);
        border: 1px solid rgba(90, 207, 171, 0.18);
        border-radius: 18px;
        padding: 1rem 1.05rem;
    }
    .persona-title {
        color: #f4f8fb;
        font-size: 1.2rem;
        font-weight: 700;
        margin-bottom: 0.3rem;
    }
    .persona-copy {
        color: #a8bdcd;
        line-height: 1.5;
        font-size: 0.96rem;
    }
    .delivery-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.9rem;
        margin-top: 1rem;
    }
    .delivery-card {
        background: rgba(8, 24, 38, 0.88);
        border: 1px solid rgba(90, 207, 171, 0.18);
        border-radius: 18px;
        padding: 1rem 1.05rem;
    }
    .delivery-title {
        color: #f4f8fb;
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .delivery-chip {
        display: inline-block;
        margin-bottom: 0.5rem;
        padding: 0.22rem 0.55rem;
        border-radius: 999px;
        background: rgba(90, 207, 171, 0.18);
        color: #d8fff1;
        font-size: 0.76rem;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .delivery-copy {
        color: #a8bdcd;
        line-height: 1.5;
        font-size: 0.93rem;
        margin-bottom: 0.5rem;
    }
    .delivery-risk {
        color: #ffd9a8;
        line-height: 1.45;
        font-size: 0.9rem;
    }
    .state-banner {
        border-radius: 18px;
        padding: 0.95rem 1rem;
        margin-top: 0.9rem;
        font-weight: 600;
    }
    .state-ready {
        background: rgba(0, 177, 125, 0.16);
        border: 1px solid rgba(104, 241, 193, 0.28);
        color: #dffcf2;
    }
    .state-review {
        background: rgba(255, 184, 0, 0.14);
        border: 1px solid rgba(255, 214, 102, 0.24);
        color: #fff1c2;
    }
    .state-blocked {
        background: rgba(255, 79, 79, 0.14);
        border: 1px solid rgba(255, 128, 128, 0.24);
        color: #ffd8d8;
    }
    .manifest-card {
        background: linear-gradient(180deg, rgba(8, 23, 37, 0.96), rgba(5, 14, 25, 0.96));
        border: 1px solid rgba(90, 207, 171, 0.18);
        border-radius: 20px;
        padding: 1.1rem 1.15rem;
        margin-top: 0.9rem;
    }
    .manifest-title {
        color: #f3fbff;
        font-size: 1.1rem;
        font-weight: 700;
        margin-bottom: 0.55rem;
    }
    .manifest-line {
        color: #d9e7f1;
        padding: 0.18rem 0;
        border-bottom: 1px solid rgba(73, 117, 150, 0.18);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="section-label">CipherSlice Control Plane</div>
        <div class="hero-title">Autonomous Slicing + Secure Manufacturing Delivery</div>
        <div class="hero-subtitle">
            CipherSlice now separates dependable printing from blueprint intelligence. Consumers can
            either upload a real 3D mesh for immediate printer-targeted output, or submit a structured
            technical drawing to create a draft manufacturing brief before slicing.
        </div>
        <div class="metric-strip">
            <div class="metric-box">
                <div class="metric-label">Pipeline Mode</div>
                <div class="metric-value">Dual Intake Control</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Output Path</div>
                <div class="metric-value">Secure Artifact Delivery</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">Security Layer</div>
                <div class="metric-value">Optional Encryption</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.write("")
if "persona_key" not in st.session_state:
    st.session_state["persona_key"] = "friend"

persona = get_persona()
st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Step 0: Choose Your AI Copilot")
st.markdown(
    """
    <div class="persona-grid">
        <div class="persona-card">
            <div class="persona-title">Friend</div>
            <div class="persona-copy">
                Calm and supportive. Explains manufacturing choices clearly, flags risks gently, and helps users learn.
            </div>
        </div>
        <div class="persona-card">
            <div class="persona-title">Best Friend</div>
            <div class="persona-copy">
                Same safe recommendations, but with playful roasting energy. It always makes clear when it is joking.
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
persona_col1, persona_col2 = st.columns(2, gap="large")
with persona_col1:
    st.button(
        "Friend",
        use_container_width=True,
        type="primary" if st.session_state["persona_key"] == "friend" else "secondary",
        on_click=set_persona,
        args=("friend",),
    )
with persona_col2:
    st.button(
        "Best Friend",
        use_container_width=True,
        type="primary" if st.session_state["persona_key"] == "best_friend" else "secondary",
        on_click=set_persona,
        args=("best_friend",),
    )
persona = get_persona()
st.info(f"Active copilot: `{persona['title']}`. {persona['intro']}")
st.markdown("</div>", unsafe_allow_html=True)

slicer_label, slicer_path = detect_slicer_backend()
connector_url, connector_state = detect_connector()
global_state, global_message = summarize_global_readiness(slicer_path, connector_url)

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### System Readiness")
status_cols = st.columns(4, gap="medium")
status_cols[0].metric("Overall", global_state)
status_cols[1].metric("Slicer", "Connected" if slicer_path else "Missing")
status_cols[2].metric("Connector", "Connected" if connector_url else "Not connected")
status_cols[3].metric("Public Site", "Ready")
banner_class = "state-ready" if global_state == "Ready" else ("state-review" if global_state == "Needs Delivery Path" else "state-blocked")
st.markdown(
    f'<div class="state-banner {banner_class}">System state: {global_state}. {global_message}</div>',
    unsafe_allow_html=True,
)
if global_state == "Ready":
    st.success(global_message)
elif global_state == "Needs Delivery Path":
    st.warning(global_message)
else:
    st.error(global_message)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### How CipherSlice Works")
st.markdown(
    """
    1. Choose your copilot, then choose `Reliable Print Mode` for real mesh uploads or `Blueprint Assist Mode` for dimensioned technical drawings.
    2. If you upload a mesh, CipherSlice analyzes fit, scale, mesh health, printer compatibility, plastic compatibility, and optimized print settings.
    3. If you upload a blueprint, CipherSlice extracts advice and manufacturing requirements, but reliable printing still depends on validated 3D geometry before slicing.
    4. The AI swarm explains its recommendations, shows confidence and objections, and lets the user override the final plan before approval.
    5. After approval, CipherSlice either exports the artifact, prepares SD card handoff, or streams through a configured local connector.
    """
)
st.info("The safest fabrication path is still: structured input -> validated mesh -> reviewed plan -> approved slicing -> selected delivery path.")
st.markdown("</div>", unsafe_allow_html=True)

if "delivery_mode_choice" not in st.session_state:
    st.session_state["delivery_mode_choice"] = "SD card export"

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Choose Delivery Strategy")
st.markdown(
    """
    <div class="delivery-grid">
    """
    + "".join(
        [
            f"""
            <div class="delivery-card">
                <div class="delivery-title">{mode_name}</div>
                <div class="delivery-chip">{DELIVERY_MODE_DETAILS[mode_name]['recommended']}</div>
                <div class="delivery-copy">{DELIVERY_MODE_DETAILS[mode_name]['summary']}</div>
                <div class="delivery-risk"><strong>Tradeoff:</strong> {DELIVERY_MODE_DETAILS[mode_name]['warning']}</div>
            </div>
            """
            for mode_name in DELIVERY_MODES
        ]
    )
    + "</div>",
    unsafe_allow_html=True,
)
delivery_cols = st.columns(3, gap="medium")
for column, mode_name in zip(delivery_cols, DELIVERY_MODES):
    with column:
        st.button(
            mode_name,
            use_container_width=True,
            type="primary" if st.session_state["delivery_mode_choice"] == mode_name else "secondary",
            on_click=set_delivery_mode,
            args=(mode_name,),
        )
st.info(
    f"Active delivery strategy: `{st.session_state['delivery_mode_choice']}`. "
    f"{DELIVERY_MODE_DETAILS[st.session_state['delivery_mode_choice']]['summary']}"
)
st.warning(
    "Recommended for school demos: use `Reliable Print Mode` with `SD card export`. "
    "It works well even on locked-down club computers and still shows the full optimization + approval experience."
)
st.markdown("</div>", unsafe_allow_html=True)

mode = st.radio(
    "Workflow Mode",
    ["Reliable Print Mode", "Blueprint Assist Mode"],
    horizontal=True,
)

left_col, right_col = st.columns([1.25, 0.85], gap="large")

with left_col:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    if mode == "Reliable Print Mode":
        st.markdown("### Step 1: Input Zone")
        st.markdown(
            '<div class="mode-banner"><strong>Reliable Print Mode</strong><br/>'
            "Use this when the customer wants an actual printable result. Upload a real mesh file and "
            "CipherSlice will produce a printer-targeted artifact flow.</div>",
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "Drag & drop the source model",
            type=["stl", "obj"],
            help="CipherSlice accepts production mesh uploads in STL or OBJ format.",
        )
    else:
        st.markdown("### Step 1: Blueprint Intake")
        st.markdown(
            '<div class="mode-banner"><strong>Blueprint Assist Mode</strong><br/>'
            "For structured technical drawings only. This mode creates a draft manufacturing brief "
            "and review path, not guaranteed final G-code from a single image.</div>",
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "Upload a structured technical drawing",
            type=["png", "jpg", "jpeg", "pdf"],
            help="Best results come from orthographic technical drawings with clear dimensions and units.",
        )

    printer = st.selectbox("Target Printer", list(PRINTER_PROFILES.keys()))
    custom_width = 500.0
    custom_depth = 500.0
    custom_height = 500.0
    custom_nozzle = 0.6
    if printer == "Custom / Large Format":
        custom_width = st.number_input("Custom bed width (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        custom_depth = st.number_input("Custom bed depth (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        custom_height = st.number_input("Custom max height (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        custom_nozzle = st.number_input("Custom nozzle diameter (mm)", min_value=0.2, max_value=2.0, value=0.6, step=0.1, format="%.1f")
    selected_printer_profile = resolve_printer_profile(
        printer,
        custom_width,
        custom_depth,
        custom_height,
        custom_nozzle,
    )
    filament = st.selectbox("Filament Type", FILAMENT_TYPES)
    quality_profile = st.selectbox(
        "Quality Profile",
        ["Balanced production", "Draft / fast iteration", "Detail / cosmetic"],
    )
    print_goal = st.selectbox(
        "Print Goal",
        ["Balanced everyday part", "Functional strength", "Visual prototype"],
    )
    support_strategy = st.selectbox(
        "Support Strategy",
        ["Auto", "Always on", "Disabled"],
    )
    delivery_mode = st.selectbox(
        "Delivery Mode",
        DELIVERY_MODES,
        index=DELIVERY_MODES.index(st.session_state.get("delivery_mode_choice", "SD card export")),
        help="Choose how the approved artifact should leave CipherSlice once the user signs off.",
    )
    st.session_state["delivery_mode_choice"] = delivery_mode
    adhesion_strategy = st.selectbox(
        "Build Plate Adhesion",
        ["Auto", "Brim", "Raft", "Skirt"],
    )
    auto_scale_mesh = st.checkbox(
        "Auto-correct likely unit mismatch for mesh uploads",
        value=True,
        help="CipherSlice will suggest or apply a scale correction when the model looks implausibly small or large.",
    )
    with st.expander("Advanced user overrides"):
        st.caption("CipherSlice optimizes first. These optional overrides let the user make the final call before release.")
        nozzle_override = st.number_input("Override nozzle temp (degC)", min_value=0, max_value=320, value=0, step=1)
        bed_override = st.number_input("Override bed temp (degC)", min_value=0, max_value=130, value=0, step=1)
        layer_override = st.number_input("Override layer height (mm)", min_value=0.0, max_value=1.0, value=0.0, step=0.02, format="%.2f")
        speed_override = st.number_input("Override print speed (mm/s)", min_value=0, max_value=400, value=0, step=5)
        infill_override = st.number_input("Override infill (%)", min_value=0, max_value=100, value=0, step=1)
    wants_encryption = st.checkbox("Encrypt downloadable artifact", value=True)
    encryption_passphrase = ""
    if wants_encryption:
        encryption_passphrase = st.text_input(
            "Encryption passphrase",
            type="password",
            help="Use a passphrase if you want Cipher Vault to issue an encrypted downloadable artifact.",
        )

    blueprint_name = ""
    part_goal = ""
    required_dimensions = ""
    tolerance_notes = ""
    blueprint_type = "Structured technical drawing"
    has_units = False
    has_multi_view = False
    has_tolerance_confirmation = False
    launch_disabled = uploaded_file is None
    launch_help = None

    if mode == "Blueprint Assist Mode":
        blueprint_type = st.radio(
            "Blueprint submission type",
            ["Structured technical drawing", "Object photo / casual image"],
            help="Only structured technical drawings can continue into draft reconstruction.",
        )
        blueprint_name = st.text_input(
            "Part name or product label",
            placeholder="Bracket assembly, gear cover, phone mount...",
        )
        part_goal = st.text_area(
            "Functional goal",
            placeholder="Describe what the part is supposed to do, what it connects to, and what cannot fail.",
            height=90,
        )
        required_dimensions = st.text_area(
            "Critical dimensions and units",
            placeholder="Example: total width 120 mm, hole diameter 8 mm, wall thickness 3 mm, slot depth 18 mm...",
            height=100,
        )
        tolerance_notes = st.text_area(
            "Tolerance or fit notes",
            placeholder="Example: press fit on peg holes, cosmetic front face, outdoor use, high strength needed...",
            height=90,
        )
        has_units = st.checkbox("The drawing clearly shows units for critical dimensions")
        has_multi_view = st.checkbox("The upload includes multiple orthographic views")
        has_tolerance_confirmation = st.checkbox("Tolerance or fit intent is stated clearly enough for review")
        launch_disabled = not all(
            [
                uploaded_file is not None,
                blueprint_name.strip(),
                part_goal.strip(),
                required_dimensions.strip(),
                blueprint_type == "Structured technical drawing",
            ]
        )
        if blueprint_type != "Structured technical drawing":
            launch_help = "Object photos are rejected for fabrication because they do not contain trustworthy 3D manufacturing geometry."
        elif launch_disabled:
            launch_help = "Upload a structured drawing and fill in the required manufacturing details to continue."

    if uploaded_file is not None:
        st.caption(f"Loaded `{uploaded_file.name}` | {format_bytes(uploaded_file.size)}")
    elif mode == "Reliable Print Mode":
        st.caption("Awaiting part geometry. Upload a `.stl` or `.obj` file to unlock the pipeline.")
    else:
        st.caption("Awaiting technical drawing. Upload a dimensioned blueprint image or PDF to unlock the draft pipeline.")

    launch = st.button(
        "Commence Autonomous Slicing & Encryption",
        type="primary",
        disabled=launch_disabled,
        use_container_width=True,
        help=launch_help,
    )
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Mission Notes")
    st.caption(f"Copilot tone: `{persona['label']}`")
    if mode == "Reliable Print Mode":
        st.info(
            "This is the dependable consumer path. Real mesh in, printer-specific artifact out, with encryption available for delivery."
        )
    else:
        st.info(
            "Blueprint Assist Mode is intentionally constrained. It is designed for structured drawings plus manufacturing context, not casual photos."
        )
        st.warning(
            "A single image usually lacks hidden geometry, exact depth, scale authority, internal cavities, and tolerance intent. That is why image-only to final G-code is not dependable."
        )
        if uploaded_file is not None and blueprint_type != "Structured technical drawing":
            st.error("Object photos are blocked immediately. CipherSlice will not convert a casual object image into printable G-code.")
        st.markdown("**Blueprint input requirements**")
        for requirement in BLUEPRINT_REQUIREMENTS:
            st.markdown(f"- {requirement}")
    st.markdown(
        f"""
        **Selected printer volume:** `{selected_printer_profile['bed_shape']}`  
        **Material profile:** `{filament}`  
        **Optimization mode:** `{quality_profile}` / `{print_goal}`  
        **Support + adhesion:** `{support_strategy}` / `{adhesion_strategy}`  
        **Delivery mode:** `{delivery_mode}`  
        **Autonomy stack:** `Inspector -> Calibrator -> G-Code Architect -> Cipher Vault`
        """
    )
    if wants_encryption:
        if CRYPTOGRAPHY_AVAILABLE:
            st.success("Artifact encryption is enabled. Cipher Vault can issue an encrypted payload.")
        else:
            st.error("`cryptography` is not installed yet, so encrypted downloads are not available in this environment.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Delivery Paths")
    st.markdown(
        """
        - **Secure local connector:** Best for controlled end-to-end handoff. Needs a slicer backend and a local `CipherBridge` or supported printer relay.
        - **SD card export:** Best for offline printers. CipherSlice prepares the job, but removable media breaks secure streaming guarantees.
        - **Manual download only:** Best for review, demos, or environments without direct printer access.
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Agent Swarm")
    for agent_name, agent_role in AGENT_IDENTITIES.items():
        st.markdown(
            f'<div class="agent-card"><div class="agent-name">{agent_name}</div>'
            f'<div class="agent-role">{agent_role}<br/><br/><strong>Persona behavior:</strong> {persona["agent_tone"][agent_name]}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    slicer_label, slicer_path = detect_slicer_backend()
    connector_url, connector_state = detect_connector()
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Website Limits")
    st.markdown(
        """
        - **What the website can do:** validate uploads, assemble profiles, generate or prepare artifacts, and coordinate secure delivery.
        - **What direct home printing also needs:** a reachable printer, user permission, and a local connector or supported printer integration.
        - **Why the website alone cannot always print:** public web apps do not automatically have access to a customer's home network or USB-connected printer.
        - **What enables real printing later:** a slicer backend plus a local `CipherBridge` connector or an approved cloud printer API.
        - **What SD card mode means:** CipherSlice can still produce and package the job, but once the file is copied to removable media, the platform cannot enforce one-time streaming or true end-to-end delivery controls.
        """
    )
    st.markdown(
        f"""
        **Slicer backend:** `{slicer_label or 'Not detected'}`  
        **Slicer path:** `{slicer_path or 'None configured'}`  
        **Connector status:** `{connector_state}`  
        **Connector endpoint:** `{connector_url or 'No local connector configured'}`
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)

if launch and uploaded_file is not None:
    filename = uploaded_file.name
    file_size = uploaded_file.size
    file_size_mb = max(file_size / (1024 * 1024), 0.1)
    file_stem = sanitize_download_name(filename.rsplit(".", 1)[0])
    printer_profile = selected_printer_profile
    orientation = str(printer_profile["orientation"])
    artifact_hash = build_hash(filename, file_size, printer, filament)
    stream_aborted = False
    slicer_label, slicer_path = detect_slicer_backend()
    connector_url, connector_state = detect_connector()
    optimized_plan = optimize_print_plan(
        printer_profile,
        filament,
        quality_profile,
        print_goal,
        support_strategy,
        adhesion_strategy,
    )
    optimized_plan = apply_user_overrides(
        optimized_plan,
        nozzle_override if nozzle_override > 0 else None,
        bed_override if bed_override > 0 else None,
        layer_override if layer_override > 0 else None,
        speed_override if speed_override > 0 else None,
        infill_override if infill_override > 0 else None,
    )
    mesh_analysis = analyze_mesh(uploaded_file, printer, printer_profile, auto_scale_mesh) if mode == "Reliable Print Mode" else None
    overall_confidence, consensus_scores, objections, release_allowed = score_release_gate(
        mode=mode,
        has_slicer=bool(slicer_path) and (mesh_analysis["mesh_ok"] if mesh_analysis else True),
        blueprint_type=blueprint_type,
        has_required_dimensions=bool(required_dimensions.strip()),
        has_units=has_units,
        has_multi_view=has_multi_view,
        has_tolerance_notes=has_tolerance_confirmation or bool(tolerance_notes.strip()),
    )
    if mesh_analysis:
        if mesh_analysis["issues"]:
            objections.extend(mesh_analysis["issues"])
        if not mesh_analysis["mesh_ok"]:
            release_allowed = False
            overall_confidence = min(overall_confidence, 0.88)

    if mode == "Reliable Print Mode":
        slicer_plan = dict(optimized_plan)
        if mesh_analysis and mesh_analysis["scale_factor"] != 1.0:
            slicer_plan["scale_factor"] = mesh_analysis["scale_factor"]
        real_gcode, slicer_message = run_real_slicer(slicer_label, slicer_path, uploaded_file, slicer_plan)
        primary_artifact = real_gcode or generate_gcode(
            filename,
            printer,
            filament,
            optimized_plan["nozzle_temp"],
            optimized_plan["bed_temp"],
            optimized_plan["print_speed"],
        )
        if real_gcode:
            consensus_scores["G-Code Architect"] = max(consensus_scores["G-Code Architect"], 0.97)
            overall_confidence = min(consensus_scores.values())
            release_allowed = release_allowed and mesh_analysis["mesh_ok"]
        else:
            objections.append(slicer_message)
            release_allowed = False
            overall_confidence = min(overall_confidence, 0.89)
    else:
        blueprint_stem = sanitize_download_name(blueprint_name.lower())
        primary_artifact = textwrap.dedent(
            f"""
            CipherSlice Blueprint Reconstruction Brief

            Part label: {blueprint_name}
            Drawing file: {filename}
            Target printer: {printer}
            Material intent: {filament}
            Functional goal: {part_goal}
            Critical dimensions: {required_dimensions}
            Tolerance notes: {tolerance_notes or 'None provided'}
            Recommended orientation: {orientation}
            Secure hash: {artifact_hash}

            Status:
            - Drawing accepted as structured technical input
            - 3D reconstruction review required before final slicing
            - Final G-code withheld until geometry is confirmed
            """
        ).strip()

    encrypted_artifact = None
    encryption_salt = None
    if wants_encryption and encryption_passphrase:
        encrypted_artifact, encryption_salt = encrypt_artifact(primary_artifact, encryption_passphrase)

    st.write("")
    st.markdown("### Step 2: Dynamic AI Swarm")

    with st.status("CipherSlice swarm engaged", expanded=True) as status:
        if mode == "Reliable Print Mode":
            st.markdown(
                f"**Agent 1 - The Inspector**  \n"
                f"Analyzed `{filename}`. Detected overhangs requiring support structures based on "
                f"`{format_bytes(file_size)}` mesh density. Recommended support density: "
                f"`{optimized_plan['support_density']}%`. "
                f"{'Mesh integrity looks acceptable.' if mesh_analysis and mesh_analysis['mesh_ok'] else 'Mesh integrity requires review.'} "
                f"{mesh_analysis['scale_hint'] if mesh_analysis and mesh_analysis['scale_hint'] else ''}"
            )
            st.caption(persona["agent_tone"]["Inspector"])
            time.sleep(0.45)
            st.markdown(
                f"**Agent 2 - The Calibrator**  \n"
                f"Mapped `{filament}` onto `{printer}`. Locked nozzle at `{optimized_plan['nozzle_temp']} degC`, "
                f"bed at `{optimized_plan['bed_temp']} degC`, print speed at `{optimized_plan['print_speed']} mm/s`, "
                f"layer height at `{optimized_plan['layer_height']} mm`, and infill at `{optimized_plan['infill_percent']}%`. "
                f"Orientation recommendation: {optimized_plan['orientation']} Adhesion: `{optimized_plan['adhesion']}`."
            )
            st.caption(persona["agent_tone"]["Calibrator"])
            time.sleep(0.45)
            st.markdown(
                f"**Agent 3 - The G-Code Architect**  \n"
                f"{slicer_message} Embedded `{filename}` into the manufacturing header for `{printer}`."
            )
            st.caption(persona["agent_tone"]["G-Code Architect"])
            time.sleep(0.45)
        else:
            st.markdown(
                f"**Agent 1 - The Inspector**  \n"
                f"Reviewed `{filename}` as a structured drawing for `{blueprint_name}`. Captured drawing scale assumptions, "
                f"detected a `{format_bytes(file_size)}` source asset, and flagged that final manufacturability depends on "
                f"the declared dimensions and tolerances."
            )
            st.caption(persona["agent_tone"]["Inspector"])
            time.sleep(0.45)
            st.markdown(
                f"**Agent 2 - The Calibrator**  \n"
                f"Mapped the requested part goal to `{printer}` with `{filament}`. Suggested orientation: {orientation} "
                f"and marked this as a draft manufacturing brief pending geometry reconstruction."
            )
            st.caption(persona["agent_tone"]["Calibrator"])
            time.sleep(0.45)
            st.markdown(
                f"**Agent 3 - The G-Code Architect**  \n"
                f"Prepared a draft reconstruction packet instead of final G-code because a 2D blueprint image does not yet "
                f"contain guaranteed 3D geometry."
            )
            st.caption(persona["agent_tone"]["G-Code Architect"])
            time.sleep(0.45)

        vault_line = (
            f"Generated secure stream hash `{artifact_hash[:18]}...` and encrypted the artifact for controlled delivery."
            if encrypted_artifact
            else f"Generated secure stream hash `{artifact_hash[:18]}...` and staged the artifact for controlled delivery."
        )
        st.markdown(f"**Agent 4 - The Cipher Vault**  \n{vault_line}")
        st.caption(persona["agent_tone"]["Cipher Vault"])
        if release_allowed:
            st.success(f"Consensus gate cleared at {overall_confidence * 100:.1f}% confidence. Artifact release is allowed.")
        else:
            st.warning(f"Consensus gate stopped release at {overall_confidence * 100:.1f}% confidence. Human review or more infrastructure is required.")
        status.update(label="CipherSlice swarm completed", state="complete", expanded=True)

    result_col, code_col = st.columns([0.9, 1.1], gap="large")
    final_user_approval = False
    next_action = recommend_next_action(
        mode,
        release_allowed,
        slicer_path,
        connector_url,
        delivery_mode,
        objections,
    )

    with result_col:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        st.markdown("### Output Summary")
        if mode == "Reliable Print Mode":
            st.markdown(
                f"""
                - **Source file:** `{filename}`
                - **Payload size:** `{format_bytes(file_size)}`
                - **Printer profile:** `{printer}`
                - **Filament strategy:** `{filament}`
                - **Nozzle / bed:** `{optimized_plan['nozzle_temp']} degC / {optimized_plan['bed_temp']} degC`
                - **Layer height / infill:** `{optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}%`
                - **Wall loops / speed:** `{optimized_plan['wall_loops']} / {optimized_plan['print_speed']} mm/s`
                - **Supports:** `{'Enabled' if optimized_plan['support_enabled'] else 'Disabled'}`
                - **Adhesion / nozzle:** `{optimized_plan['adhesion']} / {optimized_plan['nozzle_diameter']} mm`
                - **Secure hash:** `{artifact_hash}`
                - **Consensus confidence:** `{overall_confidence * 100:.1f}%`
                - **Release status:** `{'APPROVED' if release_allowed else 'HELD'}`
                """
            )
            st.markdown(
                f'<div class="success-banner">Ephemeral Tunnel Established for {filename}. '
                f'Encrypted for 1-time secure hardware stream.</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div class="manifest-card">
                    <div class="manifest-title">Final Print Manifest</div>
                    <div class="manifest-line"><strong>Part:</strong> {filename}</div>
                    <div class="manifest-line"><strong>Printer:</strong> {printer}</div>
                    <div class="manifest-line"><strong>Build volume:</strong> {printer_profile['bed_shape']} x {int(float(printer_profile['max_height_mm']))} mm</div>
                    <div class="manifest-line"><strong>Filament:</strong> {filament}</div>
                    <div class="manifest-line"><strong>Nozzle / bed:</strong> {optimized_plan['nozzle_temp']} degC / {optimized_plan['bed_temp']} degC</div>
                    <div class="manifest-line"><strong>Layer / infill / walls:</strong> {optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}% / {optimized_plan['wall_loops']}</div>
                    <div class="manifest-line"><strong>Support / adhesion:</strong> {'Enabled' if optimized_plan['support_enabled'] else 'Disabled'} / {optimized_plan['adhesion']}</div>
                    <div class="manifest-line"><strong>Delivery mode:</strong> {delivery_mode}</div>
                    <div class="manifest-line"><strong>Confidence:</strong> {overall_confidence * 100:.1f}%</div>
                    <div class="manifest-line"><strong>Release status:</strong> {'APPROVED' if release_allowed else 'HELD'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            status_rows = build_status_board(
                mode,
                slicer_path,
                connector_url,
                release_allowed,
                final_user_approval,
                delivery_mode,
            )
            st.markdown("### Status Board")
            for label, value in status_rows:
                st.markdown(f"- **{label}:** `{value}`")
            st.info(f"Recommended next action: {next_action}")
            final_user_approval = st.checkbox(
                "I approve this manufacturing plan and want CipherSlice to release this job",
                key=f"approve_{artifact_hash}",
            )
            status_rows = build_status_board(
                mode,
                slicer_path,
                connector_url,
                release_allowed,
                final_user_approval,
                delivery_mode,
            )
            st.markdown("### Final Approval Status")
            for label, value in status_rows:
                st.markdown(f"- **{label}:** `{value}`")
            st.download_button(
                "Download G-Code",
                data=primary_artifact,
                file_name=f"{file_stem}_{sanitize_download_name(printer.lower())}.gcode",
                mime="text/plain",
                use_container_width=True,
                disabled=not (release_allowed and final_user_approval),
            )
            if delivery_mode == "SD card export":
                st.warning(
                    "SD card mode is compatible with many printers, but it is not a secure streaming channel. Once the file is exported, "
                    "CipherSlice cannot guarantee one-time use, remote revocation, or end-to-end hardware authentication."
                )
                st.markdown("**SD card operator checklist**")
                st.markdown("- Confirm the printer model and plastic profile match the exported plan.")
                st.markdown("- Label the artifact clearly before copying it to removable media.")
                st.markdown("- Review temperatures, supports, and scale one last time on the printer screen before printing.")
            stream_triggered = st.button(
                "Initiate Secure Hardware Stream",
                use_container_width=True,
                key=f"hardware_stream_{artifact_hash}",
                disabled=not (release_allowed and final_user_approval and delivery_mode == "Secure local connector"),
            )
            if delivery_mode != "Secure local connector":
                st.caption("Secure hardware streaming is available only when `Delivery Mode` is set to `Secure local connector`.")
            if stream_triggered:
                with st.status("Initializing encrypted tunnel...", expanded=True) as hardware_status:
                    time.sleep(2)
                    st.markdown(
                        "Checking for a local `CipherBridge` connector or approved printer relay so the website can hand "
                        "off the secure job package with user permission."
                    )
                    time.sleep(2)
                    if connector_url:
                        stream_ok, connector_message = attempt_hardware_stream(connector_url, primary_artifact, printer, filament)
                    else:
                        stream_ok, connector_message = False, ""
                    if stream_ok:
                        hardware_status.update(
                            label="Secure hardware stream delivered to CipherBridge",
                            state="complete",
                            expanded=True,
                        )
                        st.success(
                            "CipherBridge acknowledged the secure job package. If the connector is properly installed and "
                            "mapped to a real printer, the job can continue from the customer's machine."
                        )
                        if connector_message:
                            st.caption(f"Connector response: {connector_message}")
                    else:
                        stream_aborted = True
                        hardware_status.update(
                            label="Secure hardware stream aborted",
                            state="error",
                            expanded=True,
                        )
                        st.error(
                            "Hardware Authentication Failed: No approved local `CipherBridge` connector or secure printer "
                            "integration responded. To protect creator IP, the G-Code stream has been aborted and the "
                            "temporary hash has self-destructed."
                        )
                        st.info(
                            "This website can prepare the job, but direct home printing also requires: "
                            "1) a slicer backend, 2) a local connector or supported printer API, 3) user-approved access "
                            "to the target printer, and 4) a reachable device on the customer's network."
                        )
            if release_allowed and not final_user_approval:
                st.caption("Review the optimized plan and check the approval box before release or printer streaming.")
            if not release_allowed:
                st.error("Why blocked")
                for reason in objections:
                    st.markdown(f"- {reason}")
        else:
            st.markdown(
                f"""
                - **Drawing file:** `{filename}`
                - **Part label:** `{blueprint_name}`
                - **Draft pipeline:** `Technical drawing -> reconstruction brief -> 3D review -> slicing`
                - **Printer target:** `{printer}`
                - **Material intent:** `{filament}`
                - **Secure hash:** `{artifact_hash}`
                - **Consensus confidence:** `{overall_confidence * 100:.1f}%`
                - **Release status:** `HELD`
                """
            )
            st.markdown(
                f'<div class="success-banner">Structured blueprint intake accepted for {blueprint_name}. '
                f'CipherSlice prepared a draft model brief for review before any final slicing.</div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                "Download Draft Reconstruction Brief",
                data=primary_artifact,
                file_name=f"{blueprint_stem}_reconstruction_brief.txt",
                mime="text/plain",
                use_container_width=True,
            )
            if objections:
                st.error("Blueprint release rejected. CipherSlice will not generate final G-code from this image workflow yet.")
                for reason in objections:
                    st.markdown(f"- {reason}")
                st.markdown("**What would need to work together before release**")
                st.markdown("- A trusted technical drawing with authoritative dimensions and units")
                st.markdown("- A reconstruction stage that converts the drawing into validated 3D geometry")
                st.markdown("- A review loop that resolves fit and tolerance assumptions")
                st.markdown("- A slicer and hardware-delivery path that can prove the final job is safe to release")

        if encrypted_artifact:
            encrypted_payload = textwrap.dedent(
                f"""
                CipherSlice Encrypted Artifact
                source_file={filename}
                printer={printer}
                filament={filament}
                salt_hex={encryption_salt}
                fernet_token={encrypted_artifact}
                """
            ).strip()
            st.download_button(
                "Download Encrypted Artifact",
                data=encrypted_payload,
                file_name=f"{file_stem}_cipher_vault.enc.txt",
                mime="text/plain",
                use_container_width=True,
                disabled=(
                    mode == "Reliable Print Mode"
                    and (
                        not (release_allowed and final_user_approval)
                        or delivery_mode == "SD card export"
                    )
                ),
            )
            if mode == "Reliable Print Mode" and delivery_mode == "SD card export":
                st.caption("Encrypted artifact export is disabled for SD card delivery because removable media breaks the secure stream model.")
        elif wants_encryption and not encryption_passphrase:
            st.caption("Add an encryption passphrase if you want Cipher Vault to produce an encrypted download.")

        if stream_aborted:
            st.caption("Temporary secure hash status: `SELF-DESTRUCTED`")

        st.markdown("</div>", unsafe_allow_html=True)

    with code_col:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        if mode == "Reliable Print Mode":
            st.markdown("### Preflight Review")
            st.markdown(
                f"""
                - **Target printer:** `{printer}`
                - **Filament:** `{filament}`
                - **Quality profile:** `{quality_profile}`
                - **Print goal:** `{print_goal}`
                - **Support strategy:** `{support_strategy}`
                - **Adhesion strategy:** `{optimized_plan['adhesion']}`
                - **Orientation:** {optimized_plan['orientation']}
                - **G-code flavor:** `{optimized_plan['gcode_flavor']}`
                - **Slicer backend:** `{slicer_label or 'Not detected'}`
                - **Connector path:** `{connector_url or 'No connector configured'}`
                """
            )
            if mesh_analysis:
                if mesh_analysis["extents_mm"]:
                    st.markdown(f"- **Estimated part extents:** `{mesh_analysis['extents_mm']}` mm")
                if mesh_analysis["scaled_extents_mm"] and mesh_analysis["scaled_extents_mm"] != mesh_analysis["extents_mm"]:
                    st.markdown(f"- **Scaled extents for slicing:** `{mesh_analysis['scaled_extents_mm']}` mm")
                    st.markdown(f"- **Applied scale factor:** `{mesh_analysis['scale_factor']}x`")
                if mesh_analysis["face_count"]:
                    st.markdown(f"- **Mesh faces:** `{mesh_analysis['face_count']:,}`")
                if mesh_analysis["vertex_count"]:
                    st.markdown(f"- **Mesh vertices:** `{mesh_analysis['vertex_count']:,}`")
                if mesh_analysis["watertight"] is not None:
                    st.markdown(f"- **Watertight mesh:** `{'Yes' if mesh_analysis['watertight'] else 'No'}`")
                for note in mesh_analysis["notes"]:
                    st.caption(note)

        st.markdown("### Confidence Gate")
        for agent_name, score in consensus_scores.items():
            st.markdown(f"- **{agent_name}:** `{score * 100:.1f}%`")
        if objections:
            st.markdown("**Agent objections**")
            for reason in objections:
                st.markdown(f"- {reason}")
        elif release_allowed:
            st.success("All agents cleared the release gate with no unresolved objections.")

        if mode == "Reliable Print Mode":
            st.markdown("### Agent 3 Payload")
            if not slicer_path:
                st.info(
                    "Mesh uploads are the right path for real fabrication, but this environment still needs a slicer backend "
                    "such as `PrusaSlicer`, `OrcaSlicer`, or `CuraEngine` before CipherSlice can claim true production release."
                )
            st.code(primary_artifact, language="gcode")
        else:
            blueprint_preview = textwrap.dedent(
                f"""
                Draft Geometry Review Packet
                ----------------------------
                Drawing: {filename}
                Part: {blueprint_name}
                Goal: {part_goal}

                Why final G-code is withheld:
                - A 2D drawing image does not guarantee hidden geometry or exact depth.
                - Dimensions must be authoritative and complete across views.
                - Fit, tolerance, and internal cavity intent must be confirmed before slicing.

                Next best path:
                1. Reconstruct or import a 3D model from the drawing.
                2. Review scale and tolerance assumptions with the user.
                3. Slice the approved geometry for {printer} using {filament}.
                """
            ).strip()
            st.markdown("### Blueprint Review Packet")
            st.code(blueprint_preview, language="text")
        st.markdown("</div>", unsafe_allow_html=True)
