#!/usr/bin/env python3
import os
import socket
import sys

from flask import Flask, request, send_from_directory
from flask_socketio import SocketIO, emit

# Allow running via import/runpy as well as `python server/app.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import random
import string

from bot_player import BotPlayer, HumanPlayer
from game_engine import Game

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('ROYALTEST_PROTOTYPE_SECRET', 'royaltest-prototype-secret')
socketio = SocketIO(app, cors_allowed_origins='*')


# In-memory prototype state
MAX_PLAYERS = 8
session_players = {}
sid_to_session = {}
current_game = None
session_to_player = {}
game_active = False
join_queue = []


def _lobby_players():
    return [info for info in session_players.values() if info['state'] == 'lobby']


def _lobby_seat_count() -> int:
    # Seats are reserved by being in the lobby; offline players can reconnect.
    return len(_lobby_players())


def _eligible_start_players():
    # Bots are always eligible. Humans must be connected.
    out = []
    for info in _lobby_players():
        if info.get('is_bot'):
            out.append(info)
        elif info.get('is_connected'):
            out.append(info)
    return out


def _random_id(prefix: str) -> str:
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f'{prefix}-{suffix}'


def _unique_bot_nickname(personality: str) -> str:
    existing = {p['nickname'] for p in session_players.values()}
    i = 1
    while True:
        name = f'Bot {i} ({personality})'
        if name not in existing:
            return name
        i += 1


@app.route('/')
def index():
    return send_from_directory(PUBLIC_DIR, 'index.html')


@app.route('/host')
def host():
    return send_from_directory(os.path.join(PUBLIC_DIR, 'host'), 'index.html')


@app.route('/join')
def join():
    return send_from_directory(os.path.join(PUBLIC_DIR, 'player'), 'index.html')


@app.route('/public/<path:filename>')
def public_files(filename):
    return send_from_directory(PUBLIC_DIR, filename)


@socketio.on('connect')
def on_connect():
    print(f'[prototype][connect] {_request_sid()}')


@socketio.on('disconnect')
def on_disconnect():
    session_id = sid_to_session.pop(_request_sid(), None)
    if not session_id:
        return

    info = session_players.get(session_id)
    if not info:
        return

    info['sid'] = None
    info['is_connected'] = False
    print(f'[prototype][disconnect] {info["nickname"]}')

    player = session_to_player.get(session_id)
    if player:
        player.sid = None
        player.is_connected = False

    _broadcast_lobby()
    _broadcast_queue()

    if current_game:
        if _finish_game_if_too_few_connected():
            return
        _process_automatic_turns()
        _broadcast_game_state()


@socketio.on('host_connected')
def on_host_connected():
    emit('lobby_update', _lobby_snapshot())
    emit('queue_update', _queue_snapshot())
    if current_game:
        emit('game_starting', {})
        emit('game_state', current_game.to_dict())


@socketio.on('join_game')
def on_join_game(data):
    nickname = (data.get('nickname') or '').strip()
    session_id = (data.get('session_id') or '').strip()

    if not session_id:
        emit('join_error', {'message': 'Missing browser session. Refresh and try again.'})
        return
    if len(session_id) > 100:
        emit('join_error', {'message': 'Invalid browser session.'})
        return

    existing = session_players.get(session_id)
    if existing:
        _attach_session_to_sid(session_id, _request_sid())
        _sync_player_connection(session_id)
        print(f'[prototype][rejoin] {existing["nickname"]}')
        _emit_session_state(session_id)
        _broadcast_lobby()
        _broadcast_queue()
        if current_game:
            _broadcast_game_state()
        return

    if not game_active and _lobby_seat_count() >= MAX_PLAYERS:
        emit('join_error', {'message': f'Table is full (max {MAX_PLAYERS}).'})
        return

    if not nickname:
        emit('join_error', {'message': 'Nickname cannot be empty.'})
        return
    if len(nickname) > 20:
        emit('join_error', {'message': 'Nickname must be 20 characters or less.'})
        return
    if any(p['nickname'] == nickname for p in session_players.values()):
        emit('join_error', {'message': f'"{nickname}" is already taken. Choose another.'})
        return

    session_players[session_id] = {
        'session_id': session_id,
        'nickname': nickname,
        'chips': 1000,
        'sid': None,
        'is_connected': False,
        'state': 'lobby',
    }
    _attach_session_to_sid(session_id, _request_sid())

    if game_active:
        session_players[session_id]['state'] = 'queued'
        join_queue.append(session_id)
        emit('join_queued', {'nickname': nickname, 'chips': 1000, 'position': len(join_queue)})
        _broadcast_queue()
        return

    print(f'[prototype][join] {nickname}')
    emit('join_success', {'nickname': nickname, 'chips': 1000})
    _broadcast_lobby()


@socketio.on('add_bot')
def on_add_bot(data):
    if game_active:
        emit('add_bot_error', {'message': 'Can only add bots before the game starts.'})
        return

    if _lobby_seat_count() >= MAX_PLAYERS:
        emit('add_bot_error', {'message': f'Table is full (max {MAX_PLAYERS}).'})
        return

    personality = ((data or {}).get('personality') or 'calculator').strip().lower()
    if personality not in {'calculator', 'rock', 'maniac'}:
        personality = 'calculator'

    bot_session_id = _random_id('bot')
    while bot_session_id in session_players:
        bot_session_id = _random_id('bot')

    nickname = _unique_bot_nickname(personality)
    session_players[bot_session_id] = {
        'session_id': bot_session_id,
        'nickname': nickname,
        'chips': 1000,
        'sid': None,
        'is_connected': True,
        'state': 'lobby',
        'is_bot': True,
        'personality': personality,
    }

    print(f'[prototype][add_bot] {nickname}')
    _broadcast_lobby()


@socketio.on('remove_bot')
def on_remove_bot(data):
    if game_active:
        emit('add_bot_error', {'message': 'Cannot remove bots after the game has started.'})
        return

    nickname = ((data or {}).get('nickname') or '').strip()
    if not nickname:
        return

    target_id = None
    for session_id, info in session_players.items():
        if info.get('is_bot') and info['nickname'] == nickname:
            target_id = session_id
            break

    if target_id is None:
        return

    session_players.pop(target_id, None)
    print(f'[prototype][remove_bot] {nickname}')
    _broadcast_lobby()


@socketio.on('start_game')
def on_start_game():
    global current_game, session_to_player, game_active

    eligible = _eligible_start_players()
    if len(eligible) < 2:
        emit('start_error', {'message': 'Need at least 2 connected players to start.'})
        return

    players = []
    session_to_player = {}
    for session_id, info in session_players.items():
        if info['state'] != 'lobby':
            continue
        if not info.get('is_bot') and not info.get('is_connected'):
            continue
        if len(players) >= MAX_PLAYERS:
            continue
        info['state'] = 'game'
        if info.get('is_bot'):
            player = BotPlayer(info['nickname'], info.get('personality') or 'calculator', info['chips'])
            player.session_id = session_id
            player.is_connected = True
        else:
            player = HumanPlayer(info['nickname'], session_id, info['sid'], info['chips'])
            player.is_connected = info['is_connected']
        players.append(player)
        session_to_player[session_id] = player

    current_game = Game(players)
    game_active = True
    current_game.start_hand()

    print(f'[prototype][start_game] {len(players)} players')
    socketio.emit('game_starting', {})
    _broadcast_lobby()
    _broadcast_game_state()
    _send_private_hands()
    _process_automatic_turns()


@socketio.on('player_action')
def on_player_action(data):
    if not current_game or not game_active:
        return
    action = data.get('action', '')
    amount = int(data.get('amount', 0))
    _apply_and_advance(_request_sid(), action, amount)


@socketio.on('restart_game')
def on_restart_game():
    if not current_game and not game_active:
        return

    print('[prototype][restart_game]')
    socketio.emit('game_finished', {'winner': None, 'restarted': True})
    for info in session_players.values():
        info['chips'] = 1000
    _end_game_session()


@socketio.on('next_hand')
def on_next_hand():
    if not current_game:
        return

    _flush_queue()

    if _finish_game_if_too_few_connected():
        return

    current_game.next_hand()
    _sync_all_game_player_chips()
    _broadcast_game_state()
    _send_private_hands()
    _process_automatic_turns()


def _flush_queue():
    global join_queue
    if not join_queue or not current_game:
        return

    remaining_queue = []
    for session_id in join_queue:
        if len(current_game.players) >= MAX_PLAYERS:
            remaining_queue.append(session_id)
            continue
        info = session_players.get(session_id)
        if not info:
            continue
        if not info['is_connected']:
            remaining_queue.append(session_id)
            continue
        info['state'] = 'game'
        player = HumanPlayer(info['nickname'], session_id, info['sid'], info['chips'])
        player.is_connected = info['is_connected']
        current_game.players.append(player)
        session_to_player[session_id] = player
        if info['sid']:
            socketio.emit('game_starting', {}, to=info['sid'])

    join_queue = remaining_queue
    _broadcast_queue()
    _broadcast_lobby()


_bot_action_pending = False


def _emit_action_event(player, action: str, all_in: bool = False):
    if not player or not action:
        return
    if action in ('call', 'raise'):
        amount = int(getattr(player, 'round_bet', 0) or 0)
    else:
        amount = 0
    socketio.emit('action_event', {
        'actor': player.nickname,
        'action': action,
        'amount': amount,
        'all_in': bool(all_in),
    })


def _apply_and_advance(sid: str, action: str, amount: int):
    if not current_game:
        return

    actor = current_game.current_player()
    _, event = current_game.apply_action(sid, action, amount)
    _sync_all_game_player_chips()
    _broadcast_game_state()

    if event == 'invalid_action':
        session_id = sid_to_session.get(sid)
        info = session_players.get(session_id) if session_id else None
        if info and info.get('sid'):
            socketio.emit(
                'action_error',
                {'message': current_game.last_action_error or 'Illegal action.'},
                to=info['sid'],
            )
        _notify_current_player()
        return

    if event == 'not_your_turn':
        return

    if actor is not None:
        _emit_action_event(actor, action.lower(), all_in=(actor.chips == 0 and not actor.folded))

    if event == 'game_over':
        _broadcast_hand_over()
    elif event in ('continue', 'street_end'):
        _process_automatic_turns()


def _process_automatic_turns():
    while current_game and current_game.state.value not in ('waiting', 'showdown'):
        player = current_game.current_player()
        if player is None:
            return

        if isinstance(player, BotPlayer):
            _schedule_bot_turn(player)
            return

        if isinstance(player, HumanPlayer) and not player.is_connected:
            call_amount = current_game.current_bet - getattr(player, 'round_bet', 0)
            action = 'check' if call_amount <= 0 else 'fold'
            _, event = current_game.apply_action(None, action, 0)
            _emit_action_event(player, action, all_in=(player.chips == 0 and not player.folded))
            _sync_all_game_player_chips()
            _broadcast_game_state()

            if event == 'game_over':
                _broadcast_hand_over()
                return
            continue

        _notify_current_player()
        return


def _schedule_bot_turn(player):
    global _bot_action_pending
    if _bot_action_pending:
        return
    _bot_action_pending = True
    socketio.start_background_task(_run_bot_turn, player)


def _run_bot_turn(player):
    global _bot_action_pending
    try:
        socketio.sleep(random.uniform(0.7, 1.5))

        if not current_game or current_game.state.value in ('waiting', 'showdown'):
            return
        if current_game.current_player() is not player:
            return

        game_state = {
            **current_game.legal_actions_for(player),
            'pot': current_game.pot,
            'community_cards_objects': current_game.community_cards,
        }
        decision = player.get_action(game_state) or {}
        act = (decision.get('action') or '').strip().lower()
        amount = int(decision.get('amount', 0) or 0)
        _, event = current_game.apply_action(None, act, amount)

        if event in ('invalid_action', 'not_your_turn', 'error'):
            act = 'fold'
            amount = 0
            _, event = current_game.apply_action(None, act, amount)

        _emit_action_event(player, act, all_in=(player.chips == 0 and not player.folded))
        _sync_all_game_player_chips()
        _broadcast_game_state()

        if event == 'game_over':
            _broadcast_hand_over()
            return
    finally:
        _bot_action_pending = False

    _process_automatic_turns()


def _broadcast_game_state():
    if current_game:
        socketio.emit('game_state', current_game.to_dict())


def _send_private_hands():
    if not current_game:
        return
    for player in session_to_player.values():
        _send_private_hand(player)


def _send_private_hand(player):
    if not player.sid or not player.hand:
        return
    socketio.emit('your_hand', {'hand': [card.to_dict() for card in player.hand]}, to=player.sid)


def _notify_current_player():
    if not current_game:
        return
    player = current_game.current_player()
    if player is None or player.sid is None:
        return
    socketio.emit(
        'your_turn',
        {
            **current_game.legal_actions_for(player),
            'big_blind': current_game.big_blind,
            'pot': current_game.pot,
        },
        to=player.sid,
    )


def _broadcast_hand_over():
    if not current_game:
        return
    _sync_all_game_player_chips()
    winners = current_game.get_winners()
    socketio.emit(
        'hand_over',
        {
            'winners': [p.nickname for p in winners],
            'winner_hands': current_game.winner_hand_names(),
            'winner_details': current_game.winner_hand_details(),
            'pot_results': current_game.get_pot_results(),
            'game_state': current_game.to_dict(),
        },
    )
    _finish_game_if_one_player_left()


def _finish_game_if_one_player_left() -> bool:
    if not current_game:
        return False
    survivors = [p for p in current_game.players if p.chips > 0]
    if len(survivors) >= 2:
        return False

    socketio.emit(
        'game_finished',
        {'winner': survivors[0].nickname if survivors else None},
    )
    _end_game_session()
    return True


def _connected_lobby_players():
    return [info for info in _lobby_players() if info['is_connected']]


def _connected_game_players():
    if not current_game:
        return []
    return [
        player
        for player in current_game.players
        if getattr(player, 'is_connected', True) and player.chips > 0
    ]


def _finish_game_if_too_few_connected() -> bool:
    connected_players = _connected_game_players()
    if len(connected_players) >= 2:
        return False

    socketio.emit(
        'game_finished',
        {'winner': connected_players[0].nickname if len(connected_players) == 1 else None},
    )
    _end_game_session()
    return True


def _lobby_snapshot():
    return [
        {
            'nickname': info['nickname'],
            'chips': info['chips'],
            'is_connected': info['is_connected'],
            'is_bot': bool(info.get('is_bot')),
            'personality': info.get('personality'),
        }
        for info in _lobby_players()
    ]


def _broadcast_lobby():
    socketio.emit('lobby_update', _lobby_snapshot())


def _queue_snapshot():
    out = []
    for session_id in join_queue:
        info = session_players.get(session_id)
        if not info:
            continue
        out.append(
            {
                'nickname': info['nickname'],
                'chips': info['chips'],
                'is_connected': info['is_connected'],
            }
        )
    return out


def _broadcast_queue():
    socketio.emit('queue_update', _queue_snapshot())


def _attach_session_to_sid(session_id: str, sid: str):
    info = session_players[session_id]
    old_sid = info.get('sid')
    if old_sid and old_sid != sid:
        sid_to_session.pop(old_sid, None)

    sid_to_session[sid] = session_id
    info['sid'] = sid
    info['is_connected'] = True


def _sync_player_connection(session_id: str):
    player = session_to_player.get(session_id)
    info = session_players.get(session_id)
    if player and info:
        player.sid = info['sid']
        player.is_connected = info['is_connected']


def _sync_all_game_player_chips():
    for session_id, player in session_to_player.items():
        info = session_players.get(session_id)
        if info:
            info['chips'] = player.chips


def _emit_session_state(session_id: str):
    info = session_players.get(session_id)
    if not info or not info.get('sid'):
        return

    payload = {
        'nickname': info['nickname'],
        'chips': info['chips'],
        'reconnected': True,
    }

    if info['state'] == 'queued':
        emit(
            'join_queued',
            {
                **payload,
                'position': _queue_position(session_id),
            },
        )
    else:
        emit('join_success', payload)

    if current_game and session_id in session_to_player:
        player = session_to_player[session_id]
        emit('game_starting', {})
        emit('game_state', current_game.to_dict(for_sid=player.sid))
        _send_private_hand(player)
        if current_game.current_player() is player:
            _notify_current_player()


def _queue_position(session_id: str) -> int:
    try:
        return join_queue.index(session_id) + 1
    except ValueError:
        return 0


def _end_game_session():
    global current_game, session_to_player, game_active, join_queue

    game_active = False
    current_game = None
    session_to_player = {}
    join_queue = []

    for info in session_players.values():
        info['state'] = 'lobby'

    _broadcast_queue()
    _broadcast_lobby()


def _get_local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _request_sid() -> str:
    return str(getattr(request, 'sid', ''))


if __name__ == '__main__':
    bind_host = os.getenv('ROYALTEST_PROTOTYPE_HOST', '0.0.0.0')
    port = int(os.getenv('ROYALTEST_PROTOTYPE_PORT', '5050'))
    debug = os.getenv('ROYALTEST_PROTOTYPE_DEBUG', '0').lower() in {'1', 'true', 'yes', 'on'}
    local_ip = _get_local_ip()
    print()
    print(f'  Prototype host page : http://localhost:{port}/host')
    print(f'  Prototype player URL: http://{local_ip}:{port}/join')
    print()
    socketio.run(app, host=bind_host, port=port, debug=debug)
