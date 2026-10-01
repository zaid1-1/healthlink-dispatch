CREATE MATERIALIZED VIEW mv_hospital_dispatch_summary
BUILD IMMEDIATE
REFRESH COMPLETE ON DEMAND
AS
SELECT   h.hospital_id,
         h.name,
         COUNT(d.dispatch_id) AS total_dispatches
FROM     TraumaCenters h
LEFT JOIN Dispatches d ON h.hospital_id = d.hospital_id
GROUP BY h.hospital_id, h.name;



EXEC DBMS_MVIEW.REFRESH('MV_HOSPITAL_DISPATCH_SUMMARY', 'C');