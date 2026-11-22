"""The cancellation and no-show card: every route of the feature behind one router."""

from fastapi import APIRouter

from b_k06_cancel import router as cancel_router
from b_k06_policy import router as policy_router
from b_k06_sessions import router as sessions_router

router = APIRouter()
for part in (policy_router, cancel_router, sessions_router):
    router.include_router(part)
