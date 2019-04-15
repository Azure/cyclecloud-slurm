# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
'''
The purpose of this class is to call basicConfig before any other module does, specifically requests.
'''
import logging
import logging.handlers
import os
import sys


log_level_name = os.getenv('AUTOSTART_LOG_LEVEL', "DEBUG")
log_file_level_name = os.getenv('AUTOSTART_LOG_FILE_LEVEL', "DEBUG")
log_file = os.getenv('AUTOSTART_LOG_FILE', "autoscale.log")

if log_level_name.lower() not in ["debug", "info", "warn", "error", "critical"]:
    log_level = logging.DEBUG
else:
    log_level = getattr(logging, log_level_name.upper())

if log_file_level_name.lower() not in ["debug", "info", "warn", "error", "critical"]:
    log_file_level = logging.DEBUG
else:
    log_file_level = getattr(logging, log_level_name.upper())

requests_logger = logging.getLogger("requests.packages.urllib3.connectionpool")
requests_logger.setLevel(logging.WARN)

stderr = logging.StreamHandler(stream=sys.stderr)
stderr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
stderr.setLevel(log_level)

log_file = logging.handlers.RotatingFileHandler(log_file, maxBytes=1024 * 1024 * 5, backupCount=5)
log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
log_file.setLevel(log_file_level)

logging.getLogger().addHandler(stderr)
logging.getLogger().addHandler(log_file)
logging.getLogger().setLevel(logging.DEBUG)
