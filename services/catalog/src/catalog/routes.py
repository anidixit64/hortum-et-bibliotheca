from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from catalog.search import SearchIndex, SearchResult
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
    difficulty_min: Annotated[int | None, Query(ge=0, le=10)] = None,
    difficulty_max: Annotated[int | None, Query(ge=0, le=10)] = None,
    exclude: Annotated[str, Query(description="Comma-separated question ids already seen")] = "",
) -> Tossup:
    """A random question matching the filters, for buzzer practice."""
    seen = [x for x in exclude.split(",") if x]
    tossup = store.practice(topic, category, difficulty_min, difficulty_max, seen)
    if tossup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no question matches")
    return tossup


@router.get("/tossups/{tossup_id}", tags=["practice"])
def tossup(tossup_id: str, store: Annotated[TopicStore, Depends(get_topics)]) -> Tossup:
    """One question with its parsed answer line and clue spans, for judging a buzz."""
    found = store.tossup(tossup_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no question {tossup_id!r}")
    return found
