# User Service

Your team has been put in charge of a janky web service that handles user accounts. Nobody knows what the contractors who put this thing together were thinking, but it's up to you and your intrepid teammates to turn this rickety thing into a well-oiled machine that generates tons of shareholder value.

## Getting started

One member from each group will mirror this repository privately on github.com (NOT github.sfu.ca) to create the team repository used for grading. If you wish to follow my recommended git process, then each group member will have their own private fork of the team repository from which they can make pull requests. It may help to create a github organization so your team repository isn't tied to any individual group member's account. All copies of the `user_service` repository must be private. **Making this code and your contributions to it publicly available (i.e., by making your repository public, or by making a pull request against a public repository) constitutes academic dishonesty.**

To mirror, create a private empty repository at `https://github.com/<some_id>/user_service`, and then run:
```
$ git clone https://github.sfu.ca/kjamshid/user_service
$ git remote rename origin source
$ git remote add upstream https://github.com/<some_id>/user_service
$ git push -u main upstream
```

The teaching staff will only be looking at the team repository: it suffices to add kjamsh as a collaborator. Please do not add me as a collaborator to your own repositories, only the team repository.

Project instructions will be posted to the issues page of your team repository on an ongoing basis.

To get a live deployment that you can edit follow these steps.

1. Make a `.env` file containing the following, and DO NOT check it into git:

```
POSTGRES_HOST=db
POSTGRES_USER=<some shared username>
POSTGRES_PASSWORD=<some shared password>
```

2. Launch the application by running:

```
$ docker compose watch
```

The service is now running on `localhost:8000/`.
You can visit `localhost:8000/admin`, `localhost:8000/docs`, and `localhost:8000/redoc` in your browser.

If you edit any of the files in this repo, the server restarts to reflect your changes.


3. You can follow the logs by running:
```
$ docker compose logs -f [service_name]
```
`service_name` is optional, if you only want to see logs for a given service (one of `web` or `db`).

* You may run into a ResourceExhausted: failed to copy files: userspace copy failed: write /app/.venv/bin/ruff: no space left on device.

```
$ docker system prune --volumes
```


* You can run tests as follows:
```
$ docker compose exec web pytest
```

## Relevant documentation

[FastAPI User Guide](https://fastapi.tiangolo.com/tutorial/first-steps/) - This is the main library our web service runs on. Note that wherever it says to run, e.g., `fastapi dev main.py`, you should run `docker compose watch` to get a live server.

[SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/quickstart.html) - This is the library we use to access our database (which is PostgreSQL). Use the links in the table of contents to skip to the type of query you want.

[Alembic](https://alembic.sqlalchemy.org/en/latest/) - This tool is used to manage changes to our database schemas. Whenever you want to modify a table's shape in postgres (i.e., add, remove, or change the type of a column), use an alembic migration.

[NiceGUI](https://nicegui.io/) - This is the library used for the frontend in the admin interface.
