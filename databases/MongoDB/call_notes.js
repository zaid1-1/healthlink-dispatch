use HealthLinkDocs

db.createCollection('call_notes')

// seed data: call 15 has empty arrays since it just came in,
// call 3 already has vitals/notes recorded, call 42 has fewer
// fields on its vitals reading. shows the schema flexibility
db.call_notes.insertMany([
  {
    call_id: 3,
    patient_summary: "Adult male, chest pain, conscious and alert on scene.",
    vitals: [
      { timestamp: "2026-01-15T08:15:00", heart_rate: 110, systolic_bp: 145, diastolic_bp: 95, spo2: 96 },
      { timestamp: "2026-01-15T08:22:00", heart_rate: 98, systolic_bp: 130, diastolic_bp: 88, spo2: 98 }
    ],
    paramedic_notes: [
      { author: "Omar Haddad", note: "Patient reports chest tightness for 20 minutes, no radiation to arm.", recorded_at: "2026-01-15T08:16:00" },
      { author: "Omar Haddad", note: "Condition stabilizing after oxygen administered.", recorded_at: "2026-01-15T08:24:00" }
    ],
    tags: ["cardiac", "high-priority"]
  },
  {
    call_id: 15,
    patient_summary: "Elderly female, fall at home, minor bleeding reported by caller.",
    vitals: [],
    paramedic_notes: [],
    tags: ["trauma"]
  },
  {
    call_id: 42,
    patient_summary: "Child, difficulty breathing, possible asthma attack.",
    vitals: [
      { timestamp: "2026-02-03T14:05:00", heart_rate: 130, spo2: 91 }
    ],
    paramedic_notes: [
      { author: "Lina Barakat", note: "Administered nebulizer treatment on scene, spo2 improving.", recorded_at: "2026-02-03T14:08:00" }
    ],
    tags: ["pediatric", "respiratory", "high-priority"]
  }
])

// get the notes for one call
db.call_notes.findOne({ call_id: 3 })

// find everything tagged high priority
db.call_notes.find({ tags: "high-priority" })

// low oxygen reading, dot notation into the nested array
db.call_notes.find({ "vitals.spo2": { $lt: 92 } })

// just call_id and tags, no _id
db.call_notes.find({}, { call_id: 1, tags: 1, _id: 0 })

// push a new vitals reading onto an existing call
db.call_notes.updateOne(
  { call_id: 15 },
  { $push: { vitals: { timestamp: "2026-01-20T09:40:00", heart_rate: 88, systolic_bp: 120, diastolic_bp: 80, spo2: 97 } } }
)

// push a new note the same way
db.call_notes.updateOne(
  { call_id: 15 },
  { $push: { paramedic_notes: { author: "Rana Freihat", note: "Wound cleaned and dressed, no further bleeding.", recorded_at: "2026-01-20T09:42:00" } } }
)

// addToSet so we dont end up with a duplicate tag
db.call_notes.updateOne(
  { call_id: 15 },
  { $addToSet: { tags: "high-priority" } }
)