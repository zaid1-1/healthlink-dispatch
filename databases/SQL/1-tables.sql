-- Table: Patients
CREATE TABLE Patients (
    patient_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name       VARCHAR2(100)   NOT NULL,
    phone           VARCHAR2(20)    NOT NULL,
    dob             DATE,
    CONSTRAINT uq_patient_phone UNIQUE (phone)
);

-- Table: Dispatchers
CREATE TABLE Dispatchers (
    dispatcher_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    badge_number    VARCHAR2(20)    NOT NULL,
    full_name       VARCHAR2(100)   NOT NULL,
    CONSTRAINT uq_dispatcher_badge UNIQUE (badge_number)
);

-- Table: TriageLevels
CREATE TABLE TriageLevels (
    triage_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    level_name      VARCHAR2(50)    NOT NULL,
    priority_rank   NUMBER(1)       NOT NULL,
    CONSTRAINT uq_triage_name UNIQUE (level_name),
    CONSTRAINT chk_triage_rank CHECK (priority_rank BETWEEN 1 AND 5)
);

-- Table: EmergencyCalls
CREATE TABLE EmergencyCalls (
    call_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id      NUMBER          NOT NULL,
    dispatcher_id   NUMBER          NOT NULL,
    triage_id       NUMBER          NOT NULL,
    call_time       DATE            DEFAULT SYSDATE NOT NULL,
    location        VARCHAR2(200)   NOT NULL,
    status          VARCHAR2(20)    DEFAULT 'RECEIVED' NOT NULL,
    CONSTRAINT fk_call_patient    FOREIGN KEY (patient_id)    REFERENCES Patients(patient_id),
    CONSTRAINT fk_call_dispatcher FOREIGN KEY (dispatcher_id) REFERENCES Dispatchers(dispatcher_id),
    CONSTRAINT fk_call_triage     FOREIGN KEY (triage_id)     REFERENCES TriageLevels(triage_id),
    CONSTRAINT chk_call_status    CHECK (status IN ('RECEIVED','DISPATCHED','CLOSED','CANCELLED'))
);

-- Table: Ambulances
CREATE TABLE Ambulances (
    ambulance_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plate_number    VARCHAR2(20)    NOT NULL,
    status          VARCHAR2(20)    DEFAULT 'AVAILABLE' NOT NULL,
    CONSTRAINT uq_ambulance_plate UNIQUE (plate_number),
    CONSTRAINT chk_ambulance_status CHECK (status IN ('AVAILABLE','ENROUTE','MAINTENANCE'))
);

-- Table: Paramedics
CREATE TABLE Paramedics (
    paramedic_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    license_number  VARCHAR2(20)    NOT NULL,
    full_name       VARCHAR2(100)   NOT NULL,
    CONSTRAINT uq_paramedic_license UNIQUE (license_number)
);

-- Table: TraumaCenters
CREATE TABLE TraumaCenters (
    hospital_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            VARCHAR2(150)   NOT NULL,
    capacity        NUMBER          NOT NULL,
    CONSTRAINT chk_hospital_capacity CHECK (capacity >= 0)
);

-- Table: Dispatches
CREATE TABLE Dispatches (
    dispatch_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    call_id         NUMBER          NOT NULL,
    ambulance_id    NUMBER          NOT NULL,
    paramedic_id    NUMBER          NOT NULL,
    hospital_id     NUMBER          NOT NULL,
    dispatch_time   DATE            DEFAULT SYSDATE NOT NULL,
    arrival_time    DATE,
    status          VARCHAR2(20)    DEFAULT 'ASSIGNED' NOT NULL,
    CONSTRAINT uq_dispatch_call        UNIQUE (call_id),
    CONSTRAINT fk_dispatch_call        FOREIGN KEY (call_id)      REFERENCES EmergencyCalls(call_id),
    CONSTRAINT fk_dispatch_ambulance   FOREIGN KEY (ambulance_id) REFERENCES Ambulances(ambulance_id),
    CONSTRAINT fk_dispatch_paramedic   FOREIGN KEY (paramedic_id) REFERENCES Paramedics(paramedic_id),
    CONSTRAINT fk_dispatch_hospital    FOREIGN KEY (hospital_id)  REFERENCES TraumaCenters(hospital_id),
    CONSTRAINT chk_dispatch_status     CHECK (status IN ('ASSIGNED','ENROUTE','ARRIVED','COMPLETED','CANCELLED'))
);