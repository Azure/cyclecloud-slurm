# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

# Recipe:: delayed_services

# This recipe is used to delay the start of slurmctld and slurmd services until
# cluster init has finished

defer_block 'Delayed start of services' do
    cmd = "#{node[:cyclecloud][:bootstrap]}/azure-slurm-install/start-services.sh #{node[:slurm][:role]} >> #{node[:cyclecloud][:bootstrap]}/azure-slurm-install/start-services.log 2>&1"
    Chef::Log.info "Executing #{cmd}"
    execute "delayed_start_of_services" do
        command cmd
    end

end