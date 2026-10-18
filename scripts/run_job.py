"""Run a digest script with failure reporting, including import-time errors."""

import runpy
import sys

import failure_report


if __name__ == "__main__":
    failure_report.run(lambda: runpy.run_path(sys.argv[1], run_name="__main__"))
