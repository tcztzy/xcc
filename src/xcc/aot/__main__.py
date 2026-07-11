import sys

from xcc.aot.hosted_cli import hosted_main

raise SystemExit(hosted_main(len(sys.argv), tuple(sys.argv)))
