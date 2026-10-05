from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from catalog.search import SearchIndex, SearchResult

router = APIRouter(tags=["search"])


def get_index(request: Request) -> SearchIndex:
    index: SearchIndex = request.app.state.search_index
    if not index.corpus_path.is_file():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "corpus.db has not been built yet")
    return index


@router.get("/search")
def search(
    index: Annotated[SearchIndex, Depends(get_index)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[SearchResult]:
    return index.search(q, limit)
