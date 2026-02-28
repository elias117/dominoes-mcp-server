# Changelog

## v1.1.0 — 2026-02-27

### Fixed
- **Stateless HTTP session compatibility** — MCP HTTP transport creates a new server session per tool call, causing `state.store_id` and `state.cart` to reset between calls. Fixed by persisting state to disk (`/tmp/dominos_cart_state.json`, configurable via `DOMINOS_STATE_PATH` env var).
- **Preferred store fallback** — Tools that require a selected store (`add_to_cart`, `get_menu`, `search_menu_items`, `price_order`, `validate_order`) now fall back to `preferences.preferred_store_id` from config when no store is selected in the current session.
- **Canadian postal code support** — Billing postal code is now passed as a string to the Domino's API, fixing a crash when using non-US (e.g. Canadian) postal codes.
- **Amex card detection** — Relaxed Amex card number regex to correctly identify valid Amex numbers.

### Changed
- `ServerState` now loads persisted state on init and exposes a `save()` method.
- `find_nearby_stores` saves state after auto-selecting the nearest open store.
- `add_to_cart` and `clear_cart` save state after mutations.
- Version bumped to `1.1.0` in `pyproject.toml`.

## v1.0.0 — Initial release
