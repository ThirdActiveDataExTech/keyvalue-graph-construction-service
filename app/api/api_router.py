from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from app.api.routers import keyvalue_graph, workflow
from app.dependencies import get_token_header

api_router = APIRouter(dependencies=[Depends(get_token_header)], default_response_class=JSONResponse)

api_router.include_router(keyvalue_graph.router)
api_router.include_router(workflow.router)
