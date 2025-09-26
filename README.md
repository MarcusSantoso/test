# User Service

Your team has been put in charge of a janky web service that handles user accounts. Nobody knows what the contractors who put this thing together were thinking, but it's up to you and your intrepid teammates to turn this rickety thing into a well-oiled machine that generates tons of shareholder value.

## Getting started

One member from each team will mirror this repository privately on github.com (NOT github.sfu.ca). Each team will have a team repository, and each team member will have their own fork of the team repository. It may help to create a github organization for your team.

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
