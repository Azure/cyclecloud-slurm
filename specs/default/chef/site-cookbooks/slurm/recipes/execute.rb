#
# Cookbook Name:: slurm
# Recipe:: execute

slurmver = node[:slurm][:version]
slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]

nodename = node[:cyclecloud][:instance][:hostname]

slurmrpms = %w[slurm slurm-devel slurm-example-configs slurm-slurmd]
slurmrpms.each do |slurmpkg|
  jetpack_download "#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm" do
    project "slurm"
    not_if { ::File.exist?("#{node[:jetpack][:downloads]}/#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm") }
  end
end

slurmrpms.each do |slurmpkg|
  package "#{node[:jetpack][:downloads]}/#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm" do
    action :install
  end
end

# Fix munge permissions and create key
directory "/etc/munge" do
  owner 'munge'
  group 'munge'
  mode 0700
end
directory "/var/lib/munge" do
  owner 'munge'
  group 'munge'
  mode 0711
end
directory "/var/log/munge" do
  owner 'munge'
  group 'munge'
  mode 0700
end
directory "/run/munge" do
  owner 'munge'
  group 'munge'
  mode 0755
end
directory "/sched/munge" do
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
  action [:enable, :start]
end

user slurmuser do
  comment 'User to run slurmd'
  shell '/bin/false'
  action :create
end

directory '/var/spool/slurmd' do
  owner "#{slurmuser}"
  action :create
end

directory '/var/log/slurmd' do
  owner "#{slurmuser}"
  action :create
end

link '/etc/slurm/slurm.conf' do
  to '/sched/slurm.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
  mode '0700'
end

defer_block "Defer starting slurmd until end of converge" do
  service 'slurmd' do
      action [:enable, :start]
  end
end

  
include_recipe "slurm::autostop"

