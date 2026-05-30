from fastapi import FastAPI

from routers import players, roster, schedule, standings

app = FastAPI(title="NHL Stats API")

app.include_router(schedule.router, prefix="/schedule", tags=["schedule"])
app.include_router(standings.router, prefix="/standings", tags=["standings"])
app.include_router(roster.router, prefix="/roster", tags=["roster"])
app.include_router(players.router, prefix="/players", tags=["players"])


@app.get("/health")
def health():
    return {"status": "ok"}
