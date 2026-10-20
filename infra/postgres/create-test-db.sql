-- Runs once, when the docker-compose volume is first created.
-- Integration tests use this database and refuse to touch any other.
CREATE DATABASE nba_test OWNER nba;
