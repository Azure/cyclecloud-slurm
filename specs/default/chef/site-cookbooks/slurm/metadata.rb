name 'slurm'
maintainer 'Microsoft'
maintainer_email 'support@cyclecomputing.com'
license 'All Rights Reserved'
description 'Installs/Configures slurm'
long_description 'Installs/Configures slurm'
version '0.1.0'
chef_version '>= 12.1' if respond_to?(:chef_version)

%w{ cuser cshared }.each {|c| depends c}

# The `issues_url` points to the location where issues for this cookbook are
# tracked.  A `View Issues` link will be displayed on this cookbook's page when
# uploaded to a Supermarket.
#
# issues_url 'https://github.com/<insert_org_here>/slurm/issues'

# The `source_url` points to the development repository for this cookbook.  A
# `View Source` link will be displayed on this cookbook's page when uploaded to
# a Supermarket.
#
# source_url 'https://github.com/<insert_org_here>/slurm'

