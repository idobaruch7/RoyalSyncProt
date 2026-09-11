# RoyalSync — Study Roadmap
### Topic: Real-Time Infrastructure & Orchestration (`server/app.py`)

Work through this with me — tell me which item you're on and I'll walk you through the code, quiz you, or trace it with you live.

---

## Week 1 — The backbone
**Goal:** you can open `app.py` and know what every top-level handler does.

- [x] **Day 1–2 — Map every `on_*` event handler**
  Read `on_join_game`, `on_player_action`, `on_add_bot`, `on_remove_bot`, `on_start_game`, `on_restart_game`, `on_pause_game`, `on_next_hand`, `on_disconnect` top to bottom. Goal: "client emits X → this function runs."

- [x] **Day 3–4 — Trace one full action lifecycle**
  `on_player_action` → `_apply_and_advance` → `_broadcast_game_state`. Practice saying it in one breath: **emit → validate → mutate → broadcast.**

- [ ] **Day 5 — Broadcasting & private state**
  `_broadcast_game_state`, `_send_private_hands`, `_send_private_hand`, `_notify_current_player` — why some data goes to everyone and hole cards go only to one socket.

- [ ] **Day 6–7 — Buffer + skim the blackjack mirror**
  Confirm `bj_apply_action` / `_bj_broadcast_state` repeat the same pattern for the second game instance.

---

## Week 2 — Concurrency & continuity (the hard part)
**Goal:** you can explain the two trickiest stories in the codebase without notes.

- [ ] **Day 1–2 — Session & reconnect**
  `_attach_session_to_sid`, `_sync_player_connection`, the `session_players` / `sid_to_session` maps. Draw it from memory: browser refresh → new `sid`, same `session_id` → server re-links it.

- [ ] **Day 3–4 — Turn scheduling**
  `_process_automatic_turns`, `_schedule_bot_turn`, `_run_bot_turn`. Know why `socketio.sleep()` beats blocking `time.sleep()`, and what `_bot_action_pending` prevents — describe the race condition concretely.

- [ ] **Day 5 — Disconnects & the queue**
  `on_disconnect`, `_finish_game_if_too_few_connected`, `_queue_position`, `_flush_queue` — why the game doesn't just hang when someone drops.

- [ ] **Day 6–7 — First cold self-quiz**
  Run through the Q&A section of the presentation guide unaided. Flag anything you can't answer yet — bring it to me.

---

## Week 3 — Integration & defense
**Goal:** presentation-ready, not just "understood."

- [ ] **Day 1 — Defend the architecture tradeoffs**
  Why `DB_ENABLED = False`, why LAN-only (`_get_local_ip`), why one Flask process runs two concurrent game instances. Be ready for "why not X instead?"

- [ ] **Day 2–3 — One unbroken end-to-end trace**
  Pick a real scenario (e.g. a bot's human neighbor disconnects mid-hand, the bot plays its turn, the human reconnects two hands later) and narrate it out loud through every layer you own.

- [ ] **Day 4 — Second self-quiz — should be clean**
  Anything still shaky, re-read that exact function in `app.py` directly.

- [ ] **Day 5 — Timed dry run, cold**
  Present out loud to your partner or anyone else, no notes open.

- [ ] **Day 6 — Fix what the dry run exposed**
  Usually pacing or one weak transition, not content.

- [ ] **Day 7 — Buffer / light review only**
  Sleep, don't cram.

---

**Reference:** full presentation-prep guide (Hebrew) — see the artifact link shared earlier.
