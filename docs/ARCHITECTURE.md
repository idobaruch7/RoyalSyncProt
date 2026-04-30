# Architecture Overview

This prototype is a self-contained Texas Hold'em demo. It runs as a single Flask + Socket.IO server with three static HTML pages and an in-memory game state. There is no database, no persistence layer, and no auth.

## Top-level layout

```
prototype_royalsync/
├── server/
│   ├── app.py            # Flask + Socket.IO server, lobby, session/queue mgmt
│   ├── game_engine.py    # Cards, deck, hand evaluation, betting state machine
│   └── bot_player.py     # Player base class + Human/Bot subclasses & strategies
└── public/
    ├── index.html        # Landing page (links to /host and /join)
    ├── host/index.html   # Host/table view — shows lobby, bots, full board
    └── player/index.html # Player view — joins via nickname, sees own hole cards
```

## Runtime model

- **One process, one table.** Global state in `app.py` (`session_players`, `current_game`, `join_queue`, `game_active`) holds a single active game. Restarting the server wipes everything.
- **Sessions are browser-scoped.** Each player browser generates a `session_id` (kept in `localStorage`) and sends it with `join_game`. The server maps `session_id → player info` and `sid (socket id) → session_id`. This is what allows reconnect after a refresh: the socket id changes, but the session id is stable.
- **Two roles:**
  - **Host** (`/host`) — passive observer of lobby + table. Can add bots, start the game, advance to next hand. Doesn't play.
  - **Player** (`/join`) — picks a nickname, joins the lobby, plays the hand.
- **Bots** are server-side only. They have a `session_id` (prefixed `bot-`) but no socket; they're always treated as connected.

## Lifecycle of a hand

1. Players join the lobby → `session_players[sid].state = 'lobby'`.
2. Host clicks **Start** → `on_start_game` builds `Player` objects (Human or Bot) and constructs a `Game`. `game_active = True`.
3. `Game.start_hand()` shuffles, deals 2 hole cards each, posts blinds, sets the action queue (`to_act`).
4. The server enters `_process_automatic_turns()`:
   - If current player is a bot → `_schedule_bot_turn(player)` spawns a background task (`socketio.start_background_task` + `socketio.sleep` for a 0.7–1.5 s "thinking" delay) and returns immediately. The task re-validates state on wake, applies the action, then re-invokes the scheduler.
   - If current player is a disconnected human → auto check/fold synchronously, loop.
   - If current player is a connected human → emit `your_turn`, return and wait for `player_action`.
5. Each `apply_action` returns one of `continue`, `street_end`, `game_over`, `invalid_action`, `not_your_turn`. The scheduler resumes on `continue`/`street_end`. After every successfully applied action the server emits an `action_event` (used by clients to render toasts).
6. On `game_over`, `_broadcast_hand_over` emits winners + showdown state. Host clicks **Next hand** → `on_next_hand` flushes the queue, calls `Game.next_hand()`, repeats.
7. If fewer than 2 players remain connected, `_finish_game_if_too_few_connected` ends the session and returns everyone to the lobby.

## Joining mid-game

- A new player joining while `game_active` is **queued** rather than rejected. They see `join_queued`. On the next hand, `_flush_queue` adds them as a real `HumanPlayer` to `Game.players` before `Game.next_hand()` runs.
- Reconnects (same `session_id`) re-attach the socket via `_attach_session_to_sid` and re-emit lobby/game state without changing seat order.

## Socket events (cheat sheet)

Client → server:
- `join_game {nickname, session_id}`
- `add_bot {personality}` (host only by convention)
- `remove_bot {nickname}` (host; pre-game only)
- `start_game`, `next_hand`, `restart_game` (host)
- `player_action {action, amount}`
- `host_connected` (host requests current snapshot)

Server → client:
- `lobby_update`, `queue_update` — broadcast snapshots
- `join_success`, `join_queued`, `join_error`
- `game_starting`, `game_state` — full table snapshot for everyone
- `your_hand` — private, only to the owning socket
- `your_turn` — private, includes `legal_actions_for(player)`
- `action_error` — private, illegal action feedback
- `action_event {actor, action, amount, all_in}` — broadcast after every applied action (powers client-side toasts)
- `hand_over`, `game_finished`
- `add_bot_error` — private, surfaces add/remove-bot rejection messages

## Key design choices

- **Polymorphic players.** `_process_automatic_turns` treats connected humans, disconnected humans, and bots distinctly but in one loop. Disconnected humans auto-act synchronously; bots are scheduled via a background task; connected humans get `your_turn` and the loop returns.
- **Single-flight bot scheduling.** A `_bot_action_pending` flag plus `socketio.start_background_task` mean only one bot turn is ever in flight. On wake-up the task re-checks `current_game.current_player()` so a restart, disconnect, or game-end during the sleep is a clean no-op.
- **Server is authoritative.** Clients never compute legal actions, pots, or winners. The server emits `legal_actions_for(player)` with `your_turn`; the UI just renders buttons.
- **Bots can't stall the table.** If a bot returns an invalid action, `_run_bot_turn` falls back to `fold`. See `app.py`.
- **`to_dict(for_sid=...)`** in `game_engine.py` is how private hole cards are kept private. The full game state is broadcast, but each socket only sees its own cards (or all cards at showdown).
- **Busted players stay seated.** `Game.next_hand` does not drop chip-zero players; `start_hand` pre-folds them and `_next_active_index` rotates the dealer/blinds past them. They remain visible in `to_dict` (folded, no hand, 0 chips).
- **Action toasts via broadcast.** `_emit_action_event` fires from every action-applied site (human, bot, auto-fold for offline humans). Both host and player pages render the same toast UI.

For poker rules / betting state machine, see `GAME_ENGINE.md`.
For bot personalities, see `BOTS.md`.
