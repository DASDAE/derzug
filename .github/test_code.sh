#!/bin/bash

# Script to run tests to account for wonkiness of periodic mac failures.
args="tests -s --cov derzug --cov-append --cov-report=xml"
if [[ "$1" == "doctest" ]]; then
  args="derzug --doctest-modules"
fi
# Only the Qt-free tree is instrumented: CodSpeed's simulation mode is
# valgrind-based, and an instruction count for a Qt paint is dominated by Qt's
# own instructions rather than DerZug's. See docs/dev/benchmarking.md.
if [[ "$1" == "profile" ]]; then
  args="benchmarks/core --codspeed"
fi
# Executes every benchmark once, un-instrumented, so the Qt tree cannot rot.
if [[ "$1" == "benchmarks" ]]; then
  args="benchmarks -q"
fi

exit_code=0

python -m pytest $args || exit_code=$?

# Check the exit code is related to sporadic failures on mac, see #312
if [ $exit_code -ne 132 ] && [ $exit_code -ne 0 ]; then
  exit $exit_code
fi
