"""Job sources. Each module exposes NAME, MIN_INTERVAL_HOURS, parse() and fetch(http, companies)."""
from jobhunter.sources import (
    arbeitnow,
    ashby,
    greenhouse,
    himalayas,
    hackernews,
    jobicy,
    remoteok,
    remotive,
    weworkremotely,
)

SOURCES = {
    module.NAME: module
    for module in (
        remoteok,
        remotive,
        himalayas,
        jobicy,
        arbeitnow,
        weworkremotely,
        hackernews,
        greenhouse,
        ashby,
    )
}
