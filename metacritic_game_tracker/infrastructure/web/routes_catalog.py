"""US1-3 catalog endpoints (contracts/web-ui.md) — no auth."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


async def get_catalog_use_case():
    """Marker dependency — no default implementation.

    `infrastructure` cannot import `application` (tach.toml), so the real
    `CatalogUseCase` is wired here via `app.dependency_overrides` by the
    composition root (`main.py`), the same mechanism the contract tests use.
    """
    raise RuntimeError(
        "get_catalog_use_case has no default implementation — "
        "wire it via app.dependency_overrides in main.py"
    )


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    return request.app.state.templates.TemplateResponse(request, "index.html", {})


@router.get("/games", response_class=HTMLResponse)
async def list_games(
    request: Request,
    platform: str | None = None,
    q: str | None = None,
    sort: str | None = "rating",
    page: int = Query(default=1, ge=1),
    use_case=Depends(get_catalog_use_case),
):
    paginated = await use_case.list_games(platform=platform, q=q, sort=sort, page=page, page_size=20)
    platforms = await use_case.list_platforms()
    return request.app.state.templates.TemplateResponse(
        request,
        "list.html",
        {
            "games": paginated.games,
            "paginated": paginated,
            "platforms": platforms,
            "platform": platform,
            "q": q,
            "sort": sort,
        },
    )


@router.get("/games/{slug}", response_class=HTMLResponse)
async def game_detail(request: Request, slug: str, use_case=Depends(get_catalog_use_case)):
    detail = await use_case.get_game_detail(slug)
    if detail is None:
        raise HTTPException(status_code=404, detail="Game not found")
    return request.app.state.templates.TemplateResponse(
        request, "game_card.html", {"game": detail.game, "similar_games": detail.similar_games}
    )
