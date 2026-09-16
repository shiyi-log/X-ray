\set ON_ERROR_STOP on
\getenv admin_password XRAY_ADMIN_DB_PASSWORD
\getenv subscription_password XRAY_SUBSCRIPTION_DB_PASSWORD
\getenv worker_password XRAY_WORKER_DB_PASSWORD
\getenv outbox_password XRAY_OUTBOX_DB_PASSWORD

SELECT format('CREATE ROLE xray_admin_api LOGIN PASSWORD %L', :'admin_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'xray_admin_api') \gexec
SELECT format('CREATE ROLE xray_subscription_reader LOGIN PASSWORD %L', :'subscription_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'xray_subscription_reader') \gexec
SELECT format('CREATE ROLE xray_worker LOGIN PASSWORD %L', :'worker_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'xray_worker') \gexec
SELECT format('CREATE ROLE xray_outbox LOGIN PASSWORD %L', :'outbox_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'xray_outbox') \gexec

SELECT format('ALTER ROLE xray_admin_api PASSWORD %L', :'admin_password') \gexec
SELECT format('ALTER ROLE xray_subscription_reader PASSWORD %L', :'subscription_password') \gexec
SELECT format('ALTER ROLE xray_worker PASSWORD %L', :'worker_password') \gexec
SELECT format('ALTER ROLE xray_outbox PASSWORD %L', :'outbox_password') \gexec

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO xray_admin_api, xray_subscription_reader, xray_worker, xray_outbox;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO xray_admin_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO xray_admin_api;

ALTER DEFAULT PRIVILEGES FOR ROLE xray_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO xray_admin_api;
ALTER DEFAULT PRIVILEGES FOR ROLE xray_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO xray_admin_api;

SELECT format(
    'GRANT SELECT ON TABLE %I.%I TO xray_subscription_reader',
    schemaname,
    tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename = ANY (ARRAY[
    'subscriptions_accessprofile',
    'subscriptions_subscription',
    'subscriptions_subscriptiontoken',
    'subscriptions_subscriptionrevision',
    'subscriptions_securitystate',
    'subscriptions_revocationtombstone'
  ]) \gexec

SELECT format(
    'GRANT SELECT, INSERT, UPDATE ON TABLE %I.%I TO xray_worker',
    schemaname,
    tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename = ANY (ARRAY[
    'operations_operation',
    'operations_operationstep',
    'operations_outboxevent',
    'nodes_managednode',
    'subscriptions_revocationnodestate',
    'subscriptions_nodecredential',
    'subscriptions_revocationtombstone',
    'subscriptions_securityeventrecord',
    'subscriptions_securityeventoutbox',
    'subscriptions_securitystate',
    'subscriptions_subscription',
    'subscriptions_subscriptiontoken'
  ]) \gexec

SELECT format(
    'GRANT SELECT, INSERT, UPDATE ON TABLE %I.%I TO xray_outbox',
    schemaname,
    tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'operations_outboxevent',
    'subscriptions_securityeventoutbox',
    'subscriptions_securityeventrecord',
    'subscriptions_securitystate'
  ) \gexec

SELECT format(
    'REVOKE UPDATE, DELETE ON TABLE %I.%I FROM xray_admin_api, xray_subscription_reader',
    schemaname,
    tablename
)
FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'audit_auditevent' \gexec

SELECT format(
    'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I FROM xray_subscription_reader',
    schemaname,
    tablename
)
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('cloud_accounts_cloudaccount', 'cloud_accounts_cloudcredentialversion')
\gexec
