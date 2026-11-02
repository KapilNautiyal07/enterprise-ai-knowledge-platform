from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as document_router
from app.api.search import router as search_router
from app.api.ask import router as ask_router


app = FastAPI(
    title="Enterprise AI Knowledge Platform",
    description="AI Enterprise Knowledge & Decision Intelligence Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(document_router)

app.include_router(search_router)

app.include_router(ask_router)

@app.get("/")
def root():
    return {
        "application": "Enterprise AI Knowledge Platform",
        "status": "running",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }       
