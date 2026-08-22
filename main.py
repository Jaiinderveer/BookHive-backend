import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError
from config import settings
from database.mongodb import db_helper
from routes import auth, books, members, transactions, dashboard, ai

# Without this the standard library discards anything below WARNING and prints
# the rest unformatted, which makes a deployed failure very hard to read.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("bookhive")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare the database at startup without making it a condition of starting.

    A MongoDB problem used to stop the process from booting, which meant no CORS
    headers were ever sent and the browser blamed CORS for a database outage.
    Now startup always completes and the failure is logged plainly; requests that
    need the database answer 503 until it is reachable again.
    """
    try:
        db_helper.initialize()
    except PyMongoError:
        logger.exception(
            "MongoDB initialisation failed - starting anyway. Endpoints that need "
            "the database will return 503 until it is reachable. Check MONGODB_URL "
            "and that this deployment's IP is allowed by the database firewall."
        )
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Smart Library Management System Backend API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PyMongoError)
async def database_unavailable_handler(request: Request, exc: PyMongoError):
    """Answer database failures with a clear 503 instead of an opaque crash.

    The response travels back out through CORSMiddleware, so the browser sees a
    real status code rather than a blocked request.
    """
    logger.exception("Database error handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The database is temporarily unavailable. Please try again."},
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
