"""Job sources. Each module exposes NAME, MIN_INTERVAL_HOURS, parse() and fetch(http, companies)."""
from jobhunter.sources import (
    arbeitnow,
    ashby,
    greenhouse,
    himalayas,
    hackernews,
    jobicy,
    landingjobs,
    lever,
    nodesk,
    remoteok,
    remotive,
    weworkremotely,
    workday,
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
        nodesk,
        landingjobs,
        greenhouse,
        ashby,
        lever,
        workday,
    )
}
