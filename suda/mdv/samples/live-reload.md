# Live reload over SSE

The viewer keeps one `EventSource` open per tab. When a file changes on disk, the server pushes a small event and the page re-renders only the blocks that changed.

## Event shape

| Field | Type | Meaning |
|---|---|---|
| `name` | string | path inside the space |
| `mtime` | number | seconds since the epoch |
| `blocks` | number[] | indexes of the changed blocks |

## Client

```js
const es = new EventSource('/events?space=mds');
es.addEventListener('change', e => {
  const { name, blocks } = JSON.parse(e.data);
  if (name === current) rerender(blocks); // flash what changed
});
```

## Failure modes

- The tab sleeps on the phone: on wake it asks for `mtime` and reloads if it is older.
- The server restarts: `EventSource` reconnects by itself after 3 s.
- Two edits inside 200 ms are merged into one event.

> Rule: the server binds `127.0.0.1` only; a reverse proxy in front of it is the one door from outside.
