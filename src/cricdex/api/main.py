from fastapi import FastAPI

from cricdex import __version__

app = FastAPI(title="CricDex API", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
