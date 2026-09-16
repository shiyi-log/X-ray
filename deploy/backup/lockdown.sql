\set ON_ERROR_STOP on
BEGIN;

INSERT INTO subscriptions_securitystate (
    singleton_key,
    mode,
    last_security_sequence,
    expected_security_sequence,
    last_external_security_sequence,
    security_backup_lagging,
    restore_epoch,
    updated_at
) VALUES (1, 'MAINTENANCE', 0, 0, 0, TRUE, 1, CURRENT_TIMESTAMP)
ON CONFLICT (singleton_key) DO UPDATE SET
    mode = 'MAINTENANCE',
    security_backup_lagging = TRUE,
    restore_epoch = subscriptions_securitystate.restore_epoch + 1,
    updated_at = CURRENT_TIMESTAMP;

UPDATE nodes_managednode
SET security_state = 'MAINTENANCE', updated_at = CURRENT_TIMESTAMP
WHERE desired_state <> 'DELETED';

UPDATE operations_operation
SET status = 'NEEDS_RECONCILIATION',
    lease_owner = '',
    lease_expires_at = NULL,
    lease_fence = lease_fence + 1,
    error_code = 'RESTORE_RECONCILIATION_REQUIRED',
    updated_at = CURRENT_TIMESTAMP
WHERE status NOT IN ('CANCELLED', 'SUCCEEDED', 'FAILED', 'PARTIALLY_SUCCEEDED');

UPDATE operations_outboxevent
SET delivered_at = CURRENT_TIMESTAMP,
    last_error_code = 'RESTORE_RECONCILIATION_REQUIRED'
WHERE delivered_at IS NULL;

COMMIT;
