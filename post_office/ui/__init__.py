"""
The live page, and the contract it is written against.

`live.html` is the shell served at `GET /`: the run line, the controls, the
expert roster, and four panes (the floor, Consultations, Ollama calls,
DK-RMM). `floor.html` is the floor and the fleet, carried inside the shell's
first pane. `live.py` fills both from what the runner published; `views.py`
says what a frame and the building look like.

The contract, in full:

    GET  /summary, /frame, /consultations, /llm/calls, /settings,
         /dkrmm/state, /dkrmm/series, /dkrmm/indicators     polled by the page
    WS   /ws             {"type":"hello", state}   the state on connect
                         {"type":"tick",  ...}     one per tick, with counters
                         {"type":"event", ...}     every logged event, live
                         {"type":"reset", run_id}  the ecosystem was rebuilt

Every event carries `tick`, `category`, `topic`, `actor`, `target` and
`correlation_id`, so a page can group by parcel, filter by agent or follow a
consultation (`consult_*` topics, correlated by consultation id) without
knowing anything about post offices.

Adapted from the source `post_office/ui/__init__.py`: the minimal viewer and
the settings panel it served are not part of this prototype.
"""

from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
