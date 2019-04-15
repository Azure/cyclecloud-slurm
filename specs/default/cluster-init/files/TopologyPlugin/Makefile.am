# Makefile for topology/cyclecloud plugin

AUTOMAKE_OPTIONS = foreign

PLUGIN_FLAGS = -module -avoid-version --export-dynamic

AM_CPPFLAGS = -I$(top_srcdir) -I$(top_srcdir)/src/common

pkglib_LTLIBRARIES = topology_cyclecloud.la

# Null topology plugin.
topology_cyclecloud_la_SOURCES = topology_cyclecloud.c
topology_cyclecloud_la_LDFLAGS = $(PLUGIN_FLAGS)