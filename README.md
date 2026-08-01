# cena-nonna

Private RSVP portal for Ale's Aug 10-20 2026 dinner near his grandma's.

- Flask + SQLAlchemy (SQLite locally, Postgres on Render)
- Italian UI, friend-verification quiz gate, multi-date select, mystery location page + email capture
- Admin dashboard at `/admin?key=...` with tally + CSV export

Deployed on Render as a Blueprint (see `render.yaml`).
