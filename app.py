from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

room_players = db.Table('room_players',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('room_id', db.Integer, db.ForeignKey('room.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    role = db.Column(db.String(50), default='player') # 'admin', 'gamemaker', 'player'

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    game = db.Column(db.String(50))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    players = db.relationship('User', secondary=room_players, lazy='subquery',
                            backref=db.backref('rooms_joined', lazy=True))
    default_buyin = db.Column(db.Integer, default=400)
    chip_ratio = db.Column(db.Float, default=0.5)
    circulating_chips = db.Column(db.Integer, default=0)
    game_phase = db.Column(db.String(50), default='playing') # playing, counting
    dealer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class PlayerState(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), primary_key=True)
    buy_in_amount = db.Column(db.Integer, default=0)
    chips = db.Column(db.Integer, default=0)
    bet_amount = db.Column(db.Integer, default=10)

class BlackjackHand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'))
    hand_number = db.Column(db.Integer, default=1)
    result = db.Column(db.String(50)) # e.g., 'win', 'lose', 'push', 'blackjack', 'double'

class PlayerResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'))
    final_chip_count = db.Column(db.Integer)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('lobby'))
        flash('Please check your login details and try again.')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username already exists')
            return redirect(url_for('signup'))
        new_user = User(username=username, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/lobby')
@login_required
def lobby():
    rooms = Room.query.all()
    return render_template('lobby.html', rooms=rooms)

@app.route('/create_room', methods=['GET', 'POST'])
@login_required
def create_room():
    if request.method == 'POST':
        room_name = request.form.get('room_name')
        game = request.form.get('game')
        if game == 'poker':
            default_buyin = request.form.get('default_buyin')
            chip_ratio = request.form.get('chip_ratio')
            new_room = Room(name=room_name, game=game, created_by=current_user.id,
                            default_buyin=int(default_buyin), chip_ratio=float(chip_ratio))
        else:
            new_room = Room(name=room_name, game=game, created_by=current_user.id)

        db.session.add(new_room)
        db.session.commit()
        return redirect(url_for('lobby'))
    return render_template('create_room.html')

@app.route('/room/<int:room_id>')
@login_required
def room(room_id):
    room = Room.query.get_or_404(room_id)
    player_state = None
    show_buy_in_modal = False

    if room.game == 'poker':
        player_state = PlayerState.query.filter_by(user_id=current_user.id, room_id=room.id).first()
        if not player_state:
            show_buy_in_modal = True

    player_states = PlayerState.query.filter_by(room_id=room.id).all()

    # Map player IDs to their states for easy lookup in the template
    player_states_map = {ps.user_id: ps for ps in player_states}

    results = []
    all_results_in = False
    if room.game_phase == 'counting':
        results = PlayerResult.query.filter_by(room_id=room.id).all()
        if len(results) == len(room.players):
            all_results_in = True

    hands = {}
    if room.game == 'blackjack':
        all_hands = BlackjackHand.query.filter_by(room_id=room.id).all()
        for hand in all_hands:
            if hand.player_id not in hands:
                hands[hand.player_id] = []
            hands[hand.player_id].append(hand)

    return render_template('room.html', room=room, show_buy_in_modal=show_buy_in_modal, player_states_map=player_states_map, results=results, all_results_in=all_results_in, hands=hands)

@app.route('/join_room/<int:room_id>')
@login_required
def join_room(room_id):
    room = Room.query.get_or_404(room_id)
    if current_user not in room.players:
        room.players.append(current_user)
        # For blackjack, create a default player state immediately
        if room.game == 'blackjack':
            player_state = PlayerState.query.filter_by(user_id=current_user.id, room_id=room.id).first()
            if not player_state:
                new_player_state = PlayerState(user_id=current_user.id, room_id=room.id)
                db.session.add(new_player_state)
        db.session.commit()
    return redirect(url_for('room', room_id=room.id))

@app.route('/buy_in/<int:room_id>', methods=['POST'])
@login_required
def buy_in(room_id):
    room = Room.query.get_or_404(room_id)
    if room.game == 'poker':
        buy_in_amount = int(request.form.get('buy_in_amount'))

        # Create a new player state
        new_player_state = PlayerState(
            user_id=current_user.id,
            room_id=room.id,
            buy_in_amount=buy_in_amount,
            chips=buy_in_amount
        )
        db.session.add(new_player_state)

        # Update circulating chips
        room.circulating_chips += buy_in_amount
        db.session.commit()

    return redirect(url_for('room', room_id=room.id))

@app.route('/rebuy/<int:room_id>', methods=['POST'])
@login_required
def rebuy(room_id):
    room = Room.query.get_or_404(room_id)
    if room.game == 'poker':
        rebuy_amount = int(request.form.get('rebuy_amount'))
        player_state = PlayerState.query.filter_by(user_id=current_user.id, room_id=room.id).first()

        if player_state:
            player_state.chips += rebuy_amount
            player_state.buy_in_amount += rebuy_amount
            room.circulating_chips += rebuy_amount
            db.session.commit()

    return redirect(url_for('room', room_id=room.id))

@app.route('/transfer_chips/<int:room_id>', methods=['POST'])
@login_required
def transfer_chips(room_id):
    room = Room.query.get_or_404(room_id)
    if room.game == 'poker':
        transfer_amount = int(request.form.get('transfer_amount'))
        to_player_id = int(request.form.get('to_player_id'))

        from_player_state = PlayerState.query.filter_by(user_id=current_user.id, room_id=room.id).first()
        to_player_state = PlayerState.query.filter_by(user_id=to_player_id, room_id=room.id).first()

        if from_player_state and to_player_state and from_player_state.chips >= transfer_amount:
            from_player_state.chips -= transfer_amount
            from_player_state.buy_in_amount -= transfer_amount # This is the key part of the request

            to_player_state.chips += transfer_amount
            to_player_state.buy_in_amount += transfer_amount

            db.session.commit()

    return redirect(url_for('room', room_id=room.id))

@app.route('/end_game/<int:room_id>', methods=['POST'])
@login_required
def end_game(room_id):
    room = Room.query.get_or_404(room_id)
    if current_user.id == room.created_by:
        room.game_phase = 'counting'
        db.session.commit()
    return redirect(url_for('room', room_id=room.id))

@app.route('/submit_chip_count/<int:room_id>', methods=['POST'])
@login_required
def submit_chip_count(room_id):
    room = Room.query.get_or_404(room_id)
    if room.game == 'poker' and room.game_phase == 'counting':
        final_chip_count = int(request.form.get('final_chip_count'))

        # Check if a result already exists
        existing_result = PlayerResult.query.filter_by(user_id=current_user.id, room_id=room.id).first()
        if not existing_result:
            new_result = PlayerResult(
                user_id=current_user.id,
                room_id=room.id,
                final_chip_count=final_chip_count
            )
            db.session.add(new_result)
            db.session.commit()

    return redirect(url_for('room', room_id=room.id))

@app.route('/set_dealer/<int:room_id>', methods=['POST'])
@login_required
def set_dealer(room_id):
    room = Room.query.get_or_404(room_id)
    if current_user.id == room.created_by and room.game == 'blackjack':
        dealer_id = int(request.form.get('dealer_id'))
        room.dealer_id = dealer_id
        db.session.commit()
    return redirect(url_for('room', room_id=room.id))

@app.route('/update_bet/<int:room_id>', methods=['POST'])
@login_required
def update_bet(room_id):
    room = Room.query.get_or_404(room_id)
    if room.game == 'blackjack':
        new_bet_amount = int(request.form.get('new_bet_amount'))
        player_state = PlayerState.query.filter_by(user_id=current_user.id, room_id=room.id).first()
        if player_state:
            player_state.bet_amount = new_bet_amount
            db.session.commit()
    return redirect(url_for('room', room_id=room.id))

@app.route('/log_hand_result/<int:room_id>/<int:player_id>', methods=['POST'])
@login_required
def log_hand_result(room_id, player_id):
    room = Room.query.get_or_404(room_id)
    if current_user.id == room.dealer_id and room.game == 'blackjack':
        result = request.form.get('result')

        # For now, we assume one hand per player. Splitting will add more.
        hand = BlackjackHand.query.filter_by(room_id=room.id, player_id=player_id).first()
        if not hand:
            hand = BlackjackHand(room_id=room.id, player_id=player_id, hand_number=1)
            db.session.add(hand)

        hand.result = result
        db.session.commit()

    return redirect(url_for('room', room_id=room.id))

@app.route('/split_hand/<int:room_id>/<int:player_id>', methods=['POST'])
@login_required
def split_hand(room_id, player_id):
    room = Room.query.get_or_404(room_id)
    if current_user.id == room.dealer_id and room.game == 'blackjack':
        # Find the highest hand number for this player and add one
        last_hand = BlackjackHand.query.filter_by(room_id=room.id, player_id=player_id).order_by(BlackjackHand.hand_number.desc()).first()
        new_hand_number = (last_hand.hand_number + 1) if last_hand else 1

        new_hand = BlackjackHand(room_id=room.id, player_id=player_id, hand_number=new_hand_number)
        db.session.add(new_hand)
        db.session.commit()

    return redirect(url_for('room', room_id=room.id))

@app.route('/')
def index():
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
