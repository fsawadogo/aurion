"""EMR write-back module (#57) — pluggable connectors for posting
approved notes to external EMR/EHR systems.

The foundation slice supports only the `stub` connector (records
attempts to the local DB; no real network call). Real backends
(Oscar, Epic SMART, generic FHIR endpoint, HL7v2 over MLLP) land in
follow-up issues — they implement the EMRConnector interface.
"""
