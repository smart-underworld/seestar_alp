#!/bin/bash -x

TOPDIR="$(cd $(dirname $0)/.. && pwd)"
cd "$THISDIR"

py_files=$(find $TOPDIR -name "*.py")

pylint --rcfile $TOPDIR/lint/pylintrc $py_files
