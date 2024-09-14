#!/bin/bash -x

TOPDIR="$(cd $(dirname $0)/.. && pwd)"
cd "$THISDIR"

py_files=$(find $TOPDIR -name "*.py" -not -path "$TOPDIR/indi/*" -not -path "$TOPDIR/templates/*")

pylint --rcfile $TOPDIR/lint/pylintrc $py_files
