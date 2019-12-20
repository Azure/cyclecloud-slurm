#
# Cookbook Name:: slurm
# Recipe:: scheduler
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

include_recipe 'slurm::default'

slurmuser = node[:slurm][:user][:name]
myplatform = node[:platform]

execute 'Create munge key' do
  command "dd if=/dev/urandom bs=1 count=1024 >/sched/munge/munge.key"
  creates "/sched/munge/munge.key"
  action :run
end

file '/sched/munge/munge.key' do
  owner 'munge'
  group 'munge'
  mode 0700
end

remote_file '/etc/munge/munge.key' do
  source 'file:///sched/munge/munge.key'
  owner 'munge'
  group 'munge'
  mode '0700'
  action :create
end

service 'munge' do
  action [:enable, :restart]
end

cookbook_file "#{node[:cyclecloud][:bootstrap]}/writeactivenodes.sh" do
    source "writeactivenodes.sh"
    mode "0700"
    owner "root"
    group "root"
end

cron "writeactivenodes" do
    command "#{node[:cyclecloud][:bootstrap]}/cron_wrapper.sh #{node[:cyclecloud][:bootstrap]}/writeactivenodes.sh"
    only_if { node['cyclecloud']['cluster']['autoscale']['start_enabled'] }
end

cron "writenodeaddrs" do
    command "AUTOSTART_LOG_FILE=#{node[:cyclecloud][:home]}/logs/nodeaddrs.log #{node[:cyclecloud][:bootstrap]}/cron_wrapper.sh #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh nodeaddrs > /sched/nodeaddrs"
end 

directory "#{node[:cyclecloud][:bootstrap]}/slurm" do
  user "root"
  group "root"
  recursive true
end


scripts = ["cyclecloud_slurm.py", "slurmcc.py", "clusterwrapper.py", "cyclecloud_slurm.sh", "resume_program.sh", "resume_fail_program.sh", "suspend_program.sh"]
scripts.each do |filename| 
    cookbook_file "#{node[:cyclecloud][:bootstrap]}/slurm/#{filename}" do
        source "#{filename}"
        mode "0755"
        owner "root"
        group "root"
    end
end

# TODO either change name to cyclecloud-api.tar.gz or make the name configurable
bash 'Install cyclecloud python api' do
  code <<-EOH
    jetpack download --project slurm cyclecloud-api-7.8.0.tar.gz cyclecloud-api.tar.gz || exit 1;
    /opt/cycle/jetpack/system/embedded/bin/pip install cyclecloud-api.tar.gz || exit 1;
    rm -f cyclecloud-api.tar.gz;
    touch /etc/cyclecloud-api.installed
    EOH
  not_if { ::File.exist?('/etc/cyclecloud-api.installed') }
end



bash 'Install job_submit/cyclecloud' do
  code <<-EOH
    jetpack download --project slurm job_submit_cyclecloud.so /usr/lib64/slurm/job_submit_cyclecloud.so || exit 1;
    touch /etc/cyclecloud-job-submit.installed
    EOH
  not_if { ::File.exist?('/etc/cyclecloud-job-submit.installed') }
end


# we will be appending to this file, so that the next step is monotonic
template '/sched/slurm.conf' do
  owner "#{slurmuser}"
  source "slurm.conf_#{myplatform}.erb"
  action :create_if_missing
  variables lazy {{
    :nodename => node[:machinename],
    :bootstrap => "#{node[:cyclecloud][:bootstrap]}/slurm",
    :resume_timeout => node[:slurm][:resume_timeout],
    :suspend_timeout => node[:slurm][:suspend_timeout],
    :suspend_time => node[:cyclecloud][:cluster][:autoscale][:idle_time_after_jobs]
  }}
end


# Note - we used to use ControlMachine, but this is deprecated. We actually do not need to 
# remove it from upgraded slurm.conf's, as simply appending SlurmctldHost will override ControlMachine
# which is especially useful if ControlMachine is pointed at a stale hostname.
bash 'Set SlurmctldHost' do
    code <<-EOH
    host=$(hostname -s)
    grep -q "SlurmctldHost=$host" /sched/slurm.conf && exit 0
    grep -v SlurmctldHost /sched/slurm.conf > /sched/slurm.conf.tmp
    printf "\nSlurmctldHost=$host\n" >> /sched/slurm.conf.tmp
    mv /sched/slurm.conf.tmp /sched/slurm.conf
    EOH
end

link '/etc/slurm/slurm.conf' do
  to '/sched/slurm.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end


template '/sched/cgroup.conf' do
  owner "#{slurmuser}"
  source "cgroup.conf.erb"
  action :create_if_missing
end


link '/etc/slurm/cgroup.conf' do
  to '/sched/cgroup.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end


# No nodes should exist the first time we start, but after that will because fixed=true on the nodes
bash 'Create cyclecloud.conf' do
  code <<-EOH
    # we want the file to exist, as we are going to do an include and it will complain that it is empty.
    touch /etc/slurm/cyclecloud.conf
    
    # upgrade the old slurm.conf
    #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh upgrade_conf || exit 1
    
    num_starts=$(jetpack config cyclecloud.cluster.start_count)
    if [ "$num_starts" == "1" ]; then
      policy=Error
      #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh remove_nodes || exit 1;
    else
      policy=AllowExisting
    fi
    
    #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh create_nodes --policy $policy || exit 1;
    #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh slurm_conf > /sched/cyclecloud.conf || exit 1;
    #{node[:cyclecloud][:bootstrap]}/slurm/cyclecloud_slurm.sh topology > /sched/topology.conf || exit 1;
    touch /etc/slurm.installed
    EOH
  not_if { ::File.exist?('/etc/slurm.installed') }
end

link '/etc/slurm/topology.conf' do
  to '/sched/topology.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/cyclecloud.conf' do
  to '/sched/cyclecloud.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

cookbook_file "/etc/security/limits.d/slurm-limits.conf" do
  source "slurm-limits.conf"
  owner "root"
  group "root"
  mode "0644"
  action :create
end

service 'slurmctld' do
  action [:enable, :start]
end

service 'munge' do
  action [:enable, :restart]
end

defer_block "Defer starting munge until end of converge" do
  service 'munge' do
    action [:enable, :restart]
  end
end
