# Pattern paste into a slot that is not playing: review and plan

18 Oct 2026. A review of an investigation of 17 Oct 2026 ("Paste a pattern
into a slot without switching to it", not in the tree) against the stock
image, and the plan that follows from it. Read from
`out/raw/section_3_MAIN_OS.bin` (SHA256 `164f3122…`), base `0x40000400`,
`m68k-linux-gnu-objdump -m m68k:cfv4e`. Nothing here was run under the
port or on a unit: ✅ = read from the code, 🟡 = inferred, ❌ = the
investigation's claim does not hold.

## 1. The finding that changes the plan

❌ **KITS already ships the feature.** `modules/kits/kits.s` `kits_ptrig`
detours `0x40056b2c`: with FUNC held (`0x4003171c(0x2d)`), a trig pressed
with PTN held stores its pattern in `PTGT` and returns before the stock
request. `inactive_op`, called from KITS' detours on FUNC+REC
(`0x40060f34`), FUNC+STOP (`0x40060db0`) and FUNC+PLAY (`0x40060eb4`),
then copies, pastes or clears that pattern while PTN and its trig are
still held, with its own repeat-to-undo (`PUNDO_OP`, `PUNDO_T`).
`kits_fright` (`0x400503c4`, PTN+FUNC+RIGHT) is the one-chord duplicate
the investigation proposes: the current pattern and its Kit into the next
empty pattern, requested. Documented in `modules/kits/README.md` "Use",
`docs/site/usage/kits.md`, `CHANGELOG.md` (6 Oct); gated by `verify_kits`
`inactive` and `inundo` under the port. The README's "On the unit" list
does not name PTN+FUNC+TRIG. All three shipped remixes carry KITS.

The investigation names KITS' hooks on `0x40026eb0`, `0x40026ef0` and
`0x4002b9b0` but not its detours on `0x40056b2c` and the FUNC+key handlers.
A second module on those sites is refused by the build (same detour span).

## 2. Claim by claim

### Routines (its section 2 table)

| claim | verdict |
|---|---|
| `0x40026eb0(p)` copy, `memcpy(0x460c8122, B+p·0x8ed8, 0x8ed8)`, kind `0x460d0ffa` := 14 | ✅; it also clears the undo tag `0x460c80f4` and the undo-valid long `0x460c80f0`: **a copy kills the pending undo** (omitted) |
| `0x40026f74(p, t)` a track's two longs, kind 15 | ✅ (`B + p·0x8ed8 + t·0x91a + 0x28/0x2c`); also clears the undo |
| `0x4002b9b0(src, p)` the paste | ✅ both copies, `0x40029b9c(-1)`, `0x4004a8a4(byte B+cur·0x8ed8+0x8e57)`, `jmp 0x4009c550` |
| `0x4002ba9c(p)` | ✅ returns a byte (`clrb d0` on the false path) |
| `0x40026ef0(kind, p)` the snapshot | ✅; `0x460c8104` is a word field |
| `0x40026664(kind, p, …)` | ✅, but **ten** more arguments, not nine (twelve in all) |
| `0x4002ba2c(kind, p)` the undo | ✅; on success clears the tag and valid long, so a third chord pastes again |
| `0x40029b9c(-1)`: dirty long, `0x100f8598`, `0x400339d8`, `0x4009da20(-1)`, `jmp 0x400486cc` | ✅ but incomplete: it also calls `0x4009da20(arg + 8)`, i.e. `0x4009da20(7)` here |
| `0x4009da20(-1)` "loops all 16 patterns of the current bank" | ❌ it loops **16 tracks** (8 audio at `+t·0x91a`, 8 MIDI at `+0x48d0 + t·0x8b0`) of the **playing** pattern (`0x800065bd` bank, `0x800065be` pattern), not the edited one; a non-negative argument is one track. It refreshes nothing of a destination that is not playing |
| `0x4009c550` reads `B + 0x8ed8·cur + 0x8e58` into `0x80001814/8` | ✅, only when `0x80000024` (per-pattern tempo) is set; else `0x80000020` |

The "kind" argument is the operation, not the clipboard type: FUNC+STOP
passes `0x11`, FUNC+PLAY `0x12`; `0x460c80f0` = 14 says the undo buffer
holds a pattern. ✅

### Panel handlers (its section 2 second table)

✅ `0x40060d04` (FUNC+STOP), `0x40060e00` (FUNC+PLAY), `0x40060f04`
(FUNC+REC) pass `0x100b14d0` as the investigation says. They are reached
through wrappers in the FUNC layer (`0x40060db0`, `0x40060eb4`,
`0x40060f34`) that first route to the track/arranger form (`0x4002dc3c`)
and grid recording (`0x460d1736`). After the paste the handler runs nine
redraw routines (`0x400418e0` … `0x4004b08c`); a hand-built chord must call
the same or the screen goes stale. 🟡 On a failed paste (clipboard not a
pattern) the snapshot is already armed and `0x40027de4` disarms it.

### The SELECT PATTERN window (its section 3a)

| claim | verdict |
|---|---|
| PTN press `0x4005a044`: `0x460d1742` := 1, mask `0x460d1ab6` cleared, window drawn | ✅; also `0x460d173e` := 0 and `0x460d1ab2` := (state ≠ 2) |
| PTN release: `0x460d1742` := 2 or the timeout path | 🟡 imprecise: state 2 (the window **latched**, a timed popup through `0x40059f8c`) only when no trig was pressed (`0x460d173e` = 0); after a trig, state := 0 |
| a 16-entry table at `0x400bef00` | ✅ at **`0x400bef04`**, keys of the window's layer `0x400bf0f2` (registered by `0x4004346c` through `0x40031494`); also NO `0x32` → `0x40056aa8` and YES `0x31` → 0 (swallowed) |
| **the request `0x400a1030` only when the last held trig is released** | ❌ **`0x40056b2c` requests on the first trig's press** (`0x40056b68`, mask empty) and appends later trigs to the chain (`0x4009c634`); the release `0x40043444` only clears the mask bit and closes a latched window. `PARTS.md` section 3 measured the same site (`0x40056b6e`). So for "hold the trig, then press STOP" the switch is already queued; only a hook **before** `0x40056b2c` requests avoids a queue to cancel |
| `0x40056b2c` ends cleanly | ❌ omitted: it tail-jumps to `0x40027de4`, which clears the undo; a stock PTN+TRIG kills FUNC+STOP's undo |
| "what receives STOP and FUNC+STOP while the window is open" (its one open question) | ✅ answered statically: the window's layer has no record for STOP, PLAY, REC or FUNC, so they reach the layer below. FUNC's held layer (keys `0x400bf628` MKII, `0x400bf2b4` MKI) maps STOP/PLAY/REC to the wrappers above and has **no trig records**, so a trig pressed with PTN then FUNC held reaches the window's `0x40056b2c` (as `kits_ptrig` assumes). FUNC **before** PTN is FUNC+PTN (`0x40083450`, 🟡 PATTERN SETTINGS) and opens no window: key order matters |

### Bank scope (its section 2, second bullet)

✅ The three bank-scoped writes are right in substance: the CS1 mirror
`0x1001614e` is the current bank's, the dirty long is `[0x46c82456] +
0x9b332`, and `0x4004a8a4`/`0x4009c550` act on the current pattern. The
"derived-record refresh" is the playing pattern's (above), so a cross-bank
paste needs: the destination bank's blob written, its dirty long set, the
CS1 write skipped (or the destination made current first), and no reliance
on `0x4009da20` for the destination. ✅ `kits_pstore_ptn` and `assign_at`
assume the current bank too, so KITS' Kit carry would need the same work.

### Its section 5 (other Elektron machines)

Not verified against the PDFs. Forum quotes support the Digitakt/Rytm
wording ("after a pattern is selected, and before releasing any key,
[RECORD], [PLAY] and [STOP] can be pressed to copy, clear or paste") and
the multi-destination hold; the "without leaving the active pattern"
sentence is quoted there from the **Rytm MKII** manual, not the Analog
Four MKII OS 1.56 one the investigation cites. The design does not depend
on it.

## 3. What KITS' version does not do (gaps, all 🟡 until measured)

1. **No transport-running proof.** `verify_kits inactive` runs stopped
   and checks pattern 14's bytes and Kit only: not that the playing
   pattern is unchanged, that nothing is queued (`0x800065bf/c0`), or that
   no chain was built.
2. **The window may latch after the gesture.** `kits_ptrig` returns
   before `0x460d173e` := −1, so on PTN's release `0x4005a044` sees no
   trig and latches SELECT PATTERN (state 2). `kits_fright` sets it
   (`PTN_USED`) and its gate checks `0x460d1742`; `inactive` does not.
3. **One destination.** `PTGT` holds the last trig; several held trigs
   paste once.
4. **`PTGT` is never reset.** Harmless while `inactive_op` also requires
   PTN and that trig held, but a later plain PTN+TRIG (a request) on the
   same trig followed by FUNC+STOP pastes into the queued pattern.
5. **The redundant re-apply.** `inactive_op` calls `0x4002b9b0`, which
   re-applies the current pattern's Part (`0x4004a8a4` → `0x40009094`)
   and tempo while it plays. Not listened to.
6. **No redraw.** The paste path runs `toast` only, not stock's nine
   redraw calls; the pattern-select LEDs of the destination may not show
   it filled.
7. **Current bank only** (KITS README "Open"). Octakit's BANK+TRIG >
   BANK+FUNC+TRIG is not carried.
8. **Only with KITS.** A remix without KITS has no form of the feature.

## 4. Options

**A. Improve the feature where it lives (recommended).** Fix gaps 1, 2,
4, 6 and decide 3 and 5 inside `modules/kits`, on this branch. No new
claims, no conflict, the hardware-proven module keeps its sites; the
gates grow (`verify_kits`: transport running, playing pattern and queue
unchanged, window state, a second destination). Cost: KITS' proof note
must say which parts are port-only until the next flash.

**B. Split it out into `modules/pattern-paste`.** The module owns
`0x40056b2c` and the three FUNC-key wrappers and calls out to KITS
for its list ops, the way STORE owns the file sites and calls KITS'
`kits_st_*` events. Makes the feature available without KITS; costs a
refactor of a module proven on hardware, a new event interface, and a
reflash to re-prove KITS. Table pokes instead of detours do not avoid
the conflict: the window table would compose, but the FUNC layer's keys
are BRAIN's copy on MKII (`modules/brain` `FUNC_LAYER_KEYS`, an `.incbin`
of the stock table), so a poke there is bypassed.

**C. Cross-bank destinations** (BANK held as well) on top of A or B:
the three bank-scoped writes of section 2 plus KITS' `assign_at`.

## 5. Plan (option A)

1. Under the port, before any code: the stock gesture traced with the
   transport running (`--watch-pc 0x400a0570,0x4009c634,0x4002b9b0`,
   `--watch-mem 0x800065bd..0x800065c2,0x460d1742`), PTN, FUNC, TRIG 14,
   STOP, releases, on a remix with KITS. Settles gaps 1, 2, 4 and the
   key-order question as measurements.
2. `kits_ptrig`: set `PTN_USED` (`0x460d173e` := −1); add the trig to a
   target mask instead of `PTGT` (gap 3, if wanted); clear the target on
   PTN's release.
3. `inactive_op`: loop the mask; run stock's post-paste redraw sequence;
   skip or keep the current-Part re-apply after listening (gap 5).
4. `verify_kits`: the `inactive*` scenarios run with PLAY pressed first
   and check the playing pattern byte, the queue bytes, the chain count
   and `0x460d1742`; a two-target paste; FUNC+STOP on the current
   pattern after a paste-elsewhere behaves as stock (the undo tag of
   section 2).
5. README "Use"/"Open", `docs/site/usage/kits.md`, `CHANGELOG.md`
   when flashed.
6. `make check REMIX=octabam-core`, `make reach RUN=1 KEEP=1` before
   the PR (`CONTRIBUTING.md`).

Falsifiers: a trace in step 1 showing a request or a chain entry during
the gesture with KITS in the image; the window not latching (gap 2 is
then not real); the playing pattern's sound changing at the paste
(gap 5 is audible).
