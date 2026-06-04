"""Application-layer services for VoIPCalc-Core.

These services act as a facade between the external world (HTTP, RPC)
and the pure domain layer.  They handle protocol translation, external
context integration, and defensive input validation, but contain no
rate-calculation business rules.
"""