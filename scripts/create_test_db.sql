-- Runs once, the first time the Postgres container starts with an empty volume.
-- Tests use their own database so they never wipe your dev data.
CREATE DATABASE quickserve_test;
