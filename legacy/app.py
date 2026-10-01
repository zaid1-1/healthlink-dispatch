import threading
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext, messagebox

import oracledb
from pymongo import MongoClient
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

ORACLE_USER = os.environ["ORACLE_USER"]
ORACLE_PASSWORD = os.environ["ORACLE_PASSWORD"]
ORACLE_DSN = os.environ["ORACLE_DSN"]
NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ["MONGO_DB_NAME"]

ORACLE_CALL_TIMEOUT_MS = 5000

KNOWN_ZONES = [
    "Abdoun", "Jabal Amman", "Sweifieh",
    "Marka", "Zarqa", "Abdali",
]


try:
    ORACLE_POOL = oracledb.create_pool(
        user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN,
        min=1, max=4, increment=1,
        getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
        wait_timeout=5000,
    )
except oracledb.DatabaseError as e:
    raise SystemExit(f"Could not connect to Oracle at startup: {e}")


def get_oracle_connection():
    conn = ORACLE_POOL.acquire()
    conn.call_timeout = ORACLE_CALL_TIMEOUT_MS
    return conn


def _require_exists(cursor, table: str, column: str, value: int, label: str):
    """quick check before writing so a bad id gives a clear error fast"""
    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = :v", v=value)
    if cursor.fetchone()[0] == 0:
        raise ValueError(f"{label} ID {value} does not exist.")


def _parse_optional_int(text: str):
    text = text.strip()
    return int(text) if text else None


#Section A: core workflow
def fetch_call_details(call_id: int) -> dict:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        _require_exists(cursor, "EmergencyCalls", "call_id", call_id, "Call")
        cursor.execute(
            """
            SELECT c.call_id, p.full_name, c.location, t.level_name, c.status
            FROM   EmergencyCalls c
            INNER JOIN Patients p ON c.patient_id = p.patient_id
            INNER JOIN TriageLevels t ON c.triage_id = t.triage_id
            WHERE  c.call_id = :call_id
            """,
            call_id=call_id,
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    details = {
        "call_id": row[0], "patient_name": row[1], "location": row[2],
        "triage": row[3], "status": row[4], "notes": None,
    }

    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        details["notes"] = mongo_client[MONGO_DB_NAME].call_notes.find_one({"call_id": call_id})
    finally:
        mongo_client.close()

    return details


def calculate_route(location_name: str, hospital_id: int) -> dict:
    """status is one of: hospital_not_found, zone_not_found, no_path, found"""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=5)
    try:
        with driver.session() as session:
            hospital_exists = session.run(
                "MATCH (h:TraumaCenter {hospital_id: $hospital_id}) RETURN h", hospital_id=hospital_id
            ).single() is not None
            if not hospital_exists:
                return {"status": "hospital_not_found"}

            zone_exists = session.run(
                "MATCH (z:IncidentZone {name: $location}) RETURN z", location=location_name
            ).single() is not None
            if not zone_exists:
                return {"status": "zone_not_found"}

            record = session.run(
                """
                MATCH p = shortestPath(
                    (z:IncidentZone {name: $location})-[:ROAD_TO*..10]-(h:TraumaCenter {hospital_id: $hospital_id})
                )
                RETURN p
                """,
                location=location_name,
                hospital_id=hospital_id,
            ).single()

            if record is None:
                return {"status": "no_path"}

            path = record["p"]
            stops = [n.get("name") or f"Hospital #{n.get('hospital_id')}" for n in path.nodes]
            total_km = sum(r.get("distance_km", 0) for r in path.relationships)
            return {"status": "found", "stops": stops, "hops": len(path.relationships), "distance_km": total_km}
    finally:
        driver.close()


def execute_dispatch(call_id: int, ambulance_id: int, paramedic_id: int, hospital_id: int) -> int:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        _require_exists(cursor, "EmergencyCalls", "call_id", call_id, "Call")
        _require_exists(cursor, "Ambulances", "ambulance_id", ambulance_id, "Ambulance")
        _require_exists(cursor, "Paramedics", "paramedic_id", paramedic_id, "Paramedic")
        _require_exists(cursor, "TraumaCenters", "hospital_id", hospital_id, "Hospital")

        new_id_var = cursor.var(int)
        cursor.callproc(
            "dispatch_pkg.process_dispatch",
            [call_id, ambulance_id, paramedic_id, hospital_id, new_id_var],
        )
        conn.commit()
        return new_id_var.getvalue()
    except oracledb.DatabaseError:
        conn.rollback()
        raise
    finally:
        conn.close()


#Section B: testing/admin
def admin_mark_maintenance(ambulance_id: int) -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        _require_exists(cursor, "Ambulances", "ambulance_id", ambulance_id, "Ambulance")
        cursor.callproc("mark_ambulance_maintenance", [ambulance_id])
        conn.commit()
        cursor.execute("SELECT status FROM Ambulances WHERE ambulance_id = :id", id=ambulance_id)
        return f"Ambulance {ambulance_id} status is now: {cursor.fetchone()[0]}"
    finally:
        conn.close()


def admin_check_high_priority(call_id: int) -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        _require_exists(cursor, "EmergencyCalls", "call_id", call_id, "Call")
        result = cursor.callfunc("is_high_priority_call", str, [call_id])
        return f"Call {call_id} high priority? {result}"
    finally:
        conn.close()


def admin_get_hospital_count(hospital_id: int) -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        _require_exists(cursor, "TraumaCenters", "hospital_id", hospital_id, "Hospital")
        result = cursor.callfunc("dispatch_pkg.get_hospital_dispatch_count", int, [hospital_id])
        return f"Hospital {hospital_id} has {result} dispatch(es) on record."
    finally:
        conn.close()


def admin_complete_dispatch(dispatch_id: int) -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        _require_exists(cursor, "Dispatches", "dispatch_id", dispatch_id, "Dispatch")
        cursor.execute("SELECT ambulance_id FROM Dispatches WHERE dispatch_id = :id", id=dispatch_id)
        ambulance_id = cursor.fetchone()[0]

        cursor.execute("UPDATE Dispatches SET status = 'COMPLETED' WHERE dispatch_id = :id", id=dispatch_id)
        conn.commit()

        cursor.execute("SELECT status FROM Ambulances WHERE ambulance_id = :id", id=ambulance_id)
        new_status = cursor.fetchone()[0]
        return f"Dispatch {dispatch_id} marked COMPLETED. Ambulance {ambulance_id} status is now: {new_status}"
    finally:
        conn.close()


def admin_try_delete_hospital(hospital_id: int) -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        _require_exists(cursor, "TraumaCenters", "hospital_id", hospital_id, "Hospital")
        cursor.execute("DELETE FROM TraumaCenters WHERE hospital_id = :id", id=hospital_id)
        conn.commit()
        return f"UNEXPECTED: hospital {hospital_id} was deleted (the trigger should have blocked this)."
    except oracledb.DatabaseError as e:
        conn.rollback()
        return f"Correctly rejected by trg_prevent_hospital_delete: {e}"
    finally:
        conn.close()


def admin_add_paramedic_note(call_id: int, note_text: str) -> str:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        db = mongo_client[MONGO_DB_NAME]
        if db.call_notes.find_one({"call_id": call_id}) is None:
            raise ValueError(f"No call_notes document exists yet for call_id {call_id}. "
                              f"Use 'Create Notes Document' in Section D first.")
        db.call_notes.update_one(
            {"call_id": call_id},
            {"$push": {"paramedic_notes": {"author": "App User", "note": note_text,
                                            "recorded_at": datetime.now().isoformat(timespec="seconds")}}},
        )
        doc = db.call_notes.find_one({"call_id": call_id})
        count = len(doc.get("paramedic_notes", []))
        return f"Note added. call_notes for call {call_id} now has {count} paramedic note(s)."
    finally:
        mongo_client.close()


#Section C: lookup helpers
def list_trauma_centers() -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT hospital_id, name FROM TraumaCenters ORDER BY hospital_id")
        rows = cursor.fetchall()
        return "Trauma centres (hospital_id: name):\n" + "\n".join(f"  {h}: {n}" for h, n in rows)
    finally:
        conn.close()


def list_available_ambulances() -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ambulance_id, plate_number FROM Ambulances WHERE status = 'AVAILABLE' ORDER BY ambulance_id"
        )
        rows = cursor.fetchall()
        if not rows:
            return "No AVAILABLE ambulances right now (they may all be ENROUTE or in MAINTENANCE)."
        return "Available ambulances (ambulance_id: plate):\n" + "\n".join(f"  {a}: {p}" for a, p in rows)
    finally:
        conn.close()


def list_paramedics() -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT paramedic_id, full_name FROM Paramedics ORDER BY paramedic_id")
        rows = cursor.fetchall()[:10]
        return "Paramedics, first 10 (paramedic_id: name):\n" + "\n".join(f"  {p}: {n}" for p, n in rows)
    finally:
        conn.close()


def list_sample_calls() -> str:
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        placeholders = ", ".join(f":z{i}" for i in range(len(KNOWN_ZONES)))
        binds = {f"z{i}": zone for i, zone in enumerate(KNOWN_ZONES)}
        cursor.execute(
            f"SELECT call_id, location, status FROM EmergencyCalls "
            f"WHERE location IN ({placeholders}) ORDER BY call_id",
            binds,
        )
        rows = cursor.fetchall()[:10]
        if not rows:
            return "No existing calls match a known routing zone - use Section D to create one."
        return ("Calls with real routing data, first 10 (call_id: location [status]):\n"
                + "\n".join(f"  {c}: {loc} [{s}]" for c, loc, s in rows))
    finally:
        conn.close()


#Section D: create new data
def admin_add_new_call(patient_id: int, dispatcher_id: int, triage_id: int, location: str) -> str:
    """fk constraints already check the ids. call_id comes from the
    identity column now, RETURNING grabs the value it generated"""
    conn = get_oracle_connection()
    try:
        cursor = conn.cursor()
        new_call_id_var = cursor.var(int)
        cursor.execute(
            """
            INSERT INTO EmergencyCalls (patient_id, dispatcher_id, triage_id, location)
            VALUES (:patient_id, :dispatcher_id, :triage_id, :location)
            RETURNING call_id INTO :new_id
            """,
            patient_id=patient_id, dispatcher_id=dispatcher_id,
            triage_id=triage_id, location=location, new_id=new_call_id_var,
        )
        conn.commit()
        new_call_id = new_call_id_var.getvalue()[0]
        return (f"New emergency call created: call_id {new_call_id} "
                f"(status defaults to RECEIVED). Use this ID in Section A.")
    except oracledb.DatabaseError:
        conn.rollback()
        raise
    finally:
        conn.close()


def admin_create_call_notes(call_id: int, patient_summary: str, heart_rate=None, systolic_bp=None,
                             diastolic_bp=None, spo2=None, initial_note=None) -> str:
    """vitals and note are optional, same idea as part 3"""
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        db = mongo_client[MONGO_DB_NAME]
        if db.call_notes.find_one({"call_id": call_id}):
            return (f"A call_notes document for call_id {call_id} already exists - "
                     f"use 'Add Note' in Section B to append to it instead.")

        vitals = []
        if any(v is not None for v in (heart_rate, systolic_bp, diastolic_bp, spo2)):
            entry = {"timestamp": datetime.now().isoformat(timespec="seconds")}
            if heart_rate is not None:
                entry["heart_rate"] = heart_rate
            if systolic_bp is not None:
                entry["systolic_bp"] = systolic_bp
            if diastolic_bp is not None:
                entry["diastolic_bp"] = diastolic_bp
            if spo2 is not None:
                entry["spo2"] = spo2
            vitals.append(entry)

        notes = []
        if initial_note:
            notes.append({"author": "App User", "note": initial_note,
                          "recorded_at": datetime.now().isoformat(timespec="seconds")})

        db.call_notes.insert_one({
            "call_id": call_id, "patient_summary": patient_summary,
            "vitals": vitals, "paramedic_notes": notes, "tags": [],
        })
        return (f"New call_notes document created for call_id {call_id} "
                f"({len(vitals)} vitals reading(s), {len(notes)} note(s)).")
    finally:
        mongo_client.close()


#GUI
class DispatchApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HealthLink Dispatch Assistant")
        self.geometry("780x860")
        self.current_call = None

        tk.Label(self, text="Output Log  (a result or error always appears here, within ~5 seconds at most)",
                 font=("Arial", 11, "bold")).pack(side="bottom", pady=(5, 0))
        self.output = scrolledtext.ScrolledText(self, width=92, height=12)
        self.output.pack(side="bottom", padx=10, pady=(0, 10), fill="x")

        container = tk.Frame(self)
        container.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        tk.Label(
            body,
            text=("SUGGESTED FLOW:  (D) Create a call & notes  ->  (A) Fetch it  ->  "
                  "(C) look up a hospital/ambulance/paramedic  ->  (A) Calculate route & Dispatch  ->  "
                  "(B) test the triggers"),
            font=("Arial", 9, "italic"), fg="#444444", wraplength=730, justify="left",
        ).pack(pady=(10, 5), padx=10)

        #Section A
        tk.Label(body, text="SECTION A - Dispatch Workflow", font=("Arial", 13, "bold"), fg="#1a4d8f").pack(pady=(10, 0))

        tk.Label(body, text="Step 1: Fetch Call Details", font=("Arial", 11, "bold")).pack(pady=(8, 0))
        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Call ID:").pack(side="left")
        self.call_id_entry = tk.Entry(f, width=10); self.call_id_entry.pack(side="left", padx=5)
        tk.Button(f, text="Fetch Details", command=self.on_fetch).pack(side="left")

        tk.Label(body, text="Step 2: Calculate Route", font=("Arial", 11, "bold")).pack(pady=(10, 0))
        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Destination Hospital ID:").pack(side="left")
        self.hospital_id_entry = tk.Entry(f, width=10); self.hospital_id_entry.pack(side="left", padx=5)
        tk.Button(f, text="Calculate Route", command=self.on_route).pack(side="left")

        tk.Label(body, text="Step 3: Execute Dispatch", font=("Arial", 11, "bold")).pack(pady=(10, 0))
        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Ambulance ID:").pack(side="left")
        self.ambulance_entry = tk.Entry(f, width=6); self.ambulance_entry.pack(side="left", padx=5)
        tk.Label(f, text="Paramedic ID:").pack(side="left")
        self.paramedic_entry = tk.Entry(f, width=6); self.paramedic_entry.pack(side="left", padx=5)
        tk.Button(f, text="Dispatch Ambulance", command=self.on_dispatch).pack(side="left", padx=10)

        #Section B
        tk.Label(body, text="SECTION B - Testing & Admin Tools", font=("Arial", 13, "bold"), fg="#8f1a1a").pack(pady=(18, 0))

        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Ambulance ID:").pack(side="left")
        self.maint_entry = tk.Entry(f, width=6); self.maint_entry.pack(side="left", padx=5)
        tk.Button(f, text="Mark as Maintenance (procedure)", command=self.on_mark_maintenance).pack(side="left")

        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Call ID:").pack(side="left")
        self.priority_entry = tk.Entry(f, width=6); self.priority_entry.pack(side="left", padx=5)
        tk.Button(f, text="Check High Priority (function)", command=self.on_check_priority).pack(side="left")

        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Hospital ID:").pack(side="left")
        self.count_entry = tk.Entry(f, width=6); self.count_entry.pack(side="left", padx=5)
        tk.Button(f, text="Get Dispatch Count (package function)", command=self.on_get_count).pack(side="left")

        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Dispatch ID:").pack(side="left")
        self.complete_entry = tk.Entry(f, width=6); self.complete_entry.pack(side="left", padx=5)
        tk.Button(f, text="Mark Completed (trigger 2)", command=self.on_complete_dispatch).pack(side="left")

        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Hospital ID:").pack(side="left")
        self.delete_entry = tk.Entry(f, width=6); self.delete_entry.pack(side="left", padx=5)
        tk.Button(f, text="Try Delete Hospital (trigger 3)", command=self.on_try_delete).pack(side="left")

        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Call ID:").pack(side="left")
        self.note_call_entry = tk.Entry(f, width=6); self.note_call_entry.pack(side="left", padx=5)
        tk.Label(f, text="Note:").pack(side="left")
        self.note_text_entry = tk.Entry(f, width=25); self.note_text_entry.pack(side="left", padx=5)
        tk.Button(f, text="Add Note (MongoDB)", command=self.on_add_note).pack(side="left")

        tk.Label(body, text="Note: trigger 1 (trg_block_maintenance_dispatch) is tested by marking an\n"
                             "ambulance as maintenance above, then trying to dispatch it in Section A.",
                 font=("Arial", 9, "italic"), fg="#555555").pack(pady=(6, 0))

        #Section C
        tk.Label(body, text="SECTION C - Lookup Helpers", font=("Arial", 13, "bold"), fg="#1a7a3d").pack(pady=(18, 0))
        f = tk.Frame(body); f.pack(pady=4)
        tk.Button(f, text="List Trauma Centres", command=lambda: self.run_lookup(list_trauma_centers)).pack(side="left", padx=4)
        tk.Button(f, text="List Available Ambulances", command=lambda: self.run_lookup(list_available_ambulances)).pack(side="left", padx=4)
        f2 = tk.Frame(body); f2.pack(pady=4)
        tk.Button(f2, text="List Paramedics", command=lambda: self.run_lookup(list_paramedics)).pack(side="left", padx=4)
        tk.Button(f2, text="List Calls With Routing Data", command=lambda: self.run_lookup(list_sample_calls)).pack(side="left", padx=4)

        #Section D
        tk.Label(body, text="SECTION D - Create New Data", font=("Arial", 13, "bold"), fg="#7a3d9c").pack(pady=(18, 0))

        tk.Label(body, text="New Emergency Call (Oracle)", font=("Arial", 10, "bold")).pack(pady=(6, 0))
        f = tk.Frame(body); f.pack(pady=2)
        tk.Label(f, text="Patient ID:").pack(side="left")
        self.new_patient_entry = tk.Entry(f, width=6); self.new_patient_entry.pack(side="left", padx=3)
        tk.Label(f, text="Dispatcher ID:").pack(side="left")
        self.new_dispatcher_entry = tk.Entry(f, width=6); self.new_dispatcher_entry.pack(side="left", padx=3)
        tk.Label(f, text="Triage ID:").pack(side="left")
        self.new_triage_entry = tk.Entry(f, width=6); self.new_triage_entry.pack(side="left", padx=3)
        tk.Label(body, text=f"Location (use one of: {', '.join(KNOWN_ZONES)} for a working route):",
                 wraplength=730, justify="left").pack(pady=(4, 0), padx=10)
        f = tk.Frame(body); f.pack(pady=2)
        self.new_location_entry = tk.Entry(f, width=40)
        self.new_location_entry.insert(0, KNOWN_ZONES[0])
        self.new_location_entry.pack(side="left", padx=3)
        tk.Button(f, text="Create Call", command=self.on_add_new_call).pack(side="left", padx=6)

        tk.Label(body, text="New call_notes Document (MongoDB)", font=("Arial", 10, "bold")).pack(pady=(12, 0))
        f = tk.Frame(body); f.pack(pady=2)
        tk.Label(f, text="Call ID:").pack(side="left")
        self.notes_call_entry = tk.Entry(f, width=6); self.notes_call_entry.pack(side="left", padx=3)
        tk.Label(f, text="Summary:").pack(side="left")
        self.notes_summary_entry = tk.Entry(f, width=30); self.notes_summary_entry.pack(side="left", padx=3)

        tk.Label(body, text="Initial vitals reading (all optional - leave blank to skip):",
                 font=("Arial", 9, "italic")).pack(pady=(6, 0))
        f = tk.Frame(body); f.pack(pady=2)
        tk.Label(f, text="Heart rate:").pack(side="left")
        self.vitals_hr_entry = tk.Entry(f, width=5); self.vitals_hr_entry.pack(side="left", padx=3)
        tk.Label(f, text="Systolic BP:").pack(side="left")
        self.vitals_sys_entry = tk.Entry(f, width=5); self.vitals_sys_entry.pack(side="left", padx=3)
        tk.Label(f, text="Diastolic BP:").pack(side="left")
        self.vitals_dia_entry = tk.Entry(f, width=5); self.vitals_dia_entry.pack(side="left", padx=3)
        tk.Label(f, text="SpO2:").pack(side="left")
        self.vitals_spo2_entry = tk.Entry(f, width=5); self.vitals_spo2_entry.pack(side="left", padx=3)

        f = tk.Frame(body); f.pack(pady=4)
        tk.Label(f, text="Initial note (optional):").pack(side="left")
        self.notes_initial_note_entry = tk.Entry(f, width=40); self.notes_initial_note_entry.pack(side="left", padx=3)
        tk.Button(f, text="Create Notes Document", command=self.on_create_notes).pack(side="left", padx=6)

        tk.Label(body, text=" ").pack(pady=6)

    def log(self, text):
        self.output.insert(tk.END, text + "\n")
        self.output.see(tk.END)

    def run_in_background(self, func, args=(), on_done=None):
        def worker():
            try:
                result = func(*args)
            except Exception as e:
                err = e  # need this, e gets deleted once the except block ends
                self.after(0, lambda: self._on_error(err))
                return
            self.after(0, lambda: self._on_success(result, on_done))
        threading.Thread(target=worker, daemon=True).start()

    def _on_success(self, result, on_done):
        if on_done:
            on_done(result)
        elif isinstance(result, str):
            self.log(result)

    def _on_error(self, error):
        if isinstance(error, ValueError):
            self.log(f"NOT FOUND / INVALID: {error}")
            messagebox.showerror("Invalid", str(error))
        elif isinstance(error, oracledb.DatabaseError):
            self.log(f"REJECTED: {error}")
            messagebox.showerror("Database Rejected This", str(error))
        else:
            self.log(f"ERROR: {error}")
            messagebox.showerror("Error", str(error))

    def run_lookup(self, func):
        self.log("Looking up...")
        self.run_in_background(func)

    #Section A handlers
    def on_fetch(self):
        try:
            call_id = int(self.call_id_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Call ID must be a whole number.")
            return

        def on_done(details):
            self.current_call = details
            lines = [
                f"--- Call {details['call_id']} ---",
                f"Patient: {details['patient_name']}",
                f"Location: {details['location']}",
                f"Triage level: {details['triage']}",
                f"Status: {details['status']}",
            ]
            if details["notes"]:
                notes_doc = details["notes"]
                lines.append(f"MongoDB summary: {notes_doc.get('patient_summary', '(none)')}")

                vitals = notes_doc.get("vitals", [])
                lines.append(f"Vitals readings on file: {len(vitals)}")
                for i, v in enumerate(vitals, start=1):
                    ts = v.get("timestamp", "")
                    fields = ", ".join(f"{k}={val}" for k, val in v.items() if k != "timestamp")
                    lines.append(f"  [{i}] {ts}: {fields}")

                paramedic_notes = notes_doc.get("paramedic_notes", [])
                lines.append(f"Paramedic notes on file: {len(paramedic_notes)}")
                for i, n in enumerate(paramedic_notes, start=1):
                    lines.append(f"  [{i}] {n.get('author', '?')} ({n.get('recorded_at', '')}): {n.get('note', '')}")

                tags = notes_doc.get("tags", [])
                if tags:
                    lines.append(f"Tags: {', '.join(tags)}")
            else:
                lines.append("No MongoDB call_notes document found for this call yet.")
            self.log("\n".join(lines))

        self.log("Fetching...")
        self.run_in_background(fetch_call_details, (call_id,), on_done)

    def on_route(self):
        if not self.current_call:
            messagebox.showwarning("Fetch First", "Fetch call details before calculating a route.")
            return
        try:
            hospital_id = int(self.hospital_id_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Hospital ID must be a whole number.")
            return

        def on_done(result):
            status = result["status"]
            if status == "hospital_not_found":
                self.log(f"Hospital ID {hospital_id} does not exist in the graph (valid range: 1-12).")
            elif status == "zone_not_found":
                self.log(f"This call's location ('{self.current_call['location']}') is not one of the "
                          f"modelled IncidentZones. Known zones: {', '.join(KNOWN_ZONES)}")
            elif status == "no_path":
                self.log("Both nodes exist, but no road connects them in the graph.")
            else:
                self.log(f"Route found ({result['hops']} hop(s), {result['distance_km']:.1f} km total): "
                          + " -> ".join(result["stops"]))

        self.log("Calculating route...")
        self.run_in_background(calculate_route, (self.current_call["location"], hospital_id), on_done)

    def on_dispatch(self):
        if not self.current_call:
            messagebox.showwarning("Fetch First", "Fetch call details before dispatching.")
            return
        try:
            ambulance_id = int(self.ambulance_entry.get())
            paramedic_id = int(self.paramedic_entry.get())
            hospital_id = int(self.hospital_id_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Ambulance, paramedic, and hospital IDs must be whole numbers.")
            return

        def on_done(new_id):
            self.log(f"SUCCESS: Dispatch #{new_id} created and committed.")
            messagebox.showinfo("Dispatch Created", f"Dispatch #{new_id} created successfully.")

        self.log("Dispatching (validating IDs, then calling dispatch_pkg.process_dispatch)...")
        self.run_in_background(
            execute_dispatch, (self.current_call["call_id"], ambulance_id, paramedic_id, hospital_id), on_done
        )

    #Section B handlers
    def on_mark_maintenance(self):
        try:
            ambulance_id = int(self.maint_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Ambulance ID must be a whole number.")
            return
        self.log("Running...")
        self.run_in_background(admin_mark_maintenance, (ambulance_id,))

    def on_check_priority(self):
        try:
            call_id = int(self.priority_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Call ID must be a whole number.")
            return
        self.log("Running...")
        self.run_in_background(admin_check_high_priority, (call_id,))

    def on_get_count(self):
        try:
            hospital_id = int(self.count_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Hospital ID must be a whole number.")
            return
        self.log("Running...")
        self.run_in_background(admin_get_hospital_count, (hospital_id,))

    def on_complete_dispatch(self):
        try:
            dispatch_id = int(self.complete_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Dispatch ID must be a whole number.")
            return
        self.log("Running...")
        self.run_in_background(admin_complete_dispatch, (dispatch_id,))

    def on_try_delete(self):
        try:
            hospital_id = int(self.delete_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Hospital ID must be a whole number.")
            return
        self.log("Running (a rejection here is the CORRECT result)...")
        self.run_in_background(admin_try_delete_hospital, (hospital_id,))

    def on_add_note(self):
        try:
            call_id = int(self.note_call_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Call ID must be a whole number.")
            return
        note_text = self.note_text_entry.get().strip()
        if not note_text:
            messagebox.showerror("Invalid Input", "Enter some note text.")
            return
        self.log("Running...")
        self.run_in_background(admin_add_paramedic_note, (call_id, note_text))

    #Section D handlers
    def on_add_new_call(self):
        try:
            patient_id = int(self.new_patient_entry.get())
            dispatcher_id = int(self.new_dispatcher_entry.get())
            triage_id = int(self.new_triage_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Patient, dispatcher, and triage IDs must be whole numbers.")
            return
        location = self.new_location_entry.get().strip()
        if not location:
            messagebox.showerror("Invalid Input", "Enter a location.")
            return
        self.log("Creating new call...")
        self.run_in_background(admin_add_new_call, (patient_id, dispatcher_id, triage_id, location))

    def on_create_notes(self):
        try:
            call_id = int(self.notes_call_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Call ID must be a whole number.")
            return
        summary = self.notes_summary_entry.get().strip()
        if not summary:
            messagebox.showerror("Invalid Input", "Enter a patient summary.")
            return
        try:
            heart_rate = _parse_optional_int(self.vitals_hr_entry.get())
            systolic_bp = _parse_optional_int(self.vitals_sys_entry.get())
            diastolic_bp = _parse_optional_int(self.vitals_dia_entry.get())
            spo2 = _parse_optional_int(self.vitals_spo2_entry.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Vitals fields must be whole numbers (or left blank).")
            return
        initial_note = self.notes_initial_note_entry.get().strip() or None

        self.log("Creating notes document...")
        self.run_in_background(
            admin_create_call_notes,
            (call_id, summary, heart_rate, systolic_bp, diastolic_bp, spo2, initial_note),
        )


if __name__ == "__main__":
    app = DispatchApp()
    app.mainloop()