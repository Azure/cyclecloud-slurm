#!/usr/bin/env bash
set -e

if [ "$1" == "" ]; then
    echo "Usage: $0 [scheduler|execute|login]"
    exit 1
fi

role=$1
monitoring_enabled=$(/opt/cycle/jetpack/bin/jetpack config cyclecloud.monitoring.enabled False)

reload_prom_config(){
    # Find the Prometheus process and send SIGHUP to reload config or log a warning if not found
    if [[ "$monitoring_enabled" == "False" ]]; then
        echo "Monitoring is disabled, skipping Prometheus config reload"
        return 0
    fi
    PROM_PID=$(pgrep -f 'prometheus')
    if [ -n "$PROM_PID" ]; then
        echo "Sending SIGHUP to Prometheus (PID $PROM_PID) to reload configuration"
        kill -HUP $PROM_PID
    else
        echo "Prometheus process not found, unable to reload configuration"
    fi  
}
# all nodes need to have munge running
echo restarting munge...
systemctl restart munge
# wait up to 60 seconds for munge to start
iters=60
while [ $iters -ge 0 ]; do
    echo test | munge > /dev/null 2>&1
    if [ $? == 0 ]; then
        break
    fi
    sleep 1
    iters=$(( $iters - 1 ))
done

# login nodes explicitly should _not_ have slurmd running.
if [ $role == "login" ]; then
    reload_prom_config
    exit 0
fi

# execute nodes just need slurmd
if [ $role == "execute" ]; then
    systemctl start slurmd
    reload_prom_config
    exit 0
fi

# sanity check - make sure a valid role was actually passed in.
# note they are defined in the slurm_*_role.rb
if [ $role != "scheduler" ]; then
    echo  unknown role! $role 1>&2
    exit 2
fi

# lastly - the scheduler

systemctl show slurmdbd 2>&1 > /dev/null && systemctl start slurmdbd
# there is no obvious way to check slurmdbd status _before_ starting slurmctld
sleep 10
systemctl start slurmctld
attempts=3
delay=5
set +e
for i in $( seq 1 $attempts ); do
    echo $i/$attempts sleeping $delay seconds before running scontrol ping
    sleep $delay
    scontrol ping
    if [ $? == 0 ]; then
        systemctl start slurmctld || exit 1
        break
    fi;
done
if [ $i == $attempts ] && [ $? != 0 ]; then
    echo FATAL: slurmctld failed to start! 1>&2
    echo Here are the last 100 lines of slurmctld.log
    tail -n 100 /var/log/slurmctld/slurmctld.log 1>&2
    exit 2
fi

run_slurm_exporter() {
    # Run Slurm Exporter in a container
    if [[ "$role" != "scheduler" ]]; then
        echo "Slurm Exporter can only be run on the scheduler node, skipping setup."
        return 0
    fi

    primary_scheduler=$(/opt/cycle/jetpack/bin/jetpack config slurm.is_primary_scheduler True)
    if [[ "$primary_scheduler" != "True" ]]; then
        echo "This is not the primary scheduler, skipping slurm_exporter setup."
        return 0
    fi
    
    SLURM_EXPORTER_PORT=9200
    SLURM_EXPORTER_IMAGE_NAME="ghcr.io/slinkyproject/slurm-exporter:0.3.0"
    # Try to get the token, retry up to 3 times
    unset SLURM_JWT
    for attempt in 1 2 3; do
        export $(scontrol token username="slurmrestd" lifespan=infinite)
        if [ -n "$SLURM_JWT" ]; then
            break
        fi
        echo "Attempt $attempt: Failed to get SLURM_JWT token, retrying in 5 seconds..."
        scontrol reconfigure
        sleep 5
    done

    if [ -z "$SLURM_JWT" ]; then
        echo "Failed to get SLURM_JWT token after 3 attempts."
        echo "Check slurmctld status, slurm.conf JWT configuration, and logs for errors."
        /opt/cycle/jetpack/bin/jetpack log "Failed to get SLURM_JWT token after 3 attempts, disabling slurm_exporter setup." --level=warn --priority=medium
        return 0
    fi
    # Check if the container is already running, and if so, stop it
    if [ "$(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)" ]; then
        echo "Slurm Exporter is already running, stopping it..."
        docker stop $(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)
    fi

    # Run the Slurm Exporter container, expose the port so prometheus can scrape it. Redirect the host.docker.internal to the host gateway == localhost
    docker run -v /var:/var -e SLURM_JWT=${SLURM_JWT} -d --restart always -p ${SLURM_EXPORTER_PORT}:8080 --add-host=host.docker.internal:host-gateway $SLURM_EXPORTER_IMAGE_NAME -server http://host.docker.internal:6820 -cache-freq 10s

    # Check if the container is running
    if [ "$(docker ps -q -f ancestor=$SLURM_EXPORTER_IMAGE_NAME)" ]; then
        echo "Slurm Exporter is running"
    else
        echo "Slurm Exporter is not running"
        /opt/cycle/jetpack/bin/jetpack log "Slurm Exporter container failed to start" --level=warn --priority=medium
        return 0 # do not fail the slurm startup if exporter fails
    fi

    reload_prom_config
        
    sleep 20
    if curl -s http://localhost:${SLURM_EXPORTER_PORT}/metrics | grep -q "slurm_nodes_total"; then
        echo "Slurm Exporter metrics are available"
    else
        echo "Slurm Exporter metrics are not available"
        /opt/cycle/jetpack/bin/jetpack log "Slurm Exporter metrics are not available" --level=warn --priority=medium
    fi 
}

# start slurmrestd
sleep 10
systemctl start slurmrestd
systemctl status slurmrestd --no-pager > /dev/null
if [ $? != 0 ]; then
    echo Warning: slurmrestd failed to start! 1>&2
    /opt/cycle/jetpack/bin/jetpack log "slurmrestd failed to start" --level=warn --priority=medium
    exit 0
fi
# start slurm_exporter if monitoring is enabled and slurmrestd is running
if [[ "$monitoring_enabled" == "True" ]]; then
    run_slurm_exporter
fi
exit 0
