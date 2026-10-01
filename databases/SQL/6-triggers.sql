-- Trigger 1 (ROW LEVEL): trg_block_maintenance_dispatch

CREATE OR REPLACE TRIGGER trg_block_maintenance_dispatch
BEFORE INSERT ON Dispatches
FOR EACH ROW
DECLARE
    v_status VARCHAR2(20);
BEGIN
    SELECT status
    INTO   v_status
    FROM   Ambulances
    WHERE  ambulance_id = :NEW.ambulance_id;

    IF v_status = 'MAINTENANCE' THEN
        RAISE_APPLICATION_ERROR(-20001, 'Cannot dispatch an ambulance that is currently in maintenance.');
    END IF;
END;
/

BEGIN mark_ambulance_maintenance(5); END;

INSERT INTO Dispatches (dispatch_id, call_id, ambulance_id, paramedic_id, hospital_id)
VALUES (9001, 1, 5, 1, 1);


-- Trigger 2 (ROW-LEVEL, column based): trg_ambulance_available_on_complete
CREATE OR REPLACE TRIGGER trg_ambulance_available_on_complete
AFTER UPDATE OF status ON Dispatches
FOR EACH ROW
WHEN (new.status = 'COMPLETED')
BEGIN
    UPDATE Ambulances
    SET    status = 'AVAILABLE'
    WHERE  ambulance_id = :NEW.ambulance_id;
END;
/



-- Trigger 3 (STATEMENT LEVEL): trg_prevent_hospital_delete

CREATE OR REPLACE TRIGGER trg_prevent_hospital_delete
BEFORE DELETE ON TraumaCenters
BEGIN
    RAISE_APPLICATION_ERROR(-20010, 'Trauma centers cannot be deleted directly.');
END;
/

DELETE FROM TraumaCenters WHERE hospital_id = 1;