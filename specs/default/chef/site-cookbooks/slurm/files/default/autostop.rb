#!/usr/bin/env ruby
require 'json'

# Arguments
AUTOSTOP_ENABLED = `jetpack config cyclecloud.cluster.autoscale.stop_enabled`.downcase.strip == "true"
if not AUTOSTOP_ENABLED
  exit 0
end
  
IDLE_TIME_AFTER_JOBS = `jetpack config cyclecloud.cluster.autoscale.idle_time_after_jobs`.to_i
IDLE_TIME_BEFORE_JOBS = `jetpack config cyclecloud.cluster.autoscale.idle_time_before_jobs`.to_i

# Checks to see if we should shutdown
idle_long_enough = false


def IsActive()
   activejobs=system("ps -ef | grep [s]lurmstepd > /dev/null 2>&1")
   #activenode=system("\"$(hostname -s)[^0-9]\" $SGE_ROOT/activenodes/qstat_t.log > /dev/null 2>&1")
   activenode=system("ls /var/spool/slurmd | grep job")
   if activejobs || activenode
     return true
   else
     return false
   end
end


# This is our autoscale runtime configuration
runtime_config = {
  "first_active_time" => nil,
  "idle_start_time" => nil
}
AUTOSCALE_DATA = "/opt/cycle/jetpack/run/autoscale.json"
if File.exist?(AUTOSCALE_DATA)
  file = File.read(AUTOSCALE_DATA)
  runtime_config.merge!(JSON.parse(file))
end

if IsActive()
  runtime_config["idle_start_time"] = nil
  if runtime_config["first_active_time"].nil?
    runtime_config["first_active_time"] = Time.now.to_i
  end
else
  if runtime_config["idle_start_time"].nil?
    runtime_config["idle_start_time"] = Time.now.to_i
  else
    idle_seconds = Time.now - Time.at(runtime_config["idle_start_time"].to_i)
    # DIfferent timeouts if the node has ever run a job
    if runtime_config["first_active_time"].nil?
      timeout = IDLE_TIME_BEFORE_JOBS
    else
      timeout = IDLE_TIME_AFTER_JOBS
    end
    
    if idle_seconds > timeout
      idle_long_enough = true
    end
    
  end
end

# Write the config information back for next time
file = File.new(AUTOSCALE_DATA, "w")
file.puts JSON.pretty_generate(runtime_config)
file.close

# Do the shutdown
if idle_long_enough
  myhost=`hostname`
  system("jetpack shutdown --idle")
end
