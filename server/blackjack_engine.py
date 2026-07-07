"""blackjack_engine.py — Prototype
Blackjack game logic: deck, player turns, dealer auto-play, payout.
"""
from game_engine import Deck

_BJ_VAL = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
    '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10, 'A': 11,
}


def hand_value(cards):
    total = aces = 0
    for c in cards:
        total += _BJ_VAL[c.rank]
        if c.rank == 'A':
            aces += 1
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackGame:
    BET = 100

    def __init__(self, players):
        self.players = list(players)
        self.deck = Deck()
        self.dealer_hand = []
        self.dealer_hidden = True
        self.player_states = {}  # session_id -> {cards, status, bet, doubled}
        self.state = 'waiting'
        self.to_act = []         # session_ids of players who still need to act
        self.results = {}        # session_id -> 'win'|'lose'|'push'|'bust'|'blackjack'

    def start_round(self):
        self.deck = Deck()
        self.dealer_hand = self.deck.deal(2)
        self.dealer_hidden = True
        self.player_states = {}
        self.results = {}
        active = []

        for p in self.players:
            if p.chips >= self.BET:
                p.chips -= self.BET
                cards = self.deck.deal(2)
                status = 'blackjack' if hand_value(cards) == 21 else 'playing'
                self.player_states[p.session_id] = {
                    'cards': cards, 'status': status, 'bet': self.BET, 'doubled': False,
                }
                if status == 'playing':
                    active.append(p.session_id)
            else:
                self.player_states[p.session_id] = {
                    'cards': [], 'status': 'sitting_out', 'bet': 0, 'doubled': False,
                }

        self.to_act = active
        self.state = 'player_turns'

        if not self.to_act:
            self._dealer_play()

        return self._current_player()

    def _current_player(self):
        if not self.to_act:
            return None
        return next((p for p in self.players if p.session_id == self.to_act[0]), None)

    def current_player(self):
        return self._current_player()

    def apply_action(self, session_id, action):
        if not self.to_act or self.to_act[0] != session_id:
            return 'not_your_turn'
        state = self.player_states.get(session_id)
        if not state or state['status'] != 'playing':
            return 'invalid'

        player = next((p for p in self.players if p.session_id == session_id), None)

        if action == 'stand':
            state['status'] = 'standing'
            self.to_act.pop(0)

        elif action == 'hit':
            state['cards'].extend(self.deck.deal(1))
            val = hand_value(state['cards'])
            if val > 21:
                state['status'] = 'bust'
                self.to_act.pop(0)
            elif val == 21:
                state['status'] = 'standing'
                self.to_act.pop(0)
            # else remains 'playing' — player may act again

        elif action == 'double':
            extra = min(state['bet'], player.chips if player else 0)
            if player and extra > 0:
                player.chips -= extra
            state['bet'] += extra
            state['doubled'] = True
            state['cards'].extend(self.deck.deal(1))
            val = hand_value(state['cards'])
            state['status'] = 'bust' if val > 21 else 'standing'
            self.to_act.pop(0)

        else:
            return 'invalid'

        if not self.to_act:
            self._dealer_play()
            return 'round_over'

        return 'continue'

    def _dealer_play(self):
        self.dealer_hidden = False
        while hand_value(self.dealer_hand) < 17:
            self.dealer_hand.extend(self.deck.deal(1))
        self._resolve()
        self.state = 'round_over'

    def _resolve(self):
        dealer_val = hand_value(self.dealer_hand)
        dealer_bust = dealer_val > 21
        for p in self.players:
            state = self.player_states.get(p.session_id, {})
            status = state.get('status')
            bet = state.get('bet', 0)
            if status in (None, 'sitting_out'):
                continue
            if status == 'bust':
                self.results[p.session_id] = 'bust'
            elif status == 'blackjack':
                p.chips += bet + int(bet * 1.5)   # pays 3:2
                self.results[p.session_id] = 'blackjack'
            elif dealer_bust:
                p.chips += bet * 2
                self.results[p.session_id] = 'win'
            else:
                pval = hand_value(state.get('cards', []))
                if pval > dealer_val:
                    p.chips += bet * 2
                    self.results[p.session_id] = 'win'
                elif pval == dealer_val:
                    p.chips += bet
                    self.results[p.session_id] = 'push'
                else:
                    self.results[p.session_id] = 'lose'

    def to_dict(self):
        if self.dealer_hidden and self.dealer_hand:
            dealer_display = [self.dealer_hand[0].to_dict(), {'rank': '?', 'suit': '?'}]
            dealer_val = _BJ_VAL.get(self.dealer_hand[0].rank, 10)
        else:
            dealer_display = [c.to_dict() for c in self.dealer_hand]
            dealer_val = hand_value(self.dealer_hand) if self.dealer_hand else 0

        current = self._current_player()
        players_out = []
        for p in self.players:
            state = self.player_states.get(p.session_id, {})
            cards = state.get('cards', [])
            players_out.append({
                'nickname': p.nickname,
                'chips': p.chips,
                'status': state.get('status', 'spectating'),
                'bet': state.get('bet', 0),
                'doubled': state.get('doubled', False),
                'is_current': current is not None and p.session_id == current.session_id,
                'is_connected': getattr(p, 'is_connected', True),
                'cards': [c.to_dict() for c in cards],
                'hand_value': hand_value(cards) if cards else 0,
                'result': self.results.get(p.session_id),
            })

        return {
            'state': self.state,
            'bet_amount': self.BET,
            'dealer_cards': dealer_display,
            'dealer_value': dealer_val,
            'players': players_out,
            'current_player': current.nickname if current else None,
        }
