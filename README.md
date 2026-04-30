# RoyalTest Prototype (Standalone)

A self-contained Texas Hold'em demo: Flask + Socket.IO server, three static HTML pages, in-memory state, no database.

## Quickstart

```bash
# 1. install deps (use a venv if you like)
pip install -r requirements.txt

# 2. run the server
python3 server/app.py
```

Then open the URLs below. The server prints both a host URL and a LAN player URL on startup so phones on the same Wi-Fi can join.

## URLs

- Landing page: `http://localhost:5050/`
- Host page (table monitor + controls): `http://localhost:5050/host`
- Player page (join the table from your device): `http://localhost:5050/join`

## Project layout

```
prototype_royalsync/
├── server/
│   ├── app.py            # Flask + Socket.IO, lobby & session management
│   ├── game_engine.py    # Cards, hand evaluation, betting state machine
│   └── bot_player.py     # Human/Bot player classes + bot strategies
├── public/
│   ├── index.html        # Landing page
│   ├── host/index.html   # Host console
│   └── player/index.html # Player view
└── docs/                 # Dev-facing docs (read these first)
    ├── ARCHITECTURE.md   # Big-picture design, socket events, lifecycle
    ├── GAME_ENGINE.md    # Poker rules + state machine implementation
    └── BOTS.md           # How bots are scheduled and how personalities decide
```

## How it works (one-paragraph version)

The server holds a single in-memory game. Players join via `/join` with a nickname; the host opens `/host`, can add/remove bots and click **Start Game**. Bots are server-side and act on a small randomized "thinking" delay. Every action (fold/check/call/raise) emits a toast to all clients. Busted players stay seated so the table view never re-shuffles. See `docs/ARCHITECTURE.md` for the full picture.

## Optional environment variables

- `ROYALTEST_PROTOTYPE_PORT` (default `5050`)
- `ROYALTEST_PROTOTYPE_HOST` (default `0.0.0.0`)
- `ROYALTEST_PROTOTYPE_DEBUG` (`1`/`0`, default `0`)
- `ROYALTEST_PROTOTYPE_SECRET` — Flask session secret. Has a hard-coded default for local use; **set this to something random if you ever expose the server beyond localhost**.

## Scope / non-goals

- In-memory only — restarting the server wipes everything.
- One global table, ever.
- No host authentication: any client can hit `start_game` / `restart_game` / `add_bot`. Fine for a demo on a trusted network.
- Blinds are fixed at 10/20; no escalation, no antes.
- No automated tests yet.
