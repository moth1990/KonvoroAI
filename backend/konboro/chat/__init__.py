"""The chat layer over the review screen (08, S25).

- `state`: the names the model knows things by (`L3`, `B1`, `F2`, `CH1`) and the money references (`$T1`), kept on
  the server with the conversation (08 §5.4).
- `brief`: the quote in counts, for every turn (08 §5.2).
- `lines`: the open quote's lines as the chat reads them, and the filter that `query_lines` and `propose_change`
  share (08 §6.2, §6.7 `target`).
- `tools`: the tools, as code; `proposals`: `propose_change`, apply, dismiss and expiry (08 §7).
- `history`: the turns sent to the model, by token budget, with compaction (08 §5.2.1).
- `check`: the answer check (08 §8.2).
- `turn`: one turn end to end, and the conversation's messages.
"""
