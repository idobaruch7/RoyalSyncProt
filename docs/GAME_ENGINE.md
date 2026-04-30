# Game Engine

`server/game_engine.py` implements the poker rules. It has no awareness of sockets, sessions, or HTTP — it works on `Player` objects passed in by the caller.

## Cards & deck

- `Card(rank, suit)` — `rank` is `'2'..'10', 'J', 'Q', 'K', 'A'`; `suit` is one of `♠ ♥ ♦ ♣`. `value` is the integer rank (Ace = 14).
- `Deck()` — 52 shuffled cards. `deal(n)` pops `n` cards off the front.

## Hand evaluation

`_eval_five(cards)` returns a comparable tuple `(category, …tiebreakers)` where `category` is:

| Category | Hand            |
|---------:|-----------------|
| 8        | Straight Flush  |
| 7        | Four of a Kind  |
| 6        | Full House      |
| 5        | Flush           |
| 4        | Straight        |
| 3        | Three of a Kind |
| 2        | Two Pair        |
| 1        | Pair            |
| 0        | High Card       |

`best_hand_value(cards)` picks the best of `C(n,5)` combinations; `best_hand_cards(cards)` returns the actual 5-card combo. Wheel straights (`A-2-3-4-5`) are special-cased.

## Game state machine

```
WAITING → PRE_FLOP → FLOP → TURN → RIVER → SHOWDOWN
```

Transitions live in `_advance_street`. After each street, `round_bet`, `current_bet`, and `min_raise` reset, and `to_act` is rebuilt from the player to the left of the dealer.

## The action queue (`to_act`)

`to_act` is a list of player indices that still need to act this betting round. The current actor is always `to_act[0]`.

- **Fold/check/call** → `_remove_current_actor` pops from the queue.
- **Full raise** → `_reopen_action_from(idx)` rebuilds the queue: every other live player must respond again, and `raise_reopened_for` is reset to that set.
- **Short all-in** (raise smaller than `min_raise`) → does *not* reopen action for players who already acted — see `can_short_all_in` and the `raise_reopened_for` set.

When `to_act` empties, `_advance_street` is called. If only one live player remains at any point, `_award_pots` runs immediately (`game_over`).

## Legal action contract

`legal_actions_for(player)` returns the dict the server hands to the client (and to bots). Important fields:

- `call_amount` — chips needed to match `current_bet`.
- `current_bet` — highest `round_bet` so far this street.
- `min_raise` — last raise size (the increment).
- `min_raise_total` — minimum total bet for a legal full raise.
- `max_total` — `round_bet + chips`, i.e. the most this player can bet (their stack).
- `can_check`, `can_call`, `can_raise`, `can_short_all_in` — booleans the UI uses to enable buttons.
- `aggressive_action` — `'raise'`, `'all_in'`, or `'none'`. Tells the UI which label to show.

## Applying an action

`apply_action(sid, action, amount)` is the single entry point. Returns `(player_or_none, event)` where event is one of:

- `continue` — same street, next actor up.
- `street_end` — moved to next street, action continues.
- `game_over` — hand is finished (fold-out or showdown). `get_winners`, `get_pot_results`, `winner_hand_details` are now valid.
- `invalid_action` — `last_action_error` has the reason; nothing changed.
- `not_your_turn` — sid mismatch; nothing changed.
- `error` — no current player.

The `sid` parameter is `None` for server-driven actions (bots, auto-fold for disconnected players).

## Pot building & side pots

`_build_pots()` walks every distinct `bet` level and constructs a layered pot list. Each pot tracks its `amount`, the `eligible` (non-folded) contributors, and all `contributors`. This is what makes side pots correct when an all-in player is matched by larger stacks.

`_award_pots(forced_winners=None)` evaluates each pot independently:
- If `forced_winners` is given (only one player left after folds), they collect.
- Otherwise, eligibles are compared via `best_hand_value` on `hand + community_cards`.
- Splits divide evenly, with the odd chip going to the lowest-seat winner.

## Snapshotting (`to_dict`)

`Game.to_dict(for_sid=None)` produces the full game state for clients. Two visibility rules govern hole cards:

1. At `SHOWDOWN`, every non-folded player's hand is revealed.
2. Otherwise, only the player whose `sid == for_sid` sees their own hand.

The host page calls without `for_sid` (so it sees nothing private until showdown). Player pages get the same broadcast and additionally receive a private `your_hand` event with their two cards. The player UI uses the same broadcast to render its "Table" section (opponents, chips, bets, dealer/blind tags, current actor highlight).

## Busted players stay seated

`Game.next_hand` does **not** filter chip-zero players out of `Game.players`. They remain in the player list (and therefore in `to_dict`) for the rest of the game. `start_hand` handles them by:

- Pre-folding (`p.folded = True`) and clearing their hand (`p.hand = []`).
- Skipping them when assigning the dealer button, small blind, big blind, and first-to-act, via `_next_active_index(from_idx)` (which walks forward to the next index whose player has `chips > 0`).

This keeps the displayed seat order stable across knockouts — the host's table list and the player's "Table" section both keep showing busted players (with `0 chips`, `FOLD` tag) until the game ends.

End-of-game detection still works because `_finish_game_if_one_player_left` (in `app.py`) counts players with `chips > 0`, not `len(players)`.

## What's *not* in the engine

- No timing/auto-fold timers. The server in `app.py` decides what to do when a human is disconnected.
- No chip top-ups, no ante, no straddle. Blinds are fixed at 10/20.
- No tournament structure. Blinds never increase. The "session" ends only when fewer than 2 players are connected.
