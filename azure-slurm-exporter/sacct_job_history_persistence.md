## Problem
Right now, when exporter crashes job history is lost. when azslurm restarts job history counter starts at 0 and will only start with job data from 1 hour before ie. starttime = now minus 1 hour, endtime = now. So we will lose all job history data before that.

## Considerations:

**Metric Type**
- Keep sacct metric as a Counter:
    - Pros:
        - Prometheus can handle resets
    - Cons:
        - Need to persist state.

- Make sacct metric into gauge:
    - Pros:
        - Exporter doesnt have to save "totals" Grafana will do the math.
        - easier failover, we just have to export the window of last successful endtime query and now.
    - Cons:
        - if prometheus scrapes every 30s and the interval we are exporting is for 5 min then prometheus will ingest the same data 10 times before the next query so the math will be wrong
            - this can be combatted by exporting once for a time stamp label and then when that time stamp changes then prometheus can collect that again. so we will not export the sacct guage for every scrape only when the query has finished and prometheus has ingested it exactly once.

        - exporter will never show cummulative metric

**Sacct state saving**

- Save initial starttime if save state file doesnt exist
    - Pros:
        - If exporter stops/crashes next time it starts it will take in the initial starttime in the first collection and pull in all the data.
        - No data lost
    - Cons:
        - First collection interval could become very big and then having all that data becomes useless because then it looks like that x amount of jobs finished in a short time frame.

- Save endtime of last successful collection
    - Pros:
        - if exporter stops/crashes next time it starts it will query from last successful endtime to now so no jobs are lost
        - The exporter only needs to catchup to how long the downtime was
        - prometheus can handle counter resets so we don't need full data we just need to make sure no intervals were missed
    - Cons:
        - catchup interval depends on downtime
        - state save file constantly changed

        Edge Case:
        - Lets say last counter was at 100 and then there was a really long downtime and then when exporter resets we do the first collection and lets say 101 jobs finished during the downtime. now prometheus thinks that 1 job finished between the downtime. Job counter always has to be less than the previous job counter for prometheus to detect a rest and calculate accordingly. Since we have a lot of labels the cardinality of the counters are already high so this shouldnt happen often especially since with HA downtime should be minimal.
