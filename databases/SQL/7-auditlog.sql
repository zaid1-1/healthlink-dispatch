CREATE TABLE AuditLog (
    log_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dispatch_id  NUMBER          NOT NULL,
    action       VARCHAR2(50)    NOT NULL,
    performed_by VARCHAR2(50)    NOT NULL,
    log_time     DATE            DEFAULT SYSDATE NOT NULL,
    CONSTRAINT fk_auditlog_dispatch FOREIGN KEY (dispatch_id) REFERENCES Dispatches(dispatch_id)
);