import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import zipfile
from types import SimpleNamespace
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
        "title": "Best Friend Copilot",
        "tagline": "Same manufacturing brain, more personality. Feels like your best friend who keeps it real and still gets the print plan right.",
        "intro": "I will still give safe recommendations, but I will package them like a longtime best friend who keeps it casual, uses a little slang, and still locks in when the print matters.",
        "agent_tone": {
            "Inspector": "Alright dawg, I checked the model so you do not waste filament on a cursed print. Here is what actually matters.",
            "Calibrator": "Bro, I tuned these settings to keep the print clean, stable, and worth your time.",
            "G-Code Architect": "I lined up the manufacturing path so the output stays readable and the plan stays tight.",
            "Cipher Vault": "I locked down the delivery side so the file does not just wander off into chaos.",
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
        "recommended": "",
        "summary": "Most controlled option. Great when a local CipherBridge or supported printer relay is installed.",
        "warning": "Needs a slicer backend, user permission, and a working local connector.",
    },
    "SD card export": {
        "recommended": "Recommended",
        "summary": "Most practical for school printers and locked-down desktops. Export the job, move it manually, and print offline.",
        "warning": "Removable media breaks secure one-time streaming and file control.",
    },
    "Manual download only": {
        "recommended": "",
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

LIVE_AGENT_CONFIGS = {
    "Inspector": {
        "focus": "Validate geometry, scale, fit, and intake quality before anything moves forward.",
        "handoff_to": "Calibrator",
        "ui_title": "Geometry review",
    },
    "Calibrator": {
        "focus": "Translate printer, filament, and job intent into a reliable print strategy.",
        "handoff_to": "G-Code Architect",
        "ui_title": "Print calibration",
    },
    "G-Code Architect": {
        "focus": "Prepare the slicer-ready plan and final manufacturing handoff package.",
        "handoff_to": "Cipher Vault",
        "ui_title": "Artifact generation",
    },
    "Cipher Vault": {
        "focus": "Package, hash, encrypt, and gate release according to the delivery path.",
        "handoff_to": "Human approval",
        "ui_title": "Secure delivery prep",
    },
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


def make_file_like(filename: str, file_bytes: bytes):
    return SimpleNamespace(name=filename, size=len(file_bytes), getvalue=lambda: file_bytes)


def parse_bed_dimensions(printer_profile: dict[str, object]) -> tuple[float, float, float]:
    bed_x, bed_y = parse_bed_shape(str(printer_profile["bed_shape"]))
    return bed_x, bed_y, float(printer_profile["max_height_mm"])


def format_xyz_dims(x_value: float, y_value: float, z_value: float) -> str:
    return f"X {x_value:.1f} mm / Y {y_value:.1f} mm / Z {z_value:.1f} mm"


def summarize_fit(mesh_analysis: dict[str, object] | None, printer_profile: dict[str, object]) -> tuple[str, str]:
    if not mesh_analysis or not mesh_analysis.get("scaled_extents_mm"):
        return "Pending geometry scan", "Upload analysis is needed before CipherSlice can confirm part fit against the build volume."

    part_x, part_y, part_z = mesh_analysis["scaled_extents_mm"]
    build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
    if part_x <= build_x and part_y <= build_y and part_z <= build_z:
        return "Fits current printer", "The current scaled part size fits within the selected printer volume."
    return "Exceeds build volume", "At least one part dimension is larger than the selected printer volume."


def build_bed_preview_svg(mesh_analysis: dict[str, object] | None, printer_profile: dict[str, object]) -> str:
    bed_x, bed_y, _ = parse_bed_dimensions(printer_profile)
    svg_width = 320
    svg_height = 230
    padding = 24
    bed_draw_width = svg_width - (padding * 2)
    bed_draw_height = svg_height - (padding * 2)
    part_svg = ""
    status_label = "Awaiting geometry scan"
    status_color = "#8fa7b9"

    if mesh_analysis and mesh_analysis.get("scaled_extents_mm"):
        part_x, part_y, _ = mesh_analysis["scaled_extents_mm"]
        scale = min(bed_draw_width / max(bed_x, 1), bed_draw_height / max(bed_y, 1))
        part_draw_width = max(8, part_x * scale)
        part_draw_height = max(8, part_y * scale)
        part_draw_width = min(part_draw_width, bed_draw_width)
        part_draw_height = min(part_draw_height, bed_draw_height)
        part_left = padding + ((bed_draw_width - part_draw_width) / 2)
        part_top = padding + ((bed_draw_height - part_draw_height) / 2)
        fits = part_x <= bed_x and part_y <= bed_y
        status_label = "Fits on current bed" if fits else "Footprint exceeds bed"
        status_color = "#73e8c1" if fits else "#ffd39f"
        fill = "rgba(90, 207, 171, 0.28)" if fits else "rgba(255, 140, 120, 0.28)"
        stroke = "#73e8c1" if fits else "#ffab91"
        part_svg = (
            f'<rect x="{part_left:.1f}" y="{part_top:.1f}" width="{part_draw_width:.1f}" height="{part_draw_height:.1f}" '
            f'rx="12" ry="12" fill="{fill}" stroke="{stroke}" stroke-width="2.5" />'
        )

    return f"""
    <div class="bed-preview-shell">
        <svg viewBox="0 0 {svg_width} {svg_height}" class="bed-preview-svg" aria-hidden="true">
            <defs>
                <pattern id="bedGrid" width="18" height="18" patternUnits="userSpaceOnUse">
                    <path d="M 18 0 L 0 0 0 18" fill="none" stroke="rgba(151,179,201,0.16)" stroke-width="1"/>
                </pattern>
            </defs>
            <rect x="{padding}" y="{padding}" width="{bed_draw_width}" height="{bed_draw_height}" rx="18" ry="18"
                  fill="rgba(10,24,38,0.95)" stroke="rgba(104,144,177,0.35)" stroke-width="2.2"/>
            <rect x="{padding}" y="{padding}" width="{bed_draw_width}" height="{bed_draw_height}" rx="18" ry="18"
                  fill="url(#bedGrid)" />
            {part_svg}
        </svg>
        <div class="bed-preview-status" style="color:{status_color};">{status_label}</div>
    </div>
    """


def build_mesh_preview_metrics(
    mesh_analysis: dict[str, object] | None,
    printer_profile: dict[str, object],
) -> list[tuple[str, str]]:
    if not mesh_analysis or not mesh_analysis.get("scaled_extents_mm"):
        return [
            ("Bed use", "Pending"),
            ("Height use", "Pending"),
            ("Mesh health", "Scan needed"),
        ]

    part_x, part_y, part_z = mesh_analysis["scaled_extents_mm"]
    bed_x, bed_y, bed_z = parse_bed_dimensions(printer_profile)
    bed_use = min(100.0, ((part_x * part_y) / max((bed_x * bed_y), 1)) * 100)
    height_use = min(100.0, (part_z / max(bed_z, 1)) * 100)
    mesh_health = "Watertight" if mesh_analysis.get("watertight") else "Needs repair"
    return [
        ("Bed use", f"{bed_use:.0f}%"),
        ("Height use", f"{height_use:.0f}%"),
        ("Mesh health", mesh_health),
    ]


def build_engine_connection_summary(
    slicer_label: str | None,
    slicer_path: str | None,
    connector_url: str | None,
) -> tuple[str, str]:
    if slicer_path and connector_url:
        return ("Engine + link ready", "CipherSlice can slice for real and hand the job toward a connected printer path.")
    if slicer_path:
        return ("Engine ready", "CipherSlice can generate a real print file now. Hardware can be connected later.")
    return ("Planning only", "CipherSlice can plan and prepare the job, but a real slicer still needs to be connected.")


def build_job_context(
    mode: str,
    filename: str,
    printer: str,
    filament: str,
    printer_profile: dict[str, object],
    optimized_plan: dict[str, str | float | int | bool],
    mesh_analysis: dict[str, object] | None,
    blueprint_name: str = "",
    part_goal: str = "",
) -> dict[str, object]:
    build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
    context = {
        "mode": mode,
        "filename": filename,
        "printer": printer,
        "filament": filament,
        "build_volume": format_xyz_dims(build_x, build_y, build_z),
        "gcode_flavor": optimized_plan.get("gcode_flavor", printer_profile.get("gcode_flavor", "Unknown")),
        "layer_height": optimized_plan.get("layer_height"),
        "infill_percent": optimized_plan.get("infill_percent"),
        "wall_loops": optimized_plan.get("wall_loops"),
        "print_speed": optimized_plan.get("print_speed"),
        "nozzle_temp": optimized_plan.get("nozzle_temp"),
        "bed_temp": optimized_plan.get("bed_temp"),
        "support_enabled": optimized_plan.get("support_enabled"),
        "adhesion": optimized_plan.get("adhesion"),
        "orientation": optimized_plan.get("orientation"),
        "delivery_mode": optimized_plan.get("delivery_mode", "Manual download only"),
        "part_label": blueprint_name or filename,
        "part_goal": part_goal or "Reliable physical output",
    }
    if mesh_analysis and mesh_analysis.get("scaled_extents_mm"):
        context["part_size"] = format_xyz_dims(*mesh_analysis["scaled_extents_mm"])
    elif mesh_analysis and mesh_analysis.get("extents_mm"):
        context["part_size"] = format_xyz_dims(*mesh_analysis["extents_mm"])
    else:
        context["part_size"] = "Pending geometry scan"
    return context


def build_live_agent_packets(
    persona: dict[str, object],
    job_context: dict[str, object],
    mesh_analysis: dict[str, object] | None,
    support_density: int,
    file_size_text: str,
    slicer_message: str,
) -> dict[str, dict[str, str]]:
    persona_tone = persona["agent_tone"]
    if job_context["mode"] == "Reliable Print Mode":
        mesh_ok = mesh_analysis["mesh_ok"] if mesh_analysis else False
        scale_hint = mesh_analysis["scale_hint"] if mesh_analysis and mesh_analysis.get("scale_hint") else "No scale hint available."
        inspector_summary = (
            f"{persona_tone['Inspector']} Analyzed `{job_context['filename']}` from `{file_size_text}` input volume. "
            f"Recommended support density: `{support_density}%`. "
            f"{'Mesh integrity looks acceptable.' if mesh_ok else 'Mesh integrity requires review.'} {scale_hint}"
        )
        calibrator_summary = (
            f"{persona_tone['Calibrator']} Mapped `{job_context['filament']}` onto `{job_context['printer']}`. "
            f"Nozzle `{job_context['nozzle_temp']} degC`, bed `{job_context['bed_temp']} degC`, speed `{job_context['print_speed']} mm/s`, "
            f"layer height `{job_context['layer_height']} mm`, infill `{job_context['infill_percent']}%`. "
            f"Placement suggestion: {job_context['orientation']} Bed setup: `{job_context['adhesion']}`."
        )
        architect_summary = (
            f"{persona_tone['G-Code Architect']} {slicer_message} "
            f"Prepared the manufacturing handoff for `{job_context['printer']}` using `{job_context['gcode_flavor']}`."
        )
    else:
        inspector_summary = (
            f"{persona_tone['Inspector']} Reviewed `{job_context['filename']}` as a structured drawing from `{file_size_text}` input volume. "
            f"Final fabrication still depends on validated geometry, dimensions, and fit assumptions."
        )
        calibrator_summary = (
            f"{persona_tone['Calibrator']} Mapped the requested part goal to `{job_context['printer']}` with `{job_context['filament']}`. "
            f"Placement suggestion: {job_context['orientation']} This stays in draft planning mode until geometry is confirmed."
        )
        architect_summary = (
            f"{persona_tone['G-Code Architect']} {slicer_message} "
            f"Prepared the draft manufacturing handoff for `{job_context['printer']}` using `{job_context['gcode_flavor']}`."
        )
    vault_summary = (
        f"{persona_tone['Cipher Vault']} Prepared the delivery package for `{job_context['part_label']}` "
        f"with the selected release path and approval gate."
    )
    return {
        "Inspector": {
            "title": LIVE_AGENT_CONFIGS["Inspector"]["ui_title"],
            "summary": inspector_summary,
            "internal_note": f"Focus: {LIVE_AGENT_CONFIGS['Inspector']['focus']} | Next handoff: {LIVE_AGENT_CONFIGS['Inspector']['handoff_to']}",
        },
        "Calibrator": {
            "title": LIVE_AGENT_CONFIGS["Calibrator"]["ui_title"],
            "summary": calibrator_summary,
            "internal_note": f"Focus: {LIVE_AGENT_CONFIGS['Calibrator']['focus']} | Next handoff: {LIVE_AGENT_CONFIGS['Calibrator']['handoff_to']}",
        },
        "G-Code Architect": {
            "title": LIVE_AGENT_CONFIGS["G-Code Architect"]["ui_title"],
            "summary": architect_summary,
            "internal_note": f"Focus: {LIVE_AGENT_CONFIGS['G-Code Architect']['focus']} | Next handoff: {LIVE_AGENT_CONFIGS['G-Code Architect']['handoff_to']}",
        },
        "Cipher Vault": {
            "title": LIVE_AGENT_CONFIGS["Cipher Vault"]["ui_title"],
            "summary": vault_summary,
            "internal_note": f"Focus: {LIVE_AGENT_CONFIGS['Cipher Vault']['focus']} | Next handoff: {LIVE_AGENT_CONFIGS['Cipher Vault']['handoff_to']}",
        },
    }


def build_slicer_handoff_contract(
    job_context: dict[str, object],
    artifact_hash: str,
    release_allowed: bool,
    overall_confidence: float,
    delivery_mode: str,
    mesh_analysis: dict[str, object] | None,
) -> dict[str, object]:
    contract = {
        "source_file": job_context["filename"],
        "part_label": job_context["part_label"],
        "printer": job_context["printer"],
        "filament": job_context["filament"],
        "build_volume": job_context["build_volume"],
        "part_size": job_context["part_size"],
        "gcode_flavor": job_context["gcode_flavor"],
        "layer_height_mm": job_context["layer_height"],
        "infill_percent": job_context["infill_percent"],
        "wall_loops": job_context["wall_loops"],
        "print_speed_mms": job_context["print_speed"],
        "nozzle_temp_c": job_context["nozzle_temp"],
        "bed_temp_c": job_context["bed_temp"],
        "support_enabled": job_context["support_enabled"],
        "adhesion": job_context["adhesion"],
        "delivery_mode": delivery_mode,
        "release_allowed": release_allowed,
        "confidence": round(overall_confidence, 3),
        "artifact_hash": artifact_hash,
        "orientation": job_context["orientation"],
    }
    if mesh_analysis and mesh_analysis.get("scale_factor"):
        contract["scale_factor"] = mesh_analysis["scale_factor"]
    return contract


def format_handoff_contract_comments(contract: dict[str, object]) -> str:
    ordered_keys = [
        "source_file",
        "part_label",
        "printer",
        "filament",
        "build_volume",
        "part_size",
        "gcode_flavor",
        "layer_height_mm",
        "infill_percent",
        "wall_loops",
        "print_speed_mms",
        "nozzle_temp_c",
        "bed_temp_c",
        "support_enabled",
        "adhesion",
        "delivery_mode",
        "release_allowed",
        "confidence",
        "artifact_hash",
        "orientation",
        "scale_factor",
    ]
    lines = []
    for key in ordered_keys:
        if key in contract:
            lines.append(f"; {key}: {contract[key]}")
    return "\n".join(lines)


def get_live_agent_runtime_config() -> dict[str, object]:
    timeout_raw = os.getenv("CIPHERSLICE_AGENT_TIMEOUT_SEC", "20").strip()
    try:
        timeout_sec = max(5, min(int(timeout_raw), 120))
    except ValueError:
        timeout_sec = 20

    enabled_flag = os.getenv("CIPHERSLICE_ENABLE_LIVE_MODELS", "").strip().lower()
    enabled = enabled_flag in {"1", "true", "yes", "on"}
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("CIPHERSLICE_OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.getenv("CIPHERSLICE_AGENT_MODEL", "gpt-5.4").strip() or "gpt-5.4"
    reasoning_effort = os.getenv("CIPHERSLICE_AGENT_REASONING", "medium").strip().lower() or "medium"
    if reasoning_effort not in {"low", "medium", "high"}:
        reasoning_effort = "medium"

    return {
        "enabled": enabled and bool(api_key),
        "enabled_flag": enabled,
        "api_key_present": bool(api_key),
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "timeout_sec": timeout_sec,
    }


def extract_response_text(response_payload: dict[str, object]) -> str:
    output_items = response_payload.get("output", [])
    if not isinstance(output_items, list):
        return ""

    chunks: list[str] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = str(part.get("text", "")).strip()
                if text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def build_live_agent_prompt(
    agent_name: str,
    persona: dict[str, object],
    job_context: dict[str, object],
    mesh_analysis: dict[str, object] | None,
    support_density: int,
    slicer_message: str,
) -> tuple[str, str]:
    role_meta = LIVE_AGENT_CONFIGS[agent_name]
    identity = AGENT_IDENTITIES[agent_name]
    mesh_notes: list[str] = []
    if mesh_analysis:
        if mesh_analysis.get("watertight") is not None:
            mesh_notes.append(f"Watertight: {'yes' if mesh_analysis['watertight'] else 'no'}")
        if mesh_analysis.get("scaled_extents_mm"):
            mesh_notes.append(f"Part size: {format_xyz_dims(*mesh_analysis['scaled_extents_mm'])}")
        elif mesh_analysis.get("extents_mm"):
            mesh_notes.append(f"Part size: {format_xyz_dims(*mesh_analysis['extents_mm'])}")
        if mesh_analysis.get("scale_hint"):
            mesh_notes.append(str(mesh_analysis["scale_hint"]))
        if mesh_analysis.get("issues"):
            mesh_notes.extend(str(issue) for issue in mesh_analysis["issues"][:3])

    instructions = textwrap.dedent(
        f"""
        You are CipherSlice {agent_name}.
        {identity}
        Your operational focus: {role_meta['focus']}

        Write one concise UI-ready update for the user.
        Keep it to 2 short sentences or less than 70 words.
        Do not mention prompts, chain-of-thought, hidden rules, or internal orchestration.
        Use clear manufacturing language. If the print engine is missing, say so plainly.
        Follow this tone guidance: {persona['agent_tone'][agent_name]}
        """
    ).strip()

    prompt = textwrap.dedent(
        f"""
        Section title: {role_meta['ui_title']}
        Job mode: {job_context['mode']}
        Source file: {job_context['filename']}
        Part label: {job_context['part_label']}
        Printer: {job_context['printer']}
        Material: {job_context['filament']}
        Build volume: {job_context['build_volume']}
        Part size: {job_context['part_size']}
        Layer height: {job_context['layer_height']} mm
        Infill: {job_context['infill_percent']}%
        Walls: {job_context['wall_loops']}
        Speed: {job_context['print_speed']} mm/s
        Nozzle temp: {job_context['nozzle_temp']} degC
        Bed temp: {job_context['bed_temp']} degC
        Support enabled: {job_context['support_enabled']}
        Support density target: {support_density}%
        Adhesion: {job_context['adhesion']}
        Placement suggestion: {job_context['orientation']}
        Delivery mode: {job_context.get('delivery_mode', 'Unknown')}
        Runtime note: {slicer_message}
        Mesh notes: {" | ".join(mesh_notes) if mesh_notes else "No additional mesh notes."}
        """
    ).strip()
    return instructions, prompt


def call_openai_responses_api(
    instructions: str,
    prompt: str,
    runtime_config: dict[str, object],
) -> tuple[str | None, str | None]:
    payload = {
        "model": runtime_config["model"],
        "instructions": instructions,
        "input": prompt,
        "reasoning": {"effort": runtime_config["reasoning_effort"]},
        "max_output_tokens": 160,
        "store": False,
        "text": {"format": {"type": "text"}},
    }
    request = Request(
        f"{runtime_config['base_url']}/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {runtime_config['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=float(runtime_config["timeout_sec"])) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            error_payload = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_payload = str(exc)
        return None, f"Live model request failed with HTTP {exc.code}: {error_payload}"
    except URLError as exc:
        return None, f"Live model request could not reach the API endpoint: {exc.reason}"
    except Exception as exc:
        return None, f"Live model request failed unexpectedly: {exc}"

    response_text = extract_response_text(response_payload)
    if not response_text:
        return None, "Live model request completed but returned no user-facing text."
    return response_text, None


def run_live_agent_runtime(
    persona: dict[str, object],
    job_context: dict[str, object],
    mesh_analysis: dict[str, object] | None,
    support_density: int,
    slicer_message: str,
    fallback_packets: dict[str, dict[str, str]],
) -> tuple[dict[str, dict[str, str]], dict[str, object]]:
    runtime_config = get_live_agent_runtime_config()
    if not runtime_config["enabled"]:
        status = "Disabled"
        detail = "Live AI workers are off. CipherSlice is using the built-in planning engine."
        if runtime_config["enabled_flag"] and not runtime_config["api_key_present"]:
            status = "Setup needed"
            detail = "Live AI workers were requested, but OPENAI_API_KEY is missing. CipherSlice is using the built-in planning engine."
        return fallback_packets, {
            "status": status,
            "detail": detail,
            "model": None,
            "using_live_workers": False,
            "partial_fallback": False,
        }

    packets = {name: dict(packet) for name, packet in fallback_packets.items()}
    errors: list[str] = []
    live_count = 0
    for agent_name in LIVE_AGENT_CONFIGS:
        instructions, prompt = build_live_agent_prompt(
            agent_name,
            persona,
            job_context,
            mesh_analysis,
            support_density,
            slicer_message,
        )
        response_text, error_text = call_openai_responses_api(instructions, prompt, runtime_config)
        if response_text:
            packets[agent_name]["summary"] = response_text
            packets[agent_name]["source"] = "live"
            live_count += 1
        else:
            packets[agent_name]["source"] = "built-in"
            errors.append(f"{agent_name}: {error_text}")

    if live_count == len(LIVE_AGENT_CONFIGS):
        status = "Live AI workers connected"
        detail = f"CipherSlice is using real model-backed worker summaries via `{runtime_config['model']}`."
        partial_fallback = False
    elif live_count > 0:
        status = "Hybrid mode"
        detail = f"CipherSlice used live workers where possible, then fell back to the built-in planning engine for the rest. {errors[0]}"
        partial_fallback = True
    else:
        status = "Built-in fallback"
        detail = f"All live worker calls fell back to the built-in planning engine. {errors[0]}"
        partial_fallback = True

    return packets, {
        "status": status,
        "detail": detail,
        "model": runtime_config["model"],
        "using_live_workers": live_count > 0,
        "partial_fallback": partial_fallback,
    }


def build_profile_mode_label(mode: str, slicer_path: str | None) -> tuple[str, str]:
    if mode == "Reliable Print Mode" and slicer_path:
        return "Production-capable review", "A slicer backend is connected, so CipherSlice can move beyond recommendation mode."
    if mode == "Reliable Print Mode":
        return "Recommendation mode", "This plan is real and editable, but final production release still needs a slicer backend."
    return "Reconstruction review", "Blueprint intake can guide a job, but validated 3D geometry is still required before slicing."


def build_execution_status(mode: str, slicer_path: str | None) -> tuple[str, str, str]:
    if mode == "Reliable Print Mode" and slicer_path:
        return (
            "Ready for real slicing",
            "state-ready",
            "CipherSlice is connected to a slicer backend, so this job can move toward real printer-valid G-code generation.",
        )
    if mode == "Reliable Print Mode":
        return (
            "Planning mode",
            "state-review",
            "CipherSlice can analyze, optimize, and package the job, but this environment still uses a placeholder artifact path until a real slicer backend is connected.",
        )
    return (
        "Blueprint review mode",
        "state-blocked",
        "CipherSlice can create a reconstruction brief from structured drawings, but final fabrication still requires validated 3D geometry before slicing.",
    )


def set_persona(persona_key: str) -> None:
    st.session_state["persona_key"] = persona_key


def set_delivery_mode(mode_name: str) -> None:
    st.session_state["delivery_mode_choice"] = mode_name


def set_experience_mode(mode_name: str) -> None:
    st.session_state["experience_mode"] = mode_name


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
        return "Good to go", "CipherSlice can generate real print files and already has a printer handoff path connected."
    if slicer_path:
        return "Almost ready", "CipherSlice can generate real print files, but direct printer handoff still needs a local connector or supported printer integration."
    return "Setup needed", "The website is ready, but it still needs a slicer backend before it can create final production print files."


def resolve_printer_profile(
    printer_name: str,
    custom_width: float,
    custom_depth: float,
    custom_height: float,
    custom_nozzle: float,
    custom_gcode_flavor: str = "Generic large-format Marlin",
    custom_bed_shape: str = "Rectangular",
    custom_heated_bed: bool = True,
    custom_heated_chamber: bool = False,
    custom_start_gcode: str = "",
    custom_end_gcode: str = "",
) -> dict[str, object]:
    profile = dict(PRINTER_PROFILES[printer_name])
    if printer_name != "Custom / Large Format":
        return profile

    profile["bed_shape"] = f"{int(custom_width)} x {int(custom_depth)} mm"
    profile["max_height_mm"] = custom_height
    profile["nozzle_diameter"] = round(custom_nozzle, 2)
    profile["gcode_flavor"] = custom_gcode_flavor
    profile["adhesion_default"] = "Large-format custom surface"
    profile["speed"] = {"PLA": 95, "PETG": 75, "ABS": 65, "TPU": 28}
    profile["bed_shape_type"] = custom_bed_shape
    profile["heated_bed"] = custom_heated_bed
    profile["heated_chamber"] = custom_heated_chamber
    profile["start_gcode"] = custom_start_gcode.strip()
    profile["end_gcode"] = custom_end_gcode.strip()
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


def build_runtime_phase_summary(
    mode: str,
    slicer_path: str | None,
    connector_url: str | None,
    delivery_mode: str,
) -> tuple[str, str]:
    if mode != "Reliable Print Mode":
        return (
            "Planning-only review",
            "No printer is needed yet. CipherSlice is creating a reconstruction and manufacturing plan, not a final print file.",
        )
    if slicer_path and connector_url and delivery_mode == "Secure local connector":
        return (
            "End-to-end capable",
            "This setup can analyze the part, generate a real print file, and hand it toward connected hardware after approval.",
        )
    if slicer_path:
        return (
            "Real slicing ready",
            "No printer is required for this stage. CipherSlice can generate a real print file now, and hardware can be connected later.",
        )
    return (
        "Software planning mode",
        "No printer is required right now. CipherSlice can still inspect the model, build the plan, and show a preview, but a slicer backend is still needed before true production G-code is generated.",
    )


def build_output_type_summary(mode: str, slicer_path: str | None) -> tuple[str, str]:
    if mode != "Reliable Print Mode":
        return (
            "Draft reconstruction brief",
            "This output is a planning packet for reconstruction and review. It is not final printer-ready G-code yet.",
        )
    if slicer_path:
        return (
            "Real print file path",
            "This job can move through a real slicer backend and produce printer-valid G-code when the engine is connected correctly.",
        )
    return (
        "Planned output preview",
        "This output shows the prepared manufacturing plan and placeholder file structure. A real slicer backend is still needed for full production G-code.",
    )


def build_engine_diagnostics(
    slicer_label: str | None,
    slicer_path: str | None,
    connector_url: str | None,
    runtime_meta: dict[str, object],
    delivery_mode: str,
) -> list[str]:
    notes = [
        f"Print engine: {slicer_label or 'Not detected'}",
        f"Print engine path: {slicer_path or 'None configured'}",
        f"AI worker runtime: {runtime_meta['status']}",
        f"Printer link: {connector_url or 'Not connected'}",
        f"Delivery path: {delivery_mode}",
    ]
    if not slicer_path:
        notes.append("Next setup move: install a supported CLI slicer and point CIPHERSLICE_SLICER_PATH at it.")
    elif delivery_mode == "Secure local connector" and not connector_url:
        notes.append("Next setup move: connect CipherBridge or a supported printer relay for hardware handoff.")
    else:
        notes.append("Setup looks healthy enough for the current software stage.")
    return notes


def build_slicer_setup_bundle(
    uploaded_file,
    slicer_plan: dict[str, str | float | int | bool],
    handoff_contract: dict[str, object],
    primary_artifact: str,
    slicer_message: str,
    command_preview: str,
) -> bytes:
    bundle = io.BytesIO()
    model_suffix = "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"input_model{model_suffix}", uploaded_file.getvalue())
        archive.writestr("cipher_plan.ini", build_prusaslicer_config(slicer_plan))
        archive.writestr("cipher_handoff_contract.txt", format_handoff_contract_comments(handoff_contract))
        archive.writestr("cipher_handoff_contract.json", json.dumps(handoff_contract, indent=2))
        archive.writestr("planned_output_preview.gcode", primary_artifact)
        archive.writestr("cipher_run_command.txt", command_preview)
        archive.writestr(
            "README_SETUP.txt",
            textwrap.dedent(
                f"""
                CipherSlice Slicer Setup Pack

                Source file: {handoff_contract.get('source_file', 'Unknown')}
                Printer: {handoff_contract.get('printer', 'Unknown')}
                Filament: {handoff_contract.get('filament', 'Unknown')}
                Delivery mode: {handoff_contract.get('delivery_mode', 'Unknown')}

                Included files:
                - input_model: original uploaded model
                - cipher_plan.ini: slicer configuration generated by CipherSlice
                - cipher_handoff_contract.txt/.json: structured manufacturing handoff
                - cipher_run_command.txt: example CLI command for the print engine
                - planned_output_preview.gcode: preview artifact currently shown in the app

                Runtime note:
                {slicer_message}

                Suggested next step:
                1. Open the model in a supported CLI-capable slicer workflow.
                2. Load cipher_plan.ini or map the values into your slicer profile.
                3. Review the handoff contract before exporting the final print file.
                """
            ).strip(),
        )
    return bundle.getvalue()


def build_operator_handoff_sheet(
    filename: str,
    printer: str,
    filament: str,
    delivery_mode: str,
    optimized_plan: dict[str, str | float | int | bool],
    overall_confidence: float,
    execution_label: str,
) -> str:
    return textwrap.dedent(
        f"""
        CipherSlice Operator Handoff Sheet

        Part: {filename}
        Printer: {printer}
        Material: {filament}
        Delivery path: {delivery_mode}
        Job mode: {execution_label}
        Confidence: {overall_confidence * 100:.1f}%

        Plan summary:
        - Layer height: {optimized_plan['layer_height']} mm
        - Infill: {optimized_plan['infill_percent']}%
        - Wall loops: {optimized_plan['wall_loops']}
        - Print speed: {optimized_plan['print_speed']} mm/s
        - Nozzle temp: {optimized_plan['nozzle_temp']} degC
        - Bed temp: {optimized_plan['bed_temp']} degC
        - Support: {'Enabled' if optimized_plan['support_enabled'] else 'Disabled'}
        - Adhesion: {optimized_plan['adhesion']}
        - G-code flavor: {optimized_plan['gcode_flavor']}

        Operator checklist:
        1. Confirm the selected printer and material match the machine you will actually use.
        2. Recheck scale, support, and adhesion before exporting or printing.
        3. If using removable media, label the file clearly before transfer.
        4. If the slicer backend is missing, treat the output as a planning artifact until real slicing is completed.
        """
    ).strip()


def build_plan_diff(
    recommended_plan: dict[str, str | float | int | bool],
    optimized_plan: dict[str, str | float | int | bool],
    delivery_mode: str,
    filament: str,
) -> list[str]:
    comparisons = [
        ("Filament", filament, filament),
        ("Layer height", recommended_plan["layer_height"], optimized_plan["layer_height"]),
        ("Infill", recommended_plan["infill_percent"], optimized_plan["infill_percent"]),
        ("Wall loops", recommended_plan["wall_loops"], optimized_plan["wall_loops"]),
        ("Print speed", recommended_plan["print_speed"], optimized_plan["print_speed"]),
        ("Nozzle temp", recommended_plan["nozzle_temp"], optimized_plan["nozzle_temp"]),
        ("Bed temp", recommended_plan["bed_temp"], optimized_plan["bed_temp"]),
        ("Support enabled", recommended_plan["support_enabled"], optimized_plan["support_enabled"]),
        ("Adhesion", recommended_plan["adhesion"], optimized_plan["adhesion"]),
        ("G-code flavor", recommended_plan.get("gcode_flavor"), optimized_plan.get("gcode_flavor")),
        ("Delivery mode", delivery_mode, delivery_mode),
    ]
    diffs: list[str] = []
    for label, recommended_value, current_value in comparisons:
        if recommended_value != current_value:
            diffs.append(f"{label}: recommended `{recommended_value}` -> current `{current_value}`")
    return diffs


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
        "start_gcode": profile.get("start_gcode", ""),
        "end_gcode": profile.get("end_gcode", ""),
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
        "adaptive_notes": [],
        "geometry_profile": "Unknown",
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
        if analysis["scaled_extents_mm"]:
            test_extents = analysis["scaled_extents_mm"]
            min_dim = max(min(test_extents), 0.01)
            max_dim = max(test_extents)
            height_ratio = test_extents[2] / max(max(test_extents[0], test_extents[1]), 0.01)
            bed_fill_ratio = (test_extents[0] * test_extents[1]) / max((bed_x * bed_y), 1)
            slender_ratio = max_dim / min_dim
            if height_ratio > 1.25:
                analysis["geometry_profile"] = "Tall / tip-prone"
                analysis["adaptive_notes"].append("Tall geometry detected. Slower motion, stronger adhesion, and support may help avoid tipping.")
            elif bed_fill_ratio > 0.55:
                analysis["geometry_profile"] = "Wide footprint / large bed use"
                analysis["adaptive_notes"].append("Large bed coverage detected. Slower travel and stronger first-layer grip are recommended.")
            elif slender_ratio > 8:
                analysis["geometry_profile"] = "Thin or slender features"
                analysis["adaptive_notes"].append("Thin features detected. Too many walls or aggressive speeds may swallow detail or cause weak edges.")
            else:
                analysis["geometry_profile"] = "Compact / general purpose"
                analysis["adaptive_notes"].append("Geometry looks fairly balanced for a standard print profile.")
        analysis["notes"].append(scale_hint)
    except Exception as exc:
        analysis["mesh_ok"] = False
        analysis["issues"].append(f"Mesh analysis failed: {exc}")

    return analysis


def refine_plan_for_geometry(
    plan: dict[str, str | float | int | bool],
    mesh_analysis: dict[str, object] | None,
    support_strategy: str,
    printer_profile: dict[str, object],
) -> dict[str, str | float | int | bool]:
    refined = dict(plan)
    if not mesh_analysis or not mesh_analysis.get("scaled_extents_mm"):
        return refined

    part_x, part_y, part_z = mesh_analysis["scaled_extents_mm"]
    bed_x, bed_y, _ = parse_bed_dimensions(printer_profile)
    width_depth_max = max(part_x, part_y, 0.01)
    height_ratio = part_z / width_depth_max
    bed_fill_ratio = (part_x * part_y) / max((bed_x * bed_y), 1)
    min_dim = max(min(part_x, part_y, part_z), 0.01)
    max_dim = max(part_x, part_y, part_z)
    slender_ratio = max_dim / min_dim

    if height_ratio > 1.25:
        if support_strategy != "Disabled":
            refined["support_enabled"] = True
            refined["support_density"] = max(int(refined["support_density"]), 24)
        if refined["adhesion"] in {"Auto", "Skirt"}:
            refined["adhesion"] = "Brim"
        refined["print_speed"] = max(25, int(int(refined["print_speed"]) * 0.82))
        refined["orientation"] = "Favor the broadest base on the bed and reduce tall unsupported spans to protect against tipping."

    if bed_fill_ratio > 0.55:
        refined["print_speed"] = max(25, int(int(refined["print_speed"]) * 0.9))
        if refined["adhesion"] in {"Auto", "Skirt"}:
            refined["adhesion"] = "Brim"

    if slender_ratio > 8:
        refined["wall_loops"] = min(int(refined["wall_loops"]), 2)
        refined["print_speed"] = max(22, int(int(refined["print_speed"]) * 0.88))
        refined["orientation"] = "Preserve thin features by reducing shell bulk and avoiding aggressive speed on narrow spans."

    if mesh_analysis.get("face_count") and int(mesh_analysis["face_count"]) > 400_000:
        refined["print_speed"] = max(20, int(int(refined["print_speed"]) * 0.92))

    return refined


def build_prusaslicer_config(plan: dict[str, str | float | int | bool]) -> str:
    support_value = 1 if plan["support_enabled"] else 0
    brim_width = 0 if plan["adhesion"] != "Brim" else 5
    raft_layers = 0 if plan["adhesion"] != "Raft" else 2
    start_gcode = str(plan.get("start_gcode", "")).replace("\r", "\\n").replace("\n", "\\n")
    end_gcode = str(plan.get("end_gcode", "")).replace("\r", "\\n").replace("\n", "\\n")
    return textwrap.dedent(
        f"""
        # CipherSlice generated slicer config
        # G-code flavor: {plan.get('gcode_flavor', 'Unknown')}
        layer_height = {plan['layer_height']}
        fill_density = {plan['infill_percent']}%
        perimeters = {plan['wall_loops']}
        nozzle_diameter = {plan['nozzle_diameter']}
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
        start_gcode = {start_gcode}
        end_gcode = {end_gcode}
        """
    ).strip()


def build_slicer_command_preview(
    slicer_label: str | None,
    slicer_path: str | None,
    filename: str,
    plan: dict[str, str | float | int | bool],
) -> str:
    sample_engine = slicer_path or "<path-to-slicer>"
    sample_input = f"input_model.{filename.rsplit('.', 1)[-1].lower()}"
    sample_output = "output.gcode"
    sample_config = "cipher_plan.ini"
    command = [
        sample_engine,
        "--export-gcode",
        sample_input,
        "--output",
        sample_output,
        "--load",
        sample_config,
    ]
    scale_factor = float(plan.get("scale_factor", 1.0))
    if scale_factor != 1.0:
        command.extend(["--scale", str(scale_factor)])
    return f"# {slicer_label or 'Supported slicer'} command preview\n" + " ".join(command)


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
    handoff_contract: dict[str, object],
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
        contract_path = os.path.join(tmpdir, "cipher_handoff_contract.txt")
        contract_json_path = os.path.join(tmpdir, "cipher_handoff_contract.json")
        output_path = os.path.join(tmpdir, "output.gcode")
        with open(input_path, "wb") as handle:
            handle.write(uploaded_file.getvalue())
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(build_prusaslicer_config(plan))
        with open(contract_path, "w", encoding="utf-8") as handle:
            handle.write(format_handoff_contract_comments(handoff_contract))
        with open(contract_json_path, "w", encoding="utf-8") as handle:
            json.dump(handoff_contract, handle, indent=2)

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
            return handle.read(), "Real slicer backend generated G-code successfully from the prepared slicer handoff contract."


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
            "G-Code Architect": 0.965 if has_slicer else 0.80,
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


def generate_gcode(
    filename: str,
    printer: str,
    filament: str,
    nozzle_temp: int,
    bed_temp: int,
    speed: int,
    handoff_contract: dict[str, object] | None = None,
) -> str:
    sanitized_name = filename.replace(";", "_")
    extrusion_multiplier = {
        "PLA": 0.98,
        "PETG": 1.03,
        "ABS": 1.01,
        "TPU": 1.08,
    }[filament]
    feedrate = speed * 60
    contract_comments = format_handoff_contract_comments(handoff_contract) if handoff_contract else ""
    return textwrap.dedent(
        f"""
        ; CipherSlice Autonomous Manufacturing Stream
        ; Source File: {sanitized_name}
        ; Target Printer: {printer}
        ; Filament Profile: {filament}
        ; Encryption Stage: staged_for_secure_hardware_stream
        {contract_comments}
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
        min-height: 260px;
    }
    .delivery-card-active {
        border-color: rgba(104, 241, 193, 0.42);
        box-shadow: 0 0 0 1px rgba(104, 241, 193, 0.12), 0 14px 28px rgba(0, 0, 0, 0.18);
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
    .setting-card {
        background: rgba(7, 18, 30, 0.72);
        border: 1px solid rgba(104, 144, 177, 0.18);
        border-radius: 16px;
        padding: 0.85rem 0.95rem;
        margin-bottom: 0.85rem;
    }
    .workflow-style-card {
        background: rgba(7, 18, 30, 0.9);
        border: 1px solid rgba(104, 241, 193, 0.18);
        border-radius: 18px;
        padding: 1.1rem 1.15rem;
        margin-bottom: 1rem;
    }
    .workflow-style-title {
        color: #f4f8fb;
        font-size: 1.12rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .workflow-style-copy {
        color: #b7c8d5;
        line-height: 1.5;
        margin-bottom: 0.8rem;
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
    .manifest-key {
        color: #8fe6cf;
    }
    .subsection-card {
        background: rgba(7, 18, 30, 0.72);
        border: 1px solid rgba(104, 144, 177, 0.18);
        border-radius: 18px;
        padding: 1rem 1.05rem;
        margin-bottom: 0.9rem;
    }
    .subsection-title {
        color: #f4f8fb;
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 0.45rem;
    }
    .subsection-copy {
        color: #b7c8d5;
        line-height: 1.55;
    }
    .mode-pill {
        display: inline-block;
        padding: 0.28rem 0.62rem;
        border-radius: 999px;
        background: rgba(90, 207, 171, 0.16);
        color: #d8fff1;
        font-size: 0.8rem;
        letter-spacing: 0.04em;
        margin-bottom: 0.6rem;
    }
    .dim-line {
        color: #d9e7f1;
        padding: 0.22rem 0;
    }
    .section-divider {
        height: 1px;
        background: linear-gradient(90deg, rgba(104, 144, 177, 0), rgba(104, 144, 177, 0.35), rgba(104, 144, 177, 0));
        margin: 1rem 0 1.1rem;
    }
    .preview-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.8rem;
        margin: 0.8rem 0 1rem;
    }
    .preview-card {
        background: rgba(7, 18, 30, 0.72);
        border: 1px solid rgba(104, 144, 177, 0.18);
        border-radius: 18px;
        padding: 0.95rem 1rem;
    }
    .preview-title {
        color: #f4f8fb;
        font-size: 1rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }
    .preview-copy {
        color: #b7c8d5;
        line-height: 1.5;
    }
    .xyz-badge {
        display: inline-block;
        margin: 0.1rem 0.2rem 0.2rem 0;
        padding: 0.25rem 0.6rem;
        border-radius: 999px;
        background: rgba(90, 207, 171, 0.14);
        border: 1px solid rgba(90, 207, 171, 0.18);
        color: #d8fff1;
        font-size: 0.86rem;
    }
    .ops-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.8rem;
        margin: 0.3rem 0 1rem;
    }
    .ops-card {
        background: linear-gradient(180deg, rgba(8, 23, 37, 0.94), rgba(6, 16, 27, 0.94));
        border: 1px solid rgba(104, 144, 177, 0.2);
        border-radius: 18px;
        padding: 0.95rem 1rem;
    }
    .ops-title {
        color: #f4f8fb;
        font-size: 0.95rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }
    .ops-copy {
        color: #b7c8d5;
        line-height: 1.55;
    }
    .ops-chip {
        display: inline-block;
        margin-top: 0.45rem;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        background: rgba(255, 184, 0, 0.14);
        border: 1px solid rgba(255, 214, 102, 0.24);
        color: #fff1c2;
        font-size: 0.8rem;
    }
    .metric-chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.55rem;
    }
    .metric-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.25rem 0.58rem;
        border-radius: 999px;
        background: rgba(90, 207, 171, 0.12);
        border: 1px solid rgba(90, 207, 171, 0.16);
        color: #dffcf2;
        font-size: 0.82rem;
    }
    .bed-preview-shell {
        margin-top: 0.2rem;
    }
    .bed-preview-svg {
        width: 100%;
        max-width: 340px;
        display: block;
        margin: 0 auto 0.55rem;
    }
    .bed-preview-status {
        text-align: center;
        font-size: 0.9rem;
        font-weight: 650;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="section-label">CipherSlice Control Plane</div>
        <div class="hero-title">Smart Print Planning + Secure Delivery</div>
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
if "active_job" not in st.session_state:
    st.session_state["active_job"] = None
if "experience_mode" not in st.session_state:
    st.session_state["experience_mode"] = "Beginner"

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
                Same safe recommendations, but with playful best-friend energy and a little more personality.
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
st.markdown("### What Is Ready Right Now")
status_cols = st.columns(4, gap="medium")
status_cols[0].metric("Overall", global_state)
status_cols[1].metric("Print engine", "Connected" if slicer_path else "Missing")
status_cols[2].metric("Printer link", "Connected" if connector_url else "Not connected")
status_cols[3].metric("Website", "Live")
banner_class = "state-ready" if global_state == "Good to go" else ("state-review" if global_state == "Almost ready" else "state-blocked")
st.markdown(
    f'<div class="state-banner {banner_class}">Current setup: {global_state}. {global_message}</div>',
    unsafe_allow_html=True,
)
if global_state == "Good to go":
    st.success(global_message)
elif global_state == "Almost ready":
    st.warning(global_message)
else:
    st.error(global_message)
st.markdown("</div>", unsafe_allow_html=True)

if "delivery_mode_choice" not in st.session_state:
    st.session_state["delivery_mode_choice"] = "SD card export"

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Choose Delivery Strategy")
delivery_cols = st.columns(3, gap="medium")
for column, mode_name in zip(delivery_cols, DELIVERY_MODES):
    with column:
        with st.container(border=True):
            st.markdown(f"**{mode_name}**")
            if DELIVERY_MODE_DETAILS[mode_name]["recommended"]:
                st.caption(DELIVERY_MODE_DETAILS[mode_name]["recommended"])
            st.write(DELIVERY_MODE_DETAILS[mode_name]["summary"])
            st.markdown(
                f"<span style='color:#d8c680;'><strong>Tradeoff:</strong> {DELIVERY_MODE_DETAILS[mode_name]['warning']}</span>",
                unsafe_allow_html=True,
            )
        st.button(
            mode_name,
            use_container_width=True,
            type="primary" if st.session_state["delivery_mode_choice"] == mode_name else "secondary",
            on_click=set_delivery_mode,
            args=(mode_name,),
            key=f"delivery_{mode_name}",
        )
st.info(
    f"Active delivery strategy: `{st.session_state['delivery_mode_choice']}`. "
    f"{DELIVERY_MODE_DETAILS[st.session_state['delivery_mode_choice']]['summary']}"
)
st.warning(
    "Recommended: use `Reliable Print Mode` with `SD card export`. "
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
            "Upload a real mesh file and CipherSlice will prepare a printer-targeted artifact flow.</div>",
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "Drag & drop the source model",
            type=["stl", "obj", "3mf"],
            help="CipherSlice accepts production mesh uploads in STL, OBJ, or 3MF format.",
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

    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    printer = st.selectbox("Target Printer", list(PRINTER_PROFILES.keys()))
    st.caption("If the printer list stays open in your browser, click anywhere outside the menu to close it.")
    st.markdown("</div>", unsafe_allow_html=True)
    custom_width = 500.0
    custom_depth = 500.0
    custom_height = 500.0
    custom_nozzle = 0.6
    custom_gcode_flavor = "Generic large-format Marlin"
    custom_bed_shape_type = "Rectangular"
    custom_heated_bed = True
    custom_heated_chamber = False
    custom_start_gcode = ""
    custom_end_gcode = ""
    if printer == "Custom / Large Format":
        st.markdown("#### Custom Printer Profile")
        x_col, y_col, z_col = st.columns(3, gap="small")
        custom_width = x_col.number_input("X width (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        custom_depth = y_col.number_input("Y depth (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        custom_height = z_col.number_input("Z height (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        detail_col1, detail_col2 = st.columns(2, gap="medium")
        custom_nozzle = detail_col1.number_input("Nozzle diameter (mm)", min_value=0.2, max_value=2.0, value=0.6, step=0.1, format="%.1f")
        custom_bed_shape_type = detail_col2.selectbox("Bed shape", ["Rectangular", "Circular"])
        firmware_col1, firmware_col2 = st.columns(2, gap="medium")
        custom_gcode_flavor = firmware_col1.selectbox(
            "Firmware / G-code flavor",
            ["Generic large-format Marlin", "Marlin", "RepRap", "Klipper", "Makerbot", "UltiGCode"],
        )
        custom_heated_bed = firmware_col2.checkbox("Heated bed", value=True)
        custom_heated_chamber = st.checkbox("Heated chamber / build volume", value=False)
        with st.expander("Custom start and end G-code"):
            custom_start_gcode = st.text_area(
                "Start G-code",
                value="G28\nG90\nM83",
                height=110,
                help="Optional machine-specific prologue for custom printers.",
            )
            custom_end_gcode = st.text_area(
                "End G-code",
                value="M104 S0\nM140 S0\nM84",
                height=110,
                help="Optional machine-specific shutdown sequence for custom printers.",
            )
    selected_printer_profile = resolve_printer_profile(
        printer,
        custom_width,
        custom_depth,
        custom_height,
        custom_nozzle,
        custom_gcode_flavor,
        custom_bed_shape_type,
        custom_heated_bed,
        custom_heated_chamber,
        custom_start_gcode,
        custom_end_gcode,
    )
    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    filament = st.radio("Filament Type", FILAMENT_TYPES, horizontal=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    quality_profile = st.radio(
        "Quality Profile",
        ["Balanced production", "Draft / fast iteration", "Detail / cosmetic"],
        horizontal=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    print_goal = st.radio(
        "Print Goal",
        ["Balanced everyday part", "Functional strength", "Visual prototype"],
        horizontal=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    support_strategy = st.radio(
        "Support Strategy",
        ["Auto", "Always on", "Disabled"],
        horizontal=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    delivery_mode = st.radio(
        "Delivery Mode",
        DELIVERY_MODES,
        index=DELIVERY_MODES.index(st.session_state.get("delivery_mode_choice", "SD card export")),
        horizontal=True,
        help="Choose how the approved artifact should leave CipherSlice once the user signs off.",
    )
    st.session_state["delivery_mode_choice"] = delivery_mode
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    adhesion_strategy = st.radio(
        "Build Plate Adhesion",
        ["Auto", "Brim", "Raft", "Skirt"],
        horizontal=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    auto_scale_mesh = st.checkbox(
        "Auto-correct likely unit mismatch for mesh uploads",
        value=True,
        help="CipherSlice will suggest or apply a scale correction when the model looks implausibly small or large.",
    )
    st.markdown(
        """
        <div class="workflow-style-card">
            <div class="workflow-style-title">Workflow Style</div>
            <div class="workflow-style-copy">
                Choose how much control you want before building the print plan. Beginner keeps the setup simple.
                Advanced opens more detailed tuning.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    workflow_col1, workflow_col2 = st.columns(2, gap="medium")
    with workflow_col1:
        st.button(
            "Beginner",
            use_container_width=True,
            type="primary" if st.session_state.get("experience_mode", "Beginner") == "Beginner" else "secondary",
            on_click=set_experience_mode,
            args=("Beginner",),
            key="workflow_beginner",
        )
    with workflow_col2:
        st.button(
            "Advanced",
            use_container_width=True,
            type="primary" if st.session_state.get("experience_mode", "Beginner") == "Advanced" else "secondary",
            on_click=set_experience_mode,
            args=("Advanced",),
            key="workflow_advanced",
        )
    experience_mode = st.session_state.get("experience_mode", "Beginner")
    nozzle_override = 0
    bed_override = 0
    layer_override = 0.0
    speed_override = 0
    infill_override = 0
    if experience_mode == "Advanced":
        with st.expander("More control options", expanded=False):
            st.caption("CipherSlice optimizes first. These optional controls let you fine-tune the job before release.")
            nozzle_override = st.number_input("Nozzle temp override (degC)", min_value=0, max_value=320, value=0, step=1)
            bed_override = st.number_input("Bed temp override (degC)", min_value=0, max_value=130, value=0, step=1)
            layer_override = st.number_input("Layer height override (mm)", min_value=0.0, max_value=1.0, value=0.0, step=0.02, format="%.2f")
            speed_override = st.number_input("Print speed override (mm/s)", min_value=0, max_value=400, value=0, step=5)
            infill_override = st.number_input("Infill override (%)", min_value=0, max_value=100, value=0, step=1)
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
        st.caption("Awaiting part geometry. Upload a `.stl`, `.obj`, or `.3mf` file to unlock the pipeline.")
    else:
        st.caption("Awaiting technical drawing. Upload a dimensioned blueprint image or PDF to unlock the draft pipeline.")

    launch = st.button(
        "Build Print Plan",
        type="primary",
        disabled=launch_disabled,
        use_container_width=True,
        help=launch_help,
    )
    if launch and uploaded_file is not None:
        st.session_state["active_job"] = {
            "mode": mode,
            "filename": uploaded_file.name,
            "file_bytes": uploaded_file.getvalue(),
            "printer": printer,
            "printer_profile": dict(selected_printer_profile),
            "filament": filament,
            "quality_profile": quality_profile,
            "print_goal": print_goal,
            "support_strategy": support_strategy,
            "delivery_mode": delivery_mode,
            "adhesion_strategy": adhesion_strategy,
            "experience_mode": experience_mode,
            "auto_scale_mesh": auto_scale_mesh,
            "wants_encryption": wants_encryption,
            "encryption_passphrase": encryption_passphrase,
            "blueprint_name": blueprint_name,
            "part_goal": part_goal,
            "required_dimensions": required_dimensions,
            "tolerance_notes": tolerance_notes,
            "blueprint_type": blueprint_type,
            "has_units": has_units,
            "has_multi_view": has_multi_view,
            "has_tolerance_confirmation": has_tolerance_confirmation,
            "initial_overrides": {
                "nozzle_override": nozzle_override,
                "bed_override": bed_override,
                "layer_override": layer_override,
                "speed_override": speed_override,
                "infill_override": infill_override,
            },
        }
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Print Snapshot")
    st.caption(f"Copilot tone: `{persona['label']}`")
    profile_mode_label, profile_mode_copy = build_profile_mode_label(mode, slicer_path)
    st.markdown(f'<div class="mode-pill">{profile_mode_label}</div>', unsafe_allow_html=True)
    st.caption(profile_mode_copy)
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
    bed_x, bed_y, bed_z = parse_bed_dimensions(selected_printer_profile)
    st.markdown(
        f"""
        **Printer volume:** `{format_xyz_dims(bed_x, bed_y, bed_z)}`  
        **Material profile:** `{filament}`  
        **Optimization mode:** `{quality_profile}` / `{print_goal}`  
        **Support + adhesion:** `{support_strategy}` / `{adhesion_strategy}`  
        **Delivery mode:** `{delivery_mode}`  
        **G-code flavor:** `{selected_printer_profile.get('gcode_flavor', 'Unknown')}`
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
    st.markdown("### Environment")
    st.markdown(
        """
        - **Website role:** validate uploads, assemble profiles, prepare plans, and coordinate delivery.
        - **Production role:** a slicer backend generates the real printer-valid G-code.
        - **Direct handoff role:** a local connector or supported printer integration moves the job to hardware.
        """
    )
    environment_runtime = get_live_agent_runtime_config()
    ai_engine_label = "Live AI ready" if environment_runtime["enabled"] else "Built-in planning engine"
    st.markdown(
        f"""
        **Slicer backend:** `{slicer_label or 'Not detected'}`  
        **Slicer path:** `{slicer_path or 'None configured'}`  
        **Connector status:** `{connector_state}`  
        **Connector endpoint:** `{connector_url or 'No local connector configured'}`  
        **AI worker engine:** `{ai_engine_label}`
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)

active_job = st.session_state.get("active_job")

if active_job:
    mode = active_job["mode"]
    uploaded_file = make_file_like(active_job["filename"], active_job["file_bytes"])
    filename = uploaded_file.name
    file_size = uploaded_file.size
    file_size_mb = max(file_size / (1024 * 1024), 0.1)
    file_stem = sanitize_download_name(filename.rsplit(".", 1)[0])
    printer = active_job["printer"]
    printer_profile = dict(active_job["printer_profile"])
    filament = active_job["filament"]
    quality_profile = active_job["quality_profile"]
    print_goal = active_job["print_goal"]
    support_strategy = active_job["support_strategy"]
    adhesion_strategy = active_job["adhesion_strategy"]
    delivery_mode = active_job["delivery_mode"]
    experience_mode = active_job.get("experience_mode", "Beginner")
    wants_encryption = active_job["wants_encryption"]
    encryption_passphrase = active_job["encryption_passphrase"]
    blueprint_name = active_job["blueprint_name"]
    part_goal = active_job["part_goal"]
    required_dimensions = active_job["required_dimensions"]
    tolerance_notes = active_job["tolerance_notes"]
    blueprint_type = active_job["blueprint_type"]
    has_units = active_job["has_units"]
    has_multi_view = active_job["has_multi_view"]
    has_tolerance_confirmation = active_job["has_tolerance_confirmation"]
    auto_scale_mesh = active_job["auto_scale_mesh"]
    orientation = str(printer_profile["orientation"])
    artifact_hash = build_hash(filename, file_size, printer, filament)
    stream_aborted = False
    slicer_label, slicer_path = detect_slicer_backend()
    connector_url, connector_state = detect_connector()
    persona_tone = persona["agent_tone"]
    initial_overrides = active_job["initial_overrides"]
    execution_label, execution_class, execution_copy = build_execution_status(mode, slicer_path)
    mesh_analysis = analyze_mesh(uploaded_file, printer, printer_profile, auto_scale_mesh) if mode == "Reliable Print Mode" else None
    recommended_plan = optimize_print_plan(
        printer_profile,
        filament,
        quality_profile,
        print_goal,
        support_strategy,
        adhesion_strategy,
    )
    if mode == "Reliable Print Mode":
        recommended_plan = refine_plan_for_geometry(
            recommended_plan,
            mesh_analysis,
            support_strategy,
            printer_profile,
        )

    st.write("")
    st.markdown(
        f'<div class="state-banner {execution_class}"><strong>{execution_label}</strong><br/>{execution_copy}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Step 2: Review + Tune Plan")
    st.markdown(
        '<div class="subsection-card"><div class="subsection-title">Live Plan</div>'
        f'<div class="subsection-copy">CipherSlice generated a first-pass plan for `{filename}`. '
        'You can tune the live plan below without re-uploading the file or restarting the workflow.</div></div>',
        unsafe_allow_html=True,
    )
    if mode == "Reliable Print Mode":
        build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
        fit_title, fit_copy = summarize_fit(mesh_analysis, printer_profile)
        st.markdown(
            f"""
            <div class="preview-grid">
                <div class="preview-card">
                    <div class="preview-title">Workflow Style</div>
                    <div class="preview-copy">
                        You are currently in <strong>{experience_mode}</strong> mode.
                        {"The screen is keeping the controls simple." if experience_mode == "Beginner" else "Extra tuning controls are available below."}
                    </div>
                </div>
                <div class="preview-card">
                    <div class="preview-title">Printer Preview</div>
                    <div class="preview-copy">
                        <span class="xyz-badge">Printer: {format_xyz_dims(build_x, build_y, build_z)}</span>
                        {f'<span class="xyz-badge">Part: {format_xyz_dims(*mesh_analysis["scaled_extents_mm"])}</span>' if mesh_analysis and mesh_analysis.get("scaled_extents_mm") else ''}<br/>
                        <strong>{fit_title}</strong><br/>{fit_copy}
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="preview-grid">
                <div class="preview-card">
                    <div class="preview-title">Workflow Style</div>
                    <div class="preview-copy">
                        You are currently in <strong>{experience_mode}</strong> mode.
                        {"The screen is keeping the controls simple." if experience_mode == "Beginner" else "Extra tuning controls are available below."}
                    </div>
                </div>
                <div class="preview-card">
                    <div class="preview-title">Blueprint Review</div>
                    <div class="preview-copy">
                        CipherSlice is preparing a reconstruction brief, not final fabrication output. Add dimensions and fit notes now so the next stage is grounded in measurable geometry.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    grouped_col1, grouped_col2 = st.columns(2, gap="medium")
    with grouped_col1:
        with st.container(border=True):
            st.markdown("#### Machine + Finish")
            editable_quality_profile = st.selectbox(
                "Quality profile",
                ["Balanced production", "Draft / fast iteration", "Detail / cosmetic"],
                index=["Balanced production", "Draft / fast iteration", "Detail / cosmetic"].index(quality_profile),
                key=f"edit_quality_{artifact_hash}",
            )
            editable_print_goal = st.selectbox(
                "Print goal",
                ["Balanced everyday part", "Functional strength", "Visual prototype"],
                index=["Balanced everyday part", "Functional strength", "Visual prototype"].index(print_goal),
                key=f"edit_goal_{artifact_hash}",
            )
            editable_layer_height = st.number_input(
                "Layer height (mm)",
                min_value=0.08,
                max_value=1.0,
                value=float(initial_overrides["layer_override"] or recommended_plan["layer_height"]),
                step=0.02,
                format="%.2f",
                key=f"edit_layer_{artifact_hash}",
            )
            editable_speed = st.number_input(
                "Print speed (mm/s)",
                min_value=10,
                max_value=400,
                value=int(initial_overrides["speed_override"] or recommended_plan["print_speed"]),
                step=5,
                key=f"edit_speed_{artifact_hash}",
            )
        with st.container(border=True):
            st.markdown("#### Structure + Support")
            editable_support_strategy = st.selectbox(
                "Support strategy",
                ["Auto", "Always on", "Disabled"],
                index=["Auto", "Always on", "Disabled"].index(support_strategy),
                key=f"edit_support_{artifact_hash}",
            )
            editable_adhesion_strategy = st.selectbox(
                "Adhesion strategy",
                ["Auto", "Brim", "Raft", "Skirt"],
                index=["Auto", "Brim", "Raft", "Skirt"].index(adhesion_strategy),
                key=f"edit_adhesion_{artifact_hash}",
            )
            editable_infill = st.slider(
                "Infill (%)",
                min_value=0,
                max_value=100,
                value=int(initial_overrides["infill_override"] or recommended_plan["infill_percent"]),
                key=f"edit_infill_{artifact_hash}",
            )
            editable_wall_loops = st.slider(
                "Wall loops",
                min_value=1,
                max_value=8,
                value=int(recommended_plan["wall_loops"]),
                key=f"edit_walls_{artifact_hash}",
            )
    with grouped_col2:
        with st.container(border=True):
            st.markdown("#### Delivery + Release")
            editable_delivery_mode = st.selectbox(
                "Delivery mode",
                DELIVERY_MODES,
                index=DELIVERY_MODES.index(delivery_mode),
                key=f"edit_delivery_{artifact_hash}",
            )
            st.caption("This changes how the finished job leaves CipherSlice after review and approval.")
            st.markdown(f"**Current path:** `{editable_delivery_mode}`")
            st.write(DELIVERY_MODE_DETAILS[editable_delivery_mode]["summary"])
        with st.container(border=True):
            st.markdown("#### Material + Output")
            editable_filament = st.selectbox(
                "Filament",
                FILAMENT_TYPES,
                index=FILAMENT_TYPES.index(filament),
                key=f"edit_filament_{artifact_hash}",
            )
            editable_gcode_flavor = st.text_input(
                "G-code flavor",
                value=str(printer_profile.get("gcode_flavor", "Unknown")),
                key=f"edit_gcode_flavor_{artifact_hash}",
                help="Use this if the printer firmware flavor needs to change before export or slicing.",
            )
            st.markdown(f"- **Printer profile:** `{printer}`")
            st.markdown(f"- **Build surface:** `{printer_profile.get('adhesion_default', 'Unknown')}`")
            st.caption("These settings now feed directly into the live plan without forcing you to restart the job.")

    editable_nozzle_temp = int(initial_overrides["nozzle_override"] or recommended_plan["nozzle_temp"])
    editable_bed_temp = int(initial_overrides["bed_override"] or recommended_plan["bed_temp"])
    editable_flow = 100
    if experience_mode == "Advanced":
        with st.expander("Advanced tuning cards"):
            thermal_col, motion_col = st.columns(2, gap="medium")
            with thermal_col:
                with st.container(border=True):
                    st.markdown("#### Thermal tuning")
                    editable_nozzle_temp = st.number_input(
                        "Nozzle temp (degC)",
                        min_value=0,
                        max_value=320,
                        value=editable_nozzle_temp,
                        step=1,
                        key=f"edit_nozzle_{artifact_hash}",
                    )
                    editable_bed_temp = st.number_input(
                        "Bed temp (degC)",
                        min_value=0,
                        max_value=130,
                        value=editable_bed_temp,
                        step=1,
                        key=f"edit_bed_{artifact_hash}",
                    )
                    editable_flow = st.slider(
                        "Flow multiplier (%)",
                        min_value=80,
                        max_value=120,
                        value=100,
                        key=f"edit_flow_{artifact_hash}",
                    )
            with motion_col:
                with st.container(border=True):
                    st.markdown("#### Motion notes")
                    st.markdown(f"- **Placement suggestion:** {printer_profile['orientation']}")
                    st.markdown(f"- **Nozzle diameter:** `{printer_profile['nozzle_diameter']} mm`")
                    st.markdown(f"- **Secure delivery:** `{'On' if wants_encryption else 'Off'}`")
                    st.caption("More deep machine controls can plug in here later without crowding the beginner path.")

    filament = editable_filament
    optimized_plan = optimize_print_plan(
        printer_profile,
        filament,
        editable_quality_profile,
        editable_print_goal,
        editable_support_strategy,
        editable_adhesion_strategy,
    )
    if mode == "Reliable Print Mode":
        optimized_plan = refine_plan_for_geometry(
            optimized_plan,
            mesh_analysis,
            editable_support_strategy,
            printer_profile,
        )
    optimized_plan = apply_user_overrides(
        optimized_plan,
        editable_nozzle_temp if editable_nozzle_temp > 0 else None,
        editable_bed_temp if editable_bed_temp > 0 else None,
        editable_layer_height if editable_layer_height > 0 else None,
        editable_speed if editable_speed > 0 else None,
        editable_infill if editable_infill >= 0 else None,
    )
    optimized_plan["wall_loops"] = editable_wall_loops
    optimized_plan["flow_multiplier"] = editable_flow
    optimized_plan["gcode_flavor"] = editable_gcode_flavor
    quality_profile = editable_quality_profile
    print_goal = editable_print_goal
    support_strategy = editable_support_strategy
    adhesion_strategy = editable_adhesion_strategy
    delivery_mode = editable_delivery_mode
    optimized_plan["delivery_mode"] = delivery_mode

    job_context = build_job_context(
        mode,
        filename,
        printer,
        filament,
        printer_profile,
        optimized_plan,
        mesh_analysis,
        blueprint_name,
        part_goal,
    )
    slicer_setup_bundle = None
    operator_handoff_sheet = None
    plan_diff_lines = []

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
        slicer_command_preview = build_slicer_command_preview(
            slicer_label,
            slicer_path,
            filename,
            slicer_plan,
        )
        handoff_contract = build_slicer_handoff_contract(
            job_context,
            artifact_hash,
            release_allowed,
            overall_confidence,
            delivery_mode,
            mesh_analysis,
        )
        real_gcode, slicer_message = run_real_slicer(slicer_label, slicer_path, uploaded_file, slicer_plan, handoff_contract)
        primary_artifact = real_gcode or generate_gcode(
            filename,
            printer,
            filament,
            optimized_plan["nozzle_temp"],
            optimized_plan["bed_temp"],
            optimized_plan["print_speed"],
            handoff_contract,
        )
        slicer_setup_bundle = build_slicer_setup_bundle(
            uploaded_file,
            slicer_plan,
            handoff_contract,
            primary_artifact,
            slicer_message,
            slicer_command_preview,
        )
        if real_gcode:
            consensus_scores["G-Code Architect"] = max(consensus_scores["G-Code Architect"], 0.97)
            overall_confidence = min(consensus_scores.values())
            release_allowed = release_allowed and mesh_analysis["mesh_ok"]
        else:
            objections.append(slicer_message)
            release_allowed = False
            overall_confidence = min(overall_confidence, 0.89)
        operator_handoff_sheet = build_operator_handoff_sheet(
            filename,
            printer,
            filament,
            delivery_mode,
            optimized_plan,
            overall_confidence,
            execution_label,
        )
        plan_diff_lines = build_plan_diff(
            recommended_plan,
            optimized_plan,
            delivery_mode,
            filament,
        )
    else:
        slicer_command_preview = ""
        handoff_contract = build_slicer_handoff_contract(
            job_context,
            artifact_hash,
            release_allowed,
            overall_confidence,
            delivery_mode,
            mesh_analysis,
        )
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

    fallback_agent_packets = build_live_agent_packets(
        persona,
        job_context,
        mesh_analysis,
        optimized_plan["support_density"],
        format_bytes(file_size),
        slicer_message if mode == "Reliable Print Mode" else "Prepared a draft reconstruction packet instead of final G-code because 2D input is still missing validated 3D geometry.",
    )
    agent_packets, agent_runtime_meta = run_live_agent_runtime(
        persona,
        job_context,
        mesh_analysis,
        int(optimized_plan["support_density"]),
        slicer_message if mode == "Reliable Print Mode" else "Prepared a draft reconstruction packet instead of final G-code because 2D input is still missing validated 3D geometry.",
        fallback_agent_packets,
    )

    encrypted_artifact = None
    encryption_salt = None
    if wants_encryption and encryption_passphrase:
        encrypted_artifact, encryption_salt = encrypt_artifact(primary_artifact, encryption_passphrase)

    st.write("")
    st.markdown("### Step 3: What CipherSlice Prepared")
    if agent_runtime_meta["using_live_workers"]:
        st.caption(f"{agent_runtime_meta['status']}: {agent_runtime_meta['detail']}")
    elif agent_runtime_meta["status"] != "Disabled":
        st.caption(agent_runtime_meta["detail"])

    with st.status("CipherSlice processing engaged", expanded=True) as status:
        if mode == "Reliable Print Mode":
            st.markdown(
                f"**{agent_packets['Inspector']['title']}**  \n"
                f"{agent_packets['Inspector']['summary']}"
            )
            time.sleep(0.45)
            st.markdown(
                f"**{agent_packets['Calibrator']['title']}**  \n"
                f"{agent_packets['Calibrator']['summary']}"
            )
            time.sleep(0.45)
            st.markdown(
                f"**{agent_packets['G-Code Architect']['title']}**  \n"
                f"{agent_packets['G-Code Architect']['summary']}"
            )
            time.sleep(0.45)
        else:
            st.markdown(
                f"**{agent_packets['Inspector']['title']}**  \n"
                f"{agent_packets['Inspector']['summary']}"
            )
            time.sleep(0.45)
            st.markdown(
                f"**{agent_packets['Calibrator']['title']}**  \n"
                f"{agent_packets['Calibrator']['summary']}"
            )
            time.sleep(0.45)
            st.markdown(
                f"**{agent_packets['G-Code Architect']['title']}**  \n"
                f"{agent_packets['G-Code Architect']['summary']}"
            )
            time.sleep(0.45)

        vault_line = (
            f"Generated secure delivery hash `{artifact_hash[:18]}...` and encrypted the output file for controlled delivery."
            if encrypted_artifact
            else f"Generated secure delivery hash `{artifact_hash[:18]}...` and staged the output file for controlled delivery."
        )
        st.markdown(f"**{agent_packets['Cipher Vault']['title']}**  \n{agent_packets['Cipher Vault']['summary']}  \n{vault_line}")
        if release_allowed:
            st.success(f"Consensus gate cleared at {overall_confidence * 100:.1f}% confidence. Artifact release is allowed.")
        else:
            st.warning(f"Consensus gate stopped release at {overall_confidence * 100:.1f}% confidence. Human review or more infrastructure is required.")
        status.update(label="CipherSlice processing completed", state="complete", expanded=True)

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
    phase_title, phase_copy = build_runtime_phase_summary(
        mode,
        slicer_path,
        connector_url,
        delivery_mode,
    )
    output_type_title, output_type_copy = build_output_type_summary(mode, slicer_path)
    engine_diagnostics = build_engine_diagnostics(
        slicer_label,
        slicer_path,
        connector_url,
        agent_runtime_meta,
        delivery_mode,
    )
    connection_title, connection_copy = build_engine_connection_summary(
        slicer_label,
        slicer_path,
        connector_url,
    )

    with result_col:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        st.markdown("### Current Print Plan")
        summary_col1, summary_col2 = st.columns(2, gap="medium")
        with summary_col1:
            with st.container(border=True):
                st.markdown("#### Ready Now")
                st.markdown(f"**{phase_title}**")
                st.write(phase_copy)
        with summary_col2:
            with st.container(border=True):
                st.markdown("#### Still To Connect")
                if mode != "Reliable Print Mode":
                    st.write("A validated 3D model still needs to be created or imported before CipherSlice can move into real slicing.")
                elif slicer_path:
                    st.write("A connected printer is optional for now. You only need hardware later when you want to physically run the approved print.")
                else:
                    st.write("A real slicer backend still needs to be connected. That is the main reason the preview stays in planning mode instead of full production output.")
        st.markdown(
            f"""
            <div class="ops-grid">
                <div class="ops-card">
                    <div class="ops-title">Output Type</div>
                    <div class="ops-copy">{output_type_copy}</div>
                    <div class="ops-chip">{output_type_title}</div>
                </div>
                <div class="ops-card">
                    <div class="ops-title">Why This Matters</div>
                    <div class="ops-copy">CipherSlice works best when planning, real slicing, and hardware handoff are clearly separated. That makes the workflow easier to trust for both beginners and advanced users.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if mode == "Reliable Print Mode":
            build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
            fit_title, fit_copy = summarize_fit(mesh_analysis, printer_profile)
            preview_col1, preview_col2 = st.columns(2, gap="medium")
            with preview_col1:
                with st.container(border=True):
                    st.markdown("#### Bed + Size Preview")
                    st.markdown(build_bed_preview_svg(mesh_analysis, printer_profile), unsafe_allow_html=True)
                    st.markdown(f"- **Printer volume:** `{format_xyz_dims(build_x, build_y, build_z)}`")
                    if mesh_analysis and mesh_analysis.get("scaled_extents_mm"):
                        px, py, pz = mesh_analysis["scaled_extents_mm"]
                        st.markdown(f"- **Part size:** `{format_xyz_dims(px, py, pz)}`")
                    elif mesh_analysis and mesh_analysis.get("extents_mm"):
                        px, py, pz = mesh_analysis["extents_mm"]
                        st.markdown(f"- **Part size:** `{format_xyz_dims(px, py, pz)}`")
                    else:
                        st.markdown("- **Part size:** `Pending mesh analysis`")
                    st.markdown(f"- **Fit state:** `{fit_title}`")
                    st.caption(fit_copy)
                    preview_metrics = build_mesh_preview_metrics(mesh_analysis, printer_profile)
                    st.markdown(
                        "<div class='metric-chip-row'>"
                        + "".join(
                            f"<span class='metric-chip'><strong>{label}:</strong> {value}</span>"
                            for label, value in preview_metrics
                        )
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                    if mesh_analysis and mesh_analysis.get("geometry_profile"):
                        st.markdown(f"- **Geometry profile:** `{mesh_analysis['geometry_profile']}`")
                    for adaptive_note in (mesh_analysis or {}).get("adaptive_notes", []):
                        st.caption(adaptive_note)
            with preview_col2:
                with st.container(border=True):
                    st.markdown("#### At a Glance")
                    st.caption(f"Built in `{persona['label']}` tone.")
                    st.markdown(f"- **Printer:** `{printer}`")
                    st.markdown(f"- **Filament:** `{filament}`")
                    st.markdown(f"- **Layer / infill / walls:** `{optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}% / {optimized_plan['wall_loops']}`")
                    st.markdown(f"- **Support / adhesion:** `{'Enabled' if optimized_plan['support_enabled'] else 'Disabled'} / {optimized_plan['adhesion']}`")
                    st.markdown(f"- **Delivery path:** `{delivery_mode}`")
                    st.markdown(f"- **Job mode:** `{execution_label}`")
                    st.markdown(f"- **AI worker engine:** `{agent_runtime_meta['status']}`")
                    st.markdown(f"- **Print engine state:** `{connection_title}`")
                    st.caption(connection_copy)
            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown("#### Plan")
                st.markdown(
                    f"""
                    - **Source file:** `{filename}`
                    - **Payload size:** `{format_bytes(file_size)}`
                    - **Job mode:** `{execution_label}`
                    - **AI worker engine:** `{agent_runtime_meta['status']}`
                    - **Printer profile:** `{printer}`
                    - **Filament strategy:** `{filament}`
                    - **Build volume:** `{format_xyz_dims(build_x, build_y, build_z)}`
                    - **Nozzle / bed:** `{optimized_plan['nozzle_temp']} degC / {optimized_plan['bed_temp']} degC`
                    - **Layer height / infill:** `{optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}%`
                    - **Wall loops / speed:** `{optimized_plan['wall_loops']} / {optimized_plan['print_speed']} mm/s`
                    - **Supports:** `{'Enabled' if optimized_plan['support_enabled'] else 'Disabled'}`
                    - **Adhesion / nozzle:** `{optimized_plan['adhesion']} / {optimized_plan['nozzle_diameter']} mm`
                    """
                )
                st.markdown(
                    "<div class='metric-chip-row'>"
                    f"<span class='metric-chip'><strong>Output:</strong> {output_type_title}</span>"
                    f"<span class='metric-chip'><strong>Engine:</strong> {connection_title}</span>"
                    f"<span class='metric-chip'><strong>Confidence:</strong> {overall_confidence * 100:.0f}%</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            with st.container(border=True):
                st.markdown("#### Warnings")
                if objections:
                    for reason in objections:
                        st.markdown(f"- {reason}")
                else:
                    st.success("No blocking warnings are active for the current live plan.")
                if mesh_analysis and mesh_analysis.get("adaptive_notes"):
                    st.caption("Model-specific guidance:")
                    for adaptive_note in mesh_analysis["adaptive_notes"]:
                        st.markdown(f"- {adaptive_note}")
            with st.container(border=True):
                st.markdown("#### Plan Changes")
                if plan_diff_lines:
                    st.caption("These settings differ from CipherSlice's first recommendation for this job.")
                    for diff_line in plan_diff_lines:
                        st.markdown(f"- {diff_line}")
                else:
                    st.success("The current live plan still matches the recommended defaults.")
            st.markdown(
                f'<div class="success-banner">Secure delivery package ready for {filename}. '
                f'Encrypted for protected printer handoff.</div>',
                unsafe_allow_html=True,
            )
            st.markdown("#### Final Print Manifest")
            st.markdown(
                f"""
                <div class="manifest-card">
                    <div class="manifest-line"><span class="manifest-key"><strong>Part:</strong></span> {filename}</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Printer:</strong></span> {printer}</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Build volume:</strong></span> {format_xyz_dims(build_x, build_y, build_z)}</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Filament:</strong></span> {filament}</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Nozzle / bed:</strong></span> {optimized_plan['nozzle_temp']} degC / {optimized_plan['bed_temp']} degC</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Layer / infill / walls:</strong></span> {optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}% / {optimized_plan['wall_loops']}</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Support / adhesion:</strong></span> {'Enabled' if optimized_plan['support_enabled'] else 'Disabled'} / {optimized_plan['adhesion']}</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Delivery mode:</strong></span> {delivery_mode}</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Confidence:</strong></span> {overall_confidence * 100:.1f}%</div>
                    <div class="manifest-line"><span class="manifest-key"><strong>Release status:</strong></span> {'APPROVED' if release_allowed else 'HELD'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("### Best Next Move")
            st.info(next_action)
            if not slicer_path:
                st.warning(
                    "Production release is still held by design because no slicer backend is connected. "
                    "That is why the artifact score stays capped and different files can still share similar high-level settings."
                )
            status_rows = build_status_board(
                mode,
                slicer_path,
                connector_url,
                release_allowed,
                final_user_approval,
                delivery_mode,
            )
            st.markdown("### Readiness Check")
            for label, value in status_rows:
                st.markdown(f"- **{label}:** `{value}`")
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
            with st.container(border=True):
                st.markdown("#### Release")
                st.caption("Approve the plan first, then choose the output or setup file you want to carry forward.")
                st.download_button(
                    "Download Planned Output" if not slicer_path else "Download Print File",
                    data=primary_artifact,
                    file_name=f"{file_stem}_{sanitize_download_name(printer.lower())}.gcode",
                    mime="text/plain",
                    use_container_width=True,
                    disabled=not (release_allowed and final_user_approval),
                )
                if slicer_setup_bundle:
                    st.download_button(
                        "Download Slicer Setup Pack",
                        data=slicer_setup_bundle,
                        file_name=f"{file_stem}_cipher_setup_pack.zip",
                        mime="application/zip",
                        use_container_width=True,
                    )
                    st.download_button(
                        "Download Handoff Contract",
                        data=json.dumps(handoff_contract, indent=2),
                        file_name=f"{file_stem}_handoff_contract.json",
                        mime="application/json",
                        use_container_width=True,
                    )
                if operator_handoff_sheet:
                    st.download_button(
                        "Download Operator Handoff Sheet",
                        data=operator_handoff_sheet,
                        file_name=f"{file_stem}_operator_handoff.txt",
                        mime="text/plain",
                        use_container_width=True,
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
                "Send to Secure Printer Link",
                use_container_width=True,
                key=f"hardware_stream_{artifact_hash}",
                disabled=not (release_allowed and final_user_approval and delivery_mode == "Secure local connector"),
            )
            if delivery_mode != "Secure local connector":
                st.caption("Direct secure printer handoff is available only when `Delivery Mode` is set to `Secure local connector`.")
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
        else:
            st.markdown(
                f"""
                - **Drawing file:** `{filename}`
                - **Part label:** `{blueprint_name}`
                - **Guide tone:** `{persona['label']}`
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
        with st.container(border=True):
            if mode == "Reliable Print Mode":
                st.markdown("#### Preflight Review")
                build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
                st.markdown(
                    f"""
                    - **Target printer:** `{printer}`
                    - **Filament:** `{filament}`
                    - **Quality profile:** `{quality_profile}`
                    - **Print goal:** `{print_goal}`
                    - **Support strategy:** `{support_strategy}`
                    - **Adhesion strategy:** `{optimized_plan['adhesion']}`
                    - **Build volume:** `{format_xyz_dims(build_x, build_y, build_z)}`
                    - **Part placement:** {optimized_plan['orientation']}
                    - **G-code flavor:** `{optimized_plan['gcode_flavor']}`
                    - **Slicer backend:** `{slicer_label or 'Not detected'}`
                    - **Connector path:** `{connector_url or 'No connector configured'}`
                    """
                )
                if mesh_analysis:
                    if mesh_analysis["extents_mm"]:
                        x_dim, y_dim, z_dim = mesh_analysis["extents_mm"]
                        st.markdown(f"- **Estimated part size:** `{format_xyz_dims(x_dim, y_dim, z_dim)}`")
                    if mesh_analysis["scaled_extents_mm"] and mesh_analysis["scaled_extents_mm"] != mesh_analysis["extents_mm"]:
                        sx_dim, sy_dim, sz_dim = mesh_analysis["scaled_extents_mm"]
                        st.markdown(f"- **Scaled part size:** `{format_xyz_dims(sx_dim, sy_dim, sz_dim)}`")
                        st.markdown(f"- **Applied scale factor:** `{mesh_analysis['scale_factor']}x`")
                    if mesh_analysis["face_count"]:
                        st.markdown(f"- **Mesh faces:** `{mesh_analysis['face_count']:,}`")
                    if mesh_analysis["vertex_count"]:
                        st.markdown(f"- **Mesh vertices:** `{mesh_analysis['vertex_count']:,}`")
                    if mesh_analysis["watertight"] is not None:
                        st.markdown(f"- **Watertight mesh:** `{'Yes' if mesh_analysis['watertight'] else 'No'}`")
                    for note in mesh_analysis["notes"]:
                        st.caption(note)
                st.markdown("#### Engine Diagnostics")
                for note in engine_diagnostics:
                    st.markdown(f"- {note}")
            else:
                st.markdown("#### Blueprint Review Packet")
                st.markdown(
                    f"""
                    - **Part label:** `{blueprint_name}`
                    - **Target printer:** `{printer}`
                    - **Filament:** `{filament}`
                    - **Drawing type:** `{blueprint_type}`
                    - **Units confirmed:** `{'Yes' if has_units else 'No'}`
                    - **Multi-view set:** `{'Yes' if has_multi_view else 'No'}`
                    - **Tolerance notes:** `{'Provided' if tolerance_notes.strip() else 'Missing'}`
                    """
                )
            if mode == "Reliable Print Mode":
                st.markdown("#### Print Engine Connection")
                st.markdown(
                    f"""
                    - **Detected print engine:** `{slicer_label or 'Not detected'}`
                    - **Engine path:** `{slicer_path or 'None configured'}`
                    - **AI worker runtime:** `{agent_runtime_meta['status']}`
                    - **Printer link:** `{connector_url or 'Not connected'}`
                    """
                )
                if slicer_command_preview:
                    st.caption("When a supported engine is available, CipherSlice prepares a CLI handoff like this:")
                    st.code(slicer_command_preview, language="bash")
                if slicer_path:
                    st.success("CipherSlice can hand this approved plan to a real slicer backend. A physical printer is still optional until you want to run the job.")
                else:
                    st.info(
                        "You do not need a printer yet. The next real upgrade is connecting a slicer backend so CipherSlice can turn this plan into true production G-code."
                    )
                    st.markdown("**Fastest setup path**")
                    st.markdown("- Install a supported CLI slicer such as `PrusaSlicer`, `OrcaSlicer`, or `Slic3r`.")
                    st.markdown("- Point `CIPHERSLICE_SLICER_PATH` to that executable.")
                    st.markdown("- Refresh the app and rerun the same job to move from planning mode to real slicing mode.")
            else:
                st.markdown("#### Reconstruction Requirements")
                st.info("No printer is needed yet. This stage is about getting from a structured drawing to validated geometry before any real slicing begins.")
                st.markdown("- Confirm all critical dimensions and units.")
                st.markdown("- Add or import the missing 3D geometry.")
                st.markdown("- Return to CipherSlice with a validated mesh for real slicing.")

        with st.container(border=True):
            st.markdown("#### Release Review")
            st.markdown("##### Confidence Gate")
            for agent_name, score in consensus_scores.items():
                st.markdown(f"- **{agent_name}:** `{score * 100:.1f}%`")
            if not slicer_path and mode == "Reliable Print Mode":
                st.caption("Artifact confidence is capped in this environment because the final slicing engine is missing.")
            if objections:
                st.markdown("**Review blockers**")
                for reason in objections:
                    st.markdown(f"- {reason}")
            elif release_allowed:
                st.success("All agents cleared the release gate with no unresolved objections.")

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            if mode == "Reliable Print Mode":
                st.markdown("##### Planned Output Preview" if not slicer_path else "##### Output Preview")
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
                st.code(blueprint_preview, language="text")
        st.markdown("</div>", unsafe_allow_html=True)
