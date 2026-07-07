# Bots

**Note:** Bots are a Texas Hold'em-specific feature. Blackjack does not currently support bot players.

Bots are server-side AI players. When it's a bot's turn, `_process_automatic_turns` hands off to `_schedule_bot_turn(player)`, which spawns a background task via `socketio.start_background_task(_run_bot_turn, player)`. That task sleeps `random.uniform(0.7, 1.5)` seconds (the "thinking" delay), re-validates that the same bot is still on the clock, calls `bot.get_action(game_state)`, applies the action, and re-enters the scheduler for the next actor.

A module-level `_bot_action_pending` flag prevents double-scheduling. On wake-up the task bails cleanly if `current_game` is gone (restart) or if `current_player()` no longer points to the same bot (disconnect / state change during the sleep).

Bots have no socket connection. They're created in `on_add_bot` (`app.py`) with a synthetic `session_id` like `bot-xxxxxxxxxx`, are always `is_connected = True`, and are added directly to the lobby. They can be removed pre-game via `remove_bot {nickname}`.

## Adding a bot

```
client → add_bot {personality: 'calculator' | 'rock' | 'maniac'}
```

The server validates the personality (defaults to `calculator` if unknown), generates a unique nickname like `Bot 1 (rock)`, and broadcasts the lobby update. Bots can only be added before the game starts - see `if game_active: return` at the top of `on_add_bot`.

## The decision contract

`BotPlayer.get_action(game_state)` (in `bot_player.py`) returns:

```python
{'action': 'fold' | 'check' | 'call' | 'raise', 'amount': int}
```

`game_state` is `legal_actions_for(player)` plus `pot` and `community_cards_objects`. So a bot has access to the same information a human's UI has, plus the raw community cards (needed for hand evaluation).

If a bot returns an illegal action, `_run_bot_turn` falls back to `fold` so it can't stall the table:

```python
if event in ('invalid_action', 'not_your_turn', 'error'):
    act = 'fold'
    amount = 0
    _, event = current_game.apply_action(None, act, amount)
```

## Hand strength

`_evaluate_hand` returns a float in `[0, 1]`:

- **5+ cards available** (flop or later): use the actual `best_hand_value` from the engine, normalized as `category / 8`. So a pair ≈ 0.125, a flush = 0.625, a straight flush = 1.0. This ignores tiebreaker kickers - it's a coarse measure on purpose.
- **2 cards (preflop)**: `high_card / 14 * 0.6 + (0.3 if pocket_pair else 0)`. AA ≈ 0.9, 72o ≈ 0.3, 22 ≈ 0.39.
- **No cards yet**: random in `[0.2, 0.5]` (shouldn't normally happen since hands are always dealt before action).

This is intentionally simple. There is no equity calculation, no opponent modeling, and no awareness of position or stack depth.

## Personalities

All three personalities call `_aggressive_action` to translate "I want to bet" into the actual action - that helper picks `raise` if a full raise is legal, `raise` for the all-in amount if only a short all-in is legal, otherwise falls back to `call` or `fold`.

### Rock - tight/passive

```
strength > 0.7 → aggressive (target = max(20, min_raise_total))
strength > 0.4 → call
otherwise     → fold
```

Folds the bottom 40% of hands, calls medium hands, only raises premium hands. The minimum raise it makes is small - close to `min_raise_total`.

### Maniac - loose/aggressive

```
strength > 0.3 → aggressive (target = current_bet + 2*min_raise)
otherwise     → call
```

Almost never folds. Raises with anything above weak. Target raise size is roughly **double** the minimum raise on top of the current bet, so the maniac builds pots fast.

### Calculator - pot-odds based (default)

```
pot_odds = call_amount / (pot + call_amount)
strength > pot_odds + 0.2 → aggressive (target = current_bet + min_raise)
strength > pot_odds       → call
otherwise                 → fold
```

This is the most "thoughtful" of the three but still naive: it treats normalized hand category as if it were equity. It's a useful baseline opponent and gives non-trivial behavior on the flop and later.

## What bots don't do

- No bluffing, slow-playing, or bet sizing relative to pot.
- No memory of opponents across hands.
- The "thinking" delay is fixed-uniform random in `_run_bot_turn`. Bots don't vary their pacing by hand strength, street, or personality. To add that, change the `socketio.sleep(...)` value in `_run_bot_turn` based on `player.personality` or the decision - keep it inside the scheduler, not inside the bot.
- No awareness of position (button vs. early), stack-to-pot ratio, or implied odds.

## Adding a new personality

1. Add the name to the allow-list in `on_add_bot` (`app.py`):
   ```python
   if personality not in {'calculator', 'rock', 'maniac', 'newbot'}:
   ```
2. Add a branch in `BotPlayer.get_action` and a `_newbot_strategy(strength, game_state)` method in `bot_player.py`.
3. Return `{'action', 'amount'}` using `legal_actions_for` fields. Use `_aggressive_action` to handle "I want to put more chips in" so short-all-in/raise-not-allowed cases work correctly.
4. Optionally surface the personality in the lobby UI (the `personality` field is already broadcast in `lobby_update` and `game_state`).
