CREATE OR REPLACE PACKAGE dispatch_pkg AS

    PROCEDURE process_dispatch (
        p_call_id      IN  NUMBER,
        p_ambulance_id IN  NUMBER,
        p_paramedic_id IN  NUMBER,
        p_hospital_id  IN  NUMBER,
        p_dispatch_id  OUT NUMBER
    );

    FUNCTION get_hospital_dispatch_count (
        p_hospital_id IN NUMBER
    ) RETURN NUMBER;

END dispatch_pkg;
/

CREATE OR REPLACE PACKAGE BODY dispatch_pkg AS

    PROCEDURE log_action (
        p_dispatch_id IN NUMBER,
        p_action      IN VARCHAR2
    ) IS
    BEGIN
        INSERT INTO AuditLog (dispatch_id, action, performed_by, log_time)
        VALUES (p_dispatch_id, p_action, 'SYSTEM', SYSDATE);
    END log_action;


    PROCEDURE process_dispatch (
        p_call_id      IN  NUMBER,
        p_ambulance_id IN  NUMBER,
        p_paramedic_id IN  NUMBER,
        p_hospital_id  IN  NUMBER,
        p_dispatch_id  OUT NUMBER
    ) IS
    BEGIN
        INSERT INTO Dispatches (call_id, ambulance_id, paramedic_id, hospital_id)
        VALUES (p_call_id, p_ambulance_id, p_paramedic_id, p_hospital_id)
        RETURNING dispatch_id INTO p_dispatch_id;

        UPDATE Ambulances
        SET    status = 'ENROUTE'
        WHERE  ambulance_id = p_ambulance_id;

        UPDATE EmergencyCalls
        SET    status = 'DISPATCHED'
        WHERE  call_id = p_call_id;

        log_action(p_dispatch_id, 'DISPATCH_CREATED');

        COMMIT;
    END process_dispatch;


    FUNCTION get_hospital_dispatch_count (
        p_hospital_id IN NUMBER
    ) RETURN NUMBER IS
        v_count NUMBER;
    BEGIN
        SELECT COUNT(dispatch_id)
        INTO   v_count
        FROM   Dispatches
        WHERE  hospital_id = p_hospital_id;

        RETURN v_count;
    END get_hospital_dispatch_count;

END dispatch_pkg;
/
