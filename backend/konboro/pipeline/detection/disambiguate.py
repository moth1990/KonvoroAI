"""3.4 (03 §3.4): the disambiguation call, for the symbols the first look left open (`Candidate.needs_decision`):
an unsure rating, a class the library doesn't have, or a box text the dictionary doesn't know.

The model sees the symbol's crop with a 50% margin (the symbol framed in red) and a sheet of 3–5 candidates: the
first look's family's classes, then those of the families a reader confuses with it (`library.CONFUSABLE`). Code
checks the answer: a chosen class must be one of the candidates, or the answer is ignored and the symbol stays as
it was.

- `choose`: the class, `method` = `detector_llm`, confidence = the first look's score × the answer's (03 §6.3).
- `none_of_these`: `unknown_symbol`, status `unknown` (03 §7).
- `not_a_symbol`: dropped (03 §7; kept as a negative example once the learning loop exists, 03 §11).

Only billable symbols go: a busbar, an earth or a load is context, never a quote line (03 §7), and stays as the
first look left it. Past `llm_budget_share` of the page's symbols, no more calls: the rest stay as the first look
left them, and the page gets `llm_budget_exceeded` (03 §8).
"""

import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw

from konboro_llm import ImageInput, LLMClient
from konboro_llm.stages import symbol_disambiguation
from konboro_llm.stages.symbol_disambiguation import DisambiguationAnswer

from .candidates import Candidate
from .config import DetectionConfig
from .library import CONFUSABLE, FAMILIES, UNKNOWN, Library
from .sheets import ImageLoader, png, sheet

_LOOKS = {f.family: f.looks for f in FAMILIES}

Decide = Callable[[Candidate, list[str], Image.Image], DisambiguationAnswer]


def candidate_classes(c: Candidate, library: Library, cfg: DetectionConfig) -> list[str]:
    families = library.families
    out: list[str] = []
    for family in (c.family, *CONFUSABLE.get(c.family, ())):
        for cls in families.get(family, []):
            if cls.symbol_class not in out:
                out.append(cls.symbol_class)
    if c.symbol_class in out:  # the first look's class first
        out.remove(c.symbol_class)
    out.insert(0, c.symbol_class)
    return out[: cfg.max_candidates]


def crop_for(c: Candidate, render: Image.Image, px_per_pt: float, cfg: DetectionConfig) -> Image.Image:
    x0, y0, x1, y1 = (v * px_per_pt for v in c.bbox)
    m = cfg.disambiguation_margin * max(x1 - x0, y1 - y0, 12 * px_per_pt)
    box = (
        max(0, int(x0 - m)),
        max(0, int(y0 - m)),
        min(render.width, math.ceil(x1 + m)),
        min(render.height, math.ceil(y1 + m)),
    )
    out = render.crop(box).convert("RGB")
    ImageDraw.Draw(out).rectangle(
        (x0 - box[0] - 3, y0 - box[1] - 3, x1 - box[0] + 3, y1 - box[1] + 3), outline=(220, 0, 0), width=2
    )
    return out


def model_decider(
    llm: LLMClient, library: Library, load: ImageLoader, legend: str, key: str, tenant_id: str | None
) -> Decide:
    def decide(c: Candidate, classes: list[str], crop: Image.Image) -> DisambiguationAnswer:
        refs = [(r.symbol_class, load(r)) for cls in classes for r in library.references if r.symbol_class == cls]
        seen: dict[str, int] = {}
        picked = []
        for cls, img in refs:  # at most two examples a class
            if seen.get(cls, 0) < 2:
                seen[cls] = seen.get(cls, 0) + 1
                picked.append((cls, img))
        listed = "\n".join(
            f"- {cls}: {library.classes[cls].display_name_he}; {_LOOKS.get(library.classes[cls].family, '')}"
            for cls in classes
        )
        context = [f"The first look took it for {c.symbol_class}, drawn as its {c.role.replace('_', ' ')}."]
        if c.box_text:
            context.append(f'The symbol is a box with the text "{c.box_text}" inside.')
        if legend:
            context.append(f"The drawing's legend says:\n{legend}")
        rounded = tuple(round(v, 1) for v in c.bbox)
        result = symbol_disambiguation.decide(
            llm,
            ImageInput(png(crop), key=f"{key}:symbol:{rounded}"),
            ImageInput(png(sheet(picked, columns=4)), key=f"{library.version}:candidates:{','.join(classes)}"),
            listed,
            "\n".join(context),
            tenant_id,
        )
        return result.data

    return decide


def apply(c: Candidate, answer: DisambiguationAnswer, classes: list[str], library: Library) -> bool:
    """The answer, checked, onto the candidate. False when the symbol is to be dropped."""
    if answer.decision == "not_a_symbol":
        return False
    decision = answer.model_dump()
    if answer.decision == "none_of_these":
        c.symbol_class, c.method, c.class_score = UNKNOWN, "detector_llm", answer.confidence
    elif answer.symbol_class in classes:
        chosen = library.classes[answer.symbol_class]
        c.family, c.symbol_class = chosen.family, chosen.symbol_class
        c.method, c.class_score = "detector_llm", answer.confidence
        c.candidates = [(chosen.symbol_class, answer.confidence)] + [
            (cls, s) for cls, s in c.candidates if cls != chosen.symbol_class
        ]
    else:
        decision["ignored"] = "not among the candidates"  # 03 §3.4: never a class off the list
    c.llm_decision = decision
    c.needs_decision = None
    return True


def resolve(
    found: list[Candidate],
    decide: Decide,
    render: Image.Image,
    px_per_pt: float,
    library: Library,
    cfg: DetectionConfig,
) -> tuple[list[Candidate], int, bool]:
    """Returns (the candidates kept, calls made, whether the budget ran out)."""
    billable = {c.symbol_class: c.billable for c in library.classes.values()}
    open_ = [c for c in found if c.needs_decision and billable.get(c.symbol_class, True)]
    budget = math.floor(cfg.llm_budget_share * len(found))
    todo = sorted(open_, key=lambda c: c.confidence)[:budget]
    jobs = [(c, candidate_classes(c, library, cfg), crop_for(c, render, px_per_pt, cfg)) for c in todo]
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        answers = list(pool.map(lambda j: decide(*j), jobs))
    dropped: set[int] = set()
    for (c, classes, _), answer in zip(jobs, answers, strict=True):
        if not apply(c, answer, classes, library):
            dropped.add(id(c))
    return [c for c in found if id(c) not in dropped], len(jobs), len(open_) > len(todo)
