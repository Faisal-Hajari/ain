# geometry-editor

Draws the zones and counting lines in `config/cameras.yml` over a still from
each camera, and writes them back.

    http://localhost:8101

One HTML file and an nginx config. It is a separate service from the API it
talks to because it is a separate thing: a page a person opens now and then
to move a polygon, versus a query layer the dashboard hits continuously. They
have different uptime requirements and no shared code, and serving the page
from the API meant that service carried a route for an HTML file and an
environment variable naming where the file sat on disk.

nginx proxies `/zones`, `/cameras` and `/frame` through to `analytics-api`,
so the page is same-origin with the API it reads and writes - it fetches with
relative paths and has no idea where the API actually is.

The page is bind-mounted in the compose stack, so editing it is a browser
reload, not a rebuild.



## Drawing

**A zone** is *+ Zone*, a click per corner, then Enter (or double-click) to
close it. Name it, and give it a capacity if you want to alert on "90% full".
On a selected zone the hollow dots between corners are new points - click one
to add a corner there and drag it where you want it; right-click a corner to
remove it.

**A counting line is a pair**, and the editor draws it as one: *+ Entrance*
asks for the two ends of the **outer** line, then starts the **inner** one for
you a little further in. Crossing outer then inner is somebody coming in -
that ordering is the whole reason there are two, because one line and a
jittering bounding box produce phantom crossings all day. The list shows them
as `entrance / outer` and `entrance / inner`, and the dropdown beside the name
swaps a shape between the two if you drew them the wrong way round. Pressing
*+ Entrance* again starts a separate line rather than a third half.

Drag any point to move it; *Delete* removes the selected shape. A `*` beside a
shape means it differs from what is on disk.

**Zones are floor patches, not furniture.** The test is on the FOOT point of a
detection box - `(xc, yc + h/2)` - so a polygon traced around a tabletop
catches nobody: a seated customer's feet are beside and under the table. Draw
where people stand and sit.

Two tabs open on the same camera would otherwise end with the second silently
deleting what the first drew, because a save replaces a whole camera. The page
sends the version it read, and a save against a stale one is refused -
*Refresh frame* re-reads both the picture and the geometry.

Saving rewrites `zones` and `lines` for the camera on screen and nothing else.
Comments survive: they are `cameras.yml`'s documentation, including the note
above each polygon saying where it stops and why. `cameras` is deliberately
not writable - adding a camera also means `scripts/compose_gen.py` and a new
source adapter, which is a command, not a click. The file is checked in, so
`git diff` is the review and `git checkout` is the undo.
