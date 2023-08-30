# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

# Recipe:: delayed_services

# This recipe is used to delay the start of slurmctld and slurmd services until
# cluster init has finished

defer_block 'Delayed start of services' do

    execute "delayed_start_of_services" do
        command "#{node[:cyclecloud][:bootstrap]/azure-slurm-install/start-services.sh #{node[:slurm][:role]}"
    end

end