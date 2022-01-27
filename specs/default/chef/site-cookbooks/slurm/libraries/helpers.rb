# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
module Slurm
  class Helpers
     
    def self.wait_for_master(sleep_time=10, max_retries=6, &block)
      results = block.call
      retries = 0
      while results.length < 2 and retries < max_retries
        sleep sleep_time
        retries += 1
        results = block.call
        Chef::Log.info "Found primary slurmctld node."
      end
      if retries >= max_retries
        raise Exception, "Timed out waiting for primary slurmctld"
      end
     
      results
    end
     
  end
end