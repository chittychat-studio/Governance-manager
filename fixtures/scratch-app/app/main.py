from fastapi import FastAPI, HTTPException

from app.db import Base, SessionLocal, engine
from app.models import User

Base.metadata.create_all(bind=engine)
app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/users/{user_id}")
def get_user(user_id: int):
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404)
        return {"id": user.id, "name": user.name}
