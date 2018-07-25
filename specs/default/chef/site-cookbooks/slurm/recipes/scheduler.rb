#
# Cookbook Name:: slurm
# Recipe:: scheduler
slurmver = node[:slurm][:version]
slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]

nodename = node[:cyclecloud][:instance][:hostname]

slurmrpms = %w[slurm slurm-devel slurm-example-configs slurm-slurmctld slurm-slurmd slurm-perlapi slurm-torque slurm-openlava]
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
  action [:enable, :start]
end

# Set up slurm 
user slurmuser do
  comment 'User to run slurmd'
  shell '/bin/false'
  action :create
end

directory '/var/spool/slurmd' do
  owner "#{slurmuser}"
  action :create
end

directory '/var/log/slurmctld' do
  owner "#{slurmuser}"
  action :create
end

template '/sched/slurm.conf' do
  owner "#{slurmuser}"
  source 'slurm.conf.erb'
  action :create_if_missing
  variables lazy {{
    :nodename => node[:machinename]
  }}
end

bash 'Add nodes to slurm config' do
  code <<-EOH
    iplist=$(grep ip- /etc/hosts | awk '{print $2}' | cut -d'.' -f1 | xargs | sed 's/ /,/g')
    echo "\nNodename=${iplist} State=FUTURE" >> /sched/slurm.conf
    touch /etc/slurm.installed
    EOH
  not_if { ::File.exist?('/etc/slurm.installed') }
end

link '/etc/slurm/slurm.conf' do
  to '/sched/slurm.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
  mode '0700'
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

include_recipe "slurm::autostart"

