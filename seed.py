"""Demo seed: 40 fictional training centres across India.

Names are generic and fictional. Coordinates are approximate city locations.
Device keys follow `dev-<centre id>` for the demo only; generate random keys in production.
"""
from __future__ import annotations

import sqlite3

from .services.chain import GENESIS

TRADES = {
    "it": (["IT-ITeS: Domestic Data Entry Operator"], {"computer": 20, "seating": 30}, 30),
    "apparel": (["Apparel: Sewing Machine Operator"], {"sewing_machine": 20, "seating": 25, "workbench": 4}, 25),
    "electrical": (["Electronics: Field Technician"], {"workbench": 6, "computer": 4, "seating": 25}, 25),
    "workshop": (["Capital Goods: Welding & Machining"], {"workbench": 6, "lathe": 2, "welding_set": 2}, 20),
    "health": (["Healthcare: General Duty Assistant"], {"hospital_bed": 4, "seating": 25, "computer": 2}, 25),
}

CENTRES = [
    # id, city/district, state, lat, lng, trade
    ("TC-KA-001", "Bengaluru Urban", "Karnataka", 12.97, 77.59, "it"),
    ("TC-KA-007", "Mysuru", "Karnataka", 12.30, 76.64, "apparel"),
    ("TC-KA-012", "Dharwad", "Karnataka", 15.36, 75.12, "electrical"),
    ("TC-TN-004", "Chennai", "Tamil Nadu", 13.08, 80.27, "health"),
    ("TC-TN-009", "Coimbatore", "Tamil Nadu", 11.02, 76.96, "apparel"),
    ("TC-TN-015", "Madurai", "Tamil Nadu", 9.93, 78.12, "it"),
    ("TC-KL-003", "Ernakulam", "Kerala", 9.93, 76.27, "health"),
    ("TC-KL-008", "Thiruvananthapuram", "Kerala", 8.52, 76.94, "it"),
    ("TC-TS-006", "Hyderabad", "Telangana", 17.39, 78.49, "it"),
    ("TC-TS-011", "Warangal", "Telangana", 17.97, 79.59, "electrical"),
    ("TC-AP-005", "Visakhapatnam", "Andhra Pradesh", 17.69, 83.22, "workshop"),
    ("TC-AP-010", "Krishna", "Andhra Pradesh", 16.51, 80.65, "apparel"),
    ("TC-MH-002", "Mumbai Suburban", "Maharashtra", 19.08, 72.88, "it"),
    ("TC-MH-013", "Pune", "Maharashtra", 18.52, 73.86, "workshop"),
    ("TC-MH-021", "Nagpur", "Maharashtra", 21.15, 79.09, "electrical"),
    ("TC-GJ-004", "Ahmedabad", "Gujarat", 23.02, 72.57, "workshop"),
    ("TC-GJ-009", "Surat", "Gujarat", 21.17, 72.83, "apparel"),
    ("TC-RJ-006", "Jaipur", "Rajasthan", 26.91, 75.79, "it"),
    ("TC-RJ-018", "Jodhpur", "Rajasthan", 26.24, 73.02, "apparel"),
    ("TC-MP-003", "Bhopal", "Madhya Pradesh", 23.26, 77.41, "health"),
    ("TC-MP-011", "Indore", "Madhya Pradesh", 22.72, 75.86, "electrical"),
    ("TC-CG-002", "Raipur", "Chhattisgarh", 21.25, 81.63, "workshop"),
    ("TC-UP-008", "Lucknow", "Uttar Pradesh", 26.85, 80.95, "it"),
    ("TC-UP-019", "Kanpur Nagar", "Uttar Pradesh", 26.45, 80.33, "workshop"),
    ("TC-UP-027", "Varanasi", "Uttar Pradesh", 25.32, 82.97, "apparel"),
    ("TC-BR-005", "Patna", "Bihar", 25.59, 85.14, "it"),
    ("TC-BR-014", "Gaya", "Bihar", 24.79, 85.00, "electrical"),
    ("TC-BR-022", "Banka", "Bihar", 24.89, 86.92, "apparel"),
    ("TC-JH-004", "Ranchi", "Jharkhand", 23.34, 85.31, "health"),
    ("TC-WB-007", "Kolkata", "West Bengal", 22.57, 88.36, "it"),
    ("TC-OD-003", "Khordha", "Odisha", 20.30, 85.82, "electrical"),
    ("TC-AS-002", "Kamrup Metro", "Assam", 26.14, 91.74, "health"),
    ("TC-PB-014", "Ludhiana", "Punjab", 30.90, 75.85, "workshop"),
    ("TC-PB-020", "Amritsar", "Punjab", 31.63, 74.87, "apparel"),
    ("TC-HR-006", "Gurugram", "Haryana", 28.46, 77.03, "it"),
    ("TC-DL-010", "New Delhi", "Delhi", 28.61, 77.21, "health"),
    ("TC-UK-003", "Dehradun", "Uttarakhand", 30.32, 78.03, "electrical"),
    ("TC-HP-002", "Shimla", "Himachal Pradesh", 31.10, 77.17, "it"),
    ("TC-JK-004", "Srinagar", "Jammu & Kashmir", 34.08, 74.80, "apparel"),
    ("TC-CH-001", "Chandigarh", "Chandigarh", 30.73, 76.78, "workshop"),
]

NAME_STYLE = {"it": "Digital Skills Centre", "apparel": "Apparel Training Centre", "electrical": "Electronics Skill Centre",
              "workshop": "Technical Workshop Centre", "health": "Healthcare Skills Centre"}


def seed_rows():
    for cid, district, state, lat, lng, trade in CENTRES:
        trades, inv, cap = TRADES[trade]
        yield {
            "id": cid, "name": f"{district} {NAME_STYLE[trade]}", "state": state, "district": district,
            "lat": lat, "lng": lng, "scheme": "PMKVY 4.0", "trades": trades, "capacity": cap,
            "sanctioned_inventory": inv, "device_key": f"dev-{cid}", "trade": trade,
        }


def seed_if_empty(con: sqlite3.Connection) -> int:
    if con.execute("SELECT COUNT(*) FROM centres").fetchone()[0]:
        return 0
    from .db import dumps

    n = 0
    for c in seed_rows():
        con.execute(
            "INSERT INTO centres (id,name,state,district,lat,lng,scheme,trades,capacity,sanctioned_inventory,device_key,chain_head) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (c["id"], c["name"], c["state"], c["district"], c["lat"], c["lng"], c["scheme"], dumps(c["trades"]),
             c["capacity"], dumps(c["sanctioned_inventory"]), c["device_key"], GENESIS))
        n += 1
    con.commit()
    return n
