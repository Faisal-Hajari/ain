"""`python -m ain_ingest`, which is what the container runs."""

import sys

from ain_ingest import ingest

sys.exit(ingest.main())
