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
import streamlit.components.v1 as components
import numpy as np

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
        "family": "Bambu Lab X1 series",
        "printer_note": "Fast enclosed core-XY printer. Great for polished PLA, PETG, and stronger engineering workflows when the material profile is dialed in.",
        "bed_shape": "256 x 256 mm",
        "max_height_mm": 256,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin / Bambu",
        "nozzle": {"PLA": 220, "PETG": 250, "ABS": 255, "ASA": 260, "TPU": 228, "Nylon": 270, "PC": 275, "CF Nylon": 280},
        "bed": {"PLA": 60, "PETG": 78, "ABS": 95, "ASA": 95, "TPU": 45, "Nylon": 90, "PC": 110, "CF Nylon": 85},
        "speed": {"PLA": 220, "PETG": 150, "ABS": 120, "ASA": 115, "TPU": 60, "Nylon": 75, "PC": 65, "CF Nylon": 70},
        "orientation": "Tilt 32 degrees rearward to reduce support contact on cosmetic faces.",
    },
    "Bambu P1S": {
        "family": "Bambu Lab P1 series",
        "printer_note": "Fast enclosed Bambu option with strong everyday throughput and better support for warmer materials than open-frame machines.",
        "bed_shape": "256 x 256 mm",
        "max_height_mm": 256,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin / Bambu",
        "nozzle": {"PLA": 220, "PETG": 248, "ABS": 255, "ASA": 258, "TPU": 228, "Nylon": 268, "PC": 272, "CF Nylon": 278},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 95, "ASA": 95, "TPU": 45, "Nylon": 90, "PC": 108, "CF Nylon": 85},
        "speed": {"PLA": 210, "PETG": 145, "ABS": 115, "ASA": 110, "TPU": 55, "Nylon": 70, "PC": 62, "CF Nylon": 68},
        "orientation": "Favor a broad, stable base and keep outer faces angled away from heavy support zones.",
    },
    "Bambu P1P": {
        "family": "Bambu Lab P1 series",
        "printer_note": "Fast open-frame Bambu variant. Excellent for PLA and PETG, but more limited for enclosure-hungry materials like ABS and ASA.",
        "bed_shape": "256 x 256 mm",
        "max_height_mm": 256,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin / Bambu",
        "nozzle": {"PLA": 220, "PETG": 245, "ABS": 250, "ASA": 252, "TPU": 228, "Nylon": 265, "PC": 270, "CF Nylon": 275},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 95, "ASA": 95, "TPU": 45, "Nylon": 88, "PC": 105, "CF Nylon": 82},
        "speed": {"PLA": 210, "PETG": 140, "ABS": 105, "ASA": 100, "TPU": 50, "Nylon": 65, "PC": 58, "CF Nylon": 62},
        "orientation": "Use broad contact patches and avoid tall exposed ABS or ASA jobs unless the environment is temperature-stable.",
    },
    "Bambu A1": {
        "family": "Bambu Lab A1 series",
        "printer_note": "Beginner-friendly bedslinger. Strong everyday PLA and PETG choice with simple setup and good community familiarity.",
        "bed_shape": "256 x 256 mm",
        "max_height_mm": 256,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin / Bambu",
        "nozzle": {"PLA": 220, "PETG": 245, "ABS": 250, "ASA": 252, "TPU": 225, "Nylon": 260, "PC": 265, "CF Nylon": 270},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 95, "ASA": 95, "TPU": 45, "Nylon": 85, "PC": 100, "CF Nylon": 80},
        "speed": {"PLA": 160, "PETG": 105, "ABS": 85, "ASA": 82, "TPU": 42, "Nylon": 55, "PC": 48, "CF Nylon": 52},
        "orientation": "Keep taller parts centered and prefer strong first-layer grip over aggressive speed on thin jobs.",
    },
    "Bambu A1 Mini": {
        "family": "Bambu Lab A1 series",
        "printer_note": "Compact beginner-friendly machine. Best for smaller PLA and PETG parts where reliability matters more than large build volume.",
        "bed_shape": "180 x 180 mm",
        "max_height_mm": 180,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin / Bambu",
        "nozzle": {"PLA": 220, "PETG": 245, "ABS": 248, "ASA": 250, "TPU": 225, "Nylon": 258, "PC": 262, "CF Nylon": 268},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 95, "ASA": 95, "TPU": 45, "Nylon": 85, "PC": 100, "CF Nylon": 80},
        "speed": {"PLA": 150, "PETG": 95, "ABS": 80, "ASA": 78, "TPU": 40, "Nylon": 50, "PC": 45, "CF Nylon": 48},
        "orientation": "Use compact, centered placement and watch for oversized parts that spill beyond the smaller bed.",
    },
    "Prusa MK4": {
        "family": "Prusa MK series",
        "printer_note": "Well-balanced open-frame workhorse. Strong for dependable PLA and PETG jobs with very readable slicer behavior.",
        "bed_shape": "250 x 210 mm",
        "max_height_mm": 220,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Smooth PEI",
        "gcode_flavor": "Marlin / Prusa",
        "nozzle": {"PLA": 215, "PETG": 245, "ABS": 255, "ASA": 258, "TPU": 225, "Nylon": 265, "PC": 270, "CF Nylon": 275},
        "bed": {"PLA": 60, "PETG": 85, "ABS": 100, "ASA": 100, "TPU": 45, "Nylon": 90, "PC": 108, "CF Nylon": 85},
        "speed": {"PLA": 145, "PETG": 95, "ABS": 85, "ASA": 82, "TPU": 38, "Nylon": 55, "PC": 50, "CF Nylon": 52},
        "orientation": "Lay the broadest face down and yaw 18 degrees to minimize seam visibility.",
    },
    "Prusa XL": {
        "family": "Prusa XL series",
        "printer_note": "Large-format Prusa option. Excellent when you need more bed area while keeping familiar slicer behavior and controlled motion.",
        "bed_shape": "360 x 360 mm",
        "max_height_mm": 360,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured / satin PEI",
        "gcode_flavor": "Marlin / Prusa",
        "nozzle": {"PLA": 215, "PETG": 245, "ABS": 255, "ASA": 260, "TPU": 225, "Nylon": 268, "PC": 272, "CF Nylon": 278},
        "bed": {"PLA": 60, "PETG": 85, "ABS": 100, "ASA": 100, "TPU": 45, "Nylon": 90, "PC": 110, "CF Nylon": 88},
        "speed": {"PLA": 135, "PETG": 90, "ABS": 82, "ASA": 80, "TPU": 35, "Nylon": 55, "PC": 48, "CF Nylon": 52},
        "orientation": "Use the extra bed area to bias toward stable first layers and shorter support towers on larger parts.",
    },
    "Creality K1 Max": {
        "family": "Creality K1 series",
        "printer_note": "Large fast enclosed Creality machine. Useful for roomy prototypes and long parts when tuned carefully.",
        "bed_shape": "300 x 300 mm",
        "max_height_mm": 300,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Marlin",
        "nozzle": {"PLA": 225, "PETG": 248, "ABS": 260, "ASA": 262, "TPU": 230, "Nylon": 270, "PC": 275, "CF Nylon": 280},
        "bed": {"PLA": 58, "PETG": 80, "ABS": 105, "ASA": 105, "TPU": 45, "Nylon": 92, "PC": 110, "CF Nylon": 88},
        "speed": {"PLA": 250, "PETG": 140, "ABS": 130, "ASA": 125, "TPU": 55, "Nylon": 70, "PC": 62, "CF Nylon": 68},
        "orientation": "Rotate 45 degrees on the build plate so long spans bridge across the X-axis.",
    },
    "Creality Ender 3 V3 KE": {
        "family": "Creality Ender series",
        "printer_note": "Accessible everyday Creality bedslinger. Best for beginner PLA and PETG work with moderate speeds and careful setup.",
        "bed_shape": "220 x 220 mm",
        "max_height_mm": 240,
        "nozzle_diameter": 0.4,
        "adhesion_default": "PEI spring steel",
        "gcode_flavor": "Marlin",
        "nozzle": {"PLA": 215, "PETG": 240, "ABS": 250, "ASA": 252, "TPU": 223, "Nylon": 255, "PC": 260, "CF Nylon": 265},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 100, "ASA": 100, "TPU": 45, "Nylon": 85, "PC": 100, "CF Nylon": 80},
        "speed": {"PLA": 120, "PETG": 80, "ABS": 65, "ASA": 62, "TPU": 30, "Nylon": 45, "PC": 40, "CF Nylon": 42},
        "orientation": "Favor wide first layers and avoid very tall unsupported parts at aggressive speeds.",
    },
    "Anycubic Kobra 2 Max": {
        "family": "Anycubic Kobra series",
        "printer_note": "Very large bedslinger. Useful for oversized prototypes, but large-bed adhesion and motion stability matter a lot.",
        "bed_shape": "420 x 420 mm",
        "max_height_mm": 500,
        "nozzle_diameter": 0.4,
        "adhesion_default": "PEI-coated spring steel",
        "gcode_flavor": "Marlin",
        "nozzle": {"PLA": 220, "PETG": 245, "ABS": 255, "ASA": 258, "TPU": 225, "Nylon": 265, "PC": 270, "CF Nylon": 275},
        "bed": {"PLA": 60, "PETG": 80, "ABS": 100, "ASA": 100, "TPU": 45, "Nylon": 90, "PC": 108, "CF Nylon": 85},
        "speed": {"PLA": 150, "PETG": 95, "ABS": 80, "ASA": 78, "TPU": 35, "Nylon": 50, "PC": 45, "CF Nylon": 48},
        "orientation": "Use slower accelerations and stronger first-layer grip on wide parts that consume a lot of bed area.",
    },
    "Voron 2.4 350": {
        "family": "Voron 2.4 series",
        "printer_note": "Community-built enclosed core-XY platform. Excellent for tuned engineering workflows, but machine quality depends on the build.",
        "bed_shape": "350 x 350 mm",
        "max_height_mm": 330,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Textured PEI",
        "gcode_flavor": "Klipper",
        "nozzle": {"PLA": 220, "PETG": 248, "ABS": 255, "ASA": 260, "TPU": 225, "Nylon": 270, "PC": 275, "CF Nylon": 280},
        "bed": {"PLA": 60, "PETG": 80, "ABS": 105, "ASA": 105, "TPU": 45, "Nylon": 90, "PC": 110, "CF Nylon": 88},
        "speed": {"PLA": 220, "PETG": 140, "ABS": 125, "ASA": 120, "TPU": 45, "Nylon": 75, "PC": 65, "CF Nylon": 70},
        "orientation": "Use the enclosed chamber to your advantage on warmer materials and keep cosmetic faces away from support-heavy zones.",
    },
    "Raise3D Pro3": {
        "family": "Raise3D Pro series",
        "printer_note": "Professional enclosed printer with large build volume. Good for durable prototyping and cleaner engineering handoffs.",
        "bed_shape": "300 x 300 mm",
        "max_height_mm": 300,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Flexible build plate",
        "gcode_flavor": "Marlin / Raise3D",
        "nozzle": {"PLA": 210, "PETG": 245, "ABS": 255, "ASA": 260, "TPU": 225, "Nylon": 265, "PC": 272, "CF Nylon": 278},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 100, "ASA": 100, "TPU": 45, "Nylon": 90, "PC": 110, "CF Nylon": 88},
        "speed": {"PLA": 100, "PETG": 72, "ABS": 65, "ASA": 62, "TPU": 32, "Nylon": 48, "PC": 45, "CF Nylon": 48},
        "orientation": "Bias toward support removal and dimensional control on functional parts rather than maximum speed.",
    },
    "Ultimaker S5": {
        "family": "Ultimaker S series",
        "printer_note": "Large reliable dual-extrusion platform with conservative motion. Great for stable educational and professional workflows.",
        "bed_shape": "330 x 240 mm",
        "max_height_mm": 300,
        "nozzle_diameter": 0.4,
        "adhesion_default": "Glass / glue assist",
        "gcode_flavor": "UltiGCode / Marlin compatible",
        "nozzle": {"PLA": 210, "PETG": 240, "ABS": 250, "ASA": 255, "TPU": 220, "Nylon": 260, "PC": 265, "CF Nylon": 270},
        "bed": {"PLA": 60, "PETG": 75, "ABS": 95, "ASA": 95, "TPU": 45, "Nylon": 85, "PC": 105, "CF Nylon": 82},
        "speed": {"PLA": 95, "PETG": 70, "ABS": 60, "ASA": 58, "TPU": 35, "Nylon": 45, "PC": 40, "CF Nylon": 42},
        "orientation": "Stand the part upright with a 12 degree cant to preserve edge detail and cut raft size.",
    },
    "Custom / Large Format": {
        "family": "Custom / user-defined",
        "printer_note": "Fallback profile for unsupported or unusual machines. Enter the real bed, height, nozzle, and firmware data carefully.",
        "bed_shape": "500 x 500 mm",
        "max_height_mm": 500,
        "nozzle_diameter": 0.6,
        "adhesion_default": "Custom surface",
        "gcode_flavor": "Generic Marlin",
        "nozzle": {"PLA": 220, "PETG": 245, "ABS": 255, "ASA": 260, "TPU": 225, "Nylon": 265, "PC": 270, "CF Nylon": 275},
        "bed": {"PLA": 60, "PETG": 80, "ABS": 95, "ASA": 95, "TPU": 45, "Nylon": 88, "PC": 108, "CF Nylon": 85},
        "speed": {"PLA": 120, "PETG": 90, "ABS": 80, "ASA": 78, "TPU": 35, "Nylon": 50, "PC": 45, "CF Nylon": 48},
        "orientation": "Keep the longest face stable on the bed and bias toward support reduction on cosmetic surfaces.",
    },
}

FILAMENT_TYPES = [
    "PLA",
    "PLA Silk",
    "PLA Wood",
    "PLA-GF",
    "PETG",
    "PETG-GF",
    "ABS",
    "ASA",
    "TPU",
    "Nylon",
    "Glass-Fiber Nylon",
    "CF Nylon",
    "PC",
]

FILAMENT_BASE_MAP = {
    "PLA": "PLA",
    "PLA Silk": "PLA",
    "PLA Wood": "PLA",
    "PLA-GF": "PLA",
    "PETG": "PETG",
    "PETG-GF": "PETG",
    "ABS": "ABS",
    "ASA": "ASA",
    "TPU": "TPU",
    "Nylon": "Nylon",
    "Glass-Fiber Nylon": "Nylon",
    "CF Nylon": "CF Nylon",
    "PC": "PC",
}

ABRASIVE_FILAMENTS = {
    "PLA-GF",
    "PETG-GF",
    "Glass-Fiber Nylon",
    "CF Nylon",
}

FILAMENT_DETAILS = {
    "PLA": {
        "summary": "Easiest everyday material. Great for clean prototypes, school demos, and rigid parts that do not need high heat resistance.",
        "warning": "Can soften in hot cars, direct sun, or high-heat environments.",
        "strength": "Easy print, lower heat resistance, good all-purpose rigidity.",
    },
    "PLA Silk": {
        "summary": "Decorative PLA blend with a shinier finish. Great for display parts and presentation pieces.",
        "warning": "Looks nice, but often sacrifices a little strength and dimensional honesty compared with plain PLA.",
        "strength": "Best for appearance-first prints, not heavy-duty parts.",
    },
    "PLA Wood": {
        "summary": "PLA blend made for a wood-like look and feel. Useful for props, decor, and visual prototypes.",
        "warning": "Can be more brittle, can vary by brand, and may prefer a wider nozzle if particles are coarse.",
        "strength": "Looks-first material with modest strength.",
    },
    "PLA-GF": {
        "summary": "Glass-fiber reinforced PLA for stiffer everyday parts with more bite than plain PLA.",
        "warning": "Abrasive filler can wear softer nozzles faster. Hardened or wear-resistant nozzles are the safer long-term path.",
        "strength": "Stiffer than plain PLA, still easier than hot engineering plastics.",
    },
    "PETG": {
        "summary": "Stronger and more heat-tolerant than PLA. Good for durable utility parts and light outdoor use.",
        "warning": "Can string more easily and often benefits from slower tuning than PLA.",
        "strength": "Good balance of toughness, layer bonding, and everyday durability.",
    },
    "PETG-GF": {
        "summary": "Glass-fiber reinforced PETG for tougher utility parts that need more stiffness than plain PETG.",
        "warning": "Abrasive filler means nozzle wear matters. Hardened nozzles are strongly recommended for repeated use.",
        "strength": "Tougher and stiffer than PETG, with more machine wear risk.",
    },
    "ABS": {
        "summary": "Good for tougher, warmer-use parts when you need more heat resistance than PLA or PETG.",
        "warning": "Usually prefers an enclosure and stable temperatures to avoid warping.",
        "strength": "Better heat resistance and toughness than everyday PLA/PETG.",
    },
    "ASA": {
        "summary": "Outdoor-friendly cousin to ABS. Useful when UV resistance and better weather tolerance matter.",
        "warning": "Still prefers an enclosure and can warp if the environment is too drafty.",
        "strength": "Good outdoor durability with stronger weather resistance than ABS.",
    },
    "TPU": {
        "summary": "Flexible material for grips, bumpers, and soft-contact parts.",
        "warning": "Prints slower than rigid plastics and needs gentler retraction and motion settings.",
        "strength": "Flexible rather than rigid. Great for impact and bend, not stiffness.",
    },
    "Nylon": {
        "summary": "Strong and durable engineering plastic with good toughness for functional parts.",
        "warning": "High-moisture-risk material. Dry storage, dryer use, and stable print conditions matter a lot or print quality can fall apart fast.",
        "strength": "Very tough with strong layer bonding when dried and printed well.",
    },
    "Glass-Fiber Nylon": {
        "summary": "Glass-fiber nylon for stiffer technical parts that still want nylon toughness underneath.",
        "warning": "Abrasive filler plus moisture sensitivity is a serious combo. Use a hardened nozzle, keep the filament dry, and expect more machine wear than plain nylon.",
        "strength": "Stiffer than plain nylon, with stronger machine demands.",
    },
    "PC": {
        "summary": "High-strength, higher-heat engineering material for demanding parts.",
        "warning": "Often needs a hotter setup, enclosure support, and careful warping control.",
        "strength": "High heat and strength potential, but much less forgiving to print.",
    },
    "CF Nylon": {
        "summary": "Carbon-fiber reinforced nylon for rigid, technical parts that need better stiffness than plain nylon.",
        "warning": "Very high caution material. It is abrasive, wants a hardened or wear-resistant nozzle, needs drying, and can punish casual machine setups quickly.",
        "strength": "Excellent stiffness-to-weight for technical parts, but high setup demand.",
    },
}

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
        "intro": "I will still give safe recommendations, but I will package them like a longtime best friend who keeps it casual, uses a little slang, and locks in hard when the print actually matters.",
        "agent_tone": {
            "Inspector": "Alright, I checked the model so you do not waste filament on a cursed print. Here is what actually matters.",
            "Calibrator": "I tuned these settings to keep the print clean, stable, and worth your time, not just technically possible.",
            "G-Code Architect": "I lined up the manufacturing path so the output stays readable, tight, and not weird later.",
            "Cipher Vault": "I locked down the delivery side so the file does not wander off and create unnecessary chaos.",
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
        "summary": "Safest choice when you want analysis, recommendations, and a downloadable print file without printer handoff.",
        "warning": "No direct printer handoff. The user still has to move the file into their own workflow.",
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
        "Secure print package delivery agent. Hashes, encrypts, labels, and stages print files so the "
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
        "ui_title": "Print file prep",
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


def footprint_fits_printer(part_x: float, part_y: float, printer_profile: dict[str, object]) -> tuple[bool, str]:
    build_x, build_y, _ = parse_bed_dimensions(printer_profile)
    bed_shape_type = str(printer_profile.get("bed_shape_type", "Rectangular"))
    if bed_shape_type == "Circular":
        bed_diameter = min(build_x, build_y)
        footprint_diagonal = math.sqrt((part_x ** 2) + (part_y ** 2))
        fits = footprint_diagonal <= bed_diameter
        message = (
            f"Circular bed check: footprint diagonal {footprint_diagonal:.1f} mm vs bed diameter {bed_diameter:.1f} mm."
        )
        return fits, message
    fits = part_x <= build_x and part_y <= build_y
    message = f"Rectangular bed check: X {part_x:.1f}/{build_x:.1f} mm and Y {part_y:.1f}/{build_y:.1f} mm."
    return fits, message


def summarize_fit(mesh_analysis: dict[str, object] | None, printer_profile: dict[str, object]) -> tuple[str, str]:
    if not mesh_analysis or not mesh_analysis.get("scaled_extents_mm"):
        return "Pending geometry scan", "Upload analysis is needed before CipherSlice can confirm part fit against the build volume."

    part_x, part_y, part_z = mesh_analysis["scaled_extents_mm"]
    build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
    xy_fits, fit_detail = footprint_fits_printer(part_x, part_y, printer_profile)
    if xy_fits and part_z <= build_z:
        return "Fits current printer", f"The current scaled part size fits within the selected printer volume. {fit_detail}"
    return "Exceeds build volume", "At least one part dimension is larger than the selected printer volume."


def build_orientation_candidates(
    extents: list[float] | tuple[float, float, float] | None,
    printer_profile: dict[str, object],
    mesh_analysis: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    if not extents:
        return []

    x_dim, y_dim, z_dim = [float(value) for value in extents]
    build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
    geometry_profile = str((mesh_analysis or {}).get("geometry_profile", "Unknown"))
    risk_level = str((mesh_analysis or {}).get("risk_level", "Unknown"))
    detail_risk = str((mesh_analysis or {}).get("detail_risk", "Unknown"))

    candidates = [
        {
            "label": "As loaded",
            "dims": (x_dim, y_dim, z_dim),
            "summary": "Keeps the uploaded orientation exactly as it arrived.",
        },
        {
            "label": "Lay flattest face",
            "dims": tuple(sorted([x_dim, y_dim, z_dim], reverse=True)[:2] + [min(x_dim, y_dim, z_dim)]),
            "summary": "Pushes the broadest faces onto the bed to improve first-layer stability.",
        },
        {
            "label": "Balanced side",
            "dims": (max(x_dim, y_dim, z_dim), min(x_dim, y_dim, z_dim), sorted([x_dim, y_dim, z_dim])[1]),
            "summary": "Trades a little more height for better side support on some parts.",
        },
    ]

    evaluated: list[dict[str, object]] = []
    for candidate in candidates:
        part_x, part_y, part_z = candidate["dims"]
        fits_xy, fit_detail = footprint_fits_printer(part_x, part_y, printer_profile)
        fits = bool(fits_xy and part_z <= build_z)
        contact_area = part_x * part_y
        base_fill = min(100.0, (contact_area / max(build_x * build_y, 1)) * 100)
        height_use = min(100.0, (part_z / max(build_z, 1)) * 100)
        stability_score = contact_area / max(part_z, 1)
        support_pressure = 0
        if height_use > 70:
            support_pressure += 2
        elif height_use > 45:
            support_pressure += 1
        if base_fill < 8:
            support_pressure += 2
        elif base_fill < 15:
            support_pressure += 1
        if geometry_profile in {"Tall / slender", "Dense detail"}:
            support_pressure += 1
        if risk_level == "High":
            support_pressure += 1
        score = stability_score - (support_pressure * 22)
        if not fits:
            score -= 1000
        if detail_risk == "Very small features" and candidate["label"] == "Lay flattest face":
            score -= 8
        recommendation = "Good default"
        if support_pressure >= 4:
            recommendation = "High support pressure"
        elif base_fill < 10:
            recommendation = "Small bed contact"
        elif height_use < 40 and base_fill > 18:
            recommendation = "Strong first-layer posture"
        evaluated.append(
            {
                **candidate,
                "fits": fits,
                "fit_detail": fit_detail,
                "contact_area": contact_area,
                "bed_use": round(base_fill, 1),
                "height_use": round(height_use, 1),
                "support_pressure": support_pressure,
                "score": round(score, 2),
                "recommendation": recommendation,
            }
        )

    best_score = max(candidate["score"] for candidate in evaluated)
    for candidate in evaluated:
        candidate["recommended"] = bool(candidate["score"] == best_score)
        candidate["tradeoff"] = (
            "Best contact patch and easiest first layer."
            if candidate["recommended"]
            else (
                "Safer for some features, but likely taller or more support-hungry."
                if candidate["support_pressure"] >= 3
                else "Balanced alternative if you need a different face or seam placement."
            )
        )
    return evaluated


def build_orientation_candidate_preview(candidates: list[dict[str, object]]) -> str:
    if not candidates:
        return "<div class='shape-preview-empty'>Orientation candidates appear after CipherSlice reads the model.</div>"

    cards: list[str] = []
    for candidate in candidates:
        part_x, part_y, part_z = candidate["dims"]
        max_dim = max(part_x, part_y, part_z, 1)
        scale = 72 / max_dim
        front_w = max(14, part_x * scale)
        front_h = max(14, part_z * scale)
        top_w = max(14, part_x * scale)
        top_h = max(14, part_y * scale)
        front_x = 30
        front_y = 58 - (front_h / 2)
        top_x = front_x + 12
        top_y = front_y - max(8, top_h * 0.35)
        right_x = front_x + front_w
        right_y = front_y - max(6, top_h * 0.2)
        badge = "<div class='orientation-badge'>Recommended</div>" if candidate.get("recommended") else ""
        fit_color = "#8fe6cf" if candidate["fits"] else "#ffab91"
        fit_fill = "rgba(90,207,171,0.18)" if candidate["fits"] else "rgba(255,140,120,0.18)"
        cards.append(
            f"""
            <div class="orientation-card{' orientation-card-recommended' if candidate.get('recommended') else ''}">
                {badge}
                <div class="orientation-title">{candidate['label']}</div>
                <div class="orientation-copy">{candidate['summary']}</div>
                <svg viewBox="0 0 170 128" class="orientation-svg" aria-hidden="true">
                    <rect x="16" y="88" width="138" height="20" rx="10" fill="rgba(8,22,36,0.9)" stroke="rgba(104,144,177,0.28)" />
                    <polygon points="{top_x:.1f},{top_y:.1f} {top_x + top_w:.1f},{top_y:.1f} {right_x + top_w * 0.18:.1f},{right_y:.1f} {front_x + top_w * 0.18:.1f},{right_y:.1f}"
                        fill="{fit_fill}" stroke="{fit_color}" stroke-width="1.6"/>
                    <rect x="{front_x:.1f}" y="{front_y:.1f}" width="{front_w:.1f}" height="{front_h:.1f}" rx="8"
                        fill="{fit_fill}" stroke="{fit_color}" stroke-width="1.9"/>
                    <polygon points="{right_x:.1f},{front_y:.1f} {right_x + top_w * 0.18:.1f},{right_y:.1f} {right_x + top_w * 0.18:.1f},{right_y + front_h:.1f} {right_x:.1f},{front_y + front_h:.1f}"
                        fill="rgba(90,207,171,0.12)" stroke="{fit_color}" stroke-width="1.4"/>
                </svg>
                <div class="orientation-meta">Bed use: {candidate['bed_use']:.0f}% | Height: {candidate['height_use']:.0f}%</div>
                <div class="orientation-meta">Support pressure: {candidate['support_pressure']} | {candidate['recommendation']}</div>
                <div class="orientation-copy">{candidate['tradeoff']}</div>
            </div>
            """
        )
    return "<div class='orientation-grid'>" + "".join(textwrap.dedent(card).strip() for card in cards) + "</div>"


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
        fits, _ = footprint_fits_printer(part_x, part_y, printer_profile)
        status_label = "Fits on current bed" if fits else "Footprint exceeds bed"
        status_color = "#73e8c1" if fits else "#ffd39f"
        fill = "rgba(90, 207, 171, 0.28)" if fits else "rgba(255, 140, 120, 0.28)"
        stroke = "#73e8c1" if fits else "#ffab91"
        if str(printer_profile.get("bed_shape_type", "Rectangular")) == "Circular":
            radius = min(bed_draw_width, bed_draw_height) / 2
            center_x = padding + bed_draw_width / 2
            center_y = padding + bed_draw_height / 2
            part_svg = (
                f'<ellipse cx="{center_x:.1f}" cy="{center_y:.1f}" rx="{part_draw_width/2:.1f}" ry="{part_draw_height/2:.1f}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="2.5" />'
            )
        else:
            part_svg = (
                f'<rect x="{part_left:.1f}" y="{part_top:.1f}" width="{part_draw_width:.1f}" height="{part_draw_height:.1f}" '
                f'rx="12" ry="12" fill="{fill}" stroke="{stroke}" stroke-width="2.5" />'
            )

    return textwrap.dedent(
        f"""
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
    ).strip()


def build_model_shape_preview_svg(mesh_analysis: dict[str, object] | None) -> str:
    if not mesh_analysis or not mesh_analysis.get("scaled_extents_mm"):
        return textwrap.dedent(
            """
        <div class="shape-preview-empty">
            Shape preview appears after CipherSlice reads the model dimensions.
        </div>
        """
        ).strip()

    part_x, part_y, part_z = mesh_analysis["scaled_extents_mm"]
    max_dim = max(part_x, part_y, part_z, 1)
    scale = 92 / max_dim

    def view_rect(width: float, height: float) -> tuple[float, float]:
        return max(12, width * scale), max(12, height * scale)

    top_w, top_h = view_rect(part_x, part_y)
    front_w, front_h = view_rect(part_x, part_z)
    side_w, side_h = view_rect(part_y, part_z)
    views = [
        ("Top X/Y", top_w, top_h),
        ("Front X/Z", front_w, front_h),
        ("Side Y/Z", side_w, side_h),
    ]
    cards = []
    for label, width, height in views:
        rect_x = 58 - (width / 2)
        rect_y = 56 - (height / 2)
        cards.append(
            f"""
            <div class="shape-view">
                <svg viewBox="0 0 116 112" class="shape-svg" aria-hidden="true">
                    <rect x="10" y="10" width="96" height="88" rx="10" fill="rgba(8,22,36,0.85)" stroke="rgba(104,144,177,0.25)" />
                    <line x1="18" y1="56" x2="98" y2="56" stroke="rgba(151,179,201,0.13)" />
                    <line x1="58" y1="18" x2="58" y2="92" stroke="rgba(151,179,201,0.13)" />
                    <rect x="{rect_x:.1f}" y="{rect_y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="7"
                          fill="rgba(90,207,171,0.24)" stroke="#8fe6cf" stroke-width="2" />
                </svg>
                <div class="shape-label">{label}</div>
            </div>
            """
        )

    return "<div class='shape-preview-grid'>" + "".join(textwrap.dedent(card).strip() for card in cards) + "</div>"


def build_preview_mesh_data(
    mesh,
    scale_factor: float,
    max_faces: int = 2800,
) -> dict[str, object] | None:
    try:
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
        if len(vertices) == 0 or len(faces) == 0:
            return None
        if len(faces) > max_faces:
            sample_idx = np.linspace(0, len(faces) - 1, max_faces, dtype=int)
            sampled_faces = faces[sample_idx]
            unique_vertices, inverse = np.unique(sampled_faces.reshape(-1), return_inverse=True)
            vertices = vertices[unique_vertices]
            faces = inverse.reshape(-1, 3)
        scaled_vertices = vertices * float(scale_factor or 1.0)
        center = scaled_vertices.mean(axis=0)
        centered = scaled_vertices - center
        max_abs = float(np.max(np.abs(centered))) if centered.size else 1.0
        if max_abs <= 0:
            max_abs = 1.0
        normalized = np.round((centered / max_abs) * 42.0, 3)
        return {
            "vertices": normalized.tolist(),
            "faces": faces.tolist(),
            "scale_mm": round(max_abs, 3),
        }
    except Exception:
        return None


def render_interactive_mesh_preview(
    mesh_analysis: dict[str, object] | None,
    printer_profile: dict[str, object],
    camera_preset: str,
    orientation_label: str,
    seam_position: str,
    component_key: str,
) -> None:
    preview_mesh = (mesh_analysis or {}).get("preview_mesh")
    if not preview_mesh:
        st.info("Interactive 3D preview appears after CipherSlice can read the mesh geometry.")
        return

    camera_map = {
        "Isometric": [88, 68, 88],
        "Top": [0, 138, 0.1],
        "Front": [0, 18, 138],
        "Side": [138, 20, 0.1],
    }
    orientation_rotation_map = {
        "As loaded": [0.0, 0.0, 0.0],
        "Lay flattest face": [-1.5708, 0.0, 0.0],
        "Balanced side": [0.0, 0.0, 1.5708],
    }
    bed_x, bed_y, _ = parse_bed_dimensions(printer_profile)
    extents = (mesh_analysis or {}).get("scaled_extents_mm") or (mesh_analysis or {}).get("extents_mm") or [100, 100, 100]
    max_part_dim = max(float(value) for value in extents) if extents else 100.0
    plane_scale = 84.0 / max(max_part_dim, 1.0)
    plane_x = max(36.0, min(138.0, bed_x * plane_scale))
    plane_y = max(36.0, min(138.0, bed_y * plane_scale))
    is_circular = str(printer_profile.get("bed_shape_type", "Rectangular")) == "Circular"
    mesh_json = json.dumps(preview_mesh)
    camera_json = json.dumps(camera_map.get(camera_preset, camera_map["Isometric"]))
    rotation_json = json.dumps(orientation_rotation_map.get(orientation_label, orientation_rotation_map["As loaded"]))
    seam_json = json.dumps(seam_position)
    height_use = float((mesh_analysis or {}).get("height_use_percent") or 0.0)
    bed_use = float((mesh_analysis or {}).get("bed_use_percent") or 0.0)
    unsupported_risk = str((mesh_analysis or {}).get("unsupported_risk", "Unknown"))
    bridge_risk = str((mesh_analysis or {}).get("bridge_risk", "Unknown"))
    support_hotspots = unsupported_risk in {"Widespread unsupported surfaces", "Localized unsupported pockets"} or bridge_risk in {"Bridge-heavy geometry", "Some bridging pressure"}
    support_hotspot_json = json.dumps(bool(support_hotspots))
    html = f"""
    <div style="background:rgba(8,23,37,0.88);border:1px solid rgba(104,144,177,0.18);border-radius:18px;padding:0.7rem 0.7rem 0.4rem;">
      <div style="color:#f4f8fb;font-weight:700;margin-bottom:0.35rem;">Interactive 3D Preview</div>
      <div style="color:#b7c8d5;font-size:0.9rem;line-height:1.45;margin-bottom:0.55rem;">
        Drag to orbit, scroll to zoom, and inspect the part against a simplified build surface.
      </div>
      <div id="{component_key}" style="width:100%;height:420px;border-radius:16px;overflow:hidden;"></div>
    </div>
    <script src="https://unpkg.com/three@0.160.0/build/three.min.js"></script>
    <script src="https://unpkg.com/three@0.160.0/examples/js/controls/OrbitControls.js"></script>
    <script>
      (function() {{
        const host = document.getElementById("{component_key}");
        if (!host || host.dataset.loaded === "1") return;
        host.dataset.loaded = "1";
        const meshData = {mesh_json};
        const cameraStart = {camera_json};
        const partRotation = {rotation_json};
        const seamMode = {seam_json};
        const showSupportHotspots = {support_hotspot_json};
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x08131f);

        const camera = new THREE.PerspectiveCamera(42, host.clientWidth / host.clientHeight, 0.1, 1000);
        camera.position.set(cameraStart[0], cameraStart[1], cameraStart[2]);

        const renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
        renderer.setSize(host.clientWidth, host.clientHeight);
        renderer.setPixelRatio(window.devicePixelRatio || 1);
        host.appendChild(renderer.domElement);

        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.target.set(0, 10, 0);

        const ambient = new THREE.AmbientLight(0xffffff, 1.1);
        scene.add(ambient);
        const keyLight = new THREE.DirectionalLight(0x9cf0d4, 1.25);
        keyLight.position.set(65, 90, 70);
        scene.add(keyLight);
        const rimLight = new THREE.DirectionalLight(0x4b8cff, 0.7);
        rimLight.position.set(-60, 35, -80);
        scene.add(rimLight);

        const planeGroup = new THREE.Group();
        const bedUse = {bed_use:.2f};
        const planeColor = bedUse > 70 ? 0x3b221f : (bedUse > 45 ? 0x213244 : 0x0c1f31);
        const planeMaterial = new THREE.MeshStandardMaterial({{ color: planeColor, roughness: 0.9, metalness: 0.08 }});
        let bedMesh;
        if ({str(is_circular).lower()}) {{
          bedMesh = new THREE.Mesh(new THREE.CylinderGeometry({plane_x/2:.2f}, {plane_x/2:.2f}, 2, 64), planeMaterial);
          bedMesh.rotation.x = Math.PI / 2;
        }} else {{
          bedMesh = new THREE.Mesh(new THREE.BoxGeometry({plane_x:.2f}, 2, {plane_y:.2f}), planeMaterial);
        }}
        planeGroup.add(bedMesh);
        const edge = new THREE.LineSegments(
          new THREE.EdgesGeometry(bedMesh.geometry),
          new THREE.LineBasicMaterial({{ color: 0x5dd8b7, transparent: true, opacity: 0.55 }})
        );
        edge.rotation.copy(bedMesh.rotation);
        planeGroup.add(edge);
        scene.add(planeGroup);

        const grid = new THREE.GridHelper(Math.max({plane_x:.2f}, {plane_y:.2f}) * 0.98, 14, 0x2c4e67, 0x173246);
        grid.position.y = 1.1;
        scene.add(grid);

        const verts = new Float32Array(meshData.vertices.flat());
        const faceFlat = meshData.faces.flat();
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(verts, 3));
        geometry.setIndex(faceFlat);
        geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({{
          color: 0x5dd8b7,
          roughness: 0.45,
          metalness: 0.16,
          transparent: true,
          opacity: 0.96,
          side: THREE.DoubleSide
        }});
        const partMesh = new THREE.Mesh(geometry, material);
        partMesh.position.y = 14;
        partMesh.rotation.set(partRotation[0], partRotation[1], partRotation[2]);
        scene.add(partMesh);

        const wire = new THREE.LineSegments(
          new THREE.EdgesGeometry(geometry),
          new THREE.LineBasicMaterial({{ color: 0xdffcf2, transparent: true, opacity: 0.18 }})
        );
        wire.position.copy(partMesh.position);
        wire.rotation.copy(partMesh.rotation);
        scene.add(wire);

        const box = new THREE.Box3().setFromObject(partMesh);
        const size = new THREE.Vector3();
        box.getSize(size);
        const center = new THREE.Vector3();
        box.getCenter(center);

        if (showSupportHotspots) {{
          const hotspotMaterial = new THREE.MeshBasicMaterial({{ color: 0xffb347, transparent: true, opacity: 0.85 }});
          const hotspotGeometry = new THREE.SphereGeometry(2.1, 18, 18);
          const hotspotPositions = [
            [center.x - size.x * 0.22, box.min.y + size.y * 0.12, center.z + size.z * 0.18],
            [center.x + size.x * 0.24, box.min.y + size.y * 0.24, center.z - size.z * 0.2],
          ];
          hotspotPositions.forEach((pos) => {{
            const marker = new THREE.Mesh(hotspotGeometry, hotspotMaterial);
            marker.position.set(pos[0], pos[1], pos[2]);
            scene.add(marker);
          }});
        }}

        const seamLineMaterial = new THREE.LineBasicMaterial({{ color: 0x8fd3ff, transparent: true, opacity: 0.78 }});
        const seamLineGeometry = new THREE.BufferGeometry();
        let seamX = center.x;
        let seamZ = center.z;
        if (seamMode === "Rear") seamZ = box.max.z;
        if (seamMode === "Front") seamZ = box.min.z;
        if (seamMode === "Left") seamX = box.min.x;
        if (seamMode === "Right") seamX = box.max.x;
        seamLineGeometry.setFromPoints([
          new THREE.Vector3(seamX, box.min.y, seamZ),
          new THREE.Vector3(seamX, box.max.y, seamZ)
        ]);
        const seamLine = new THREE.Line(seamLineGeometry, seamLineMaterial);
        scene.add(seamLine);

        if ({height_use:.2f} > 70) {{
          const pillarGeo = new THREE.CylinderGeometry(1.1, 1.1, size.y + 18, 18);
          const pillarMat = new THREE.MeshBasicMaterial({{ color: 0xff7f7f, transparent: true, opacity: 0.28 }});
          const pillar = new THREE.Mesh(pillarGeo, pillarMat);
          pillar.position.set(center.x, center.y, center.z);
          scene.add(pillar);
        }}

        const resize = () => {{
          const width = host.clientWidth || 640;
          const height = host.clientHeight || 420;
          camera.aspect = width / height;
          camera.updateProjectionMatrix();
          renderer.setSize(width, height);
        }};
        window.addEventListener("resize", resize);
        resize();

        const animate = () => {{
          requestAnimationFrame(animate);
          controls.update();
          renderer.render(scene, camera);
        }};
        animate();
      }})();
    </script>
    """
    components.html(html, height=450)


def build_mesh_preview_metrics(
    mesh_analysis: dict[str, object] | None,
    printer_profile: dict[str, object],
) -> list[tuple[str, str]]:
    if not mesh_analysis or not mesh_analysis.get("scaled_extents_mm"):
        return [
            ("Bed use", "Pending"),
            ("Height use", "Pending"),
            ("Mesh health", "Scan needed"),
            ("Risk", "Pending"),
        ]

    part_x, part_y, part_z = mesh_analysis["scaled_extents_mm"]
    bed_x, bed_y, bed_z = parse_bed_dimensions(printer_profile)
    bed_use = float(mesh_analysis.get("bed_use_percent") or min(100.0, ((part_x * part_y) / max((bed_x * bed_y), 1)) * 100))
    height_use = float(mesh_analysis.get("height_use_percent") or min(100.0, (part_z / max(bed_z, 1)) * 100))
    mesh_health = "Watertight" if mesh_analysis.get("watertight") else "Needs repair"
    risk = str(mesh_analysis.get("risk_level", "Unknown"))
    return [
        ("Bed use", f"{bed_use:.0f}%"),
        ("Height use", f"{height_use:.0f}%"),
        ("First-layer contact", f"{float(mesh_analysis.get('first_layer_contact_percent', 0)):.0f}%"
         if mesh_analysis.get("first_layer_contact_percent") is not None else "Pending"),
        ("Mesh health", mesh_health),
        ("Risk", risk),
    ]


def build_geometry_intelligence(mesh_analysis: dict[str, object] | None, printer_profile: dict[str, object]) -> list[tuple[str, str]]:
    if not mesh_analysis:
        return [
            ("Scale hint", "Waiting for mesh scan"),
            ("Face count", "Pending"),
            ("Watertight", "Pending"),
            ("Fit against printer", "Pending"),
        ]

    bed_x, bed_y, bed_z = parse_bed_dimensions(printer_profile)
    extents = mesh_analysis.get("scaled_extents_mm") or mesh_analysis.get("extents_mm")
    scale_hint = str(mesh_analysis.get("scale_hint", "Pending"))
    face_count = str(mesh_analysis.get("face_count") or "Unknown")
    watertight_state = mesh_analysis.get("watertight")
    watertight = "Pending" if watertight_state is None else ("Yes" if watertight_state else "No")
    fit_state = "Pending"
    bed_use = mesh_analysis.get("bed_use_percent")
    height_use = mesh_analysis.get("height_use_percent")
    fit_margin = mesh_analysis.get("fit_margin_mm")
    if extents:
        part_x, part_y, part_z = extents
        fits_xy, fit_detail = footprint_fits_printer(part_x, part_y, printer_profile)
        fit_state = "Fits" if fits_xy and part_z <= bed_z else f"Needs review ({fit_detail})"
    return [
        ("Risk level", str(mesh_analysis.get("risk_level", "Unknown"))),
        ("Geometry profile", str(mesh_analysis.get("geometry_profile", "Unknown"))),
        ("Scale hint", scale_hint),
        ("Likely unit case", str(mesh_analysis.get("likely_unit_case", "Unknown"))),
        ("Face count", face_count),
        ("Watertight", watertight),
        ("Bed use", f"{bed_use}%" if bed_use is not None else "Pending"),
        ("Height use", f"{height_use}%" if height_use is not None else "Pending"),
        ("Fit margin", f"{fit_margin} mm" if fit_margin is not None else "Pending"),
        ("Detail risk", str(mesh_analysis.get("detail_risk", "Unknown"))),
        ("Thin-wall risk", str(mesh_analysis.get("thin_wall_risk", "Unknown"))),
        ("Estimated wall width", str(mesh_analysis.get("wall_thickness_estimate", "Unknown"))),
        ("Warp risk", str(mesh_analysis.get("warp_risk", "Unknown"))),
        ("Unsupported risk", str(mesh_analysis.get("unsupported_risk", "Unknown"))),
        ("Bridge risk", str(mesh_analysis.get("bridge_risk", "Unknown"))),
        ("Hole / opening risk", str(mesh_analysis.get("hole_risk", "Unknown"))),
        ("Overhang scope", str(mesh_analysis.get("overhang_scope", "Unknown"))),
        ("Feature survivability", str(mesh_analysis.get("survivability_hint", "Unknown"))),
        ("Fragile zones", str(mesh_analysis.get("fragile_zone_summary", "Unknown"))),
        ("Fit against printer", fit_state),
    ]


def build_printer_material_notes(
    printer_profile: dict[str, object],
    filament: str,
    mesh_analysis: dict[str, object] | None,
) -> list[str]:
    notes: list[str] = []
    family = str(printer_profile.get("family", "")).lower()
    base_filament = get_base_filament(filament)
    filament_key = base_filament.lower()
    open_frame_family = any(
        tag in family for tag in ("a1", "mk", "ender", "kobra", "open-frame", "bedslinger")
    )
    enclosure_hungry = {"abs", "asa", "pc", "nylon", "cf nylon"}
    nozzle_diameter = float(printer_profile.get("nozzle_diameter", 0.4))
    gcode_flavor = str(printer_profile.get("gcode_flavor", "Unknown"))
    bed_shape_type = str(printer_profile.get("bed_shape_type", "Rectangular"))
    heated_bed = bool(printer_profile.get("heated_bed", True))
    heated_chamber = bool(printer_profile.get("heated_chamber", False))
    if open_frame_family and filament_key in enclosure_hungry:
        notes.append(
            "This printer family is more exposed to room drafts, so hotter engineering plastics may need extra care or a warmer enclosure."
        )
    if filament_key in enclosure_hungry and not heated_chamber:
        notes.append(
            "This material usually benefits from a warmer print environment, so enclosure control matters more than it does for PLA or PETG."
        )
    if filament_key in {"petg", "abs", "asa", "nylon", "pc", "cf nylon"} and not heated_bed:
        notes.append(
            "This printer profile does not show a heated bed, so first-layer grip and warp control may be more difficult for this material."
        )
    if filament_key == "tpu":
        notes.append(
            "Flexible TPU usually behaves better with slower motion and steadier filament feeding than rigid plastics."
        )
    if filament_key == "nylon":
        notes.append(
            "Nylon is one of the easiest materials to underestimate. Moisture control, a stable print environment, and patient tuning matter much more here than they do for PLA."
        )
    if is_abrasive_filament(filament):
        notes.append(
            "This filament includes abrasive fiber, so a hardened or wear-resistant nozzle is strongly recommended before repeated use."
        )
    if filament_key == "cf nylon" and nozzle_diameter <= 0.4:
        notes.append(
            "Carbon-fiber nylon is tougher on smaller nozzles. A hardened nozzle and a less fragile machine path are the safer choice."
        )
    if filament == "Glass-Fiber Nylon" and nozzle_diameter <= 0.4:
        notes.append(
            "Glass-fiber nylon can wear softer nozzles surprisingly fast. A hardened nozzle is the safer match, especially on long or repeated jobs."
        )
    if nozzle_diameter >= 0.6:
        notes.append(
            "This larger nozzle can help big durable parts print faster, but it may soften tiny detail and thin features."
        )
    elif nozzle_diameter <= 0.25:
        notes.append(
            "This finer nozzle can preserve more detail, but it usually wants slower motion and cleaner filament control."
        )
    if bed_shape_type == "Circular":
        notes.append(
            "This printer uses a circular bed check, so wide diagonal parts may fail fit even when their X and Y numbers look close."
        )
    if "Klipper" in gcode_flavor:
        notes.append("This firmware path expects Klipper-style behavior, so matching the target machine's macros and commands matters.")
    elif "Makerbot" in gcode_flavor or "UltiGCode" in gcode_flavor:
        notes.append("This firmware flavor is less generic than plain Marlin, so export settings should match the target machine carefully.")
    if mesh_analysis and mesh_analysis.get("bed_use_percent") is not None:
        bed_use = float(mesh_analysis["bed_use_percent"])
        if bed_use >= 75:
            notes.append(
                "This part uses a large portion of the bed, so first-layer consistency and adhesion matter more than usual."
            )
    if mesh_analysis and mesh_analysis.get("height_use_percent") is not None:
        height_use = float(mesh_analysis["height_use_percent"])
        if height_use >= 70:
            notes.append(
                "This part is tall for the chosen machine, so slower speeds and a stable first layer are the safer path."
            )
    return notes


def build_agent_handoff_states(
    mode: str,
    mesh_analysis: dict[str, object] | None,
    slicer_path: str | None,
    connector_url: str | None,
    delivery_mode: str,
    objections: list[str],
) -> dict[str, tuple[str, str]]:
    states: dict[str, tuple[str, str]] = {}
    mesh_ok = bool(mesh_analysis and mesh_analysis.get("mesh_ok"))
    risk_level = str((mesh_analysis or {}).get("risk_level", "Unknown"))

    if mode != "Reliable Print Mode":
        states["Inspector"] = ("hold", "I am holding this until the drawing becomes validated 3D geometry.")
        states["Calibrator"] = ("hold", "I can suggest a print path, but I still need confirmed geometry before I trust the setup.")
        states["G-Code Architect"] = ("hold", "I am not releasing a real print file from a drawing-only workflow.")
        states["Cipher Vault"] = ("hold", "I can package the draft review packet, but final release stays blocked.")
        return states

    if not mesh_ok:
        states["Inspector"] = ("hold", "I am holding handoff because the model still has geometry, fit, or scale problems.")
    elif risk_level == "Medium":
        states["Inspector"] = ("pass", "I am passing this forward with caution because the part still has moderate print risk.")
    else:
        states["Inspector"] = ("pass", "I am passing this forward because the geometry review looks stable enough for setup work.")

    if not mesh_ok:
        states["Calibrator"] = ("hold", "I am pushing back until the model is safer to tune for a real print plan.")
    elif risk_level in {"Medium", "High"}:
        states["Calibrator"] = ("pass", "I am passing this forward with a safer profile so the next stage does not inherit a reckless setup.")
    else:
        states["Calibrator"] = ("pass", "I am passing this forward with a balanced print strategy.")

    if not slicer_path:
        states["G-Code Architect"] = ("hold", "I am holding the final print-file step because no real slicer backend is connected yet.")
    elif objections:
        states["G-Code Architect"] = ("hold", "I am holding this until the remaining blockers are resolved.")
    else:
        states["G-Code Architect"] = ("pass", "I am passing a slicer-ready plan forward for delivery review.")

    if delivery_mode == "Secure local connector" and not connector_url:
        states["Cipher Vault"] = ("hold", "I can stage the package, but I am holding secure handoff until a printer link is connected.")
    elif objections:
        states["Cipher Vault"] = ("hold", "I am keeping the release gate closed until the blockers are cleared.")
    else:
        states["Cipher Vault"] = ("pass", "I am passing the package to human approval with the selected delivery path.")

    return states


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


def build_guidance_visibility_summary(runtime_meta: dict[str, object]) -> tuple[str, str]:
    if runtime_meta.get("using_live_workers"):
        return (
            "Live guidance",
            "Specialized model workers are connected behind the scenes. The site only shows their short user-facing summaries.",
        )
    if runtime_meta.get("status") == "Hybrid mode":
        return (
            "Hybrid guidance",
            "Some live workers answered, and CipherSlice filled the rest with built-in planning logic.",
        )
    return (
        "Built-in guidance",
        "CipherSlice is using its built-in planning logic. Live model workers can be enabled later with environment variables.",
    )


def build_print_engine_setup_notes(
    slicer_label: str | None,
    slicer_path: str | None,
    engine_diagnostics: list[str],
) -> str:
    return textwrap.dedent(
        f"""
        CipherSlice Slicer Connection Notes

        Current engine: {slicer_label or 'Not detected'}
        Current path: {slicer_path or 'None configured'}

        Expected environment variable:
        CIPHERSLICE_SLICER_PATH=<full path to PrusaSlicer, OrcaSlicer, or Slic3r console executable>
        Optional Prusa-specific variable:
        CIPHERSLICE_PRUSASLICER_PATH=<full path to prusa-slicer-console.exe>

        Diagnostics:
        {chr(10).join(f'- {note}' for note in engine_diagnostics)}

        Notes:
        - A printer is not needed to test this connection.
        - The slicer backend is what turns the approved model and settings into real production G-code.
        - Hardware delivery can stay as SD card or manual download until a connector is installed later.
        - Raw engine command details stay out of the website so the customer flow stays clean.
        - CLI means command-line interface: a slicer program the app can launch in the background without opening the full visual editor.
        - On Windows, PrusaSlicer usually exposes prusa-slicer-console.exe for scripted slicing.
        """
    ).strip()


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
    agent_handoffs: dict[str, tuple[str, str]],
) -> dict[str, dict[str, str]]:
    persona_tone = persona["agent_tone"]
    inspector_handoff = agent_handoffs["Inspector"][1]
    calibrator_handoff = agent_handoffs["Calibrator"][1]
    architect_handoff = agent_handoffs["G-Code Architect"][1]
    vault_handoff = agent_handoffs["Cipher Vault"][1]
    if job_context["mode"] == "Reliable Print Mode":
        mesh_ok = mesh_analysis["mesh_ok"] if mesh_analysis else False
        scale_hint = mesh_analysis["scale_hint"] if mesh_analysis and mesh_analysis.get("scale_hint") else "No scale hint available."
        geometry_profile = mesh_analysis.get("geometry_profile", "Unknown") if mesh_analysis else "Unknown"
        risk_level = mesh_analysis.get("risk_level", "Unknown") if mesh_analysis else "Unknown"
        inspector_summary = (
            f"{persona_tone['Inspector']} Analyzed `{job_context['filename']}` from `{file_size_text}` input volume. "
            f"Recommended support density: `{support_density}%`. "
            f"{'Mesh integrity looks acceptable.' if mesh_ok else 'Mesh integrity requires review.'} "
            f"Risk level: `{risk_level}`. Geometry profile: `{geometry_profile}`. {scale_hint} {inspector_handoff}"
        )
        calibrator_summary = (
            f"{persona_tone['Calibrator']} Mapped `{job_context['filament']}` onto `{job_context['printer']}`. "
            f"Nozzle `{job_context['nozzle_temp']} degC`, bed `{job_context['bed_temp']} degC`, speed `{job_context['print_speed']} mm/s`, "
            f"layer height `{job_context['layer_height']} mm`, infill `{job_context['infill_percent']}%`. "
            f"Placement suggestion: {job_context['orientation']} Bed setup: `{job_context['adhesion']}`. {calibrator_handoff}"
        )
        architect_summary = (
            f"{persona_tone['G-Code Architect']} {slicer_message} "
            f"Prepared the manufacturing handoff for `{job_context['printer']}` using `{job_context['gcode_flavor']}`. {architect_handoff}"
        )
    else:
        inspector_summary = (
            f"{persona_tone['Inspector']} Reviewed `{job_context['filename']}` as a structured drawing from `{file_size_text}` input volume. "
            f"Final fabrication still depends on validated geometry, dimensions, and fit assumptions. {inspector_handoff}"
        )
        calibrator_summary = (
            f"{persona_tone['Calibrator']} Mapped the requested part goal to `{job_context['printer']}` with `{job_context['filament']}`. "
            f"Placement suggestion: {job_context['orientation']} This stays in draft planning mode until geometry is confirmed. {calibrator_handoff}"
        )
        architect_summary = (
            f"{persona_tone['G-Code Architect']} {slicer_message} "
            f"Prepared the draft manufacturing handoff for `{job_context['printer']}` using `{job_context['gcode_flavor']}`. {architect_handoff}"
        )
    vault_summary = (
        f"{persona_tone['Cipher Vault']} Prepared the delivery package for `{job_context['part_label']}` "
        f"with the selected release path and approval gate. {vault_handoff}"
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
    agent_handoffs: dict[str, tuple[str, str]],
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
        if mesh_analysis.get("risk_level"):
            mesh_notes.append(f"Risk level: {mesh_analysis['risk_level']}")
        if mesh_analysis.get("geometry_profile"):
            mesh_notes.append(f"Geometry profile: {mesh_analysis['geometry_profile']}")
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
        If something is wrong, say you are holding the handoff and why.
        If things look acceptable, say you are passing the job to the next role.
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
        Expected handoff state: {agent_handoffs[agent_name][0]}
        Handoff guidance: {agent_handoffs[agent_name][1]}
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
    agent_handoffs: dict[str, tuple[str, str]],
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
            agent_handoffs,
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
            "CipherSlice can analyze, optimize, and package the job, but this environment still uses a preview print file until a real slicer backend is connected.",
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


def open_guided_workspace() -> None:
    st.session_state["experience_mode"] = "Beginner"
    st.switch_page("app.py")


def open_advanced_workspace() -> None:
    st.session_state["experience_mode"] = "Advanced"
    st.switch_page("pages/Advanced_Workspace.py")


def return_to_guided_workspace(target: str | None = None) -> None:
    if target:
        st.session_state["review_workspace_target"] = target
    st.switch_page("app.py")


def clear_active_job() -> None:
    active_job = st.session_state.get("active_job")
    if active_job:
        approval_key = active_job.get("approval_key")
        if approval_key:
            st.session_state.pop(approval_key, None)
    st.session_state["active_job"] = None


def reset_live_plan_state(
    artifact_hash: str,
    recommended_plan: dict[str, str | float | int | bool],
    quality_profile: str,
    print_goal: str,
    support_strategy: str,
    adhesion_strategy: str,
    delivery_mode: str,
    filament: str,
    printer_profile: dict[str, object],
) -> None:
    base_speed = int(recommended_plan["print_speed"])
    base_layer = float(recommended_plan["layer_height"])
    st.session_state[f"edit_quality_{artifact_hash}"] = quality_profile
    st.session_state[f"edit_goal_{artifact_hash}"] = print_goal
    st.session_state[f"edit_layer_{artifact_hash}"] = base_layer
    st.session_state[f"edit_speed_{artifact_hash}"] = base_speed
    st.session_state[f"edit_support_{artifact_hash}"] = support_strategy
    st.session_state[f"edit_adhesion_{artifact_hash}"] = adhesion_strategy
    st.session_state[f"edit_infill_{artifact_hash}"] = int(recommended_plan["infill_percent"])
    st.session_state[f"edit_walls_{artifact_hash}"] = int(recommended_plan["wall_loops"])
    st.session_state[f"edit_delivery_{artifact_hash}"] = delivery_mode
    st.session_state[f"edit_filament_{artifact_hash}"] = filament
    st.session_state[f"edit_gcode_flavor_{artifact_hash}"] = str(printer_profile.get("gcode_flavor", "Unknown"))
    st.session_state[f"edit_nozzle_{artifact_hash}"] = int(recommended_plan["nozzle_temp"])
    st.session_state[f"edit_bed_{artifact_hash}"] = int(recommended_plan["bed_temp"])
    st.session_state[f"edit_flow_{artifact_hash}"] = 100
    st.session_state[f"edit_support_density_{artifact_hash}"] = int(recommended_plan.get("support_density", 24))
    st.session_state[f"edit_top_layers_{artifact_hash}"] = int(recommended_plan.get("top_layers", 4))
    st.session_state[f"edit_bottom_layers_{artifact_hash}"] = int(recommended_plan.get("bottom_layers", 4))
    st.session_state[f"edit_retraction_{artifact_hash}"] = float(recommended_plan.get("retraction_length", 1.2))
    st.session_state[f"edit_acceleration_{artifact_hash}"] = int(recommended_plan.get("acceleration", 3000))
    st.session_state[f"edit_seam_{artifact_hash}"] = str(recommended_plan.get("seam_position", "Rear"))
    st.session_state[f"edit_outer_wall_speed_{artifact_hash}"] = int(recommended_plan.get("outer_wall_speed", max(15, int(base_speed * 0.55))))
    st.session_state[f"edit_inner_wall_speed_{artifact_hash}"] = int(recommended_plan.get("inner_wall_speed", max(18, int(base_speed * 0.82))))
    st.session_state[f"edit_travel_speed_{artifact_hash}"] = int(recommended_plan.get("travel_speed", min(400, int(base_speed * 2.2))))
    st.session_state[f"edit_infill_pattern_{artifact_hash}"] = str(recommended_plan.get("infill_pattern", "Gyroid"))
    st.session_state[f"edit_support_interface_{artifact_hash}"] = bool(recommended_plan.get("support_interface", recommended_plan.get("support_enabled", False)))
    st.session_state[f"edit_support_pattern_{artifact_hash}"] = str(recommended_plan.get("support_pattern", "Lines"))
    st.session_state[f"edit_brim_width_{artifact_hash}"] = float(recommended_plan.get("brim_width", 6.0 if recommended_plan.get("adhesion") == "Brim" else 0.0))
    st.session_state[f"edit_skirt_loops_{artifact_hash}"] = int(recommended_plan.get("skirt_loops", 2))
    st.session_state[f"edit_first_layer_height_{artifact_hash}"] = float(recommended_plan.get("first_layer_height", max(base_layer, round(base_layer * 1.4, 2))))
    st.session_state[f"edit_first_layer_speed_{artifact_hash}"] = int(recommended_plan.get("first_layer_speed", max(15, int(base_speed * 0.45))))
    st.session_state[f"edit_first_layer_flow_{artifact_hash}"] = int(recommended_plan.get("first_layer_flow", 100))
    st.session_state[f"edit_jerk_{artifact_hash}"] = int(recommended_plan.get("jerk_control", 8))
    st.session_state[f"edit_stability_{artifact_hash}"] = str(recommended_plan.get("stability_mode", "Balanced"))
    st.session_state[f"edit_profile_preset_{artifact_hash}"] = str(recommended_plan.get("profile_preset", "Recommended"))
    st.session_state[f"edit_restore_point_{artifact_hash}"] = "Recommended baseline"


def build_tuning_preset_values(
    preset_name: str,
    recommended_plan: dict[str, str | float | int | bool],
    printer_profile: dict[str, object],
) -> dict[str, str | float | int | bool]:
    base_speed = int(recommended_plan["print_speed"])
    base_layer = float(recommended_plan["layer_height"])
    nozzle_diameter = float(printer_profile.get("nozzle_diameter", 0.4))
    values: dict[str, str | float | int | bool] = {
        "layer_height": base_layer,
        "print_speed": base_speed,
        "infill_percent": int(recommended_plan["infill_percent"]),
        "wall_loops": int(recommended_plan["wall_loops"]),
        "outer_wall_speed": int(recommended_plan.get("outer_wall_speed", max(15, int(base_speed * 0.55)))),
        "inner_wall_speed": int(recommended_plan.get("inner_wall_speed", max(18, int(base_speed * 0.82)))),
        "travel_speed": int(recommended_plan.get("travel_speed", min(400, int(base_speed * 2.2)))),
        "top_layers": int(recommended_plan.get("top_layers", 4)),
        "bottom_layers": int(recommended_plan.get("bottom_layers", 4)),
        "flow_multiplier": int(recommended_plan.get("flow_multiplier", 100)),
        "first_layer_height": float(recommended_plan.get("first_layer_height", max(base_layer, round(base_layer * 1.4, 2)))),
        "first_layer_speed": int(recommended_plan.get("first_layer_speed", max(15, int(base_speed * 0.45)))),
        "first_layer_flow": int(recommended_plan.get("first_layer_flow", 100)),
        "support_density": int(recommended_plan.get("support_density", 24)),
        "support_interface": bool(recommended_plan.get("support_interface", recommended_plan.get("support_enabled", False))),
        "support_pattern": str(recommended_plan.get("support_pattern", "Lines")),
        "infill_pattern": str(recommended_plan.get("infill_pattern", "Gyroid")),
        "brim_width": float(recommended_plan.get("brim_width", 6.0 if recommended_plan.get("adhesion") == "Brim" else 0.0)),
        "skirt_loops": int(recommended_plan.get("skirt_loops", 2)),
        "retraction_length": float(recommended_plan.get("retraction_length", 1.2)),
        "acceleration": int(recommended_plan.get("acceleration", 3000)),
        "jerk_control": int(recommended_plan.get("jerk_control", 8)),
        "seam_position": str(recommended_plan.get("seam_position", "Rear")),
        "stability_mode": str(recommended_plan.get("stability_mode", "Balanced")),
    }
    if preset_name == "Strength-first":
        values.update(
            {
                "layer_height": round(max(0.12, base_layer), 2),
                "print_speed": max(25, int(base_speed * 0.9)),
                "infill_percent": min(55, max(values["infill_percent"], 35)),
                "wall_loops": min(6, max(values["wall_loops"], 4)),
                "top_layers": min(10, max(values["top_layers"], 5)),
                "bottom_layers": min(10, max(values["bottom_layers"], 5)),
                "support_density": max(values["support_density"], 28),
                "support_interface": True,
                "infill_pattern": "Gyroid",
                "stability_mode": "Stable",
                "acceleration": min(values["acceleration"], 2600),
            }
        )
    elif preset_name == "Quality-first":
        values.update(
            {
                "layer_height": round(max(0.08, min(values["layer_height"], max(0.08, nozzle_diameter * 0.3))), 2),
                "print_speed": max(18, int(base_speed * 0.72)),
                "outer_wall_speed": max(12, int(base_speed * 0.4)),
                "inner_wall_speed": max(15, int(base_speed * 0.62)),
                "travel_speed": max(80, int(values["travel_speed"] * 0.85)),
                "top_layers": min(12, max(values["top_layers"], 6)),
                "seam_position": "Rear",
                "stability_mode": "Surface-first",
                "acceleration": min(values["acceleration"], 2200),
            }
        )
    elif preset_name == "Speed-first":
        values.update(
            {
                "layer_height": round(min(max(0.2, values["layer_height"]), max(0.2, nozzle_diameter * 0.6)), 2),
                "print_speed": min(280, max(35, int(base_speed * 1.18))),
                "outer_wall_speed": min(180, max(20, int(base_speed * 0.8))),
                "inner_wall_speed": min(220, max(28, int(base_speed * 1.08))),
                "travel_speed": min(450, max(120, int(values["travel_speed"] * 1.08))),
                "infill_pattern": "Grid",
                "support_interface": False,
                "stability_mode": "Fast",
                "acceleration": min(6000, max(values["acceleration"], 3600)),
            }
        )
    elif preset_name == "Prototype-first":
        values.update(
            {
                "layer_height": round(min(max(0.2, values["layer_height"]), max(0.24, nozzle_diameter * 0.7)), 2),
                "print_speed": min(250, max(30, int(base_speed * 1.08))),
                "infill_percent": min(values["infill_percent"], 12),
                "wall_loops": min(values["wall_loops"], 2),
                "top_layers": min(values["top_layers"], 3),
                "bottom_layers": min(values["bottom_layers"], 3),
                "support_density": min(values["support_density"], 15),
                "infill_pattern": "Lines",
                "stability_mode": "Prototype",
            }
        )
    return values


def apply_tuning_preset_to_state(
    artifact_hash: str,
    preset_name: str,
    recommended_plan: dict[str, str | float | int | bool],
    printer_profile: dict[str, object],
) -> None:
    values = build_tuning_preset_values(preset_name, recommended_plan, printer_profile)
    state_map = {
        "layer_height": f"edit_layer_{artifact_hash}",
        "print_speed": f"edit_speed_{artifact_hash}",
        "infill_percent": f"edit_infill_{artifact_hash}",
        "wall_loops": f"edit_walls_{artifact_hash}",
        "outer_wall_speed": f"edit_outer_wall_speed_{artifact_hash}",
        "inner_wall_speed": f"edit_inner_wall_speed_{artifact_hash}",
        "travel_speed": f"edit_travel_speed_{artifact_hash}",
        "top_layers": f"edit_top_layers_{artifact_hash}",
        "bottom_layers": f"edit_bottom_layers_{artifact_hash}",
        "flow_multiplier": f"edit_flow_{artifact_hash}",
        "first_layer_height": f"edit_first_layer_height_{artifact_hash}",
        "first_layer_speed": f"edit_first_layer_speed_{artifact_hash}",
        "first_layer_flow": f"edit_first_layer_flow_{artifact_hash}",
        "support_density": f"edit_support_density_{artifact_hash}",
        "support_interface": f"edit_support_interface_{artifact_hash}",
        "support_pattern": f"edit_support_pattern_{artifact_hash}",
        "infill_pattern": f"edit_infill_pattern_{artifact_hash}",
        "brim_width": f"edit_brim_width_{artifact_hash}",
        "skirt_loops": f"edit_skirt_loops_{artifact_hash}",
        "retraction_length": f"edit_retraction_{artifact_hash}",
        "acceleration": f"edit_acceleration_{artifact_hash}",
        "jerk_control": f"edit_jerk_{artifact_hash}",
        "seam_position": f"edit_seam_{artifact_hash}",
        "stability_mode": f"edit_stability_{artifact_hash}",
    }
    for field, state_key in state_map.items():
        st.session_state[state_key] = values[field]
    st.session_state[f"edit_profile_preset_{artifact_hash}"] = preset_name


def extract_plan_controls(plan: dict[str, str | float | int | bool]) -> dict[str, str | float | int | bool]:
    return {
        "layer_height": float(plan.get("layer_height", 0.2)),
        "print_speed": int(plan.get("print_speed", 50)),
        "infill_percent": int(plan.get("infill_percent", 20)),
        "wall_loops": int(plan.get("wall_loops", 3)),
        "nozzle_temp": int(plan.get("nozzle_temp", 220)),
        "bed_temp": int(plan.get("bed_temp", 60)),
        "flow_multiplier": int(plan.get("flow_multiplier", 100)),
        "support_density": int(plan.get("support_density", 24)),
        "top_layers": int(plan.get("top_layers", 4)),
        "bottom_layers": int(plan.get("bottom_layers", 4)),
        "retraction_length": float(plan.get("retraction_length", 1.2)),
        "acceleration": int(plan.get("acceleration", 3000)),
        "seam_position": str(plan.get("seam_position", "Rear")),
        "gcode_flavor": str(plan.get("gcode_flavor", "Unknown")),
        "outer_wall_speed": int(plan.get("outer_wall_speed", max(15, int(int(plan.get("print_speed", 50)) * 0.55)))),
        "inner_wall_speed": int(plan.get("inner_wall_speed", max(18, int(int(plan.get("print_speed", 50)) * 0.82)))),
        "travel_speed": int(plan.get("travel_speed", min(400, int(int(plan.get("print_speed", 50)) * 2.2)))),
        "infill_pattern": str(plan.get("infill_pattern", "Gyroid")),
        "support_interface": bool(plan.get("support_interface", plan.get("support_enabled", False))),
        "support_pattern": str(plan.get("support_pattern", "Lines")),
        "brim_width": float(plan.get("brim_width", 6.0 if plan.get("adhesion") == "Brim" else 0.0)),
        "skirt_loops": int(plan.get("skirt_loops", 2)),
        "first_layer_height": float(plan.get("first_layer_height", max(float(plan.get("layer_height", 0.2)), round(float(plan.get("layer_height", 0.2)) * 1.4, 2)))),
        "first_layer_speed": int(plan.get("first_layer_speed", max(15, int(int(plan.get("print_speed", 50)) * 0.45)))),
        "first_layer_flow": int(plan.get("first_layer_flow", 100)),
        "jerk_control": int(plan.get("jerk_control", 8)),
        "stability_mode": str(plan.get("stability_mode", "Balanced")),
        "profile_preset": str(plan.get("profile_preset", "Recommended")),
        "adhesion": str(plan.get("adhesion", "Skirt")),
        "support_enabled": bool(plan.get("support_enabled", False)),
    }


def apply_snapshot_to_state(artifact_hash: str, snapshot: dict[str, object]) -> None:
    controls = dict(snapshot.get("controls", {}))
    state_map = {
        "layer_height": f"edit_layer_{artifact_hash}",
        "print_speed": f"edit_speed_{artifact_hash}",
        "infill_percent": f"edit_infill_{artifact_hash}",
        "wall_loops": f"edit_walls_{artifact_hash}",
        "nozzle_temp": f"edit_nozzle_{artifact_hash}",
        "bed_temp": f"edit_bed_{artifact_hash}",
        "flow_multiplier": f"edit_flow_{artifact_hash}",
        "support_density": f"edit_support_density_{artifact_hash}",
        "top_layers": f"edit_top_layers_{artifact_hash}",
        "bottom_layers": f"edit_bottom_layers_{artifact_hash}",
        "retraction_length": f"edit_retraction_{artifact_hash}",
        "acceleration": f"edit_acceleration_{artifact_hash}",
        "seam_position": f"edit_seam_{artifact_hash}",
        "gcode_flavor": f"edit_gcode_flavor_{artifact_hash}",
        "outer_wall_speed": f"edit_outer_wall_speed_{artifact_hash}",
        "inner_wall_speed": f"edit_inner_wall_speed_{artifact_hash}",
        "travel_speed": f"edit_travel_speed_{artifact_hash}",
        "infill_pattern": f"edit_infill_pattern_{artifact_hash}",
        "support_interface": f"edit_support_interface_{artifact_hash}",
        "support_pattern": f"edit_support_pattern_{artifact_hash}",
        "brim_width": f"edit_brim_width_{artifact_hash}",
        "skirt_loops": f"edit_skirt_loops_{artifact_hash}",
        "first_layer_height": f"edit_first_layer_height_{artifact_hash}",
        "first_layer_speed": f"edit_first_layer_speed_{artifact_hash}",
        "first_layer_flow": f"edit_first_layer_flow_{artifact_hash}",
        "jerk_control": f"edit_jerk_{artifact_hash}",
        "stability_mode": f"edit_stability_{artifact_hash}",
        "profile_preset": f"edit_profile_preset_{artifact_hash}",
    }
    for field, state_key in state_map.items():
        if field in controls:
            st.session_state[state_key] = controls[field]
    st.session_state[f"edit_restore_point_{artifact_hash}"] = str(snapshot.get("label", "Saved snapshot"))


def ensure_plan_snapshot_baseline(
    artifact_hash: str,
    recommended_plan: dict[str, str | float | int | bool],
    filename: str,
    printer: str,
    filament: str,
) -> None:
    snapshot_key = f"plan_snapshots_{artifact_hash}"
    if snapshot_key not in st.session_state:
        st.session_state[snapshot_key] = [
            {
                "label": "Recommended baseline",
                "filename": filename,
                "printer": printer,
                "filament": filament,
                "controls": extract_plan_controls(recommended_plan),
                "kind": "baseline",
            }
        ]


def save_plan_snapshot(
    artifact_hash: str,
    label: str,
    filename: str,
    printer: str,
    filament: str,
    plan: dict[str, str | float | int | bool],
    reason: str,
) -> None:
    snapshot_key = f"plan_snapshots_{artifact_hash}"
    snapshots = list(st.session_state.get(snapshot_key, []))
    snapshots.append(
        {
            "label": label,
            "filename": filename,
            "printer": printer,
            "filament": filament,
            "controls": extract_plan_controls(plan),
            "kind": reason,
        }
    )
    st.session_state[snapshot_key] = snapshots[-8:]


def build_snapshot_diff_lines(
    left_snapshot: dict[str, object],
    right_snapshot: dict[str, object],
) -> list[str]:
    left_controls = dict(left_snapshot.get("controls", {}))
    right_controls = dict(right_snapshot.get("controls", {}))
    labels = {
        "layer_height": "Layer height",
        "print_speed": "Print speed",
        "infill_percent": "Infill",
        "wall_loops": "Wall loops",
        "nozzle_temp": "Nozzle temp",
        "bed_temp": "Bed temp",
        "flow_multiplier": "Flow multiplier",
        "support_density": "Support density",
        "top_layers": "Top layers",
        "bottom_layers": "Bottom layers",
        "retraction_length": "Retraction",
        "acceleration": "Acceleration",
        "seam_position": "Seam position",
        "outer_wall_speed": "Outer wall speed",
        "inner_wall_speed": "Inner wall speed",
        "travel_speed": "Travel speed",
        "infill_pattern": "Infill pattern",
        "support_interface": "Support interface",
        "support_pattern": "Support pattern",
        "brim_width": "Brim width",
        "skirt_loops": "Skirt loops",
        "first_layer_height": "First-layer height",
        "first_layer_speed": "First-layer speed",
        "first_layer_flow": "First-layer flow",
        "jerk_control": "Jerk control",
        "stability_mode": "Stability mode",
        "profile_preset": "Profile preset",
    }
    lines: list[str] = []
    for field, label in labels.items():
        if left_controls.get(field) != right_controls.get(field):
            lines.append(f"{label}: `{left_controls.get(field)}` -> `{right_controls.get(field)}`")
    return lines


def build_snapshot_export_text(snapshot: dict[str, object]) -> str:
    controls = dict(snapshot.get("controls", {}))
    return textwrap.dedent(
        f"""
        CipherSlice Plan Snapshot

        Label: {snapshot.get('label', 'Unnamed snapshot')}
        Part: {snapshot.get('filename', 'Unknown')}
        Printer: {snapshot.get('printer', 'Unknown')}
        Filament: {snapshot.get('filament', 'Unknown')}
        Snapshot type: {snapshot.get('kind', 'manual')}

        Controls:
        {json.dumps(controls, indent=2)}
        """
    ).strip()


def build_what_if_plan_summary(
    uploaded_file,
    printer_name: str,
    printer_profile: dict[str, object],
    filament: str,
    quality_profile: str,
    print_goal: str,
    support_strategy: str,
    adhesion_strategy: str,
    auto_scale_mesh: bool,
) -> tuple[dict[str, object] | None, dict[str, str | float | int | bool], float, str]:
    mesh_analysis = analyze_mesh(uploaded_file, printer_name, printer_profile, auto_scale_mesh)
    plan = optimize_print_plan(
        printer_profile,
        filament,
        quality_profile,
        print_goal,
        support_strategy,
        adhesion_strategy,
    )
    plan = refine_plan_for_geometry(plan, mesh_analysis, support_strategy, printer_profile)
    risk_lookup = {"Low": 0.98, "Medium": 0.88, "High": 0.72, "Unknown": 0.8}
    score = risk_lookup.get(str(mesh_analysis.get("risk_level", "Unknown")), 0.8)
    if mesh_analysis.get("issues"):
        score -= 0.12
    if not mesh_analysis.get("mesh_ok", True):
        score -= 0.12
    score = max(0.45, min(0.99, score))
    fit_state = "Fits cleanly" if mesh_analysis.get("mesh_ok", True) and not mesh_analysis.get("issues") else "Needs review"
    return mesh_analysis, plan, score, fit_state


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

    profile["family"] = "Custom / user-defined"
    profile["printer_note"] = "Fallback profile for unsupported or unusual machines. Double-check firmware flavor, nozzle size, and full X/Y/Z volume before trusting the plan."
    profile["bed_shape"] = f"{int(custom_width)} x {int(custom_depth)} mm"
    profile["max_height_mm"] = custom_height
    profile["nozzle_diameter"] = round(custom_nozzle, 2)
    profile["gcode_flavor"] = custom_gcode_flavor
    profile["adhesion_default"] = "Large-format custom surface"
    profile["speed"] = {"PLA": 95, "PETG": 75, "ABS": 65, "ASA": 62, "TPU": 28, "Nylon": 45, "PC": 42, "CF Nylon": 40}
    profile["bed_shape_type"] = custom_bed_shape
    profile["heated_bed"] = custom_heated_bed
    profile["heated_chamber"] = custom_heated_chamber
    profile["start_gcode"] = custom_start_gcode.strip()
    profile["end_gcode"] = custom_end_gcode.strip()
    profile["orientation"] = (
        "Favor a wide, stable first layer and reduce tall unsupported features. Large-format jobs benefit from slower speed and stronger adhesion."
    )
    return profile


def get_profile_material_value(profile: dict[str, object], bucket: str, filament: str) -> int:
    values = dict(profile.get(bucket, {}))
    base_filament = FILAMENT_BASE_MAP.get(filament, filament)
    if filament in values:
        return int(values[filament])
    if base_filament in values:
        return int(values[base_filament])
    return int(values.get("PLA", 0))


def get_base_filament(filament: str) -> str:
    return FILAMENT_BASE_MAP.get(filament, filament)


def is_abrasive_filament(filament: str) -> bool:
    return filament in ABRASIVE_FILAMENTS


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


def build_confidence_explanation(
    mode: str,
    overall_confidence: float,
    slicer_path: str | None,
    objections: list[str],
) -> list[str]:
    confidence_percent = overall_confidence * 100
    notes = [
        f"Current review confidence is {confidence_percent:.1f}%.",
        "Confidence is CipherSlice's software review score for this job, not a promise that the final physical print will be perfect.",
        "The final number follows the most cautious review role in the chain, so one weak handoff can hold the whole job back.",
    ]
    if mode != "Reliable Print Mode":
        notes.append("Blueprint jobs stay held because a 2D drawing still needs validated 3D geometry before slicing.")
    elif not slicer_path:
        notes.append("Confidence is intentionally capped because no real slicer backend is connected yet.")
        notes.append("Different files may still share similar settings until real slicing and deeper geometry checks are available.")
    elif objections:
        notes.append("Confidence is held because at least one review blocker still needs to be resolved.")
    else:
        notes.append("A slicer backend is connected, so the plan can move closer to production review after user approval.")
    if confidence_percent < 94:
        notes.append("CipherSlice requires at least 94% confidence before claiming a production-ready release.")
    else:
        notes.append("This clears the software review threshold, but the user still has final approval.")
    return notes


def build_pre_printer_checklist(
    mode: str,
    slicer_path: str | None,
    connector_url: str | None,
    delivery_mode: str,
    is_production_print_file: bool,
) -> list[tuple[str, str]]:
    if mode != "Reliable Print Mode":
        return [
            ("Validated 3D model", "Still needed"),
            ("Slicer backend", "Still needed after geometry exists"),
            ("Printer access", "Not needed yet"),
            ("Safe output", "Draft brief only"),
        ]
    return [
        ("Uploaded mesh", "Ready"),
        ("Slicer backend", "Connected" if slicer_path else "Still needed"),
        ("Production print file", "Ready" if is_production_print_file else "Preview only"),
        ("Printer connector", "Connected" if connector_url else "Optional until direct printer handoff"),
        ("Delivery route", delivery_mode),
    ]


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
) -> bytes:
    bundle = io.BytesIO()
    model_suffix = "." + uploaded_file.name.rsplit(".", 1)[-1].lower()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"input_model{model_suffix}", uploaded_file.getvalue())
        archive.writestr("cipher_plan.ini", build_prusaslicer_config(slicer_plan))
        archive.writestr("cipher_handoff_contract.txt", format_handoff_contract_comments(handoff_contract))
        archive.writestr("cipher_handoff_contract.json", json.dumps(handoff_contract, indent=2))
        archive.writestr("planned_output_preview.gcode", primary_artifact)
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
                - planned_output_preview.gcode: preview print file currently shown in the app

                Runtime note:
                {slicer_message}

                Suggested next step:
                1. Open the model in a supported slicer workflow.
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
        4. If the slicer backend is missing, treat the output as a planning preview until real slicing is completed.
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
        ("Outer wall speed", recommended_plan.get("outer_wall_speed"), optimized_plan.get("outer_wall_speed")),
        ("Inner wall speed", recommended_plan.get("inner_wall_speed"), optimized_plan.get("inner_wall_speed")),
        ("Travel speed", recommended_plan.get("travel_speed"), optimized_plan.get("travel_speed")),
        ("Nozzle temp", recommended_plan["nozzle_temp"], optimized_plan["nozzle_temp"]),
        ("Bed temp", recommended_plan["bed_temp"], optimized_plan["bed_temp"]),
        ("Flow multiplier", recommended_plan.get("flow_multiplier"), optimized_plan.get("flow_multiplier")),
        ("First-layer height", recommended_plan.get("first_layer_height"), optimized_plan.get("first_layer_height")),
        ("First-layer speed", recommended_plan.get("first_layer_speed"), optimized_plan.get("first_layer_speed")),
        ("First-layer flow", recommended_plan.get("first_layer_flow"), optimized_plan.get("first_layer_flow")),
        ("Support enabled", recommended_plan["support_enabled"], optimized_plan["support_enabled"]),
        ("Support density", recommended_plan.get("support_density"), optimized_plan.get("support_density")),
        ("Support interface", recommended_plan.get("support_interface"), optimized_plan.get("support_interface")),
        ("Support pattern", recommended_plan.get("support_pattern"), optimized_plan.get("support_pattern")),
        ("Adhesion", recommended_plan["adhesion"], optimized_plan["adhesion"]),
        ("Brim width", recommended_plan.get("brim_width"), optimized_plan.get("brim_width")),
        ("Skirt loops", recommended_plan.get("skirt_loops"), optimized_plan.get("skirt_loops")),
        ("Top layers", recommended_plan.get("top_layers"), optimized_plan.get("top_layers")),
        ("Bottom layers", recommended_plan.get("bottom_layers"), optimized_plan.get("bottom_layers")),
        ("Retraction", recommended_plan.get("retraction_length"), optimized_plan.get("retraction_length")),
        ("Acceleration", recommended_plan.get("acceleration"), optimized_plan.get("acceleration")),
        ("Jerk control", recommended_plan.get("jerk_control"), optimized_plan.get("jerk_control")),
        ("Seam position", recommended_plan.get("seam_position"), optimized_plan.get("seam_position")),
        ("Infill pattern", recommended_plan.get("infill_pattern"), optimized_plan.get("infill_pattern")),
        ("Stability mode", recommended_plan.get("stability_mode"), optimized_plan.get("stability_mode")),
        ("Profile preset", recommended_plan.get("profile_preset"), optimized_plan.get("profile_preset")),
        ("G-code flavor", recommended_plan.get("gcode_flavor"), optimized_plan.get("gcode_flavor")),
        ("Delivery mode", delivery_mode, delivery_mode),
    ]
    diffs: list[str] = []
    for label, recommended_value, current_value in comparisons:
        if recommended_value != current_value:
            diffs.append(f"{label}: recommended `{recommended_value}` -> current `{current_value}`")
    return diffs


def build_plan_change_cards(
    recommended_plan: dict[str, str | float | int | bool],
    optimized_plan: dict[str, str | float | int | bool],
) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    comparisons = [
        ("Layer height", recommended_plan["layer_height"], optimized_plan["layer_height"], "Lower layer height improves detail but can slow the print."),
        ("Infill", recommended_plan["infill_percent"], optimized_plan["infill_percent"], "Higher infill usually adds strength, time, and material use."),
        ("Wall loops", recommended_plan["wall_loops"], optimized_plan["wall_loops"], "More walls can help durability, but too many can swallow thin features."),
        ("Print speed", recommended_plan["print_speed"], optimized_plan["print_speed"], "Faster motion can save time but increase ringing, layer inconsistency, or instability."),
        ("Outer wall speed", recommended_plan.get("outer_wall_speed"), optimized_plan.get("outer_wall_speed"), "Outer wall speed affects visible surface quality more than inner structure speed."),
        ("Inner wall speed", recommended_plan.get("inner_wall_speed"), optimized_plan.get("inner_wall_speed"), "Inner wall speed changes how quickly the machine builds the internal shell."),
        ("Travel speed", recommended_plan.get("travel_speed"), optimized_plan.get("travel_speed"), "Travel speed changes stringing risk and motion aggression between features."),
        ("Nozzle temp", recommended_plan["nozzle_temp"], optimized_plan["nozzle_temp"], "Temperature changes affect bonding, stringing, and surface behavior."),
        ("Bed temp", recommended_plan["bed_temp"], optimized_plan["bed_temp"], "Bed heat changes first-layer grip and warp resistance."),
        ("Flow multiplier", recommended_plan.get("flow_multiplier"), optimized_plan.get("flow_multiplier"), "Flow changes can rescue underfill or distort part dimensions if pushed too far."),
        ("Support density", recommended_plan.get("support_density"), optimized_plan.get("support_density"), "Denser support can help overhangs but is harder to remove."),
        ("Support interface", recommended_plan.get("support_interface"), optimized_plan.get("support_interface"), "Support interface can improve the underside finish, but adds more contact and cleanup."),
        ("Support pattern", recommended_plan.get("support_pattern"), optimized_plan.get("support_pattern"), "Support pattern changes support strength and peel-away behavior."),
        ("Adhesion", recommended_plan["adhesion"], optimized_plan["adhesion"], "Adhesion changes shift first-layer safety and cleanup effort."),
        ("Brim width", recommended_plan.get("brim_width"), optimized_plan.get("brim_width"), "Brim width mainly affects first-layer grip on wide or tall parts."),
        ("Skirt loops", recommended_plan.get("skirt_loops"), optimized_plan.get("skirt_loops"), "Skirt loops are mostly a priming and consistency choice."),
        ("Top layers", recommended_plan.get("top_layers"), optimized_plan.get("top_layers"), "More top layers can help close surfaces but increase print time."),
        ("Bottom layers", recommended_plan.get("bottom_layers"), optimized_plan.get("bottom_layers"), "More bottom layers can strengthen the base but use more material."),
        ("First-layer height", recommended_plan.get("first_layer_height"), optimized_plan.get("first_layer_height"), "First-layer height strongly affects initial grip and surface squish."),
        ("First-layer speed", recommended_plan.get("first_layer_speed"), optimized_plan.get("first_layer_speed"), "First-layer speed is one of the biggest first-layer reliability levers."),
        ("First-layer flow", recommended_plan.get("first_layer_flow"), optimized_plan.get("first_layer_flow"), "First-layer flow changes how aggressively the part bonds to the bed."),
        ("Retraction", recommended_plan.get("retraction_length"), optimized_plan.get("retraction_length"), "Retraction changes can reduce stringing or create jams if pushed too far."),
        ("Acceleration", recommended_plan.get("acceleration"), optimized_plan.get("acceleration"), "Higher acceleration feels faster but can hurt print consistency on shaky parts."),
        ("Jerk control", recommended_plan.get("jerk_control"), optimized_plan.get("jerk_control"), "Jerk changes how abruptly the machine changes direction."),
        ("Seam position", recommended_plan.get("seam_position"), optimized_plan.get("seam_position"), "Seam changes mostly affect where surface marks collect."),
        ("Infill pattern", recommended_plan.get("infill_pattern"), optimized_plan.get("infill_pattern"), "Pattern changes internal strength direction and print rhythm."),
        ("Stability mode", recommended_plan.get("stability_mode"), optimized_plan.get("stability_mode"), "Stability mode explains whether the plan leans toward safety, speed, or surface finish."),
        ("Profile preset", recommended_plan.get("profile_preset"), optimized_plan.get("profile_preset"), "The preset signals the overall tuning personality of the current live plan."),
        ("G-code flavor", recommended_plan.get("gcode_flavor"), optimized_plan.get("gcode_flavor"), "Flavor changes must match the target firmware to avoid bad commands."),
    ]
    for label, recommended_value, current_value, reason in comparisons:
        if recommended_value == current_value:
            continue
        risk = "moderate"
        recommended_num = recommended_value if isinstance(recommended_value, (int, float)) else None
        current_num = current_value if isinstance(current_value, (int, float)) else None
        if label in {"Print speed", "Outer wall speed", "Nozzle temp", "Bed temp", "Acceleration", "Retraction", "First-layer height", "First-layer speed", "First-layer flow", "G-code flavor"}:
            risk = "watch closely"
        elif label in {"Wall loops", "Infill", "Support density"} and recommended_num is not None and current_num is not None and current_num > recommended_num:
            risk = "stronger but heavier"
        elif label in {"Layer height", "Flow multiplier", "Travel speed", "Jerk control"}:
            risk = "tuning-sensitive"
        cards.append(
            {
                "label": label,
                "recommended": str(recommended_value),
                "current": str(current_value),
                "risk": risk,
                "reason": reason,
            }
        )
    return cards


def build_plan_change_summary(cards: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    if not cards:
        return [
            ("Override count", "0", "The current live plan still matches CipherSlice's recommended path."),
            ("Risky overrides", "0", "No high-attention tuning changes are active right now."),
            ("Tradeoff tilt", "Balanced", "This plan is still sitting close to the safer recommended profile."),
        ]
    risk_count = sum(1 for card in cards if card["risk"] in {"watch closely", "tuning-sensitive"})
    strength_count = sum(1 for card in cards if card["risk"] == "stronger but heavier")
    if risk_count >= 4:
        tilt = "Aggressive"
        tilt_copy = "Several high-attention changes are active, so the plan is leaning further away from the safer baseline."
    elif strength_count >= 3:
        tilt = "Strength-heavy"
        tilt_copy = "This plan is leaning toward stronger shells and support at the cost of time or cleanup."
    else:
        tilt = "Balanced"
        tilt_copy = "The current changes look more like measured tuning than a full profile rewrite."
    return [
        ("Override count", str(len(cards)), "How many tracked settings moved away from CipherSlice's first recommendation."),
        ("Risky overrides", str(risk_count), "These are the settings most likely to change print behavior in noticeable ways."),
        ("Tradeoff tilt", tilt, tilt_copy),
    ]


def build_plan_tradeoff_estimate(
    recommended_plan: dict[str, str | float | int | bool],
    optimized_plan: dict[str, str | float | int | bool],
) -> list[tuple[str, str]]:
    rec_speed = float(recommended_plan.get("print_speed", 50))
    cur_speed = float(optimized_plan.get("print_speed", 50))
    rec_infill = float(recommended_plan.get("infill_percent", 20))
    cur_infill = float(optimized_plan.get("infill_percent", 20))
    rec_walls = float(recommended_plan.get("wall_loops", 3))
    cur_walls = float(optimized_plan.get("wall_loops", 3))
    rec_layers = float(recommended_plan.get("layer_height", 0.2))
    cur_layers = float(optimized_plan.get("layer_height", 0.2))
    time_factor = (rec_speed / max(cur_speed, 1.0)) * (rec_layers / max(cur_layers, 0.05))
    material_factor = ((cur_infill + (cur_walls * 6.0)) / max(rec_infill + (rec_walls * 6.0), 1.0))
    quality_delta = "Higher" if cur_layers < rec_layers or cur_speed < rec_speed else ("Lower" if cur_layers > rec_layers or cur_speed > rec_speed else "Similar")
    return [
        ("Time drift", f"{time_factor * 100:.0f}% of baseline"),
        ("Material drift", f"{material_factor * 100:.0f}% of baseline"),
        ("Surface tilt", quality_delta),
    ]


def restore_risky_recommended_settings(
    artifact_hash: str,
    recommended_plan: dict[str, str | float | int | bool],
) -> None:
    risky_state_map = {
        "print_speed": f"edit_speed_{artifact_hash}",
        "outer_wall_speed": f"edit_outer_wall_speed_{artifact_hash}",
        "nozzle_temp": f"edit_nozzle_{artifact_hash}",
        "bed_temp": f"edit_bed_{artifact_hash}",
        "first_layer_height": f"edit_first_layer_height_{artifact_hash}",
        "first_layer_speed": f"edit_first_layer_speed_{artifact_hash}",
        "first_layer_flow": f"edit_first_layer_flow_{artifact_hash}",
        "retraction_length": f"edit_retraction_{artifact_hash}",
        "acceleration": f"edit_acceleration_{artifact_hash}",
        "jerk_control": f"edit_jerk_{artifact_hash}",
        "gcode_flavor": f"edit_gcode_flavor_{artifact_hash}",
        "seam_position": f"edit_seam_{artifact_hash}",
    }
    for field, state_key in risky_state_map.items():
        if field in recommended_plan:
            st.session_state[state_key] = recommended_plan[field]


def build_geometry_fix_actions(mesh_analysis: dict[str, object] | None) -> list[str]:
    if not mesh_analysis:
        return ["Upload a mesh so CipherSlice can start geometry-specific fixes."]
    actions: list[str] = []
    if str(mesh_analysis.get("unsupported_risk")) in {"Widespread unsupported surfaces", "Localized unsupported pockets"}:
        actions.append("Try the recommended orientation first, then increase support only if the new posture still leaves exposed underside areas.")
    if str(mesh_analysis.get("bridge_risk")) in {"Bridge-heavy geometry", "Some bridging pressure"}:
        actions.append("Slow the part down slightly or choose a posture that shortens unsupported spans before adding more material everywhere.")
    if float(mesh_analysis.get("first_layer_contact_percent") or 0.0) < 16:
        actions.append("Use a brim or a flatter starting face so the print begins with a wider contact patch.")
    if str(mesh_analysis.get("thin_wall_risk")) in {"Thin-wall danger", "Thin-wall sensitive"}:
        actions.append("Reduce wall count or use a finer nozzle if preserving slim detail matters more than brute strength.")
    if str(mesh_analysis.get("warp_risk")) in {"High warp footprint", "Moderate warp footprint"}:
        actions.append("Keep first-layer grip stronger than usual and avoid unnecessary speed on wide parts.")
    if not actions:
        actions.append("No major geometry-specific fix path is active. The current part looks fairly cooperative for the selected machine.")
    return actions


def build_slicer_capability_report(
    slicer_label: str | None,
    slicer_path: str | None,
    printer_profile: dict[str, object],
    optimized_plan: dict[str, str | float | int | bool],
) -> list[tuple[str, str]]:
    flavor = str(optimized_plan.get("gcode_flavor", printer_profile.get("gcode_flavor", "Unknown")))
    engine_ok = bool(slicer_path)
    flavor_ok = bool(slicer_path) and any(token in (slicer_label or "").lower() for token in ("prusa", "orca", "slic3r", "cura"))
    custom_profile = bool(printer_profile.get("start_gcode") or printer_profile.get("end_gcode"))
    return [
        ("Engine detected", "Yes" if engine_ok else "No"),
        ("Engine family", slicer_label or "Not detected"),
        ("Flavor mapping", "Looks compatible" if flavor_ok else f"Review needed for `{flavor}`"),
        ("Custom start/end code", "Included" if custom_profile else "Not customized"),
        ("Release truth", "Can move toward real print file" if engine_ok else "Still planning preview only"),
    ]


def build_slicer_decision_notes(
    optimized_plan: dict[str, str | float | int | bool],
    mesh_analysis: dict[str, object] | None,
) -> list[str]:
    notes = [
        "The slicer will still decide the exact toolpath order, line placement, acceleration timing, and support geometry details.",
        "CipherSlice is deciding the strategy and the safer starting profile, not replacing the deterministic toolpath engine.",
    ]
    if mesh_analysis and mesh_analysis.get("recommended_orientation_label"):
        notes.append(f"CipherSlice will hand the slicer a preferred posture of `{mesh_analysis.get('recommended_orientation_label')}` for this part.")
    notes.append(f"The current seam strategy entering the slicer is `{optimized_plan.get('seam_position', 'Rear')}`.")
    return notes


def build_handoff_audit_trail(
    filename: str,
    artifact_hash: str,
    printer: str,
    filament: str,
    delivery_mode: str,
    optimized_plan: dict[str, str | float | int | bool],
    mesh_analysis: dict[str, object] | None,
    overall_confidence: float,
    objections: list[str],
) -> str:
    return textwrap.dedent(
        f"""
        CipherSlice Handoff Audit Trail

        Source file: {filename}
        Artifact hash: {artifact_hash}
        Printer: {printer}
        Filament: {filament}
        Delivery mode: {delivery_mode}
        Confidence: {overall_confidence * 100:.1f}%
        Recommended orientation: {mesh_analysis.get('recommended_orientation_label', 'Unknown') if mesh_analysis else 'Unknown'}
        Geometry risk: {mesh_analysis.get('risk_level', 'Unknown') if mesh_analysis else 'Unknown'}
        Thin-wall risk: {mesh_analysis.get('thin_wall_risk', 'Unknown') if mesh_analysis else 'Unknown'}
        Unsupported risk: {mesh_analysis.get('unsupported_risk', 'Unknown') if mesh_analysis else 'Unknown'}
        Bridge risk: {mesh_analysis.get('bridge_risk', 'Unknown') if mesh_analysis else 'Unknown'}
        Layer height: {optimized_plan.get('layer_height')}
        Infill: {optimized_plan.get('infill_percent')}%
        Wall loops: {optimized_plan.get('wall_loops')}
        Print speed: {optimized_plan.get('print_speed')} mm/s
        Support density: {optimized_plan.get('support_density')}
        Adhesion: {optimized_plan.get('adhesion')}
        G-code flavor: {optimized_plan.get('gcode_flavor')}
        Blockers: {len(objections)}

        Blocker details:
        {chr(10).join('- ' + item for item in objections) if objections else '- No active blockers in the software review chain.'}
        """
    ).strip()


def build_slicer_transition_notes(
    slicer_path: str | None,
    is_production_print_file: bool,
) -> list[tuple[str, str]]:
    if is_production_print_file:
        return [
            ("Print file status", "A real slicer backend is connected, so this workflow can produce a printer-targeted file instead of only a planning preview."),
            ("What changed", "The slicer is now responsible for the final toolpath generation, which makes the output more trustworthy than the fallback preview path."),
            ("Still not automatic", "Human approval and the final delivery route still matter before any real printer run should happen."),
        ]
    return [
        ("Print file status", "This is still a planning-stage preview, not final slicer-generated output."),
        ("What changes later", "Once a slicer backend is connected, CipherSlice can turn the approved plan into a real printer-targeted file."),
        ("Why that matters", "That slicer step is what turns recommendations into trustworthy motion commands for a specific machine."),
    ]


def build_machine_profile_notes(
    printer_profile: dict[str, object],
    filament: str,
) -> list[tuple[str, str]]:
    notes: list[tuple[str, str]] = []
    notes.append(("Firmware flavor", str(printer_profile.get("gcode_flavor", "Unknown"))))
    notes.append(("Bed shape", f"{printer_profile.get('bed_shape_type', 'Rectangular')} / {printer_profile.get('bed_shape', 'Unknown')}"))
    notes.append(("Nozzle setup", f"{float(printer_profile.get('nozzle_diameter', 0.4)):.2f} mm"))
    notes.append(("Heated bed", "Yes" if bool(printer_profile.get("heated_bed", True)) else "No"))
    notes.append(("Heated chamber", "Yes" if bool(printer_profile.get("heated_chamber", False)) else "No"))

    filament_key = get_base_filament(filament).lower()
    if filament_key in {"abs", "asa", "nylon", "pc", "cf nylon"}:
        notes.append(("Material fit", "This material is more demanding and benefits from a stable heat environment."))
    elif filament_key == "tpu":
        notes.append(("Material fit", "This material is flexible, so slower motion and cleaner filament feeding are safer."))
    else:
        notes.append(("Material fit", "This material is generally forgiving on a wider range of hobby printers."))
    if is_abrasive_filament(filament):
        notes.append(("Nozzle wear", "A hardened or wear-resistant nozzle is the safer long-term match for this fiber-filled material."))
    return notes


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

    configured_prusa = os.getenv("CIPHERSLICE_PRUSASLICER_PATH", "").strip()
    if configured_prusa and os.path.exists(configured_prusa):
        return "PrusaSlicer", configured_prusa

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
        r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer.exe",
        os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "PrusaSlicer", "prusa-slicer-console.exe"),
        os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "PrusaSlicer", "prusa-slicer.exe"),
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
    bed_limit = max(bed_x, bed_y)
    if largest < 0.5:
        return 1000.0, "Part appears microscopic. A 1000x scale can help when meter-authored geometry was interpreted as millimeters."
    if largest < 8:
        return 25.4, "Part appears extremely small. A 25.4x scale can help when inch-authored geometry was interpreted as millimeters."
    if largest < 40 and largest * 10 <= bed_limit * 1.25:
        return 10.0, "Part appears smaller than expected. A 10x scale can help when centimeter-authored geometry was interpreted as millimeters."
    if largest > bed_limit * 100:
        return 0.01, "Part appears massively oversized. A 0.01x scale can help when millimeter geometry was exported as meters."
    if largest > bed_limit * 5:
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
    base_filament = get_base_filament(filament)
    base_speed = get_profile_material_value(profile, "speed", filament)
    nozzle_temp = get_profile_material_value(profile, "nozzle", filament)
    bed_temp = get_profile_material_value(profile, "bed", filament)
    nozzle_diameter = float(profile.get("nozzle_diameter", 0.4))
    heated_bed = bool(profile.get("heated_bed", True))
    heated_chamber = bool(profile.get("heated_chamber", False))

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
            and (base_filament in {"PETG", "ABS", "ASA", "TPU", "Nylon", "PC", "CF Nylon"} or print_goal == "Functional strength")
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
    if nozzle_diameter >= 0.6:
        optimized_speed = max(28, int(optimized_speed * 0.95))
        layer_height_map = {
            "Draft / fast iteration": 0.32,
            "Balanced production": 0.24,
            "Detail / cosmetic": 0.16,
        }
    elif nozzle_diameter <= 0.25:
        optimized_speed = max(20, int(optimized_speed * 0.72))
        layer_height_map = {
            "Draft / fast iteration": 0.18,
            "Balanced production": 0.12,
            "Detail / cosmetic": 0.08,
        }
    if base_filament in {"ABS", "ASA", "Nylon", "PC", "CF Nylon"} and not heated_chamber:
        optimized_speed = max(20, int(optimized_speed * 0.9))
    if base_filament in {"PETG", "ABS", "ASA", "Nylon", "PC", "CF Nylon"} and not heated_bed:
        bed_temp = max(0, int(bed_temp * 0.85))
    support_pattern = "Grid" if base_filament in {"ABS", "ASA", "PC", "CF Nylon"} else "Lines"
    infill_pattern = "Gyroid" if print_goal == "Functional strength" else ("Lines" if print_goal == "Visual prototype" else "Grid")
    first_layer_height = round(max(layer_height_map[quality_profile], min(nozzle_diameter * 0.75, layer_height_map[quality_profile] * 1.4)), 2)
    return {
        "layer_height": layer_height_map[quality_profile],
        "infill_percent": infill_map[print_goal],
        "wall_loops": wall_map[print_goal],
        "print_speed": optimized_speed,
        "outer_wall_speed": max(15, int(optimized_speed * 0.55)),
        "inner_wall_speed": max(18, int(optimized_speed * 0.82)),
        "travel_speed": min(400, max(80, int(optimized_speed * 2.2))),
        "support_enabled": support_enabled,
        "support_density": 18 if not support_enabled else 24,
        "support_interface": support_enabled,
        "support_pattern": support_pattern,
        "support_threshold": 40,
        "adhesion": adhesion_map[adhesion_strategy],
        "brim_width": 6.0 if adhesion_map[adhesion_strategy] == "Brim" else 0.0,
        "skirt_loops": 2,
        "nozzle_temp": nozzle_temp,
        "bed_temp": bed_temp,
        "flow_multiplier": 100,
        "top_layers": 4,
        "bottom_layers": 4,
        "first_layer_height": first_layer_height,
        "first_layer_speed": max(15, int(optimized_speed * 0.45)),
        "first_layer_flow": 100,
        "retraction_length": 1.2 if filament != "TPU" else 0.6,
        "acceleration": 3000 if print_goal != "Visual prototype" else 2200,
        "jerk_control": 8,
        "seam_position": "Rear",
        "infill_pattern": infill_pattern,
        "stability_mode": "Balanced",
        "profile_preset": "Recommended",
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
        "longest_original_dimension_mm": None,
        "longest_corrected_dimension_mm": None,
        "likely_unit_case": "Unknown",
        "fit_margin_mm": None,
        "bed_use_percent": None,
        "height_use_percent": None,
        "risk_level": "Unknown",
        "mesh_ok": True,
        "issues": [],
        "warning_issues": [],
        "healthy_signals": [],
        "notes": [],
        "adaptive_notes": [],
        "geometry_profile": "Unknown",
        "detail_risk": "Unknown",
        "warp_risk": "Unknown",
        "fit_style": "Unknown",
        "thin_wall_risk": "Unknown",
        "unsupported_risk": "Unknown",
        "first_layer_contact_percent": None,
        "bridge_risk": "Unknown",
        "overhang_scope": "Unknown",
        "survivability_hint": "Unknown",
        "orientation_candidates": [],
        "recommended_orientation_label": "Unknown",
        "orientation_shift_note": "",
        "support_density_hint": "Unknown",
        "adhesion_hint": "Unknown",
        "preview_mesh": None,
        "component_count": 1,
        "hole_risk": "Unknown",
        "wall_thickness_estimate": "Unknown",
        "fragile_zone_summary": "Unknown",
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
        analysis["longest_original_dimension_mm"] = round(max(extents), 2) if extents else None
        scale_factor, scale_hint = infer_scale_adjustment(extents, printer_profile)
        analysis["scale_hint"] = scale_hint
        if scale_factor == 1000.0:
            analysis["likely_unit_case"] = "Meters interpreted as millimeters"
        elif scale_factor == 25.4:
            analysis["likely_unit_case"] = "Inches interpreted as millimeters"
        elif scale_factor == 10.0:
            analysis["likely_unit_case"] = "Centimeters interpreted as millimeters"
        elif scale_factor == 0.1:
            analysis["likely_unit_case"] = "Centimeters exported as millimeters"
        elif scale_factor == 0.01:
            analysis["likely_unit_case"] = "Meters exported as millimeters"
        else:
            analysis["likely_unit_case"] = "Millimeter-native or already plausible"
        if auto_scale:
            analysis["scale_factor"] = scale_factor
            analysis["scaled_extents_mm"] = [round(value * scale_factor, 2) for value in extents]
        else:
            analysis["scaled_extents_mm"] = extents
        if analysis["scaled_extents_mm"]:
            analysis["longest_corrected_dimension_mm"] = round(max(analysis["scaled_extents_mm"]), 2)
        analysis["preview_mesh"] = build_preview_mesh_data(mesh, float(analysis.get("scale_factor", 1.0)))

        if not mesh.is_watertight:
            analysis["mesh_ok"] = False
            analysis["issues"].append("Mesh is not watertight, so slicing may fail or produce weak shells.")

        test_extents = analysis["scaled_extents_mm"]
        xy_fits, fit_detail = footprint_fits_printer(test_extents[0], test_extents[1], printer_profile)
        analysis["fit_style"] = fit_detail
        if not xy_fits or test_extents[2] > max_height:
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
            face_density = (int(analysis["face_count"] or 0) / max(max_dim * max(min_dim, 1), 1)) if analysis["face_count"] else 0
            components = mesh.split(only_watertight=False) if hasattr(mesh, "split") else [mesh]
            component_count = len(components) if components is not None else 1
            analysis["component_count"] = component_count
            scale_area_factor = float(analysis.get("scale_factor", 1.0)) ** 2
            bbox_footprint_area = max(float(extents[0]) * float(extents[1]), 1.0)
            min_z = float(mesh.bounds[0][2])
            z_span = max(float(mesh.extents[2]), 0.01)
            centers = np.asarray(mesh.triangles_center)
            normals = np.asarray(mesh.face_normals)
            areas = np.asarray(mesh.area_faces)
            bottom_mask = (normals[:, 2] < -0.72) & (centers[:, 2] <= min_z + max(z_span * 0.025, 0.45))
            overhang_mask = (normals[:, 2] < -0.38) & (centers[:, 2] > min_z + max(z_span * 0.08, 0.8))
            bridge_mask = (normals[:, 2] < -0.76) & (centers[:, 2] > min_z + max(z_span * 0.18, 1.2))
            base_contact_area = float(areas[bottom_mask].sum()) * scale_area_factor if len(areas) else 0.0
            overhang_area_ratio = float(areas[overhang_mask].sum() / max(float(areas.sum()), 1.0)) if len(areas) else 0.0
            bridge_area_ratio = float(areas[bridge_mask].sum() / max(float(areas.sum()), 1.0)) if len(areas) else 0.0
            base_contact_ratio = base_contact_area / max(test_extents[0] * test_extents[1], 1.0)
            analysis["bed_use_percent"] = round(min(100.0, bed_fill_ratio * 100), 1)
            analysis["height_use_percent"] = round(min(100.0, (test_extents[2] / max(max_height, 1)) * 100), 1)
            analysis["first_layer_contact_percent"] = round(min(100.0, base_contact_ratio * 100), 1)
            analysis["fit_margin_mm"] = round(
                min(bed_x - test_extents[0], bed_y - test_extents[1], max_height - test_extents[2]),
                2,
            )
            if min_dim < 1.2:
                analysis["detail_risk"] = "Very small features"
                analysis["warning_issues"].append("Very small features were detected, so nozzles, wall count, and speed need more caution.")
            elif min_dim < 2.5 or face_density > 350:
                analysis["detail_risk"] = "Fine detail sensitive"
                analysis["warning_issues"].append("This model appears detail-sensitive, so larger nozzles or aggressive shell settings may soften edges.")
            else:
                analysis["detail_risk"] = "Normal detail scale"
                analysis["healthy_signals"].append("Feature scale looks reasonable for a standard hobby-printer workflow.")

            nozzle_diameter = float(printer_profile.get("nozzle_diameter", 0.4))
            if min_dim < nozzle_diameter * 2.1:
                analysis["thin_wall_risk"] = "Thin-wall danger"
                analysis["warning_issues"].append("Some features look close to or below a comfortable multi-line nozzle width, so walls may vanish or fuse together.")
            elif min_dim < nozzle_diameter * 3.4:
                analysis["thin_wall_risk"] = "Thin-wall sensitive"
                analysis["warning_issues"].append("This model has slim features, so wall count and nozzle size matter more than usual.")
            else:
                analysis["thin_wall_risk"] = "Normal wall scale"
                analysis["healthy_signals"].append("Feature thickness looks more forgiving for a standard nozzle.")
            estimated_lines = max(min_dim / max(nozzle_diameter * 0.48, 0.01), 0.0)
            analysis["wall_thickness_estimate"] = f"~{estimated_lines:.1f} line-widths at the thinnest visible scale"

            if face_density > 450 and min_dim < 3.0:
                analysis["hole_risk"] = "Small openings may close up"
                analysis["warning_issues"].append("Very fine openings or slots may print smaller than designed unless the nozzle and wall settings stay conservative.")
            elif face_density > 280:
                analysis["hole_risk"] = "Fine openings deserve review"
            else:
                analysis["hole_risk"] = "No obvious small-hole pressure"

            if bed_fill_ratio > 0.7 and test_extents[2] < max_height * 0.45:
                analysis["warp_risk"] = "High warp footprint"
                analysis["warning_issues"].append("This wide footprint can raise warping risk, especially on hotter materials or drafty machines.")
            elif bed_fill_ratio > 0.45:
                analysis["warp_risk"] = "Moderate warp footprint"
                analysis["warning_issues"].append("This footprint uses a lot of bed area, so first-layer grip matters more than usual.")
            else:
                analysis["warp_risk"] = "Low warp footprint"
                analysis["healthy_signals"].append("Bed coverage is moderate enough that warping pressure looks manageable.")

            if component_count > 1:
                analysis["unsupported_risk"] = "Multiple loose bodies"
                analysis["warning_issues"].append("The upload appears to contain multiple disconnected mesh bodies, so slicing may create separate islands or accidental loose pieces.")
            elif overhang_area_ratio > 0.16:
                analysis["unsupported_risk"] = "Widespread unsupported surfaces"
                analysis["warning_issues"].append("A large amount of the model appears to face downward away from the bed, so support planning matters much more here.")
            elif overhang_area_ratio > 0.07:
                analysis["unsupported_risk"] = "Localized unsupported pockets"
                analysis["warning_issues"].append("There are likely unsupported pockets or local overhangs that deserve support review.")
            else:
                analysis["unsupported_risk"] = "Low unsupported exposure"
                analysis["healthy_signals"].append("Most surfaces look support-friendly from the current print direction.")

            if bridge_area_ratio > 0.12:
                analysis["bridge_risk"] = "Bridge-heavy geometry"
                analysis["warning_issues"].append("This part appears to have several unsupported spans that may behave more like bridges than normal overhangs.")
            elif bridge_area_ratio > 0.05:
                analysis["bridge_risk"] = "Some bridging pressure"
                analysis["warning_issues"].append("There are a few likely bridge spans, so cooling and orientation deserve a closer look.")
            else:
                analysis["bridge_risk"] = "Low bridge pressure"

            if overhang_area_ratio > 0.18:
                analysis["overhang_scope"] = "Widespread"
            elif overhang_area_ratio > 0.08:
                analysis["overhang_scope"] = "Local pockets"
            else:
                analysis["overhang_scope"] = "Limited"

            if base_contact_ratio < 0.16:
                analysis["warning_issues"].append("The estimated first-layer contact patch is small, so the part may feel unstable unless orientation or adhesion improves.")
            elif base_contact_ratio > 0.38:
                analysis["healthy_signals"].append("The first-layer contact patch looks comfortably broad for a more stable start.")

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

            if analysis["first_layer_contact_percent"] is not None and analysis["first_layer_contact_percent"] < 16:
                analysis["adaptive_notes"].append("First-layer contact looks narrow. A flatter orientation or stronger brim strategy would likely help.")
            if analysis["unsupported_risk"] in {"Widespread unsupported surfaces", "Localized unsupported pockets"}:
                analysis["adaptive_notes"].append("Support pressure is not evenly distributed. A better orientation could remove some avoidable support burden.")
            if analysis["bridge_risk"] in {"Bridge-heavy geometry", "Some bridging pressure"}:
                analysis["adaptive_notes"].append("Bridge-heavy surfaces were detected. Cooling, slower bridge motion, or a rotated posture could improve the result.")

            fragile_zones: list[str] = []
            if analysis["thin_wall_risk"] in {"Thin-wall danger", "Thin-wall sensitive"}:
                fragile_zones.append("slim walls")
            if analysis["bridge_risk"] in {"Bridge-heavy geometry", "Some bridging pressure"}:
                fragile_zones.append("unsupported spans")
            if analysis["first_layer_contact_percent"] is not None and analysis["first_layer_contact_percent"] < 16:
                fragile_zones.append("narrow starting footprint")
            if analysis["unsupported_risk"] == "Multiple loose bodies":
                fragile_zones.append("disconnected islands")
            analysis["fragile_zone_summary"] = ", ".join(fragile_zones) if fragile_zones else "No strong fragile zones detected"

            if min_dim < nozzle_diameter * 2.1:
                analysis["survivability_hint"] = "Some small features may not survive a standard nozzle cleanly."
            elif min_dim < nozzle_diameter * 3.4:
                analysis["survivability_hint"] = "Fine features should survive, but only if walls and speed stay conservative."
            else:
                analysis["survivability_hint"] = "Feature scale looks reasonable for the current nozzle."

            recommended_support_density = 24
            if analysis["unsupported_risk"] == "Widespread unsupported surfaces":
                recommended_support_density = 30
            elif analysis["unsupported_risk"] == "Localized unsupported pockets":
                recommended_support_density = 22
            elif analysis["bridge_risk"] == "Bridge-heavy geometry":
                recommended_support_density = 28
            analysis["support_density_hint"] = f"{recommended_support_density}% suggested from geometry review"

            adhesion_hint = "Skirt is probably enough."
            if base_contact_ratio < 0.16 or height_ratio > 1.25:
                adhesion_hint = "Brim is strongly recommended."
            elif bed_fill_ratio > 0.55:
                adhesion_hint = "Brim is worth considering for a safer first layer."
            analysis["adhesion_hint"] = adhesion_hint

            orientation_candidates = build_orientation_candidates(test_extents, printer_profile, analysis)
            analysis["orientation_candidates"] = orientation_candidates
            if orientation_candidates:
                recommended_candidate = next((candidate for candidate in orientation_candidates if candidate.get("recommended")), orientation_candidates[0])
                analysis["recommended_orientation_label"] = str(recommended_candidate["label"])
                if recommended_candidate["label"] != "As loaded":
                    analysis["orientation_shift_note"] = (
                        f"CipherSlice would rather print this as `{recommended_candidate['label']}` than leave it exactly as loaded."
                    )
                    analysis["adaptive_notes"].append(analysis["orientation_shift_note"])
                else:
                    analysis["orientation_shift_note"] = "The uploaded orientation already looks like the best starting posture."
            if analysis["watertight"]:
                analysis["healthy_signals"].append("Mesh is watertight, which is a strong sign for cleaner slicing behavior.")
            if xy_fits and test_extents[2] <= max_height:
                analysis["healthy_signals"].append("The scaled part size fits the selected machine envelope.")
            if not analysis["mesh_ok"]:
                analysis["risk_level"] = "High"
            elif (
                height_ratio > 1.25
                or bed_fill_ratio > 0.55
                or slender_ratio > 8
                or min_dim < 1.2
                or base_contact_ratio < 0.16
                or overhang_area_ratio > 0.16
                or bridge_area_ratio > 0.12
            ):
                analysis["risk_level"] = "Medium"
            else:
                analysis["risk_level"] = "Low"
        if analysis["scale_factor"] != 1.0 and analysis["longest_corrected_dimension_mm"] is not None:
            analysis["notes"].append(
                f"{scale_hint} Longest corrected dimension: {analysis['longest_corrected_dimension_mm']:.2f} mm."
            )
        else:
            analysis["notes"].append(scale_hint)
        if analysis["fit_style"] != "Unknown":
            analysis["notes"].append(str(analysis["fit_style"]))
    except Exception as exc:
        analysis["mesh_ok"] = False
        analysis["risk_level"] = "High"
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
    nozzle_diameter = float(printer_profile.get("nozzle_diameter", 0.4))
    heated_chamber = bool(printer_profile.get("heated_chamber", False))

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
        refined["acceleration"] = min(int(refined.get("acceleration", 3000)), 2600)

    if slender_ratio > 8:
        refined["wall_loops"] = min(int(refined["wall_loops"]), 2)
        refined["print_speed"] = max(22, int(int(refined["print_speed"]) * 0.88))
        refined["orientation"] = "Preserve thin features by reducing shell bulk and avoiding aggressive speed on narrow spans."
        refined["seam_position"] = "Rear"

    if nozzle_diameter >= 0.6 and min_dim < nozzle_diameter * 3:
        refined["print_speed"] = max(20, int(int(refined["print_speed"]) * 0.84))
        refined["wall_loops"] = min(int(refined["wall_loops"]), 2)
        refined["orientation"] = "Protect finer edges by easing shell bulk and slowing motion on small features."

    if min_dim < 1.2:
        refined["layer_height"] = min(float(refined["layer_height"]), max(0.08, round(nozzle_diameter * 0.35, 2)))
        refined["print_speed"] = max(18, int(int(refined["print_speed"]) * 0.8))
        refined["acceleration"] = min(int(refined.get("acceleration", 3000)), 2200)

    if bed_fill_ratio > 0.7 and not heated_chamber:
        refined["print_speed"] = max(20, int(int(refined["print_speed"]) * 0.9))
        refined["adhesion"] = "Brim" if refined["adhesion"] in {"Auto", "Skirt"} else refined["adhesion"]

    if mesh_analysis.get("face_count") and int(mesh_analysis["face_count"]) > 400_000:
        refined["print_speed"] = max(20, int(int(refined["print_speed"]) * 0.92))

    unsupported_risk = str(mesh_analysis.get("unsupported_risk", "Unknown"))
    bridge_risk = str(mesh_analysis.get("bridge_risk", "Unknown"))
    first_layer_contact = float(mesh_analysis.get("first_layer_contact_percent") or 0.0)
    if unsupported_risk == "Widespread unsupported surfaces":
        refined["support_enabled"] = True
        refined["support_density"] = max(int(refined.get("support_density", 24)), 30)
        refined["support_interface"] = True
        refined["support_pattern"] = "Grid"
    elif unsupported_risk == "Localized unsupported pockets":
        refined["support_enabled"] = True if support_strategy != "Disabled" else refined["support_enabled"]
        refined["support_density"] = max(int(refined.get("support_density", 24)), 22)
        refined["support_pattern"] = "Lines"

    if bridge_risk == "Bridge-heavy geometry":
        refined["print_speed"] = max(18, int(int(refined["print_speed"]) * 0.86))
        refined["outer_wall_speed"] = max(12, int(int(refined.get("outer_wall_speed", refined["print_speed"])) * 0.9))
        refined["support_enabled"] = True if support_strategy != "Disabled" else refined["support_enabled"]

    if first_layer_contact and first_layer_contact < 16:
        if refined["adhesion"] in {"Auto", "Skirt"}:
            refined["adhesion"] = "Brim"
        refined["brim_width"] = max(float(refined.get("brim_width", 0.0)), 8.0)
        refined["first_layer_flow"] = max(int(refined.get("first_layer_flow", 100)), 103)
        refined["first_layer_speed"] = max(12, int(int(refined.get("first_layer_speed", 20)) * 0.9))

    recommended_orientation_label = str(mesh_analysis.get("recommended_orientation_label", ""))
    if recommended_orientation_label and recommended_orientation_label != "As loaded":
        refined["orientation"] = f"{recommended_orientation_label} is the safer starting posture for this part."

    return refined


def build_prusaslicer_config(plan: dict[str, str | float | int | bool]) -> str:
    support_value = 1 if plan["support_enabled"] else 0
    brim_width = 0 if plan["adhesion"] != "Brim" else float(plan.get("brim_width", 5))
    raft_layers = 0 if plan["adhesion"] != "Raft" else 2
    start_gcode = str(plan.get("start_gcode", "")).replace("\r", "\\n").replace("\n", "\\n")
    end_gcode = str(plan.get("end_gcode", "")).replace("\r", "\\n").replace("\n", "\\n")
    support_threshold = int(plan.get("support_threshold", 40))
    top_layers = int(plan.get("top_layers", 4))
    bottom_layers = int(plan.get("bottom_layers", 4))
    retraction_length = float(plan.get("retraction_length", 1.2))
    acceleration = int(plan.get("acceleration", 3000))
    jerk_control = int(plan.get("jerk_control", 8))
    seam_position = str(plan.get("seam_position", "Rear"))
    outer_wall_speed = int(plan.get("outer_wall_speed", plan["print_speed"]))
    inner_wall_speed = int(plan.get("inner_wall_speed", plan["print_speed"]))
    travel_speed = int(plan.get("travel_speed", plan["print_speed"]))
    support_interface = 1 if plan.get("support_interface", False) else 0
    support_pattern = str(plan.get("support_pattern", "Lines")).lower()
    infill_pattern = str(plan.get("infill_pattern", "Gyroid")).lower()
    skirt_loops = int(plan.get("skirt_loops", 2))
    first_layer_height = float(plan.get("first_layer_height", plan["layer_height"]))
    first_layer_speed = int(plan.get("first_layer_speed", max(15, int(plan["print_speed"] * 0.45))))
    first_layer_flow = int(plan.get("first_layer_flow", 100))
    flow_multiplier = int(plan.get("flow_multiplier", 100))
    return textwrap.dedent(
        f"""
        # CipherSlice generated slicer config
        # G-code flavor: {plan.get('gcode_flavor', 'Unknown')}
        layer_height = {plan['layer_height']}
        first_layer_height = {first_layer_height}
        fill_density = {plan['infill_percent']}%
        fill_pattern = {infill_pattern}
        perimeters = {plan['wall_loops']}
        top_solid_layers = {top_layers}
        bottom_solid_layers = {bottom_layers}
        nozzle_diameter = {plan['nozzle_diameter']}
        support_material = {support_value}
        support_material_interface_layers = {support_interface}
        support_material_pattern = {support_pattern}
        support_material_threshold = {support_threshold}
        first_layer_temperature = {plan['nozzle_temp']}
        temperature = {plan['nozzle_temp']}
        first_layer_bed_temperature = {plan['bed_temp']}
        bed_temperature = {plan['bed_temp']}
        perimeters_speed = {outer_wall_speed}
        external_perimeter_speed = {outer_wall_speed}
        infill_speed = {inner_wall_speed}
        solid_infill_speed = {inner_wall_speed}
        travel_speed = {travel_speed}
        first_layer_speed = {first_layer_speed}
        extrusion_multiplier = {flow_multiplier / 100:.3f}
        first_layer_extrusion_width = {first_layer_flow / 100:.3f}
        retract_length = {retraction_length}
        default_acceleration = {acceleration}
        machine_max_jerk_x = {jerk_control}
        machine_max_jerk_y = {jerk_control}
        seam_position = {seam_position}
        brim_width = {brim_width}
        skirts = {skirt_loops}
        raft_layers = {raft_layers}
        start_gcode = {start_gcode}
        end_gcode = {end_gcode}
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
    base_filament = get_base_filament(filament)
    extrusion_multiplier = {
        "PLA": 0.98,
        "PETG": 1.03,
        "ABS": 1.01,
        "ASA": 1.01,
        "TPU": 1.08,
        "Nylon": 1.04,
        "PC": 1.02,
        "CF Nylon": 0.97,
    }.get(base_filament, 1.0)
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
    .shape-preview-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.45rem;
        margin-top: 0.7rem;
    }
    .shape-view {
        background: rgba(7, 18, 30, 0.58);
        border: 1px solid rgba(104, 144, 177, 0.16);
        border-radius: 10px;
        padding: 0.35rem;
        text-align: center;
    }
    .shape-svg {
        width: 100%;
        display: block;
    }
    .shape-label {
        color: #b7c8d5;
        font-size: 0.76rem;
        margin-top: 0.15rem;
    }
    .shape-preview-empty {
        border: 1px dashed rgba(104, 144, 177, 0.28);
        border-radius: 10px;
        color: #9db4c7;
        padding: 0.75rem;
        margin-top: 0.65rem;
        font-size: 0.9rem;
    }
    @media (max-width: 980px) {
        .glance-grid, .change-grid, .transition-grid, .metric-strip, .delivery-grid, .persona-grid, .preview-grid, .ops-grid, .review-header-grid, .summary-strip, .compare-grid, .manifest-grid, .confidence-grid {
            grid-template-columns: 1fr !important;
        }
    }
    .review-section {
        background: linear-gradient(180deg, rgba(7, 18, 30, 0.84), rgba(6, 15, 26, 0.84));
        border: 1px solid rgba(104, 144, 177, 0.22);
        border-radius: 22px;
        padding: 1rem 1.05rem 1.05rem;
        margin: 0.85rem 0 1rem;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 18px 34px rgba(0,0,0,0.16);
    }
    .review-kicker {
        color: #7ce0bf;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 0.74rem;
        margin-bottom: 0.2rem;
    }
    .review-copy {
        color: #9fb6c8;
        line-height: 1.55;
        margin-bottom: 0.75rem;
        font-size: 0.94rem;
    }
    .glance-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.7rem;
        margin-bottom: 0.8rem;
    }
    .glance-card {
        background: linear-gradient(180deg, rgba(10, 26, 42, 0.92), rgba(8, 20, 34, 0.92));
        border: 1px solid rgba(90, 207, 171, 0.15);
        border-radius: 18px;
        padding: 0.85rem 0.9rem;
        min-height: 112px;
    }
    .glance-label {
        color: #8fa8bb;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.35rem;
    }
    .glance-value {
        color: #f4f8fb;
        font-size: 1.08rem;
        font-weight: 700;
        line-height: 1.25;
        margin-bottom: 0.3rem;
    }
    .glance-note {
        color: #a9bfce;
        font-size: 0.86rem;
        line-height: 1.45;
    }
    .review-header-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 0.7rem;
        margin: 0.35rem 0 0.9rem;
    }
    .review-header-card {
        background: linear-gradient(180deg, rgba(11, 28, 44, 0.96), rgba(8, 20, 34, 0.96));
        border: 1px solid rgba(104, 144, 177, 0.22);
        border-radius: 18px;
        padding: 0.85rem 0.9rem;
        min-height: 104px;
    }
    .review-header-title {
        color: #8fa8bb;
        font-size: 0.75rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.28rem;
    }
    .review-header-value {
        color: #f4f8fb;
        font-size: 1.06rem;
        font-weight: 700;
        margin-bottom: 0.24rem;
    }
    .review-header-copy {
        color: #a9bfce;
        font-size: 0.84rem;
        line-height: 1.45;
    }
    .summary-strip {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.6rem;
        margin: 0.4rem 0 0.8rem;
    }
    .summary-pill {
        background: rgba(90, 207, 171, 0.1);
        border: 1px solid rgba(90, 207, 171, 0.16);
        border-radius: 16px;
        padding: 0.7rem 0.8rem;
        color: #dffcf2;
    }
    .summary-pill strong {
        display: block;
        color: #f4f8fb;
        margin-bottom: 0.18rem;
    }
    .change-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.75rem;
        margin-top: 0.35rem;
    }
    .change-card {
        background: rgba(10, 23, 37, 0.92);
        border: 1px solid rgba(104, 144, 177, 0.2);
        border-radius: 18px;
        padding: 0.9rem 0.95rem;
    }
    .change-card-risk {
        border-color: rgba(255, 214, 102, 0.28);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
    }
    .change-name {
        color: #f4f8fb;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .change-meta {
        color: #c9d7e2;
        font-size: 0.9rem;
        line-height: 1.45;
    }
    .change-risk {
        display: inline-block;
        margin-top: 0.45rem;
        padding: 0.18rem 0.52rem;
        border-radius: 999px;
        background: rgba(255, 184, 0, 0.12);
        border: 1px solid rgba(255, 214, 102, 0.2);
        color: #fff1c2;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .compare-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.8rem;
        margin-top: 0.75rem;
    }
    .compare-card {
        background: rgba(8, 23, 37, 0.9);
        border: 1px solid rgba(104, 144, 177, 0.2);
        border-radius: 18px;
        padding: 0.95rem 1rem;
    }
    .compare-card h5 {
        color: #f4f8fb;
        margin: 0 0 0.45rem;
        font-size: 1rem;
    }
    .compare-card p {
        color: #b7c8d5;
        margin: 0.18rem 0;
        line-height: 1.45;
    }
    .manifest-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.75rem;
        margin-top: 0.8rem;
    }
    .manifest-section {
        background: rgba(8, 23, 37, 0.9);
        border: 1px solid rgba(104, 144, 177, 0.18);
        border-radius: 18px;
        padding: 0.95rem 1rem;
    }
    .manifest-section-title {
        color: #f4f8fb;
        font-size: 0.98rem;
        font-weight: 700;
        margin-bottom: 0.45rem;
    }
    .confidence-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.7rem;
        margin: 0.35rem 0 0.8rem;
    }
    .confidence-card {
        background: rgba(8, 23, 37, 0.88);
        border: 1px solid rgba(104, 144, 177, 0.18);
        border-radius: 18px;
        padding: 0.85rem 0.9rem;
    }
    .confidence-card-title {
        color: #8fa8bb;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.25rem;
    }
    .confidence-card-value {
        color: #f4f8fb;
        font-size: 1.1rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .transition-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.75rem;
    }
    .transition-card {
        background: rgba(9, 23, 38, 0.92);
        border: 1px solid rgba(104, 144, 177, 0.2);
        border-radius: 18px;
        padding: 0.9rem 0.95rem;
    }
    .transition-title {
        color: #f4f8fb;
        font-size: 0.96rem;
        font-weight: 700;
        margin-bottom: 0.35rem;
    }
    .transition-copy {
        color: #b7c8d5;
        line-height: 1.5;
        font-size: 0.9rem;
    }
    .orientation-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.8rem;
        margin-top: 0.75rem;
    }
    .orientation-card {
        position: relative;
        background: linear-gradient(180deg, rgba(9, 23, 38, 0.96), rgba(6, 15, 25, 0.96));
        border: 1px solid rgba(104, 144, 177, 0.2);
        border-radius: 18px;
        padding: 0.95rem 1rem 1rem;
        min-height: 280px;
    }
    .orientation-card-recommended {
        border-color: rgba(104, 241, 193, 0.34);
        box-shadow: 0 0 0 1px rgba(104, 241, 193, 0.08), 0 12px 26px rgba(0, 0, 0, 0.2);
    }
    .orientation-badge {
        display: inline-block;
        margin-bottom: 0.55rem;
        padding: 0.22rem 0.58rem;
        border-radius: 999px;
        background: rgba(90, 207, 171, 0.16);
        border: 1px solid rgba(104, 241, 193, 0.2);
        color: #dffcf2;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .orientation-title {
        color: #f4f8fb;
        font-size: 1rem;
        font-weight: 700;
        margin-bottom: 0.28rem;
    }
    .orientation-copy {
        color: #b7c8d5;
        line-height: 1.5;
        font-size: 0.9rem;
    }
    .orientation-svg {
        width: 100%;
        height: 126px;
        margin: 0.55rem 0 0.35rem;
    }
    .orientation-meta {
        color: #cfe0ec;
        font-size: 0.86rem;
        line-height: 1.45;
        margin-bottom: 0.2rem;
    }
    .insight-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.75rem;
        margin: 0.75rem 0 0.9rem;
    }
    .insight-card {
        background: rgba(8, 23, 37, 0.9);
        border: 1px solid rgba(104, 144, 177, 0.18);
        border-radius: 18px;
        padding: 0.85rem 0.95rem;
    }
    .insight-card-title {
        color: #8fa8bb;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.25rem;
    }
    .insight-card-value {
        color: #f4f8fb;
        font-size: 1rem;
        font-weight: 700;
        margin-bottom: 0.18rem;
    }
    .insight-card-copy {
        color: #b7c8d5;
        font-size: 0.88rem;
        line-height: 1.45;
    }
    .preview-section-grid {
        display: grid;
        grid-template-columns: 1.2fr 0.8fr;
        gap: 0.85rem;
        margin-top: 0.85rem;
    }
    .preview-visual-stack {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0.75rem;
    }
    .preview-notes-card {
        background: rgba(8, 23, 37, 0.88);
        border: 1px solid rgba(104, 144, 177, 0.18);
        border-radius: 18px;
        padding: 0.95rem 1rem;
    }
    .preview-notes-title {
        color: #f4f8fb;
        font-size: 0.98rem;
        font-weight: 700;
        margin-bottom: 0.4rem;
    }
    .preview-notes-copy {
        color: #b7c8d5;
        line-height: 1.55;
        font-size: 0.92rem;
    }
    @media (max-width: 980px) {
        .orientation-grid, .insight-grid, .preview-section-grid {
            grid-template-columns: 1fr;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero-card">
        <div class="section-label">CipherSlice Control Plane</div>
        <div class="hero-title">Build + Review Your Print</div>
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
                <div class="metric-value">Secure Print File Delivery</div>
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
if st.session_state.get("active_job"):
    active_name = st.session_state["active_job"].get("filename", "current job")
    active_mode = st.session_state["active_job"].get("mode", "print job")
    st.info(
        f"Active job loaded: `{active_name}` in `{active_mode}`. "
        "Your review and approval controls are still available below."
    )
    st.button("Start a Different Job", use_container_width=True, on_click=clear_active_job)
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
                Same safe recommendations, but with relaxed best-friend energy, more personality, and a little more edge.
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
        st.markdown("### Step 1: Start Your Print")
        st.markdown(
            '<div class="mode-banner"><strong>Reliable Print Mode</strong><br/>'
            "Upload a real mesh file and CipherSlice will prepare a printer-targeted print package.</div>",
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
        st.caption("PDF is accepted here for technical drawings only. Real print mode still expects mesh files like STL, OBJ, or 3MF.")
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
        st.caption("Enter the real machine envelope using X, Y, and Z so CipherSlice can check fit and produce a better handoff plan.")
        x_col, y_col, z_col = st.columns(3, gap="small")
        custom_width = x_col.number_input("X width / left-to-right (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        custom_depth = y_col.number_input("Y depth / front-to-back (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
        custom_height = z_col.number_input("Z height / bottom-to-top (mm)", min_value=100.0, max_value=2000.0, value=500.0, step=10.0)
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
    st.caption(f"Printer family: {selected_printer_profile.get('family', 'Unknown')}")
    st.caption(selected_printer_profile.get("printer_note", ""))
    st.markdown('<div class="setting-card">', unsafe_allow_html=True)
    filament = st.selectbox("Filament Type", FILAMENT_TYPES)
    st.caption(FILAMENT_DETAILS[filament]["summary"])
    st.caption(f"Strength profile: {FILAMENT_DETAILS[filament]['strength']}")
    st.caption(f"Watch for: {FILAMENT_DETAILS[filament]['warning']}")
    if is_abrasive_filament(filament):
        st.warning("This fiber-filled material should use a hardened or wear-resistant nozzle for repeat printing.")
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
        help="Choose how the approved print package should leave CipherSlice once the user signs off.",
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
        help="CipherSlice will suggest or apply a scale correction when the model looks implausibly small or large, then report the longest corrected dimension so you can sanity-check it.",
    )
    st.markdown(
        """
        <div class="workflow-style-card">
            <div class="workflow-style-title">Choose Your Control Level</div>
            <div class="workflow-style-copy">
                Beginner keeps the setup simple and continues below. Advanced opens a dedicated workspace while still using the same live job underneath.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    workflow_col1, workflow_col2 = st.columns(2, gap="medium")
    with workflow_col1:
        if st.button(
            "Beginner",
            use_container_width=True,
            type="primary" if st.session_state.get("experience_mode", "Beginner") == "Beginner" else "secondary",
            key="workflow_beginner",
        ):
            st.session_state["experience_mode"] = "Beginner"
    with workflow_col2:
        if st.button(
            "Advanced",
            use_container_width=True,
            type="primary" if st.session_state.get("experience_mode", "Beginner") == "Advanced" else "secondary",
            key="workflow_advanced",
        ):
            open_advanced_workspace()
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
    wants_encryption = st.checkbox("Encrypt downloadable print file", value=True)
    encryption_passphrase = ""
    if wants_encryption:
        encryption_passphrase = st.text_input(
            "Encryption passphrase",
            type="password",
            help="Use a passphrase if you want Cipher Vault to issue an encrypted downloadable print file.",
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
        "Create Print Plan",
        type="primary",
        disabled=launch_disabled,
        use_container_width=True,
        help=launch_help,
    )
    if launch and uploaded_file is not None:
        new_artifact_hash = build_hash(uploaded_file.name, uploaded_file.size, printer, filament)
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
            "approval_key": f"approve_{new_artifact_hash}",
        }
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Quick Job View")
    st.caption(f"Copilot tone: `{persona['label']}`")
    profile_mode_label, profile_mode_copy = build_profile_mode_label(mode, slicer_path)
    st.markdown(f'<div class="mode-pill">{profile_mode_label}</div>', unsafe_allow_html=True)
    st.caption(profile_mode_copy)
    if mode == "Reliable Print Mode":
        st.info(
            "This is the dependable consumer path. Real mesh in, printer-specific print package out, with encryption available for delivery."
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
        **Printer family:** `{selected_printer_profile.get('family', 'Unknown')}`  
        **Material profile:** `{filament}`  
        **Material strength:** `{FILAMENT_DETAILS[filament]['strength']}`  
        **Optimization mode:** `{quality_profile}` / `{print_goal}`  
        **Support + adhesion:** `{support_strategy}` / `{adhesion_strategy}`  
        **Delivery mode:** `{delivery_mode}`  
        **Printer command style:** `{selected_printer_profile.get('gcode_flavor', 'Unknown')}`
        """
    )
    if wants_encryption:
        if CRYPTOGRAPHY_AVAILABLE:
            st.success("Print-file encryption is enabled. Cipher Vault can issue an encrypted download.")
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
    approval_key = active_job.get("approval_key", f"approve_{artifact_hash}")
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
    if f"edit_profile_preset_{artifact_hash}" not in st.session_state:
        reset_live_plan_state(
            artifact_hash,
            recommended_plan,
            quality_profile,
            print_goal,
            support_strategy,
            adhesion_strategy,
            delivery_mode,
            filament,
            printer_profile,
        )
    ensure_plan_snapshot_baseline(
        artifact_hash,
        recommended_plan,
        filename,
        printer,
        filament,
    )
    orientation_state_key = f"preview_orientation_{artifact_hash}"
    if orientation_state_key not in st.session_state:
        default_orientation = "As loaded"
        if mesh_analysis and mesh_analysis.get("recommended_orientation_label") not in {None, "", "Unknown"}:
            default_orientation = str(mesh_analysis.get("recommended_orientation_label"))
        st.session_state[orientation_state_key] = default_orientation
    saved_profile_key = f"saved_profiles_{artifact_hash}"
    if saved_profile_key not in st.session_state:
        st.session_state[saved_profile_key] = []

    st.write("")
    st.markdown(
        f'<div class="state-banner {execution_class}"><strong>{execution_label}</strong><br/>{execution_copy}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Step 2: Review + Adjust")
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

    snapshots = list(st.session_state.get(f"plan_snapshots_{artifact_hash}", []))
    action_col1, action_col2, action_col3, action_col4 = st.columns(4, gap="small")
    with action_col1:
        if st.button("Reset To Recommended", use_container_width=True, key=f"reset_live_plan_{artifact_hash}"):
            reset_live_plan_state(
                artifact_hash,
                recommended_plan,
                quality_profile,
                print_goal,
                support_strategy,
                adhesion_strategy,
                delivery_mode,
                filament,
                printer_profile,
            )
            st.rerun()
    with action_col2:
        if st.button("Save Snapshot", use_container_width=True, key=f"save_snapshot_{artifact_hash}"):
            st.session_state[f"queue_snapshot_save_{artifact_hash}"] = "manual"
    with action_col3:
        if st.button("Duplicate Path", use_container_width=True, key=f"duplicate_snapshot_{artifact_hash}"):
            st.session_state[f"queue_snapshot_save_{artifact_hash}"] = "branch"
    with action_col4:
        if len(snapshots) > 1 and st.button("Restore Last Snapshot", use_container_width=True, key=f"restore_snapshot_{artifact_hash}"):
            apply_snapshot_to_state(artifact_hash, snapshots[-1])
            st.rerun()
    st.caption("Use these to reset, save checkpoints, branch ideas, or recover a previous tuning path without restarting the job.")

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
            editable_profile_preset = st.selectbox(
                "Tuning preset",
                ["Recommended", "Strength-first", "Quality-first", "Speed-first", "Prototype-first"],
                index=["Recommended", "Strength-first", "Quality-first", "Speed-first", "Prototype-first"].index(
                    str(st.session_state.get(f"edit_profile_preset_{artifact_hash}", "Recommended"))
                ),
                key=f"edit_profile_preset_{artifact_hash}",
                help="Presets move multiple advanced controls together so the plan feels more like a real slicer profile family.",
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
            st.caption(FILAMENT_DETAILS[editable_filament]["summary"])
            st.caption(f"Watch for: {FILAMENT_DETAILS[editable_filament]['warning']}")
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
    editable_flow = int(st.session_state.get(f"edit_flow_{artifact_hash}", recommended_plan.get("flow_multiplier", 100)))
    editable_support_density = int(st.session_state.get(f"edit_support_density_{artifact_hash}", recommended_plan.get("support_density", 24)))
    editable_top_layers = int(st.session_state.get(f"edit_top_layers_{artifact_hash}", recommended_plan.get("top_layers", 4)))
    editable_bottom_layers = int(st.session_state.get(f"edit_bottom_layers_{artifact_hash}", recommended_plan.get("bottom_layers", 4)))
    editable_retraction_length = float(st.session_state.get(f"edit_retraction_{artifact_hash}", recommended_plan.get("retraction_length", 1.2)))
    editable_acceleration = int(st.session_state.get(f"edit_acceleration_{artifact_hash}", recommended_plan.get("acceleration", 3000)))
    editable_seam_position = str(st.session_state.get(f"edit_seam_{artifact_hash}", recommended_plan.get("seam_position", "Rear")))
    editable_outer_wall_speed = int(st.session_state.get(f"edit_outer_wall_speed_{artifact_hash}", recommended_plan.get("outer_wall_speed", max(15, int(recommended_plan["print_speed"] * 0.55)))))
    editable_inner_wall_speed = int(st.session_state.get(f"edit_inner_wall_speed_{artifact_hash}", recommended_plan.get("inner_wall_speed", max(18, int(recommended_plan["print_speed"] * 0.82)))))
    editable_travel_speed = int(st.session_state.get(f"edit_travel_speed_{artifact_hash}", recommended_plan.get("travel_speed", min(400, int(recommended_plan["print_speed"] * 2.2)))))
    editable_infill_pattern = str(st.session_state.get(f"edit_infill_pattern_{artifact_hash}", recommended_plan.get("infill_pattern", "Gyroid")))
    editable_support_interface = bool(st.session_state.get(f"edit_support_interface_{artifact_hash}", recommended_plan.get("support_interface", recommended_plan.get("support_enabled", False))))
    editable_support_pattern = str(st.session_state.get(f"edit_support_pattern_{artifact_hash}", recommended_plan.get("support_pattern", "Lines")))
    editable_brim_width = float(st.session_state.get(f"edit_brim_width_{artifact_hash}", recommended_plan.get("brim_width", 6.0 if recommended_plan.get("adhesion") == "Brim" else 0.0)))
    editable_skirt_loops = int(st.session_state.get(f"edit_skirt_loops_{artifact_hash}", recommended_plan.get("skirt_loops", 2)))
    editable_first_layer_height = float(st.session_state.get(f"edit_first_layer_height_{artifact_hash}", recommended_plan.get("first_layer_height", max(float(recommended_plan["layer_height"]), round(float(recommended_plan["layer_height"]) * 1.4, 2)))))
    editable_first_layer_speed = int(st.session_state.get(f"edit_first_layer_speed_{artifact_hash}", recommended_plan.get("first_layer_speed", max(15, int(recommended_plan["print_speed"] * 0.45)))))
    editable_first_layer_flow = int(st.session_state.get(f"edit_first_layer_flow_{artifact_hash}", recommended_plan.get("first_layer_flow", 100)))
    editable_jerk_control = int(st.session_state.get(f"edit_jerk_{artifact_hash}", recommended_plan.get("jerk_control", 8)))
    editable_stability_mode = str(st.session_state.get(f"edit_stability_{artifact_hash}", recommended_plan.get("stability_mode", "Balanced")))
    if editable_profile_preset != "Recommended" and st.session_state.get(f"edit_restore_point_{artifact_hash}") != f"Preset: {editable_profile_preset}":
        apply_tuning_preset_to_state(artifact_hash, editable_profile_preset, recommended_plan, printer_profile)
        st.session_state[f"edit_restore_point_{artifact_hash}"] = f"Preset: {editable_profile_preset}"
        editable_flow = int(st.session_state.get(f"edit_flow_{artifact_hash}", editable_flow))
        editable_support_density = int(st.session_state.get(f"edit_support_density_{artifact_hash}", editable_support_density))
        editable_top_layers = int(st.session_state.get(f"edit_top_layers_{artifact_hash}", editable_top_layers))
        editable_bottom_layers = int(st.session_state.get(f"edit_bottom_layers_{artifact_hash}", editable_bottom_layers))
        editable_retraction_length = float(st.session_state.get(f"edit_retraction_{artifact_hash}", editable_retraction_length))
        editable_acceleration = int(st.session_state.get(f"edit_acceleration_{artifact_hash}", editable_acceleration))
        editable_seam_position = str(st.session_state.get(f"edit_seam_{artifact_hash}", editable_seam_position))
        editable_outer_wall_speed = int(st.session_state.get(f"edit_outer_wall_speed_{artifact_hash}", editable_outer_wall_speed))
        editable_inner_wall_speed = int(st.session_state.get(f"edit_inner_wall_speed_{artifact_hash}", editable_inner_wall_speed))
        editable_travel_speed = int(st.session_state.get(f"edit_travel_speed_{artifact_hash}", editable_travel_speed))
        editable_infill_pattern = str(st.session_state.get(f"edit_infill_pattern_{artifact_hash}", editable_infill_pattern))
        editable_support_interface = bool(st.session_state.get(f"edit_support_interface_{artifact_hash}", editable_support_interface))
        editable_support_pattern = str(st.session_state.get(f"edit_support_pattern_{artifact_hash}", editable_support_pattern))
        editable_brim_width = float(st.session_state.get(f"edit_brim_width_{artifact_hash}", editable_brim_width))
        editable_skirt_loops = int(st.session_state.get(f"edit_skirt_loops_{artifact_hash}", editable_skirt_loops))
        editable_first_layer_height = float(st.session_state.get(f"edit_first_layer_height_{artifact_hash}", editable_first_layer_height))
        editable_first_layer_speed = int(st.session_state.get(f"edit_first_layer_speed_{artifact_hash}", editable_first_layer_speed))
        editable_first_layer_flow = int(st.session_state.get(f"edit_first_layer_flow_{artifact_hash}", editable_first_layer_flow))
        editable_jerk_control = int(st.session_state.get(f"edit_jerk_{artifact_hash}", editable_jerk_control))
        editable_stability_mode = str(st.session_state.get(f"edit_stability_{artifact_hash}", editable_stability_mode))
    if experience_mode == "Advanced":
        with st.expander("Advanced tuning cards", expanded=False):
            st.caption(
                "Quick guide: these controls now behave more like a slicer profile editor. You can shape surface speed, first-layer behavior, support style, motion aggression, and profile personality without losing the beginner path."
            )
            thermal_col, motion_col, support_col = st.columns(3, gap="medium")
            with thermal_col:
                with st.container(border=True):
                    st.markdown("#### Thermal tuning")
                    editable_nozzle_temp = st.number_input(
                        "Nozzle temp (degC)",
                        min_value=0,
                        max_value=320,
                        value=editable_nozzle_temp,
                        step=1,
                        help="Higher nozzle heat can improve bonding, but too much can string, sag, or overcook the material.",
                        key=f"edit_nozzle_{artifact_hash}",
                    )
                    editable_bed_temp = st.number_input(
                        "Bed temp (degC)",
                        min_value=0,
                        max_value=130,
                        value=editable_bed_temp,
                        step=1,
                        help="Bed temperature mainly affects first-layer grip and warping resistance.",
                        key=f"edit_bed_{artifact_hash}",
                    )
                    editable_flow = st.slider(
                        "Flow multiplier (%)",
                        min_value=80,
                        max_value=120,
                        value=editable_flow,
                        help="Flow changes how much plastic is pushed. It can help tune wall fullness and fit.",
                        key=f"edit_flow_{artifact_hash}",
                    )
                    editable_first_layer_height = st.number_input(
                        "First-layer height (mm)",
                        min_value=0.08,
                        max_value=1.0,
                        value=editable_first_layer_height,
                        step=0.02,
                        format="%.2f",
                        help="A taller first layer can forgive small bed issues, while a smaller one can preserve detail.",
                        key=f"edit_first_layer_height_{artifact_hash}",
                    )
                    editable_first_layer_flow = st.slider(
                        "First-layer flow (%)",
                        min_value=90,
                        max_value=120,
                        value=editable_first_layer_flow,
                        help="This changes how aggressively the first layer squishes into the bed.",
                        key=f"edit_first_layer_flow_{artifact_hash}",
                    )
            with motion_col:
                with st.container(border=True):
                    st.markdown("#### Motion + shell tuning")
                    editable_outer_wall_speed = st.number_input(
                        "Outer wall speed (mm/s)",
                        min_value=10,
                        max_value=250,
                        value=editable_outer_wall_speed,
                        step=1,
                        help="Slow this down when surface quality matters more than print speed.",
                        key=f"edit_outer_wall_speed_{artifact_hash}",
                    )
                    editable_inner_wall_speed = st.number_input(
                        "Inner wall speed (mm/s)",
                        min_value=10,
                        max_value=300,
                        value=editable_inner_wall_speed,
                        step=1,
                        help="Inner walls can usually move faster than the visible outer shell.",
                        key=f"edit_inner_wall_speed_{artifact_hash}",
                    )
                    editable_travel_speed = st.number_input(
                        "Travel speed (mm/s)",
                        min_value=20,
                        max_value=500,
                        value=editable_travel_speed,
                        step=5,
                        help="Faster travel saves time, but can increase shake and stringing.",
                        key=f"edit_travel_speed_{artifact_hash}",
                    )
                    editable_first_layer_speed = st.number_input(
                        "First-layer speed (mm/s)",
                        min_value=5,
                        max_value=120,
                        value=editable_first_layer_speed,
                        step=1,
                        help="This is one of the strongest first-layer reliability levers.",
                        key=f"edit_first_layer_speed_{artifact_hash}",
                    )
                    editable_support_density = st.slider(
                        "Support density target (%)",
                        min_value=0,
                        max_value=60,
                        value=editable_support_density,
                        help="Higher support density is stronger and easier to print over, but slower and harder to remove.",
                        key=f"edit_support_density_{artifact_hash}",
                    )
                    editable_support_interface = st.checkbox(
                        "Use support interface layers",
                        value=editable_support_interface,
                        help="Interface layers can improve the underside finish on supported surfaces.",
                        key=f"edit_support_interface_{artifact_hash}",
                    )
                    editable_support_pattern = st.selectbox(
                        "Support pattern",
                        ["Lines", "Grid", "Zig-zag"],
                        index=["Lines", "Grid", "Zig-zag"].index(editable_support_pattern if editable_support_pattern in {"Lines", "Grid", "Zig-zag"} else "Lines"),
                        help="Pattern changes support strength and peel-away behavior.",
                        key=f"edit_support_pattern_{artifact_hash}",
                    )
            with support_col:
                with st.container(border=True):
                    st.markdown("#### Surface + structure")
                    editable_infill_pattern = st.selectbox(
                        "Infill pattern",
                        ["Gyroid", "Grid", "Lines", "Cubic"],
                        index=["Gyroid", "Grid", "Lines", "Cubic"].index(editable_infill_pattern if editable_infill_pattern in {"Gyroid", "Grid", "Lines", "Cubic"} else "Gyroid"),
                        help="Pattern changes strength feel, print rhythm, and material behavior.",
                        key=f"edit_infill_pattern_{artifact_hash}",
                    )
                    editable_top_layers = st.slider(
                        "Top solid layers",
                        min_value=1,
                        max_value=12,
                        value=editable_top_layers,
                        help="More top layers usually improve roof strength and surface closure.",
                        key=f"edit_top_layers_{artifact_hash}",
                    )
                    editable_bottom_layers = st.slider(
                        "Bottom solid layers",
                        min_value=1,
                        max_value=12,
                        value=editable_bottom_layers,
                        help="More bottom layers can improve floor strength and first-layer stability.",
                        key=f"edit_bottom_layers_{artifact_hash}",
                    )
                    editable_brim_width = st.number_input(
                        "Brim width (mm)",
                        min_value=0.0,
                        max_value=20.0,
                        value=editable_brim_width,
                        step=0.5,
                        format="%.1f",
                        help="Brim width matters most on tall, narrow, or warp-prone parts.",
                        key=f"edit_brim_width_{artifact_hash}",
                    )
                    editable_skirt_loops = st.slider(
                        "Skirt loops",
                        min_value=0,
                        max_value=10,
                        value=editable_skirt_loops,
                        help="Skirts help prime the nozzle and settle the flow before the real part starts.",
                        key=f"edit_skirt_loops_{artifact_hash}",
                    )
                    editable_retraction_length = st.number_input(
                        "Retraction length (mm)",
                        min_value=0.0,
                        max_value=10.0,
                        value=editable_retraction_length,
                        step=0.1,
                        format="%.1f",
                        help="Retraction helps reduce stringing, especially on travel moves between islands.",
                        key=f"edit_retraction_{artifact_hash}",
                    )
                    editable_acceleration = st.number_input(
                        "Acceleration (mm/s^2)",
                        min_value=100,
                        max_value=20000,
                        value=editable_acceleration,
                        step=100,
                        help="Higher acceleration can shorten print time, but it can also increase ringing and motion stress.",
                        key=f"edit_acceleration_{artifact_hash}",
                    )
                    editable_jerk_control = st.number_input(
                        "Jerk control",
                        min_value=1,
                        max_value=30,
                        value=editable_jerk_control,
                        step=1,
                        help="This changes how abruptly the machine tries to change direction.",
                        key=f"edit_jerk_{artifact_hash}",
                    )
                    editable_seam_position = st.selectbox(
                        "Seam position",
                        ["Rear", "Aligned", "Nearest", "Random"],
                        index=["Rear", "Aligned", "Nearest", "Random"].index(editable_seam_position if editable_seam_position in {"Rear", "Aligned", "Nearest", "Random"} else "Rear"),
                        help="This changes where layer-start scars tend to collect on the outside of the part.",
                        key=f"edit_seam_{artifact_hash}",
                    )
                    editable_stability_mode = st.selectbox(
                        "Stability mode",
                        ["Balanced", "Stable", "Surface-first", "Fast", "Prototype"],
                        index=["Balanced", "Stable", "Surface-first", "Fast", "Prototype"].index(editable_stability_mode if editable_stability_mode in {"Balanced", "Stable", "Surface-first", "Fast", "Prototype"} else "Balanced"),
                        help="This helps explain whether the current plan leans toward safety, finish, or speed.",
                        key=f"edit_stability_{artifact_hash}",
                    )
                    st.markdown(f"- **Placement suggestion:** {printer_profile['orientation']}")
                    st.markdown(f"- **Nozzle diameter:** `{printer_profile['nozzle_diameter']} mm`")
                    st.markdown(f"- **Secure delivery:** `{'On' if wants_encryption else 'Off'}`")
                    st.caption("These controls give hobbyists more real influence over the live plan without crowding the beginner path.")

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
    optimized_plan["support_density"] = editable_support_density
    optimized_plan["top_layers"] = editable_top_layers
    optimized_plan["bottom_layers"] = editable_bottom_layers
    optimized_plan["retraction_length"] = round(editable_retraction_length, 1)
    optimized_plan["acceleration"] = editable_acceleration
    optimized_plan["seam_position"] = editable_seam_position
    optimized_plan["outer_wall_speed"] = editable_outer_wall_speed
    optimized_plan["inner_wall_speed"] = editable_inner_wall_speed
    optimized_plan["travel_speed"] = editable_travel_speed
    optimized_plan["infill_pattern"] = editable_infill_pattern
    optimized_plan["support_interface"] = editable_support_interface
    optimized_plan["support_pattern"] = editable_support_pattern
    optimized_plan["brim_width"] = round(editable_brim_width, 1)
    optimized_plan["skirt_loops"] = editable_skirt_loops
    optimized_plan["first_layer_height"] = round(editable_first_layer_height, 2)
    optimized_plan["first_layer_speed"] = editable_first_layer_speed
    optimized_plan["first_layer_flow"] = editable_first_layer_flow
    optimized_plan["jerk_control"] = editable_jerk_control
    optimized_plan["stability_mode"] = editable_stability_mode
    optimized_plan["profile_preset"] = editable_profile_preset
    optimized_plan["gcode_flavor"] = editable_gcode_flavor
    quality_profile = editable_quality_profile
    print_goal = editable_print_goal
    support_strategy = editable_support_strategy
    adhesion_strategy = editable_adhesion_strategy
    delivery_mode = editable_delivery_mode
    optimized_plan["delivery_mode"] = delivery_mode
    recommended_plan.update(extract_plan_controls(recommended_plan))
    optimized_plan.update(extract_plan_controls(optimized_plan))
    queued_snapshot_reason = st.session_state.pop(f"queue_snapshot_save_{artifact_hash}", None)
    if queued_snapshot_reason:
        snapshot_count = len(st.session_state.get(f"plan_snapshots_{artifact_hash}", []))
        snapshot_label = (
            f"Branch path {snapshot_count + 1}"
            if queued_snapshot_reason == "branch"
            else f"Saved snapshot {snapshot_count + 1}"
        )
        save_plan_snapshot(
            artifact_hash,
            snapshot_label,
            filename,
            printer,
            filament,
            optimized_plan,
            str(queued_snapshot_reason),
        )
        st.session_state[f"edit_restore_point_{artifact_hash}"] = snapshot_label
    snapshot_labels_now = [str(snapshot.get("label")) for snapshot in st.session_state.get(f"plan_snapshots_{artifact_hash}", [])]
    if "Geometry-reviewed live plan" not in snapshot_labels_now:
        save_plan_snapshot(
            artifact_hash,
            "Geometry-reviewed live plan",
            filename,
            printer,
            filament,
            optimized_plan,
            "restore-point",
        )

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
    real_gcode = None
    slicer_message = "No slicer run has been attempted yet."

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
        slicer_message = "Blueprint Assist Mode does not run a slicer backend. It prepares a reconstruction brief instead."

    agent_handoffs = build_agent_handoff_states(
        mode,
        mesh_analysis,
        slicer_path,
        connector_url,
        delivery_mode,
        objections,
    )

    fallback_agent_packets = build_live_agent_packets(
        persona,
        job_context,
        mesh_analysis,
        optimized_plan["support_density"],
        format_bytes(file_size),
        slicer_message if mode == "Reliable Print Mode" else "Prepared a draft reconstruction packet instead of final G-code because 2D input is still missing validated 3D geometry.",
        agent_handoffs,
    )
    agent_packets, agent_runtime_meta = run_live_agent_runtime(
        persona,
        job_context,
        mesh_analysis,
        int(optimized_plan["support_density"]),
        slicer_message if mode == "Reliable Print Mode" else "Prepared a draft reconstruction packet instead of final G-code because 2D input is still missing validated 3D geometry.",
        fallback_agent_packets,
        agent_handoffs,
    )

    encrypted_artifact = None
    encryption_salt = None
    if wants_encryption and encryption_passphrase:
        encrypted_artifact, encryption_salt = encrypt_artifact(primary_artifact, encryption_passphrase)

    st.write("")
    st.markdown("### Step 3: Plan + Delivery Package")
    if agent_runtime_meta["using_live_workers"]:
        st.caption(f"{agent_runtime_meta['status']}: {agent_runtime_meta['detail']}")
    elif agent_runtime_meta["status"] != "Disabled":
        st.caption(agent_runtime_meta["detail"])

    with st.status("Building your print plan", expanded=True) as status:
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
            f"Generated secure print package hash `{artifact_hash[:18]}...` and encrypted the output file for controlled delivery."
            if encrypted_artifact
            else f"Generated secure print package hash `{artifact_hash[:18]}...` and staged the output file for controlled delivery."
        )
        st.markdown(f"**{agent_packets['Cipher Vault']['title']}**  \n{agent_packets['Cipher Vault']['summary']}  \n{vault_line}")
        if release_allowed:
            st.success(f"Review check cleared at {overall_confidence * 100:.1f}% confidence. This job is ready for approval.")
        else:
            st.warning(f"Review check held this job at {overall_confidence * 100:.1f}% confidence. More setup or review is required.")
        status.update(label="Print plan ready for review", state="complete", expanded=True)

    if mode == "Reliable Print Mode":
        snapshots = list(st.session_state.get(f"plan_snapshots_{artifact_hash}", []))
        st.markdown(
            "<div class='review-header-grid'>"
            f"<div class='review-header-card'><div class='review-header-title'>Part</div><div class='review-header-value'>{filename}</div><div class='review-header-copy'>{format_bytes(file_size)} uploaded and mapped into the live planning chain.</div></div>"
            f"<div class='review-header-card'><div class='review-header-title'>Printer</div><div class='review-header-value'>{printer}</div><div class='review-header-copy'>{printer_profile.get('family', 'Unknown family')}<br/>{printer_profile.get('bed_shape_type', 'Rectangular')} bed</div></div>"
            f"<div class='review-header-card'><div class='review-header-title'>Material</div><div class='review-header-value'>{filament}</div><div class='review-header-copy'>{optimized_plan['nozzle_temp']} degC nozzle / {optimized_plan['bed_temp']} degC bed</div></div>"
            f"<div class='review-header-card'><div class='review-header-title'>Plan state</div><div class='review-header-value'>{'Printer-ready path' if slicer_path else 'Planning preview'}</div><div class='review-header-copy'>{'Real slicing is connected.' if slicer_path else 'A slicer backend still needs to be connected.'}</div></div>"
            f"<div class='review-header-card'><div class='review-header-title'>Review gate</div><div class='review-header-value'>{overall_confidence * 100:.0f}%</div><div class='review-header-copy'>{len(objections)} blockers / {len(snapshots)} saved snapshots</div></div>"
            "</div>",
            unsafe_allow_html=True,
        )

    result_col, code_col = st.columns([0.9, 1.1], gap="large")
    final_user_approval = bool(st.session_state.get(approval_key, False))
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
    guidance_title, guidance_copy = build_guidance_visibility_summary(agent_runtime_meta)
    print_engine_setup_notes = build_print_engine_setup_notes(
        slicer_label,
        slicer_path,
        engine_diagnostics,
    )
    printer_material_notes = build_printer_material_notes(printer_profile, filament, mesh_analysis)
    machine_profile_notes = build_machine_profile_notes(printer_profile, filament)
    is_production_print_file = mode == "Reliable Print Mode" and bool(real_gcode)
    print_file_download_label = (
        "Download Print File"
        if is_production_print_file
        else "Download Preview Plan (Not Printer-Ready)"
    )
    print_file_download_name = (
        f"{file_stem}_{sanitize_download_name(printer.lower())}.gcode"
        if is_production_print_file
        else f"{file_stem}_{sanitize_download_name(printer.lower())}_preview_not_for_printer.gcode"
    )
    release_caption = (
        "Approve the plan first, then download the real slicer output or setup files."
        if is_production_print_file
        else "Approve the plan first, then download the preview or setup files. The preview is not printer-ready until a slicer backend is connected."
    )
    approval_label = (
        "I approve this manufacturing plan and understand this download is printer-ready only after real slicer output exists"
        if is_production_print_file
        else "I understand this is a planning preview, and I approve saving or sharing this setup package"
    )
    output_source_title = "Planning preview"
    output_source_copy = "CipherSlice is still showing a planning-stage preview, not a confirmed printer-ready file."
    output_source_state = "Preview only"
    if mode == "Blueprint Assist Mode":
        output_source_title = "Blueprint brief"
        output_source_copy = "This mode produces a reconstruction brief and review packet, not G-code."
        output_source_state = "Draft brief"
    elif real_gcode:
        output_source_title = "Real Prusa output"
        output_source_copy = "This file came from a real PrusaSlicer backend run. The preview below is actual slicer-generated G-code."
        output_source_state = "Printer-ready path"
    elif slicer_path:
        output_source_title = "Slicer detected, output fallback used"
        output_source_copy = f"CipherSlice found a slicer backend, but this specific run did not return a usable G-code file. Current output is still a preview. Reason: {slicer_message}"
        output_source_state = "Fallback used"
    confidence_notes = build_confidence_explanation(mode, overall_confidence, slicer_path, objections)
    pre_printer_checklist = build_pre_printer_checklist(
        mode,
        slicer_path,
        connector_url,
        delivery_mode,
        is_production_print_file,
    )
    plan_change_cards = build_plan_change_cards(recommended_plan, optimized_plan) if mode == "Reliable Print Mode" else []
    plan_change_summary = build_plan_change_summary(plan_change_cards) if mode == "Reliable Print Mode" else []
    plan_tradeoff_estimate = build_plan_tradeoff_estimate(recommended_plan, optimized_plan) if mode == "Reliable Print Mode" else []
    slicer_transition_notes = build_slicer_transition_notes(slicer_path, is_production_print_file) if mode == "Reliable Print Mode" else []
    geometry_fix_actions = build_geometry_fix_actions(mesh_analysis) if mode == "Reliable Print Mode" else []
    slicer_capability_report = build_slicer_capability_report(slicer_label, slicer_path, printer_profile, optimized_plan) if mode == "Reliable Print Mode" else []
    slicer_decision_notes = build_slicer_decision_notes(optimized_plan, mesh_analysis) if mode == "Reliable Print Mode" else []
    handoff_audit_trail = build_handoff_audit_trail(
        filename,
        artifact_hash,
        printer,
        filament,
        delivery_mode,
        optimized_plan,
        mesh_analysis,
        overall_confidence,
        objections,
    ) if mode == "Reliable Print Mode" else None

    with result_col:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        st.markdown("### Current Plan Workspace")
        summary_col1, summary_col2, summary_col3 = st.columns(3, gap="medium")
        with summary_col1:
            with st.container(border=True):
                st.markdown("#### Ready Now")
                st.markdown(f"**{phase_title}**")
                st.write(phase_copy)
        with summary_col2:
            with st.container(border=True):
                st.markdown("#### Output Source")
                st.markdown(f"**{output_source_title}**")
                st.write(output_source_copy)
                st.caption(f"Current output state: {output_source_state}")
        with summary_col3:
            with st.container(border=True):
                st.markdown("#### Still To Connect")
                if mode != "Reliable Print Mode":
                    st.write("A validated 3D model still needs to be created or imported before CipherSlice can move into real slicing.")
                elif real_gcode:
                    st.write("A connected printer is optional for now. You only need hardware later when you want to physically run the approved print.")
                elif slicer_path:
                    st.write("Prusa is installed and reachable, but this run still needs a cleaner slicing pass before CipherSlice should call the output printer-ready.")
                else:
                    st.write("A real slicer backend still needs to be connected. That is the main reason the preview stays in planning mode instead of full production output.")
        review_area = "Overview"
        if mode == "Reliable Print Mode":
            workspace_key = f"review_workspace_{artifact_hash}"
            pending_workspace = st.session_state.pop("review_workspace_target", None)
            if pending_workspace:
                st.session_state[workspace_key] = pending_workspace
            elif experience_mode == "Advanced" and workspace_key not in st.session_state:
                st.session_state[workspace_key] = "Tuning"
            review_area = st.radio(
                "Review workspace",
                ["Overview", "Fit + 3D", "Tuning", "Compare", "Release"],
                horizontal=True,
                key=workspace_key,
            )
            st.caption("This keeps the workflow in focused sections so the page feels more like a workspace and less like one long report.")
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
        if mode != "Reliable Print Mode" or review_area == "Overview":
            with st.container(border=True):
                st.markdown('<div class="review-section"><div class="review-kicker">Readiness</div><div class="review-copy">This section tells the user what CipherSlice can genuinely do right now, before any printer promises get implied.</div>', unsafe_allow_html=True)
                st.markdown("#### What This Can Do Right Now")
                for label, value in pre_printer_checklist:
                    st.markdown(f"- **{label}:** `{value}`")
                if not slicer_path and mode == "Reliable Print Mode":
                    st.caption(
                        "Plain English: CipherSlice can inspect and plan the print today, but it should not claim real production G-code until a slicer engine is connected."
                    )
                st.markdown("</div>", unsafe_allow_html=True)
        if mode != "Reliable Print Mode" or review_area == "Overview":
            with st.container(border=True):
                st.markdown('<div class="review-section"><div class="review-kicker">Confidence</div><div class="review-copy">This is the software review score for the current job. The most cautious review role can hold the whole chain back.</div>', unsafe_allow_html=True)
                st.markdown("#### What Confidence Means")
                st.markdown(
                    "<div class='confidence-grid'>"
                    f"<div class='confidence-card'><div class='confidence-card-title'>Current score</div><div class='confidence-card-value'>{overall_confidence * 100:.0f}%</div><div class='review-header-copy'>CipherSlice's software-side trust score for this job.</div></div>"
                f"<div class='confidence-card'><div class='confidence-card-title'>Release bar</div><div class='confidence-card-value'>94%</div><div class='review-header-copy'>The software threshold required before CipherSlice can claim a production-ready release.</div></div>"
                f"<div class='confidence-card'><div class='confidence-card-title'>Active blockers</div><div class='confidence-card-value'>{len(objections)}</div><div class='review-header-copy'>{'The chain is clear right now.' if not objections else 'At least one review role is still holding the chain.'}</div></div>"
                "</div>",
                unsafe_allow_html=True,
                )
                for note in confidence_notes:
                    st.markdown(f"- {note}")
                st.markdown("</div>", unsafe_allow_html=True)
        if mode == "Reliable Print Mode":
            if review_area == "Overview":
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">Machine Fit</div><div class="review-copy">This section explains how the selected printer itself shapes the safe print strategy before any slicer or hardware handoff happens.</div>', unsafe_allow_html=True)
                    st.markdown("#### Printer + Material Reality Check")
                    machine_col1, machine_col2 = st.columns(2, gap="medium")
                    with machine_col1:
                        for label, value in machine_profile_notes:
                            st.markdown(f"- **{label}:** `{value}`")
                    with machine_col2:
                        st.markdown("**Why CipherSlice is being careful**")
                        for note in printer_material_notes:
                            st.markdown(f"- {note}")
                    st.markdown("</div>", unsafe_allow_html=True)
                build_x, build_y, build_z = parse_bed_dimensions(printer_profile)
                fit_title, fit_copy = summarize_fit(mesh_analysis, printer_profile)
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">Quick Summary</div><div class="review-copy">A fast read of the current job, without making the user scan a long checklist.</div>', unsafe_allow_html=True)
                    st.markdown("#### At a Glance")
                    st.caption(f"Built in `{persona['label']}` tone.")
                    st.markdown(
                        f"""
                        <div class="glance-grid">
                            <div class="glance-card">
                                <div class="glance-label">Printer</div>
                                <div class="glance-value">{printer}</div>
                                <div class="glance-note">{printer_profile.get('family', 'Unknown')}</div>
                            </div>
                            <div class="glance-card">
                                <div class="glance-label">Material</div>
                                <div class="glance-value">{filament}</div>
                                <div class="glance-note">{optimized_plan['nozzle_temp']} degC nozzle / {optimized_plan['bed_temp']} degC bed</div>
                            </div>
                            <div class="glance-card">
                                <div class="glance-label">Output</div>
                                <div class="glance-value">{output_type_title}</div>
                                <div class="glance-note">{connection_title}</div>
                            </div>
                            <div class="glance-card">
                                <div class="glance-label">Confidence</div>
                                <div class="glance-value">{overall_confidence * 100:.0f}%</div>
                                <div class="glance-note">Lowest review role sets the final score</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        "<div class='metric-chip-row'>"
                        f"<span class='metric-chip'><strong>Layer / infill / walls:</strong> {optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}% / {optimized_plan['wall_loops']}</span>"
                        f"<span class='metric-chip'><strong>Support / adhesion:</strong> {'Enabled' if optimized_plan['support_enabled'] else 'Disabled'} / {optimized_plan['adhesion']}</span>"
                        f"<span class='metric-chip'><strong>Delivery path:</strong> {delivery_mode}</span>"
                        f"<span class='metric-chip'><strong>Job mode:</strong> {execution_label}</span>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    st.caption(printer_profile.get("printer_note", ""))
                    st.caption(guidance_copy)
                    st.caption(connection_copy)
                    for note in printer_material_notes:
                        st.caption(note)
                    st.markdown("</div>", unsafe_allow_html=True)

            if review_area == "Fit + 3D":
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">Fit Preview</div><div class="review-copy">A visual sizing check so users can understand bed fit before digging into deeper tuning.</div>', unsafe_allow_html=True)
                    st.markdown("#### Print Fit Studio")
                    st.markdown("<div class='preview-section-grid'><div class='preview-visual-stack'>", unsafe_allow_html=True)
                    st.markdown(build_bed_preview_svg(mesh_analysis, printer_profile), unsafe_allow_html=True)
                    st.markdown(build_model_shape_preview_svg(mesh_analysis), unsafe_allow_html=True)
                    st.markdown("</div><div class='preview-notes-card'>", unsafe_allow_html=True)
                    st.markdown("<div class='preview-notes-title'>Fit Notes</div>", unsafe_allow_html=True)
                    st.markdown("<div class='preview-notes-copy'>", unsafe_allow_html=True)
                    st.markdown(
                        f"**Printer volume (X/Y/Z):** `{format_xyz_dims(build_x, build_y, build_z)}`"
                    )
                    if mesh_analysis and mesh_analysis.get("scaled_extents_mm"):
                        px, py, pz = mesh_analysis["scaled_extents_mm"]
                        st.markdown(f"**Part size (X/Y/Z):** `{format_xyz_dims(px, py, pz)}`")
                    elif mesh_analysis and mesh_analysis.get("extents_mm"):
                        px, py, pz = mesh_analysis["extents_mm"]
                        st.markdown(f"**Part size (X/Y/Z):** `{format_xyz_dims(px, py, pz)}`")
                    else:
                        st.markdown("**Part size (X/Y/Z):** `Pending mesh analysis`")
                    st.markdown(f"**Fit state:** `{fit_title}`")
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
                        st.markdown(f"**Geometry profile:** `{mesh_analysis['geometry_profile']}`")
                    if mesh_analysis and mesh_analysis.get("longest_corrected_dimension_mm") is not None:
                        st.markdown(
                            f"**Longest corrected dimension:** `{mesh_analysis['longest_corrected_dimension_mm']:.2f} mm`"
                        )
                    if mesh_analysis and mesh_analysis.get("adhesion_hint"):
                        st.markdown(f"**Bed grip hint:** `{mesh_analysis['adhesion_hint']}`")
                    if mesh_analysis and mesh_analysis.get("support_density_hint"):
                        st.markdown(f"**Support hint:** `{mesh_analysis['support_density_hint']}`")
                    for adaptive_note in (mesh_analysis or {}).get("adaptive_notes", [])[:3]:
                        st.caption(adaptive_note)
                    st.markdown("</div></div></div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

            if review_area == "Fit + 3D":
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">3D Inspection</div><div class="review-copy">This is the first true interactive part view in CipherSlice. Users can orbit the model, inspect scale and shape, and then compare orientation suggestions before trusting the plan.</div>', unsafe_allow_html=True)
                    st.markdown("#### Interactive Part View")
                    preview_angle = st.selectbox(
                        "3D preview camera",
                        ["Isometric", "Top", "Front", "Side"],
                        index=0,
                        key=f"preview_angle_{artifact_hash}",
                    )
                    current_orientation_label = str(st.session_state.get(orientation_state_key, "As loaded"))
                    render_interactive_mesh_preview(
                        mesh_analysis,
                        printer_profile,
                        preview_angle,
                        current_orientation_label,
                        str(optimized_plan.get("seam_position", "Rear")),
                        f"mesh_preview_{artifact_hash}",
                    )
                    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
                    st.markdown("#### Orientation Suggestions")
                    if mesh_analysis and mesh_analysis.get("orientation_shift_note"):
                        st.info(str(mesh_analysis["orientation_shift_note"]))
                    st.markdown(
                        build_orientation_candidate_preview((mesh_analysis or {}).get("orientation_candidates", [])),
                        unsafe_allow_html=True,
                    )
                    orientation_candidates = list((mesh_analysis or {}).get("orientation_candidates", []))
                    if orientation_candidates:
                        st.caption("Click a posture below to make the 3D preview inspect that print direction.")
                        orientation_cols = st.columns(len(orientation_candidates), gap="small")
                        for column, candidate in zip(orientation_cols, orientation_candidates):
                            with column:
                                if st.button(
                                    f"View {candidate['label']}",
                                    use_container_width=True,
                                    key=f"orientation_focus_{artifact_hash}_{candidate['label']}",
                                    type="primary" if current_orientation_label == candidate["label"] else "secondary",
                                ):
                                    st.session_state[orientation_state_key] = str(candidate["label"])
                                    st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)

            if review_area == "Fit + 3D":
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">Geometry Review</div><div class="review-copy">This section explains how healthy the mesh looks, how it fits the machine, and why CipherSlice trusts or questions the geometry.</div>', unsafe_allow_html=True)
                    st.markdown("#### Shape Health Review")
                    if mesh_analysis:
                        st.markdown(
                            "<div class='insight-grid'>"
                            f"<div class='insight-card'><div class='insight-card-title'>Recommended orientation</div><div class='insight-card-value'>{mesh_analysis.get('recommended_orientation_label', 'Pending')}</div><div class='insight-card-copy'>{mesh_analysis.get('orientation_shift_note', 'CipherSlice will suggest a safer print posture here when geometry review is ready.')}</div></div>"
                            f"<div class='insight-card'><div class='insight-card-title'>Support density hint</div><div class='insight-card-value'>{mesh_analysis.get('support_density_hint', 'Pending')}</div><div class='insight-card-copy'>This is the geometry-driven support starting point before you fine-tune the live plan.</div></div>"
                            f"<div class='insight-card'><div class='insight-card-title'>Bed adhesion hint</div><div class='insight-card-value'>{mesh_analysis.get('adhesion_hint', 'Pending')}</div><div class='insight-card-copy'>This is CipherSlice’s current read on how much first-layer help the part probably needs.</div></div>"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                    geo_col1, geo_col2 = st.columns([0.9, 1.1], gap="medium")
                    with geo_col1:
                        for label, value in build_geometry_intelligence(mesh_analysis, printer_profile):
                            st.markdown(f"- **{label}:** `{value}`")
                        if mesh_analysis and mesh_analysis.get("scaled_extents_mm"):
                            part_x, part_y, part_z = mesh_analysis["scaled_extents_mm"]
                            st.markdown(
                                f"- **Dimensions (X/Y/Z):** `{format_xyz_dims(part_x, part_y, part_z)}`"
                            )
                    with geo_col2:
                        if mesh_analysis and mesh_analysis.get("scale_factor") and float(mesh_analysis["scale_factor"]) != 1.0:
                            st.info(
                                f"CipherSlice applied a scale correction of `{float(mesh_analysis['scale_factor']):.2f}x` so the model could be reviewed against the selected printer more realistically."
                            )
                        if mesh_analysis and mesh_analysis.get("issues"):
                            st.markdown("**Blockers**")
                            for issue in mesh_analysis["issues"]:
                                st.markdown(f"- {issue}")
                        if mesh_analysis and mesh_analysis.get("warning_issues"):
                            st.markdown("**Cautions**")
                            for issue in mesh_analysis["warning_issues"]:
                                st.markdown(f"- {issue}")
                        if mesh_analysis and mesh_analysis.get("healthy_signals"):
                            st.markdown("**Healthy signals**")
                            for signal in mesh_analysis["healthy_signals"]:
                                st.markdown(f"- {signal}")
                        elif not (mesh_analysis and mesh_analysis.get("issues")):
                            st.markdown("**What looks healthy**")
                            st.markdown("- No major geometry blockers are active in the current software review.")
                        st.markdown("**Best recovery moves**")
                        for action in geometry_fix_actions:
                            st.markdown(f"- {action}")
                        for note in (mesh_analysis or {}).get("notes", []):
                            st.caption(note)
                        st.markdown("</div>", unsafe_allow_html=True)
            if review_area == "Overview":
                st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            if review_area == "Overview":
                with st.container(border=True):
                    st.markdown("#### Plan")
                    st.markdown(
                        f"""
                        - **Source file:** `{filename}`
                        - **File size:** `{format_bytes(file_size)}`
                        - **Job mode:** `{execution_label}`
                        - **Guidance engine:** `{guidance_title}`
                        - **Printer profile:** `{printer}`
                        - **Filament strategy:** `{filament}`
                        - **Build volume (X/Y/Z):** `{format_xyz_dims(build_x, build_y, build_z)}`
                        - **Nozzle / bed:** `{optimized_plan['nozzle_temp']} degC / {optimized_plan['bed_temp']} degC`
                        - **Layer height / infill:** `{optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}%`
                        - **Wall loops / speed:** `{optimized_plan['wall_loops']} / {optimized_plan['print_speed']} mm/s`
                        - **Top / bottom layers:** `{optimized_plan.get('top_layers', 4)} / {optimized_plan.get('bottom_layers', 4)}`
                        - **Retraction / acceleration:** `{optimized_plan.get('retraction_length', 1.2)} mm / {optimized_plan.get('acceleration', 3000)} mm/s^2`
                        - **Seam position:** `{optimized_plan.get('seam_position', 'Rear')}`
                        - **Supports:** `{'Enabled' if optimized_plan['support_enabled'] else 'Disabled'}`
                        - **Adhesion / nozzle:** `{optimized_plan['adhesion']} / {optimized_plan['nozzle_diameter']} mm`
                        """
                    )
                    st.markdown(
                        "<div class='metric-chip-row'>"
                        f"<span class='metric-chip'><strong>Output:</strong> {output_type_title}</span>"
                        f"<span class='metric-chip'><strong>Engine:</strong> {connection_title}</span>"
                        f"<span class='metric-chip'><strong>Guidance:</strong> {guidance_title}</span>"
                        f"<span class='metric-chip'><strong>Confidence:</strong> {overall_confidence * 100:.0f}%</span>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
            if review_area == "Overview":
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
            if review_area == "Tuning":
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">Editable Planning</div><div class="review-copy">These are the places where the live plan moved away from CipherSlice\'s first recommendation, along with what that tradeoff usually means.</div>', unsafe_allow_html=True)
                    st.markdown("#### Plan Changes")
                    if plan_change_summary:
                        st.markdown(
                            "<div class='insight-grid'>"
                            + "".join(
                                f"<div class='insight-card'><div class='insight-card-title'>{title}</div><div class='insight-card-value'>{value}</div><div class='insight-card-copy'>{copy}</div></div>"
                                for title, value, copy in plan_change_summary
                            )
                            + "</div>",
                            unsafe_allow_html=True,
                        )
                    if plan_tradeoff_estimate:
                        st.markdown(
                            "<div class='metric-chip-row'>"
                            + "".join(
                                f"<span class='metric-chip'><strong>{label}:</strong> {value}</span>"
                                for label, value in plan_tradeoff_estimate
                            )
                            + "</div>",
                            unsafe_allow_html=True,
                        )
                    if plan_change_cards:
                        st.caption("These settings differ from CipherSlice's first recommendation for this job.")
                        st.markdown(
                            "<div class='change-grid'>"
                            + "".join(
                                f"<div class='change-card{' change-card-risk' if card['risk'] in {'watch closely', 'tuning-sensitive'} else ''}'>"
                                f"<div class='change-name'>{card['label']}</div>"
                                f"<div class='change-meta'>Recommended: <strong>{card['recommended']}</strong><br>Current: <strong>{card['current']}</strong><br>{card['reason']}</div>"
                                f"<div class='change-risk'>{card['risk']}</div>"
                                f"</div>"
                                for card in plan_change_cards
                            )
                            + "</div>",
                            unsafe_allow_html=True,
                        )
                    elif plan_diff_lines:
                        for diff_line in plan_diff_lines:
                            st.markdown(f"- {diff_line}")
                    else:
                        st.success("The current live plan still matches the recommended defaults.")
                    tune_action_col1, tune_action_col2 = st.columns(2, gap="medium")
                    with tune_action_col1:
                        if st.button("Restore Risky Settings", use_container_width=True, key=f"restore_risky_{artifact_hash}"):
                            restore_risky_recommended_settings(artifact_hash, recommended_plan)
                            st.rerun()
                    with tune_action_col2:
                        if st.button("Save Current Profile", use_container_width=True, key=f"save_profile_{artifact_hash}"):
                            saved_profiles = list(st.session_state.get(saved_profile_key, []))
                            saved_profiles.append(
                                {
                                    "label": f"Profile {len(saved_profiles) + 1}",
                                    "controls": extract_plan_controls(optimized_plan),
                                }
                            )
                            st.session_state[saved_profile_key] = saved_profiles[-8:]
                            st.rerun()
                    saved_profiles = list(st.session_state.get(saved_profile_key, []))
                    if saved_profiles:
                        load_profile_col1, load_profile_col2 = st.columns([0.7, 0.3], gap="small")
                        with load_profile_col1:
                            selected_profile_label = st.selectbox(
                                "Saved profile",
                                [profile["label"] for profile in saved_profiles],
                                key=f"saved_profile_select_{artifact_hash}",
                            )
                        with load_profile_col2:
                            st.write("")
                            st.write("")
                            if st.button("Load Saved Profile", use_container_width=True, key=f"load_profile_{artifact_hash}"):
                                selected_profile = next(profile for profile in saved_profiles if profile["label"] == selected_profile_label)
                                apply_snapshot_to_state(
                                    artifact_hash,
                                    {
                                        "label": selected_profile["label"],
                                        "controls": selected_profile["controls"],
                                    },
                                )
                                st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)
            if mode == "Reliable Print Mode" and review_area == "Compare":
                snapshot_bank = list(st.session_state.get(f"plan_snapshots_{artifact_hash}", []))
                current_snapshot = {
                    "label": "Current live plan",
                    "filename": filename,
                    "printer": printer,
                    "filament": filament,
                    "controls": extract_plan_controls(optimized_plan),
                    "kind": "live",
                }
                snapshot_options = snapshot_bank + [current_snapshot]
                snapshot_labels = [str(snapshot["label"]) for snapshot in snapshot_options]
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">Snapshot Lab</div><div class="review-copy">Save checkpoints, compare two tuning paths, and restore a previous idea without losing the rest of the job context.</div>', unsafe_allow_html=True)
                    st.markdown("#### Plan Snapshots + Compare")
                    snap_action_col1, snap_action_col2 = st.columns(2, gap="medium")
                    with snap_action_col1:
                        left_snapshot_label = st.selectbox(
                            "Left snapshot",
                            snapshot_labels,
                            index=max(0, len(snapshot_labels) - 2),
                            key=f"snapshot_left_{artifact_hash}",
                        )
                    with snap_action_col2:
                        right_snapshot_label = st.selectbox(
                            "Right snapshot",
                            snapshot_labels,
                            index=len(snapshot_labels) - 1,
                            key=f"snapshot_right_{artifact_hash}",
                        )
                    left_snapshot = next(snapshot for snapshot in snapshot_options if snapshot["label"] == left_snapshot_label)
                    right_snapshot = next(snapshot for snapshot in snapshot_options if snapshot["label"] == right_snapshot_label)
                    st.markdown(
                        "<div class='compare-grid'>"
                        f"<div class='compare-card'><h5>{left_snapshot['label']}</h5><p>Printer: <strong>{left_snapshot['printer']}</strong></p><p>Filament: <strong>{left_snapshot['filament']}</strong></p><p>Preset: <strong>{left_snapshot['controls'].get('profile_preset', 'Recommended')}</strong></p><p>Layer / speed: <strong>{left_snapshot['controls'].get('layer_height')} mm / {left_snapshot['controls'].get('print_speed')} mm/s</strong></p></div>"
                        f"<div class='compare-card'><h5>{right_snapshot['label']}</h5><p>Printer: <strong>{right_snapshot['printer']}</strong></p><p>Filament: <strong>{right_snapshot['filament']}</strong></p><p>Preset: <strong>{right_snapshot['controls'].get('profile_preset', 'Recommended')}</strong></p><p>Layer / speed: <strong>{right_snapshot['controls'].get('layer_height')} mm / {right_snapshot['controls'].get('print_speed')} mm/s</strong></p></div>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    snapshot_diff_lines = build_snapshot_diff_lines(left_snapshot, right_snapshot)
                    if snapshot_diff_lines:
                        st.markdown("**Exactly what changed**")
                        for diff_line in snapshot_diff_lines:
                            st.markdown(f"- {diff_line}")
                    else:
                        st.success("These two snapshots currently match on the tracked plan controls.")
                    restore_compare_col1, restore_compare_col2 = st.columns(2, gap="medium")
                    with restore_compare_col1:
                        if left_snapshot["label"] != "Current live plan" and st.button("Restore Left Snapshot", use_container_width=True, key=f"restore_left_snapshot_{artifact_hash}"):
                            apply_snapshot_to_state(artifact_hash, left_snapshot)
                            st.rerun()
                    with restore_compare_col2:
                        if right_snapshot["label"] != "Current live plan" and st.button("Restore Right Snapshot", use_container_width=True, key=f"restore_right_snapshot_{artifact_hash}"):
                            apply_snapshot_to_state(artifact_hash, right_snapshot)
                            st.rerun()
                    compare_export_text = (
                        "CipherSlice Snapshot Compare\n\n"
                        f"Left: {left_snapshot['label']}\n"
                        f"Right: {right_snapshot['label']}\n\n"
                        + "\n".join(snapshot_diff_lines or ["No tracked differences."])
                    )
                    compare_button_col1, compare_button_col2 = st.columns(2, gap="medium")
                    with compare_button_col1:
                        st.download_button(
                            "Download Current Snapshot Summary",
                            data=build_snapshot_export_text(current_snapshot),
                            file_name=f"{file_stem}_current_plan_snapshot.txt",
                            mime="text/plain",
                            use_container_width=True,
                        )
                    with compare_button_col2:
                        st.download_button(
                            "Download Snapshot Comparison",
                            data=compare_export_text,
                            file_name=f"{file_stem}_snapshot_compare.txt",
                            mime="text/plain",
                            use_container_width=True,
                        )
                    st.markdown("</div>", unsafe_allow_html=True)
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">What-If Lab</div><div class="review-copy">This lets the user test another material or printer without re-uploading the same part.</div>', unsafe_allow_html=True)
                    st.markdown("#### Compare Another Printer or Material")
                    compare_col1, compare_col2 = st.columns(2, gap="medium")
                    with compare_col1:
                        compare_printer = st.selectbox(
                            "What-if printer",
                            list(PRINTER_PROFILES.keys()),
                            index=list(PRINTER_PROFILES.keys()).index(printer),
                            key=f"what_if_printer_{artifact_hash}",
                        )
                    with compare_col2:
                        compare_filament = st.selectbox(
                            "What-if filament",
                            FILAMENT_TYPES,
                            index=FILAMENT_TYPES.index(filament),
                            key=f"what_if_filament_{artifact_hash}",
                        )
                    compare_printer_profile = PRINTER_PROFILES[compare_printer]
                    alt_mesh_analysis, alt_plan, alt_score, alt_fit_state = build_what_if_plan_summary(
                        uploaded_file,
                        compare_printer,
                        compare_printer_profile,
                        compare_filament,
                        quality_profile,
                        print_goal,
                        support_strategy,
                        adhesion_strategy,
                        auto_scale_mesh,
                    )
                    current_risk = str((mesh_analysis or {}).get("risk_level", "Unknown"))
                    alt_risk = str((alt_mesh_analysis or {}).get("risk_level", "Unknown"))
                    best_safe_option = "Stay with the current setup"
                    if alt_score > overall_confidence and not (alt_mesh_analysis or {}).get("issues"):
                        best_safe_option = f"Switch to {compare_printer} with {compare_filament}"
                    st.markdown(
                        "<div class='compare-grid'>"
                        f"<div class='compare-card'><h5>Current setup</h5><p>Printer: <strong>{printer}</strong></p><p>Filament: <strong>{filament}</strong></p><p>Risk: <strong>{current_risk}</strong></p><p>Layer / speed: <strong>{optimized_plan['layer_height']} mm / {optimized_plan['print_speed']} mm/s</strong></p><p>Confidence: <strong>{overall_confidence * 100:.0f}%</strong></p></div>"
                        f"<div class='compare-card'><h5>What-if setup</h5><p>Printer: <strong>{compare_printer}</strong></p><p>Filament: <strong>{compare_filament}</strong></p><p>Fit: <strong>{alt_fit_state}</strong></p><p>Risk: <strong>{alt_risk}</strong></p><p>Layer / speed: <strong>{alt_plan['layer_height']} mm / {alt_plan['print_speed']} mm/s</strong></p><p>Estimated software confidence: <strong>{alt_score * 100:.0f}%</strong></p></div>"
                        "</div>",
                        unsafe_allow_html=True,
                    )
                    st.info(f"Best safe option right now: {best_safe_option}.")
                    st.markdown("</div>", unsafe_allow_html=True)
            if mode == "Reliable Print Mode" and review_area == "Release":
                with st.container(border=True):
                    st.markdown('<div class="review-section"><div class="review-kicker">Slicer Handoff</div><div class="review-copy">This explains what becomes more real once a slicer backend is connected and why that matters for trustworthy output.</div>', unsafe_allow_html=True)
                    st.markdown("#### What Changes When Slicing Connects")
                    st.markdown(
                        "<div class='transition-grid'>"
                        + "".join(
                            f"<div class='transition-card'><div class='transition-title'>{title}</div><div class='transition-copy'>{copy}</div></div>"
                            for title, copy in slicer_transition_notes
                        )
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                    st.markdown("**Slicer readiness report**")
                    for label, value in slicer_capability_report:
                        st.markdown(f"- **{label}:** `{value}`")
                    st.markdown("**What the slicer still decides**")
                    for note in slicer_decision_notes:
                        st.markdown(f"- {note}")
                    st.markdown("**Pre-slicer launch check**")
                    pre_slicer_ready = bool(slicer_path) and not objections
                    if pre_slicer_ready:
                        st.success("The software-side plan is ready to hand into a deterministic slicer engine for real toolpath generation.")
                    else:
                        st.warning("CipherSlice is still holding full release. Clear the blockers above and connect a supported slicer backend before calling this printer-ready.")
                    st.markdown("</div>", unsafe_allow_html=True)
            if review_area == "Release":
                st.markdown(
                f'<div class="success-banner">Delivery package ready for {filename}. '
                f'Protected for approved printer handoff.</div>',
                unsafe_allow_html=True,
            )
            if review_area == "Release":
                st.markdown(
                "<div class='summary-strip'>"
                f"<div class='summary-pill'><strong>Part + printer</strong>{filename}<br>{printer}</div>"
                f"<div class='summary-pill'><strong>Layer / speed</strong>{optimized_plan['layer_height']} mm<br>{optimized_plan['print_speed']} mm/s</div>"
                f"<div class='summary-pill'><strong>Material + output</strong>{filament}<br>{output_type_title}</div>"
                f"<div class='summary-pill'><strong>Approval state</strong>{'Ready for approval' if release_allowed else 'Held for review'}<br>{overall_confidence * 100:.0f}% confidence</div>"
                "</div>",
                unsafe_allow_html=True,
            )
            if review_area == "Release":
                st.markdown("#### Final Print Manifest")
            if review_area == "Release":
                st.markdown(
                f"""
                <div class="manifest-card">
                    <div class="manifest-grid">
                        <div class="manifest-section">
                            <div class="manifest-section-title">Job Identity</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Part:</strong></span> {filename}</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Printer:</strong></span> {printer}</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Build volume (X/Y/Z):</strong></span> {format_xyz_dims(build_x, build_y, build_z)}</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Filament:</strong></span> {filament}</div>
                        </div>
                        <div class="manifest-section">
                            <div class="manifest-section-title">Core Tuning</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Nozzle / bed:</strong></span> {optimized_plan['nozzle_temp']} degC / {optimized_plan['bed_temp']} degC</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Layer / infill / walls:</strong></span> {optimized_plan['layer_height']} mm / {optimized_plan['infill_percent']}% / {optimized_plan['wall_loops']}</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Top / bottom layers:</strong></span> {optimized_plan.get('top_layers', 4)} / {optimized_plan.get('bottom_layers', 4)}</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Infill pattern:</strong></span> {optimized_plan.get('infill_pattern', 'Gyroid')}</div>
                        </div>
                        <div class="manifest-section">
                            <div class="manifest-section-title">Motion + First Layer</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Outer / inner / travel:</strong></span> {optimized_plan.get('outer_wall_speed', optimized_plan['print_speed'])} / {optimized_plan.get('inner_wall_speed', optimized_plan['print_speed'])} / {optimized_plan.get('travel_speed', optimized_plan['print_speed'])} mm/s</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>First layer:</strong></span> {optimized_plan.get('first_layer_height', optimized_plan['layer_height'])} mm / {optimized_plan.get('first_layer_speed', 20)} mm/s / {optimized_plan.get('first_layer_flow', 100)}%</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Retraction / acceleration:</strong></span> {optimized_plan.get('retraction_length', 1.2)} mm / {optimized_plan.get('acceleration', 3000)} mm/s^2</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Jerk / seam:</strong></span> {optimized_plan.get('jerk_control', 8)} / {optimized_plan.get('seam_position', 'Rear')}</div>
                        </div>
                        <div class="manifest-section">
                            <div class="manifest-section-title">Support + Delivery</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Support:</strong></span> {'Enabled' if optimized_plan['support_enabled'] else 'Disabled'} / {optimized_plan.get('support_pattern', 'Lines')} / {'Interface on' if optimized_plan.get('support_interface') else 'Interface off'}</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Adhesion:</strong></span> {optimized_plan['adhesion']} / brim {optimized_plan.get('brim_width', 0)} mm / skirt {optimized_plan.get('skirt_loops', 0)} loops</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Delivery mode:</strong></span> {delivery_mode}</div>
                            <div class="manifest-line"><span class="manifest-key"><strong>Confidence / release:</strong></span> {overall_confidence * 100:.1f}% / {'APPROVED' if release_allowed else 'HELD'}</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if review_area == "Overview":
                st.markdown("### Best Next Move")
                st.info(next_action)
            if review_area == "Overview" and not slicer_path:
                st.warning(
                    "Production release is still held by design because no slicer backend is connected. "
                    "That is why the print-file score stays capped and different files can still share similar high-level settings."
                )
            status_rows = build_status_board(
                mode,
                slicer_path,
                connector_url,
                release_allowed,
                final_user_approval,
                delivery_mode,
            )
            if review_area == "Overview":
                st.markdown("### Readiness Check")
                for label, value in status_rows:
                    st.markdown(f"- **{label}:** `{value}`")
                if mode == "Reliable Print Mode":
                    with st.container(border=True):
                        st.markdown("#### Slicer Run Status")
                        st.markdown(f"**{output_source_title}**")
                        st.write(output_source_copy)
                        st.caption(slicer_message)
            if review_area == "Release":
                with st.container(border=True):
                    st.markdown("#### Final Human Checkpoint")
                    if is_production_print_file:
                        st.caption("This confirms you want CipherSlice to unlock the real slicer-generated print file and release tools for this job.")
                    else:
                        st.caption("This does not send anything to a printer. It only unlocks the preview and setup downloads for this planning-stage job.")
                    final_user_approval = st.checkbox(
                        approval_label,
                        key=approval_key,
                    )
            status_rows = build_status_board(
                mode,
                slicer_path,
                connector_url,
                release_allowed,
                final_user_approval,
                delivery_mode,
            )
            if review_area == "Release":
                st.markdown("### Final Approval Status")
                for label, value in status_rows:
                    st.markdown(f"- **{label}:** `{value}`")
            if review_area == "Release":
                with st.container(border=True):
                    st.markdown("#### Release")
                    st.caption(release_caption)
                    st.download_button(
                        print_file_download_label,
                        data=primary_artifact,
                        file_name=print_file_download_name,
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
                        st.download_button(
                            "Download Slicer Connection Notes",
                            data=print_engine_setup_notes,
                            file_name=f"{file_stem}_print_engine_setup.txt",
                            mime="text/plain",
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
                    if handoff_audit_trail:
                        st.download_button(
                            "Download Handoff Audit Trail",
                            data=handoff_audit_trail,
                            file_name=f"{file_stem}_handoff_audit.txt",
                            mime="text/plain",
                            use_container_width=True,
                        )
            if review_area == "Release":
                with st.container(border=True):
                    st.markdown("#### What Happens Next")
                    st.markdown(
                        "<div class='transition-grid'>"
                        + "".join(
                            f"<div class='transition-card'><div class='transition-title'>{title}</div><div class='transition-copy'>{copy}</div></div>"
                            for title, copy in (
                                [
                                    ("Preview workflow", "Download the preview or setup pack, then move into a real slicer before any physical print should be trusted."),
                                    ("Slicer workflow", "Reconnect the same job after a slicer backend is installed so CipherSlice can upgrade from planning preview to real slicing."),
                                    ("Hardware workflow", "Only after slicing and human approval should the job move toward SD transfer, connector handoff, or a live printer."),
                                ]
                                if not is_production_print_file
                                else [
                                    ("Approval workflow", "The user confirms the plan, unlocks the slicer-made print file, and keeps final human control."),
                                    ("Delivery workflow", "CipherSlice packages the file for SD export, manual review, or future secure local connector handoff."),
                                    ("Printer workflow", "A real printer is only needed at the final execution step after the software review is already complete."),
                                ]
                            )
                        )
                        + "</div>",
                        unsafe_allow_html=True,
                    )
            if review_area == "Release" and delivery_mode == "SD card export":
                st.warning(
                    "SD card mode is compatible with many printers, but it is not a secure streaming channel. Once the file is exported, "
                    "CipherSlice cannot guarantee one-time use, remote revocation, or end-to-end hardware authentication."
                )
                st.markdown("**SD card operator checklist**")
                st.markdown("- Confirm the printer model and plastic profile match the exported plan.")
                st.markdown("- Label the print file clearly before copying it to removable media.")
                st.markdown("- Review temperatures, supports, and scale one last time on the printer screen before printing.")
            stream_triggered = review_area == "Release" and st.button(
                "Send to Approved Printer Link",
                use_container_width=True,
                key=f"hardware_stream_{artifact_hash}",
                disabled=not (release_allowed and final_user_approval and delivery_mode == "Secure local connector"),
            )
            if review_area == "Release" and delivery_mode != "Secure local connector":
                st.caption("Direct secure printer handoff is available only when `Delivery Mode` is set to `Secure local connector`.")
            if stream_triggered:
                with st.status("Preparing secure printer link...", expanded=True) as hardware_status:
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
                CipherSlice Encrypted Print File
                source_file={filename}
                printer={printer}
                filament={filament}
                salt_hex={encryption_salt}
                fernet_token={encrypted_artifact}
                """
            ).strip()
            st.download_button(
                "Download Encrypted Print File",
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
                st.caption("Encrypted print-file export is disabled for SD card delivery because removable media breaks the secure stream model.")
        elif wants_encryption and not encryption_passphrase:
            st.caption("Add an encryption passphrase if you want Cipher Vault to produce an encrypted download.")

        if stream_aborted:
            st.caption("Temporary secure hash status: `SELF-DESTRUCTED`")

        st.markdown("</div>", unsafe_allow_html=True)

    with code_col:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        with st.container(border=True):
            if mode == "Reliable Print Mode":
                st.markdown("#### Readiness Check")
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
                    if mesh_analysis.get("longest_corrected_dimension_mm") is not None:
                        st.markdown(
                            f"- **Longest corrected dimension:** `{mesh_analysis['longest_corrected_dimension_mm']:.2f} mm`"
                        )
                    if mesh_analysis["face_count"]:
                        st.markdown(f"- **Mesh faces:** `{mesh_analysis['face_count']:,}`")
                    if mesh_analysis["vertex_count"]:
                        st.markdown(f"- **Mesh vertices:** `{mesh_analysis['vertex_count']:,}`")
                    if mesh_analysis["watertight"] is not None:
                        st.markdown(f"- **Watertight mesh:** `{'Yes' if mesh_analysis['watertight'] else 'No'}`")
                    for note in mesh_analysis["notes"]:
                        st.caption(note)
                    for note in printer_material_notes:
                        st.caption(note)
                st.markdown("#### Slicer Status")
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
                st.markdown("#### Slicer Connection")
                st.markdown(
                    f"""
                    - **Detected print engine:** `{slicer_label or 'Not detected'}`
                    - **Engine path:** `{slicer_path or 'None configured'}`
                    - **Guidance runtime:** `{agent_runtime_meta['status']}`
                    - **Printer link:** `{connector_url or 'Not connected'}`
                    """
                )
                st.caption("CipherSlice can prepare engine setup notes and a slicer setup pack without exposing raw command details in the main website flow.")
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
                st.caption("Print-file confidence is capped in this environment because the final slicing engine is missing.")
            if objections:
                st.markdown("**Review blockers**")
                for reason in objections:
                    st.markdown(f"- {reason}")
            elif release_allowed:
                st.success("All agents cleared the release gate with no unresolved objections.")

            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
            if mode == "Reliable Print Mode":
                st.markdown("##### Real G-code Preview" if real_gcode else "##### Planning Preview")
                if real_gcode:
                    st.success("This preview is real PrusaSlicer-generated G-code from the current job.")
                elif slicer_path:
                    st.warning(
                        "Prusa is installed, but this run still fell back to preview output. Treat this block as planning-stage output until the slicer run is fully validated."
                    )
                else:
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
