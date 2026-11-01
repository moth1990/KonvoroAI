"""A metric value that can be added up across panels, drawings and input kinds without losing its weight."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

Kind = Literal["ratio", "count", "mean"]

# Every other metric is better when higher.
LOWER_IS_BETTER = frozenset(
    {"missed_process_pages", "backtest_deviation", "confirmation_rate", "duplicates_left", "llm_share"}
)


class Score(BaseModel):
    """`ratio`: num of den were right. `count`: num things went wrong out of den chances. `mean`: num is a sum over
    den drawings. den = 0 means nothing to score (n/a), never 0%."""

    model_config = ConfigDict(frozen=True)

    num: float
    den: int
    kind: Kind = "ratio"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value(self) -> float | None:
        if self.den == 0:
            return None
        return round(self.num if self.kind == "count" else self.num / self.den, 6)

    def __add__(self, other: "Score") -> "Score":
        if self.kind != other.kind:
            raise ValueError(f"cannot add a {self.kind} to a {other.kind}")
        return Score(num=self.num + other.num, den=self.den + other.den, kind=self.kind)

    @classmethod
    def of(cls, ok: bool) -> "Score":
        return cls(num=1 if ok else 0, den=1)

    @classmethod
    def na(cls, kind: Kind = "ratio") -> "Score":
        return cls(num=0, den=0, kind=kind)


Scores = dict[str, Score]


def total(many: list[Scores]) -> Scores:
    """The micro total: numerators and denominators added, so a big drawing weighs more than a small one."""
    out: Scores = {}
    for scores in many:
        for name, score in scores.items():
            out[name] = out[name] + score if name in out else score
    return out
