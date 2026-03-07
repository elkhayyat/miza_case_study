from fastapi import APIRouter

from app.api.v1.endpoints import analytics, events, health

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(events.router, prefix="/api/v1")
api_router.include_router(analytics.router, prefix="/api/v1")
