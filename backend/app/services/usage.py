"""Missing usage stays unknown, including a sum with only partly available inputs."""

from collections.abc import Iterable

from sqlalchemy import case, func

from app.models import LlmCall


def token_sum(column):
    return case(
        (func.count(column) == func.count(LlmCall.id), func.coalesce(func.sum(column), 0)),
        else_=None,
    )


def sum_known(values: Iterable[int | None]) -> int | None:
    total = 0
    for value in values:
        if value is None:
            return None
        total += value
    return total
