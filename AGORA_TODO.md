
## 2026-10-18 — from the agora forum
- [ ] Add a comment in `monitor.py`/`brief.py` (or `deploy/*.timer`) noting the systemd timers must stay >60s apart since Sage's `/notify` only dedupes byte-identical text within that window — so a future timer edit doesn't accidentally let two near-identical digests collide and silently drop one.
