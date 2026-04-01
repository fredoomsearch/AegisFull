# AEGIS Docs

This folder was reduced to the current canonical set.

## Read Order

1. [Architecture Map](./architecture_map.md)
2. [Verification Surface Map](./verification_surface_map.md)
3. [Core Hole Scan](./core_hole_scan.md)
4. [Config Reference](./config_reference.md)
5. [Release Board](./release_board.md)
6. [Known Limits](./known_limits.md)

## Why Only These Docs Remain

The repo had too much overlapping documentation:

- duplicate architecture maps
- historical closure notes
- one-off audit docs
- planning docs that no longer matched the current runtime

Those were removed so the repo has one small, current, usable documentation surface.

## Canonical Rules

- `README.MD` is the repo entrypoint.
- `architecture_map.md` is the architecture truth.
- `verification_surface_map.md` is the runtime/gate proof map.
- `core_hole_scan.md` is the honest gap list.
- `release_board.md` is the current readiness snapshot.
