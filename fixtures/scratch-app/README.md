# scratch-app (Governor Q1 fixture)

Minimal FastAPI + Postgres app used by `scripts/verify.py`. Postgres in production via
`DATABASE_URL`; tests run on SQLite so verify needs no database server.
`deploy.sh` is a stand-in that only writes a `DEPLOYED` marker.
