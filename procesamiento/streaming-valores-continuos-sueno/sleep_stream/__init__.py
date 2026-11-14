"""Procesamiento incremental de datos biométricos de sueño (ORBIVIA).

Recibe registros por un stream de Redis, los agrega en ventanas que se van
colapsando y, al terminar la sesión, genera un vector resumen por astronauta.
Ver docs/sleep_stream_design.md.
"""
