const express = require("express");
const cors = require("cors");
const {
  initOraclePool,
  getOracleConnection,
  getMongoClient,
  getNeo4jDriver,
  MONGO_DB_NAME,
  oracledb,
} = require("./db");

const app = express();
app.use(cors());
app.use(express.json());

const KNOWN_ZONES = ["Abdoun", "Jabal Amman", "Sweifieh", "Marka", "Zarqa", "Abdali"];

// quick check before a write so a bad id gives a clear error fast
async function requireExists(conn, table, column, value, label) {
  const result = await conn.execute(`SELECT COUNT(*) AS CNT FROM ${table} WHERE ${column} = :v`, { v: value });
  if (result.rows[0].CNT === 0) {
    const err = new Error(`${label} ID ${value} does not exist.`);
    err.status = 404;
    throw err;
  }
}

// ---- lookups ----
app.get("/zones", (req, res) => {
  res.json(KNOWN_ZONES);
});

app.get("/hospitals", async (req, res, next) => {
  let conn;
  try {
    conn = await getOracleConnection();
    const result = await conn.execute("SELECT hospital_id, name FROM TraumaCenters ORDER BY hospital_id");
    res.json(result.rows.map((r) => ({ hospital_id: r.HOSPITAL_ID, name: r.NAME })));
  } catch (err) {
    next(err);
  } finally {
    if (conn) await conn.close();
  }
});

app.get("/ambulances", async (req, res, next) => {
  let conn;
  try {
    conn = await getOracleConnection();
    const { status } = req.query;
    const sql = status
      ? "SELECT ambulance_id, plate_number, status FROM Ambulances WHERE status = :s ORDER BY ambulance_id"
      : "SELECT ambulance_id, plate_number, status FROM Ambulances ORDER BY ambulance_id";
    const result = await conn.execute(sql, status ? { s: status } : {});
    res.json(result.rows.map((r) => ({ ambulance_id: r.AMBULANCE_ID, plate_number: r.PLATE_NUMBER, status: r.STATUS })));
  } catch (err) {
    next(err);
  } finally {
    if (conn) await conn.close();
  }
});

app.get("/paramedics", async (req, res, next) => {
  let conn;
  try {
    conn = await getOracleConnection();
    const result = await conn.execute("SELECT paramedic_id, full_name FROM Paramedics ORDER BY paramedic_id");
    res.json(result.rows.map((r) => ({ paramedic_id: r.PARAMEDIC_ID, full_name: r.FULL_NAME })));
  } catch (err) {
    next(err);
  } finally {
    if (conn) await conn.close();
  }
});

// ---- call details (Oracle + Mongo combined) ----
app.get("/calls/:callId", async (req, res, next) => {
  const callId = parseInt(req.params.callId, 10);
  let conn;
  let mongoClient;
  try {
    conn = await getOracleConnection();
    await requireExists(conn, "EmergencyCalls", "call_id", callId, "Call");

    const result = await conn.execute(
      `SELECT c.call_id, p.full_name, c.location, t.level_name, c.status
       FROM   EmergencyCalls c
       INNER JOIN Patients p ON c.patient_id = p.patient_id
       INNER JOIN TriageLevels t ON c.triage_id = t.triage_id
       WHERE  c.call_id = :callId`,
      { callId }
    );
    const row = result.rows[0];

    mongoClient = getMongoClient();
    await mongoClient.connect();
    const notes = await mongoClient.db(MONGO_DB_NAME).collection("call_notes").findOne({ call_id: callId }, { projection: { _id: 0 } });

    res.json({
      call_id: row.CALL_ID,
      patient_name: row.FULL_NAME,
      location: row.LOCATION,
      triage: row.LEVEL_NAME,
      status: row.STATUS,
      notes: notes || null,
    });
  } catch (err) {
    next(err);
  } finally {
    if (conn) await conn.close();
    if (mongoClient) await mongoClient.close();
  }
});

// ---- route calculation (Neo4j) ----
app.get("/route", async (req, res, next) => {
  const { zone, hospital_id } = req.query;
  const hospitalId = parseInt(hospital_id, 10);
  const driver = getNeo4jDriver();
  const session = driver.session();
  try {
    const hospitalCheck = await session.run(
      "MATCH (h:TraumaCenter {hospital_id: $hospitalId}) RETURN h",
      { hospitalId }
    );
    if (hospitalCheck.records.length === 0) {
      return res.json({ status: "hospital_not_found" });
    }

    const zoneCheck = await session.run("MATCH (z:IncidentZone {name: $zone}) RETURN z", { zone });
    if (zoneCheck.records.length === 0) {
      return res.json({ status: "zone_not_found" });
    }

    const result = await session.run(
      `MATCH p = shortestPath(
         (z:IncidentZone {name: $zone})-[:ROAD_TO*..10]-(h:TraumaCenter {hospital_id: $hospitalId})
       )
       RETURN p`,
      { zone, hospitalId }
    );

    if (result.records.length === 0) {
      return res.json({ status: "no_path" });
    }

    const path = result.records[0].get("p");
    const stops = path.segments.length
      ? [path.start, ...path.segments.map((s) => s.end)].map((n) => ({
          name: n.properties.name || `Hospital #${n.properties.hospital_id}`,
          lat: n.properties.lat,
          lng: n.properties.lng,
        }))
      : [{
          name: path.start.properties.name,
          lat: path.start.properties.lat,
          lng: path.start.properties.lng,
        }];
    const totalKm = path.segments.reduce((sum, s) => sum + (s.relationship.properties.distance_km || 0), 0);

    res.json({ status: "found", stops, hops: path.segments.length, distance_km: totalKm });
  } catch (err) {
    next(err);
  } finally {
    await session.close();
    await driver.close();
  }
});

// ---- dispatch (Oracle write, calls the existing package) ----
app.post("/dispatch", async (req, res, next) => {
  const { call_id, ambulance_id, paramedic_id, hospital_id } = req.body;
  let conn;
  try {
    conn = await getOracleConnection();
    await requireExists(conn, "EmergencyCalls", "call_id", call_id, "Call");
    await requireExists(conn, "Ambulances", "ambulance_id", ambulance_id, "Ambulance");
    await requireExists(conn, "Paramedics", "paramedic_id", paramedic_id, "Paramedic");
    await requireExists(conn, "TraumaCenters", "hospital_id", hospital_id, "Hospital");

    const result = await conn.execute(
      `BEGIN
         dispatch_pkg.process_dispatch(:call_id, :ambulance_id, :paramedic_id, :hospital_id, :dispatch_id);
       END;`,
      {
        call_id,
        ambulance_id,
        paramedic_id,
        hospital_id,
        dispatch_id: { type: oracledb.NUMBER, dir: oracledb.BIND_OUT },
      }
    );
    await conn.commit();
    res.json({ dispatch_id: result.outBinds.dispatch_id });
  } catch (err) {
    if (conn) await conn.rollback();
    err.status = err.status || 400;
    next(err);
  } finally {
    if (conn) await conn.close();
  }
});

// ---- create new data ----
app.post("/calls", async (req, res, next) => {
  const { patient_id, dispatcher_id, triage_id, location } = req.body;
  let conn;
  try {
    conn = await getOracleConnection();
    const result = await conn.execute(
      `INSERT INTO EmergencyCalls (patient_id, dispatcher_id, triage_id, location)
       VALUES (:patient_id, :dispatcher_id, :triage_id, :location)
       RETURNING call_id INTO :new_id`,
      {
        patient_id,
        dispatcher_id,
        triage_id,
        location,
        new_id: { type: oracledb.NUMBER, dir: oracledb.BIND_OUT },
      }
    );
    await conn.commit();
    res.json({ call_id: result.outBinds.new_id[0] });
  } catch (err) {
    if (conn) await conn.rollback();
    err.status = err.status || 400;
    next(err);
  } finally {
    if (conn) await conn.close();
  }
});

app.post("/calls/:callId/notes", async (req, res, next) => {
  const callId = parseInt(req.params.callId, 10);
  const { patient_summary, heart_rate, systolic_bp, diastolic_bp, spo2, initial_note } = req.body;
  let mongoClient;
  try {
    mongoClient = getMongoClient();
    await mongoClient.connect();
    const collection = mongoClient.db(MONGO_DB_NAME).collection("call_notes");

    const existing = await collection.findOne({ call_id: callId });
    if (existing) {
      const err = new Error("call_notes document already exists for this call_id.");
      err.status = 409;
      throw err;
    }

    const vitals = [];
    if ([heart_rate, systolic_bp, diastolic_bp, spo2].some((v) => v !== undefined && v !== null)) {
      const entry = { timestamp: new Date().toISOString() };
      if (heart_rate != null) entry.heart_rate = heart_rate;
      if (systolic_bp != null) entry.systolic_bp = systolic_bp;
      if (diastolic_bp != null) entry.diastolic_bp = diastolic_bp;
      if (spo2 != null) entry.spo2 = spo2;
      vitals.push(entry);
    }

    const notes = [];
    if (initial_note) {
      notes.push({ author: "Web User", note: initial_note, recorded_at: new Date().toISOString() });
    }

    await collection.insertOne({ call_id: callId, patient_summary, vitals, paramedic_notes: notes, tags: [] });
    res.json({ call_id: callId, vitals_count: vitals.length, notes_count: notes.length });
  } catch (err) {
    next(err);
  } finally {
    if (mongoClient) await mongoClient.close();
  }
});

// ---- error handler, keeps error messages visible instead of a blank 500 ----
app.use((err, req, res, next) => {
  console.error(err);
  res.status(err.status || 500).json({ detail: err.message });
});

const PORT = 8000;
initOraclePool()
  .then(() => {
    app.listen(PORT, () => console.log(`Server running on http://localhost:${PORT}`));
  })
  .catch((err) => {
    console.error("Could not connect to Oracle at startup:", err.message);
    process.exit(1);
  });