import redis


REDIS_URL = "redis://default:4CV7bRghkO7lnfpPkVTVj3Gt9B5rlX1S@redis-14160.c92.us-east-1-3.ec2.redns.redis-cloud.com:14160"

r = redis.Redis.from_url(REDIS_URL, db=0)

vote_items = r.hgetall("votes")

print(vote_items)


if r.exists("fen"):

        print(r.get("fen"))

# Set the FEN string in Redis
fen_string = "r1bqk2r/1pppbppp/p1n2n2/4p3/B3P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 6"
r.set("fen", fen_string)

print(r.get("fen"))



