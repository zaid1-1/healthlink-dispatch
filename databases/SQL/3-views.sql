--View 1: vw_patient_directory

CREATE OR REPLACE VIEW vw_patient_directory AS
SELECT patient_id, full_name
FROM   Patients;

-- View 2: vw_ambulance_status

CREATE OR REPLACE VIEW vw_ambulance_status AS
SELECT ambulance_id, plate_number, status
FROM   Ambulances
WHERE  status IN ('AVAILABLE', 'ENROUTE')
WITH CHECK OPTION;