"""`python -m ain_sink`, which is what the container runs."""

import sys

from ain_sink import sink

sys.exit(sink.main())
