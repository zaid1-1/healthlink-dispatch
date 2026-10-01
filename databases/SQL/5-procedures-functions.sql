-- Procedure: mark_ambulance_maintenance

CREATE OR REPLACE PROCEDURE mark_ambulance_maintenance (
    p_ambulance_id IN NUMBER
) AS
BEGIN
    UPDATE Ambulances
    SET    status = 'MAINTENANCE'
    WHERE  ambulance_id = p_ambulance_id;

    COMMIT;
END mark_ambulance_maintenance;
/


BEGIN
     mark_ambulance_maintenance(5);
END;

SELECT ambulance_id, status FROM Ambulances WHERE ambulance_id = 5;


-- Function: is_high_priority_call

CREATE OR REPLACE FUNCTION is_high_priority_call (
    p_call_id IN NUMBER
) RETURN VARCHAR2 AS
    v_priority_rank NUMBER;
BEGIN
    SELECT t.priority_rank
    INTO   v_priority_rank
    FROM   EmergencyCalls c
    INNER JOIN TriageLevels t ON c.triage_id = t.triage_id
    WHERE  c.call_id = p_call_id;

    IF v_priority_rank >= 4 THEN
        RETURN 'Y';
    ELSE
        RETURN 'N';
    END IF;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RETURN 'N';
END is_high_priority_call;
/


SET SERVEROUTPUT ON
DECLARE
     result VARCHAR2(1);
 BEGIN
    result := is_high_priority_call(3);
    DBMS_OUTPUT.PUT_LINE(result);
END;
 /