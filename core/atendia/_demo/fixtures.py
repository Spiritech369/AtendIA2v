# core/atendia/_demo/fixtures.py
"""All hardcoded demo data in one place.

These constants are the single source of truth for demo tenant fixtures.
They are referenced by _demo/providers.py and served only when
tenant.is_demo is True.
"""
from __future__ import annotations

# ── Appointments ──────────────────────────────────────────────────────────────
# Copied from api/appointments_routes.py

DEMO_ADVISORS: list[dict] = [
    {"id": "maria_gonzalez", "name": "María González", "phone": "+5218110000101", "max_per_day": 8, "close_rate": 0.32},
    {"id": "ricardo_diaz", "name": "Ricardo Díaz", "phone": "+5218110000102", "max_per_day": 7, "close_rate": 0.29},
    {"id": "diego_morales", "name": "Diego Morales", "phone": "+5218110000103", "max_per_day": 7, "close_rate": 0.27},
    {"id": "sofia_nava", "name": "Sofía Nava", "phone": "+5218110000104", "max_per_day": 6, "close_rate": 0.34},
    {"id": "andrea_lopez", "name": "Andrea López", "phone": "+5218110000105", "max_per_day": 6, "close_rate": 0.26},
    {"id": "luis_hernandez", "name": "Luis Hernández", "phone": "+5218110000106", "max_per_day": 6, "close_rate": 0.24},
    {"id": "omar_medina", "name": "Omar Medina", "phone": "+5218110000107", "max_per_day": 6, "close_rate": 0.31},
    {"id": "claudia_pena", "name": "Claudia Peña", "phone": "+5218110000108", "max_per_day": 6, "close_rate": 0.28},
]

DEMO_VEHICLES: list[dict] = [
    {"id": "tcross_2024", "label": "T-Cross 2024", "status": "available", "available_for_test_drive": True},
    {"id": "jetta_2024", "label": "Jetta 2024", "status": "available", "available_for_test_drive": True},
    {"id": "taso_224", "label": "Taso 224", "status": "available", "available_for_test_drive": True},
    {"id": "tiguan_rline", "label": "Tiguan R-Line", "status": "reserved", "available_for_test_drive": True},
    {"id": "amarok_2024", "label": "Amarok 2024", "status": "available", "available_for_test_drive": True},
    {"id": "polo_2024", "label": "Polo 2024", "status": "available", "available_for_test_drive": True},
    {"id": "virtus_2024", "label": "Virtus 2024", "status": "available", "available_for_test_drive": True},
    {"id": "saveiro_2024", "label": "Saveiro 2024", "status": "maintenance", "available_for_test_drive": False},
]

# ── Handoffs command center ────────────────────────────────────────────────────
# Copied from api/_handoffs/command_center.py (was HUMAN_AGENT_SEED)

DEMO_HUMAN_AGENTS: list[dict] = [
    {"id": "andrea-ruiz", "name": "Andrea Ruiz", "email": "andrea@demo.com", "role": "operator", "status": "online", "max_active_cases": 8, "skills": ["facturacion", "documentos", "credito"], "current_workload": 2},
    {"id": "carlos-mendez", "name": "Carlos Mendez", "email": "carlos@demo.com", "role": "operator", "status": "online", "max_active_cases": 12, "skills": ["negociacion", "ventas", "cierre"], "current_workload": 3},
    {"id": "mariana-vega", "name": "Mariana Vega", "email": "mariana@demo.com", "role": "operator", "status": "busy", "max_active_cases": 12, "skills": ["pagos", "soporte", "sistema"], "current_workload": 6},
    {"id": "luis-ortega", "name": "Luis Ortega", "email": "luis@demo.com", "role": "operator", "status": "online", "max_active_cases": 10, "skills": ["agenda", "disponibilidad", "sucursal"], "current_workload": 4},
    {"id": "paola-nava", "name": "Paola Nava", "email": "paola@demo.com", "role": "manager", "status": "online", "max_active_cases": 6, "skills": ["sla", "quejas", "alto_valor"], "current_workload": 1},
    {"id": "diego-ai", "name": "Diego Salas", "email": "diego.ai@demo.com", "role": "ai_supervisor", "status": "online", "max_active_cases": 8, "skills": ["kb", "routing", "training"], "current_workload": 2},
]
