import subprocess
import redis
import threading
import uuid
import functools



def cache_connection(db_connector):
    cached_connections = {}
    @functools.wraps(db_connector)
    def wrapper(*args, **kwargs):
        cache_key = (db_connector.__name__, args, frozenset(kwargs.items()))
        if redis_instance := cached_connections.get(cache_key):
            return redis_instance
        cached_connections[cache_key] = db_connector(*args, **kwargs)
        return cached_connections[cache_key]
    return wrapper

    
@cache_connection
def access_redis(host="localhost", port=6379, decode_responses=True) -> redis.Redis:
    print("connecting to redis")
    return redis.Redis(host=host, port=port, decode_responses=decode_responses)


def stream_logs(proc):
    redis_instance = access_redis()
    for line in iter(proc.stdout.readline, ""):
        redis_instance.xadd(key_logs, {"msg": line.strip()})
    proc.wait()
    exit_code = proc.returncode
    redis_instance.hset(key_status, mapping={"status": "finished", "exit_code": exit_code})