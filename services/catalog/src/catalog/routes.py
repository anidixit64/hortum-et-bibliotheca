from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from catalog.search import SearchIndex, SearchResult, TopicLink
from catalog.topics import TopicStore, Tossup, TossupPage

router = APIRouter()


def get_index(request: Request) -> SearchIndex:
    index: SearchIndex = request.app.state.search_index
    if not index.corpus_path.is_file():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "corpus.db has not been built yet")
    return index


def get_topics(request: Request) -> TopicStore:
    store: TopicStore = request.app.state.topic_store
    if not store.corpus_path.is_file():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "corpus.db has not been built yet")
    return store


@router.get("/search", tags=["search"])
def search(
    index: Annotated[SearchIndex, Depends(get_index)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SearchResult]:
    return index.search(q, limit)


class LookupRequest(BaseModel):
    names: list[str] = Field(max_length=300)
    exclude: str | None = None  # the page's own topic


@router.post("/topics/lookup", tags=["topics"])
def lookup(
    index: Annotated[SearchIndex, Depends(get_index)], body: LookupRequest
) -> dict[str, TopicLink]:
    """The names (proper nouns on a page, clue labels) that are topics of their own, so
    the page can link them: {"Battle of Waterloo": {"id": "Q48314", ...}}."""
    return index.lookup(body.names, body.exclude)


@router.get(
    "/topics/{key}",
    tags=["topics"],
    responses={200: {"description": "The topic's page record (see docs/ARCHITECTURE.md)"}},
)
def topic(key: str, store: Annotated[TopicStore, Depends(get_topics)]) -> Response:
    """A topic's ready-made page, by id ("Q1784288") or slug ("invisible-man")."""
    raw = store.snapshot(key)
    if raw is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {key!r}")
    return Response(raw, media_type="application/json")


class Filing(BaseModel):
    topic_id: str
    category: str | None
    subcategory: str | None
    alt_subcategory: str | None
    difficulty: int | None


@router.get("/topics/{key}/filing", tags=["topics"])
def topic_filing(key: str, store: Annotated[TopicStore, Depends(get_topics)]) -> Filing:
    """How a topic's questions are filed, so flashcards can be filtered the same way."""
    found = store.filing(key)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {key!r}")
    return Filing.model_validate(found)


@router.get(
    "/topics/{key}/clues",
    tags=["topics"],
    responses={200: {"description": "Clue records, the same shape as the page's clues"}},
)
def topic_clues(
    key: str,
    store: Annotated[TopicStore, Depends(get_topics)],
    offset: Annotated[int, Query(ge=0)] = 10,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
) -> Response:
    """More of the topic's clues after the page's first ``offset`` (by default the next 5)."""
    records = store.clues(key, offset, limit)
    if records is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {key!r}")
    return Response(f"[{','.join(records)}]", media_type="application/json")


@router.get("/topics/{key}/clue-candidates", tags=["topics"])
def clue_candidates(
    key: str,
    store: Annotated[TopicStore, Depends(get_topics)],
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
) -> dict[str, object]:
    """The topic's top clues with each spelling's questions, for the content service's
    cleanup pass."""
    found = store.clue_candidates(key, limit)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {key!r}")
    return found


@router.get("/topics/{key}/tossups", tags=["topics"])
def topic_tossups(
    key: str,
    store: Annotated[TopicStore, Depends(get_topics)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TossupPage:
    """The topic's questions, newest first."""
    page = store.tossups(key, limit, offset)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {key!r}")
    return page


@router.get("/practice/next", tags=["practice"])
def practice_next(
    store: Annotated[TopicStore, Depends(get_topics)],
    topic: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    difficulty_min: Annotated[int | None, Query(ge=0, le=10)] = None,
    difficulty_max: Annotated[int | None, Query(ge=0, le=10)] = None,
    exclude: Annotated[str, Query(description="Comma-separated question ids already seen")] = "",
) -> Tossup:
    """A random question matching the filters, for buzzer practice."""
    seen = [x for x in exclude.split(",") if x]
    tossup = store.practice(topic, category, subcategory, difficulty_min, difficulty_max, seen)
    if tossup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no question matches")
    return tossup


@router.get("/explore/roulette", tags=["explore"])
def explore_roulette(
    store: Annotated[TopicStore, Depends(get_topics)],
    limit: Annotated[int, Query(ge=1, le=60)] = 32,
) -> list[dict[str, object]]:
    """Random topics from the corpus, for the explore-page roulette."""
    return store.roulette(limit)


@router.get("/explore/top", tags=["explore"])
def explore_top(
    store: Annotated[TopicStore, Depends(get_topics)],
    category: str = Query(min_length=1),
    subcategory: str | None = None,
    alt_subcategory: str | None = None,
    difficulty_min: Annotated[int | None, Query(ge=0, le=10)] = None,
    difficulty_max: Annotated[int | None, Query(ge=0, le=10)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[dict[str, object]]:
    return store.explore_top(
        category, subcategory, alt_subcategory, difficulty_min, difficulty_max, limit
    )


@router.get("/topics/{key}/clues-brief", tags=["explore"])
def clues_brief(
    key: str,
    store: Annotated[TopicStore, Depends(get_topics)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[dict[str, object]]:
    """Top clues for a topic, lightweight: just label and question count."""
    found = store.topic_clues_brief(key, limit)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no topic {key!r}")
    return found


@router.get("/tossups/{tossup_id}", tags=["practice"])
def tossup(tossup_id: str, store: Annotated[TopicStore, Depends(get_topics)]) -> Tossup:
    """One question with its parsed answer line and clue spans, for judging a buzz."""
    found = store.tossup(tossup_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no question {tossup_id!r}")
    return found
