from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import settings
from routes import auth, books, members, transactions, dashboard, ai

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Smart Library Management System Backend API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(books.router)
app.include_router(members.router)
app.include_router(transactions.router)
app.include_router(dashboard.router)
app.include_router(ai.router)

@app.get("/", tags=["Health Check"])
def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}
