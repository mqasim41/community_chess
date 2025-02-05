import threading
import time
import uuid
import requests  # Added for API calls
from collections import defaultdict

from flask import Flask, render_template, request, jsonify, session
import chess
import chess.svg

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Replace with a strong secret key

# Global game state: a single chess game.
game = chess.Board()

# Pre-play move 1. e4
move_e4 = chess.Move.from_uci("e2e4")
if move_e4 in game.legal_moves:
    game.push(move_e4)
    print("Pre-played move: e2e4")
else:
    print("Error: e2e4 is not legal on the initial board.")

# Pre-play move 1... e5
move_e5 = chess.Move.from_uci("e7e5")
if move_e5 in game.legal_moves:
    game.push(move_e5)
    print("Pre-played move: e7e5")
else:
    print("Error: e7e5 is not legal on the board after e4.")

# Pre-play move 2. Nf3
move_Nf3 = chess.Move.from_uci("g1f3")
if move_Nf3 in game.legal_moves:
    game.push(move_Nf3)
    print("Pre-played move: Nf3")
else:
    print("Error: Nf3 is not legal on the board after e4 e5.")

# Pre-play move 2... Nc6
move_Nc6 = chess.Move.from_uci("b8c6")
if move_Nc6 in game.legal_moves:
    game.push(move_Nc6)
    print("Pre-played move: Nc6")
else:
    print("Error: Nc6 is not legal on the board after e4, e5, Nf3.")

# Pre-play move 2. Bb5
move_Nf3 = chess.Move.from_uci("f1b5")
if move_Nf3 in game.legal_moves:
    game.push(move_Nf3)
    print("Pre-played move: Bf5")
else:
    print("Error: Bf5 is not legal.")

# Pre-play move 2... Nc6
move_Nc6 = chess.Move.from_uci("a7a6")
if move_Nc6 in game.legal_moves:
    game.push(move_Nc6)
    print("Pre-played move: a6")
else:
    print("Error: a6 is not legal.")

# Global dictionary to store votes for each legal move (keyed by UCI string)
votes = defaultdict(int)

# Global dictionary to record which visitor (by ID) has voted in each round.
# Keys are round numbers, values are sets of visitor IDs.
votes_record = {}

# Voting period in seconds (3 hours)
VOTING_PERIOD = 10800  # 10,800 seconds = 3 hours

# Last vote timestamp
last_vote_time = time.time()

# Global round counter: increments each time a community move is executed.
current_round = 1

STOCKFISH_API_URL = "https://chess-api.com/v1"
API_PARAMS = {
    "depth": 6,         # Max supported depth for free tier
    "variants": 1,      # Number of lines to analyze
    "maxThinkingTime": 50  # Milliseconds
}

def format_duration(seconds):
    """
    Convert a duration in seconds to a formatted string showing hours and minutes.
    For example, 3665 seconds becomes "1h 1m".
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"

def get_bot_move():
    """Get best move from Chess-API.com"""
    try:
        response = requests.post(
            STOCKFISH_API_URL,
            json={
                "fen": game.fen(),
                **API_PARAMS
            },
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("type") == "bestmove":
                return data["move"]
        return None
    
    except Exception as e:
        print(f"API Error: {str(e)}")
        return None

def voting_loop():
    """
    Background thread to check if the voting period has expired.
    When expired, if there are any votes, it applies the move with the most votes.
    If no votes were cast, it resets the timer with no changes.
    If a community move is made, the bot then makes a move.
    """
    global votes, last_vote_time, game, current_round, votes_record

    while True:
        time.sleep(1)
        if game.is_game_over():
            continue  # Game finished, do nothing

        # Check if the voting period has expired
        if time.time() - last_vote_time > VOTING_PERIOD:
            if votes:
                # Determine the move with the most votes (using UCI key)
                selected_move_uci = max(votes, key=votes.get)
                selected_move = chess.Move.from_uci(selected_move_uci)

                # Verify the move is still legal
                if selected_move in game.legal_moves:
                    print(f"Community-selected move: {selected_move_uci} with {votes[selected_move_uci]} votes. ({game.san(selected_move)})")
                    game.push(selected_move)
                else:
                    print("Selected move is no longer legal. Skipping.")

                # Let the bot make a move if the game is not over
                if not game.is_game_over():
                    bot_move_uci = get_bot_move()
                    if bot_move_uci:
                        bot_move = chess.Move.from_uci(bot_move_uci)
                        if bot_move in game.legal_moves:
                            print(f"Bot moves: {bot_move_uci} ({game.san(bot_move)})")
                            game.push(bot_move)
                        else:
                            print("Invalid bot move received from API")
                    else:
                        print("Bot could not determine a move.")
            else:
                print("Voting period expired with no votes. Resetting timer with no changes.")

            # Reset votes and timer for next move
            votes = defaultdict(int)
            last_vote_time = time.time()

            # Increment the round counter
            current_round += 1
            votes_record[current_round] = set()

# Start the background voting thread
threading.Thread(target=voting_loop, daemon=True).start()

@app.route("/")
def index():
    """Main page that shows the board and current voting options."""
    board_svg = chess.svg.board(board=game)
    legal_moves = [
        {"uci": move.uci(), "san": game.san(move)}
        for move in game.legal_moves
    ]
    # Calculate remaining time in the current round
    time_elapsed = time.time() - last_vote_time
    time_left = max(0, int(VOTING_PERIOD - time_elapsed))
    time_left_formatted = format_duration(time_left)
    return render_template(
        "index.html",
        board_svg=board_svg,
        legal_moves=legal_moves,
        votes=dict(votes),
        time_left=time_left,  # raw seconds
        voting_duration=VOTING_PERIOD,  # total duration for progress bar calculation
        time_left_formatted=time_left_formatted,  # formatted time string
        game_over=game.is_game_over()
    )

@app.route("/vote", methods=["POST"])
def vote():
    """Endpoint to accept a vote from a visitor.
    Each visitor is allowed only one vote per round.
    """
    global votes, last_vote_time, current_round, votes_record

    # Generate a unique visitor ID if one doesn't exist
    if "visitor_id" not in session:
        session["visitor_id"] = str(uuid.uuid4())
    visitor_id = session["visitor_id"]

    # Ensure we have an entry for the current round
    if current_round not in votes_record:
        votes_record[current_round] = set()

    data = request.get_json()
    move_uci = data.get("move") if data else None
    if move_uci is None:
        return jsonify({"success": False, "message": "No move provided."})

    # Check if this visitor has already voted in the current round
    if visitor_id in votes_record[current_round]:
        return jsonify({"success": False, "message": "You have already voted this round."})

    # Ensure the move is legal
    move = chess.Move.from_uci(move_uci)
    if move not in game.legal_moves:
        return jsonify({"success": False, "message": "Illegal move."})

    votes[move_uci] += 1
    votes_record[current_round].add(visitor_id)

    return jsonify({"success": True, "votes": votes[move_uci]})

@app.route("/state")
def state():
    """Endpoint for AJAX polling: returns the current board SVG, vote tallies, and timer."""
    board_svg = chess.svg.board(board=game)
    legal_moves = [
        {"uci": move.uci(), "san": game.san(move)}
        for move in game.legal_moves
    ]
    time_elapsed = time.time() - last_vote_time
    remaining_time = max(0, int(VOTING_PERIOD - time_elapsed))
    formatted_time_left = format_duration(remaining_time)
    return jsonify({
        "board_svg": board_svg,
        "legal_moves": legal_moves,
        "votes": votes,
        "time_left": remaining_time,  # raw seconds
        "formatted_time_left": formatted_time_left,  # e.g., "2h 45m"
        "voting_duration": VOTING_PERIOD,  # total duration (3 hours)
        "game_over": game.is_game_over()
    })

if __name__ == "__main__":
    app.run(debug=True)
