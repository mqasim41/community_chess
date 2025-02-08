import threading
import time
import uuid
import requests
import chess
import chess.svg
import redis
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

REDIS_URL = "redis://default:4CV7bRghkO7lnfpPkVTVj3Gt9B5rlX1S@redis-14160.c92.us-east-1-3.ec2.redns.redis-cloud.com:14160"
VOTING_PERIOD = 10800  # 3 hours in seconds
STOCKFISH_API_URL = "https://chess-api.com/v1"
API_PARAMS = {
    "depth": 6,
    "variants": 1,
    "maxThinkingTime": 50
}

# Redis connection helper
def get_redis():
    return redis.Redis.from_url(REDIS_URL, db=0)

# State management helpers
def get_current_fen():
    r = get_redis()
    return r.get("fen").decode('utf-8') or chess.Board().fen()

def get_current_votes():
    r = get_redis()
    return {k.decode(): int(v) for k, v in r.hgetall("votes").items()}

def get_votes_record(round_num):
    r = get_redis()
    return {m.decode() for m in r.smembers(f"votes_record:{round_num}")}

def get_current_round():
    r = get_redis()
    return int(r.get("current_round") or 1)

def get_last_vote_time():
    r = get_redis()
    return float(r.get("last_vote_time") or time.time())

def save_state(fen=None, votes=None, current_round=None, last_vote_time=None):
    r = get_redis()
    pipeline = r.pipeline()
    
    if fen is not None:
        pipeline.set("fen", fen)
    if votes is not None:
        pipeline.delete("votes")
        if votes:
            pipeline.hset("votes", mapping={k: int(v) for k, v in votes.items()})
    if current_round is not None:
        pipeline.set("current_round", current_round)
    if last_vote_time is not None:
        pipeline.set("last_vote_time", last_vote_time)
    
    pipeline.execute()

def initialize_game():
    r = get_redis()
    if not r.exists("fen"):
        board = chess.Board()
        pre_moves = [
            "e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "b1c3", "f8e7"
        ]
        for uci in pre_moves:
            move = chess.Move.from_uci(uci)
            if move in board.legal_moves:
                board.push(move)
        save_state(fen=board.fen(), current_round=1, last_vote_time=time.time())
        print("Initialized new game")

# Initialize game on startup
initialize_game()

def voting_loop():
    while True:
        time.sleep(1)
        
        r = get_redis()
        fen = get_current_fen()
        board = chess.Board(fen)
        
        if board.is_game_over():
            continue

        last_vote_time = get_last_vote_time()
        current_round = get_current_round()
        
        if time.time() - last_vote_time > VOTING_PERIOD:
            votes = get_current_votes()
            
            if votes:
                selected_move_uci = max(votes, key=votes.get)
                move = chess.Move.from_uci(selected_move_uci)
                
                if move in board.legal_moves:
                    board.push(move)
                    print(f"Community move: {selected_move_uci}")
                    save_state(fen=board.fen(), votes={}, current_round=current_round+1)
                    
                    # Bot move
                    if not board.is_game_over():
                        try:
                            response = requests.post(
                                STOCKFISH_API_URL,
                                json={"fen": board.fen(), **API_PARAMS},
                                timeout=5
                            )
                            if response.ok:
                                data = response.json()
                                if data.get("type") == "bestmove":
                                    bot_move = chess.Move.from_uci(data["move"])
                                    if bot_move in board.legal_moves:
                                        board.push(bot_move)
                                        print(f"Bot move: {data['move']}")
                                        save_state(fen=board.fen())
                        except Exception as e:
                            print(f"Bot error: {str(e)}")
            else:
                print("No votes - resetting timer")
                save_state(last_vote_time=time.time(), current_round=current_round+1, votes={})

# Start voting thread
threading.Thread(target=voting_loop, daemon=True).start()

@app.route("/")
def index():
    fen = get_current_fen()
    board = chess.Board(fen)
    votes = get_current_votes()
    current_round = get_current_round()
    last_vote_time = get_last_vote_time()
    
    time_elapsed = time.time() - last_vote_time
    time_left = max(0, int(VOTING_PERIOD - time_elapsed))
    
    return render_template(
        "index.html",
        board_svg=chess.svg.board(board=board),
        legal_moves=[{"uci": move.uci(), "san": board.san(move)} for move in board.legal_moves],
        votes=votes,
        time_left=time_left,
        voting_duration=VOTING_PERIOD,
        time_left_formatted=f"{time_left // 3600}h {(time_left % 3600) // 60}m",
        game_over=board.is_game_over()
    )

@app.route("/vote", methods=["POST"])
def vote():
    # Get visitor ID
    if "visitor_id" not in session:
        session["visitor_id"] = str(uuid.uuid4())
    visitor_id = session["visitor_id"]

    # Get current state
    current_round = get_current_round()
    board = chess.Board(get_current_fen())
    
    # Validate request
    data = request.get_json()
    if not data or "move" not in data:
        return jsonify({"success": False, "message": "No move provided"})
    
    move_uci = data["move"]
    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        return jsonify({"success": False, "message": "Invalid move format"})
    
    # Validate move legality
    if move not in board.legal_moves:
        return jsonify({"success": False, "message": "Illegal move"})
    
    # Check existing votes
    r = get_redis()
    if r.sismember(f"votes_record:{current_round}", visitor_id):
        return jsonify({"success": False, "message": "Already voted this round"})
    
    # Record vote
    pipeline = r.pipeline()
    pipeline.hincrby("votes", move_uci, 1)
    pipeline.sadd(f"votes_record:{current_round}", visitor_id)
    pipeline.execute()
    
    return jsonify({"success": True, "votes": get_current_votes().get(move_uci, 0) + 1})

@app.route("/state")
def state():
    fen = get_current_fen()
    board = chess.Board(fen)
    votes = get_current_votes()
    last_vote_time = get_last_vote_time()
    
    time_elapsed = time.time() - last_vote_time
    remaining_time = max(0, int(VOTING_PERIOD - time_elapsed))
    
    return jsonify({
        "board_svg": chess.svg.board(board=board),
        "legal_moves": [{"uci": move.uci(), "san": board.san(move)} for move in board.legal_moves],
        "votes": votes,
        "time_left": remaining_time,
        "formatted_time_left": f"{remaining_time // 3600}h {(remaining_time % 3600) // 60}m",
        "voting_duration": VOTING_PERIOD,
        "game_over": board.is_game_over()
    })

if __name__ == "__main__":
    app.run(debug=True)