"""
bot_player.py
Polymorphic player model: HumanPlayer waits for socket input,
BotPlayer runs an instant decision algorithm.
"""


class Player:
    """Base player - holds shared state."""

    def __init__(self, nickname: str, chips: int = 1000):
        self.nickname = nickname
        self.chips = chips
        self.hand = []
        self.bet = 0
        self.round_bet = 0
        self.folded = False

    def get_action(self, game_state: dict) -> dict:
        raise NotImplementedError

    def to_dict(self):
        return {
            'nickname': self.nickname,
            'chips': self.chips,
            'bet': self.bet,
            'round_bet': self.round_bet,
            'folded': self.folded,
        }


class HumanPlayer(Player):
    """Action comes from the player's browser via Socket.IO."""

    def __init__(self, nickname: str, session_id: str, sid: str | None, chips: int = 1000):
        super().__init__(nickname, chips)
        self.session_id = session_id
        self.sid = sid
        self.is_connected = sid is not None

    def get_action(self, game_state: dict) -> dict:
        raise RuntimeError('HumanPlayer actions come from socket events, not get_action()')


class BotPlayer(Player):
    """Base bot - available for future extensions."""

    def __init__(self, nickname: str, personality: str = 'calculator', chips: int = 1000):
        super().__init__(nickname, chips)
        self.is_bot = True
        self.personality = personality
        self.session_id = None
        self.sid = None

    def get_action(self, game_state: dict) -> dict:
        hand_strength = self._evaluate_hand(game_state)

        if self.personality == 'rock':
            return self._rock_strategy(hand_strength, game_state)
        if self.personality == 'maniac':
            return self._maniac_strategy(hand_strength, game_state)
        return self._calculator_strategy(hand_strength, game_state)

    def _rock_strategy(self, strength: float, game_state: dict) -> dict:
        if strength > 0.7:
            pot = game_state.get('pot', 0)
            raise_size = max(game_state.get('min_raise', 20), pot // 2)
            target = game_state.get('current_bet', 20) + raise_size
            return self._aggressive_action(game_state, target)
        if strength > 0.4:
            return {'action': 'call', 'amount': 0}
        return {'action': 'fold', 'amount': 0}

    def _maniac_strategy(self, strength: float, game_state: dict) -> dict:
        if strength > 0.3:
            pot = game_state.get('pot', 0)
            raise_size = max(2 * game_state.get('min_raise', 20), pot)
            target = game_state.get('current_bet', 20) + raise_size
            return self._aggressive_action(game_state, target)
        return {'action': 'call', 'amount': 0}

    def _calculator_strategy(self, strength: float, game_state: dict) -> dict:
        call_amount = game_state.get('call_amount', 0)
        pot = game_state.get('pot', 1)
        pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0

        if strength > pot_odds + 0.2:
            # Size the raise to the strength/pot-odds edge, scaled by pot,
            # so a stronger edge means a bigger bet - not just the table minimum.
            edge = strength - pot_odds
            raise_size = max(game_state.get('min_raise', 20), int(pot * min(edge * 2, 1.0)))
            target = game_state.get('current_bet', 20) + raise_size
            return self._aggressive_action(game_state, target)
        if strength > pot_odds:
            return {'action': 'call', 'amount': call_amount}
        return {'action': 'fold', 'amount': 0}

    def _aggressive_action(self, game_state: dict, target: int) -> dict:
        if game_state.get('can_raise'):
            amount = min(target, game_state.get('max_total', target))
            amount = max(amount, game_state.get('min_raise_total', amount))
            return {'action': 'raise', 'amount': amount}
        if game_state.get('can_short_all_in'):
            return {'action': 'raise', 'amount': game_state.get('max_total', 0)}
        if game_state.get('can_call') or game_state.get('call_amount', 0) == 0:
            return {'action': 'call', 'amount': game_state.get('call_amount', 0)}
        return {'action': 'fold', 'amount': 0}

    def _evaluate_hand(self, game_state: dict) -> float:
        community = game_state.get('community_cards_objects', [])
        cards = (self.hand or []) + community
        if len(cards) >= 5:
            from game_engine import best_hand_value
            val = best_hand_value(cards)
            return val[0] / 8.0
        if len(self.hand) == 2:
            high = max(c.value for c in self.hand) / 14.0
            pair = 0.3 if self.hand[0].value == self.hand[1].value else 0.0
            return min(1.0, high * 0.6 + pair)
        import random
        return random.uniform(0.2, 0.5)
