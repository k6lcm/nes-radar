# LINK state definitions

The visible field is nine tiles wide and has exactly three states.

## RECEIVING

A fresh, CRC-valid traffic scene was accepted less than ten seconds ago and
the host did not mark its upstream data stale. The scene's target sprites,
table rows, selected-aircraft details, and count are visible.

## WAITING

The radar is waiting for current traffic. This is shown:

- before the first accepted traffic scene;
- after ten seconds without a valid packet; or
- immediately when an accepted scene carries the upstream-stale flag.

Entering `WAITING` clears target sprites, callsign/type rows, selected-aircraft
details, scene sequence state, and the target count. Static scope graphics,
range, airport, and table slot labels remain visible. A later fresh scene
restores its targets and changes the state to `RECEIVING`.

## ERROR

A UART framing, packet header, CRC-16, record validation, scene sequence, or
severe upstream error occurred. A damaged packet never replaces the last
complete scene. If fresh traffic recovers, the next accepted scene changes the
state to `RECEIVING`; if silence continues to the ten-second threshold, the
state changes to `WAITING` and all targets are cleared.
