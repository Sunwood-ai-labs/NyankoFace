CREATE DATABASE nyankoface_metrics OWNER nyankoface;
CREATE DATABASE nyankoface_maintenance OWNER nyankoface;

\connect nyankoface_metrics
CREATE SCHEMA IF NOT EXISTS nyankoface_pipeline AUTHORIZATION nyankoface;
