# Makefile for job_submit/cyclecloud plugin

AUTOMAKE_OPTIONS = foreign

PLUGIN_FLAGS = -module -avoid-version --export-dynamic

AM_CPPFLAGS = -I$(top_srcdir) -I$(top_srcdir)/src/common

pkglib_LTLIBRARIES = job_submit_cyclecloud.la

job_submit_cyclecloud_la_SOURCES = job_submit_cyclecloud.c
job_submit_cyclecloud_la_LDFLAGS = $(PLUGIN_FLAGS)