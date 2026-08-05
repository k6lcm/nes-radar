"""C64U Radar traffic code, reduced to the part NES Radar uses.

NES Radar needs a client for adsb.fi, and C64U Radar already had a proven one,
so ``ultimate_radar_server`` here carries that layer: TrafficService,
ServerConfig, Scope, extract_targets, and distance_nm.

Upstream the same file is a complete standalone C64 radar server. Its
Commodore-specific half is not included. Retained code is copied verbatim from
a pinned upstream commit -- see ../../THIRD_PARTY_NOTICES.md.
"""
