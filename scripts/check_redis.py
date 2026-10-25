"""Pre-push hook: verify Redis is reachable before running integration tests."""

from __future__ import annotations

from redis import Redis
from redis.exceptions import RedisError


def check_redis_is_up() -> None:
    try:
        Redis(socket_connect_timeout=1).ping()
    except RedisError as err:
        print(
            r"  /\_/\  "
            "\n"
            r" ( >.< ) "
            "\n"
            r"  /| |\ "
            "\n"
            r" (_| |_)/"
            "\n"
        )
        print(
            "!!! ERROR: Redis must be running for integration tests !!!\nStart it with: docker compose up -d redis\n",
        )
        raise AssertionError(
            "!!! ERROR: Redis must be running for integration tests !!!\nStart it with: docker compose up -d redis\n",
        ) from err


if __name__ == "__main__":
    check_redis_is_up()
