"""Infrastructure adapters — concrete implementations of application ports.

Adapters depend on the application layer (ports, DTOs) and external
systems (sqlite3, etc.).  The application layer never imports from here.
"""