#!/usr/bin/env python3
"""KITS under the port: does a key that KITS handles while a pattern plays
start a voice the sequencer would not have started? A field report (MKII,
24 Oct 2026): PTN+FUNC+RIGHT while playing retriggered "a step or two" at
the press, with DIRECT_JUMP off.

    python3 tools/verify/verify_kits_retrig.py REMIX [--project DIR]
        [--press-ms 3000] [--after-ms 8000] [--inactive 15,16] [--only fright,quick]

The instrument is the per-track START byte 0x46104d15[t]: every START
form, a sequencer trig and a panel key's alike, is written there on its way
to the DSP and the packer (modules/cxosc/poly.s, po_retrig). `ot_emu
--trig-log` records every nonzero write to it with the frame it landed in,
from the boot, so each scenario forked from the one load carries the same
clock. The project (OT_PROJECT, ~/.octabam_project) is staged with its own
.work files (kits.work and scenes.work included) and plays from where it
was saved; no samples are staged and no DSP core runs, so what is compared
is what the ColdFire posts, not sound.

Every scenario: NO, PLAY, then at --press-ms after PLAY its keys, then the
same end time for all.

  base      nothing pressed.
  null      nothing pressed: a second fork of the same load. Its log must
            equal base's from the script start, or the comparison below
            cannot tell a press from the port's own variation (inconclusive).
  fright    PTN+FUNC+RIGHT (KITS' pattern clone: the stock Part Save, two
            Kit copies, the stock pattern write 0x4002b9b0 into the next
            empty pattern, a request for it).
  quick     FUNC+PART, then FUNC+YES: SAVE KIT's quick save of the current
            Kit, i.e. the stock Part Save path alone.
  inactive  PTN+FUNC held: TRIG A + REC (copy pattern A), TRIG B + STOP
            (paste into B): the same stock pattern write, no Part Save.
            A and B (--inactive, 1-based) must not be the playing pattern.

For each press scenario: its START writes from the press to the end against
base's. A write base has not (an extra START) or base has and it lacks (a
lost one) before the pattern switch lands is the field report reproduced:
FAIL, with the frames, tracks and bytes. A difference at or after the
switch is reported apart (the copy plays its own first step; that is not
the report). Which routines ran is shown from PC watches on the stock Part
Save (0x4004a908) and the stock pattern write (0x4002b9b0), against base.

What it cannot see: the sound (no DSP, no samples); a retrigger that never
passes the START byte; the hardware's timing (the port runs the UI task and
the frame interrupt in lockstep, so a press that takes longer than a frame
on the unit does not delay a frame here). MKII panel only (--mkii).
"""
import argparse
import collections
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); import toolpath  # noqa: E402,F401
from remix import registry  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
EMU = ROOT / "out/emu/ot_emu"
PY = ROOT / ".venv/bin/python3"
OUT = ROOT / "out/kitsretrig"
K = dict(no=0x32, yes=0x31, play=0x28, stop=0x27, ptn=0x2e, func=0x2d, part=0x1d, right=0x21, rec=0x29)
STATE = ("READY KDIRTY NOWRITE PENDING ISR NOSLOT INVALID IOERR BADFILE "
         "STAGED REPOINT STAMP").split()
CUR = 0x80000002                     # current bank, Part, pattern (bytes)
P_SAVE, P_WRITE = 0x4004a908, 0x4002b9b0
FRAME_HZ = 44100 / 16
T_NO, T_PLAY = 1500, 2000            # the script's NO, then PLAY (ms from its start)
HALT = ("stopped before", "stopped in a wait", "FAULT", "ILLEGAL", "EXCEPTION", "DID NOT RETURN", "WAIT TIMEOUT")


def frames_at(ms):
    """The frame a live-script line at `ms` lands on, after the script's
    start (main.cpp msFrames)."""
    return int(ms / 1000.0 * FRAME_HZ)


def keys(t, *events):
    """(ms, 'down'|'up', key) -> live-script lines from t."""
    return [(t + dt, f"key {(K[k] if isinstance(k, str) else k):#x} {what}") for dt, what, k in events]


def presses(name, tp, inactive):
    a, b = inactive
    if name == "fright":
        return keys(tp, (0, "down", "ptn"), (80, "down", "func"), (160, "down", "right"), (200, "up", "right"),
                    (500, "up", "func"), (580, "up", "ptn"))
    if name == "quick":
        return keys(tp, (0, "down", "func"), (80, "down", "part"), (120, "up", "part"), (900, "up", "func"), (1300, "down", "func"), (1400, "down", "yes"), (1440, "up", "yes"),
                    (1640, "up", "func"))
    if name == "inactive":
        return keys(tp, (0, "down", "ptn"), (80, "down", "func"),
                    (160, "down", a - 1), (260, "down", "rec"), (300, "up", "rec"), (500, "up", a - 1),
                    (700, "down", b - 1), (800, "down", "stop"), (840, "up", "stop"), (1100, "up", b - 1),
                    (1300, "up", "func"), (1380, "up", "ptn"))
    return []


def script(name, tp, end, inactive):
    lines = keys(0, (T_NO, "down", "no"), (T_NO + 40, "up", "no"), (T_PLAY, "down", "play"), (T_PLAY + 40, "up", "play"))
    lines += presses(name, tp, inactive)
    lines.sort(key=lambda x: x[0])
    return "".join(f"{t:.0f} {x}\n" for t, x in lines) + f"{end:.0f} quit\n"


def parse(log):
    """-> dict(f0, end_frame, end_sample, trigs [(frame, track, byte, pc)],
    pcs {addr: hits}, ptn [(frame, value)], halted)."""
    r = dict(f0=None, end_frame=None, end_sample=None, trigs=[], pcs=collections.Counter(), ptn=[], halted=False,
             armed=False)
    raw_ptn = []
    for ln in log.splitlines():
        if (m := re.search(r"live script: starts at frame (\d+)", ln)):
            r["f0"] = int(m.group(1))
        elif (m := re.search(r"trig-log   : (\d+) nonzero write\(s\) .* ended at frame (\d+), sample ([\d.]+)", ln)):
            r["end_frame"], r["end_sample"] = int(m.group(2)), float(m.group(3))
        elif "trig-log   :" in ln and "armed before the boot" in ln:
            r["armed"] = True
        elif (m := re.match(r"\s+trig frame (\d+) track (\d+) byte (0x[0-9a-f]+|0) at pc (0x[0-9a-f]+|0)", ln)):
            r["trigs"].append((int(m.group(1)), int(m.group(2)), int(m.group(3), 16), int(m.group(4), 16)))
        elif (m := re.match(r"\s+\[\s*\d+\] at (0x[0-9a-f]+) ", ln)):
            r["pcs"][int(m.group(1), 16)] += 1
        elif (m := re.match(r"\s+\[\s*([\d.]+)\] \[(0x[0-9a-f]+)\] <- (0x[0-9a-f]+|0) \((\d+)\)", ln)):
            if int(m.group(2), 16) == CUR + 2:
                raw_ptn.append((float(m.group(1)), int(m.group(3), 16) & 0xff))
        if any(w in ln for w in HALT):
            r["halted"] = True
    if r["end_frame"] is not None:
        # the frame engine runs 16 samples a frame through the live script:
        # a write's sample, placed against the run's last frame
        r["ptn"] = [(r["end_frame"] - int((r["end_sample"] - s) / 16), v) for s, v in raw_ptn]
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("remix", nargs="?", default=os.environ.get("REMIX"))
    home = pathlib.Path.home() / ".octabam_project"
    ap.add_argument("--project", default=os.environ.get("OT_PROJECT") or (home.read_text().strip() if home.is_file() else ""))
    ap.add_argument("--press-ms", type=float, default=3000, help="the press, after PLAY (default 3000)")
    ap.add_argument("--after-ms", type=float, default=8000, help="how long the run goes on after the press (default 8000)")
    ap.add_argument("--inactive", default="15,16", help="the inactive scenario's source and target patterns, 1-based (default 15,16)")
    ap.add_argument("--only", default="", help="comma-separated press scenarios (fright, quick, inactive); base and null always run")
    a = ap.parse_args()
    remix = registry.remix(a.remix)
    if "KITS" not in remix.modules:
        print(f"  [ -- ] verify_kits_retrig: {a.remix} carries no KITS"); return 0
    if not a.project:
        print("  [SKIP] verify_kits_retrig: no project (OT_PROJECT=<dir> or --project)"); return 0
    if not EMU.is_file():
        print("  [SKIP] verify_kits_retrig: no port binary (make emu-cf)"); return 0
    pdir = pathlib.Path(a.project).expanduser()
    if not (pdir / "project.work").is_file():
        sys.exit(f"verify_kits_retrig: {pdir} is not a project")
    inactive = tuple(int(x) for x in a.inactive.split(","))
    if len(inactive) != 2 or not all(1 <= x <= 16 for x in inactive) or inactive[0] == inactive[1]:
        sys.exit("verify_kits_retrig: --inactive takes two different patterns, 1-16")
    press = [n for n in ("fright", "quick", "inactive") if not a.only or n in a.only.split(",")]
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # ---- the image and the unit's symbols (as verify_kits) ---------------------
    env = dict(os.environ, REMIX=a.remix, XBUS="1", SPEC="1"); env.setdefault("BUILD", "0")
    r = subprocess.run([sys.executable, str(ROOT / "tools/build/build_bus.py")], env=env,
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        sys.exit(f"verify_kits_retrig: building {a.remix} failed:\n{(r.stdout + r.stderr)[-1500:]}")
    image = OUT / "mainos.bin"
    shutil.copy2(ROOT / "out/mainos_bus.bin", image)
    nm = subprocess.run(["m68k-elf-nm", str(ROOT / "out/platform/runtime/runtime.elf")],
                        capture_output=True, text=True).stdout
    sym = {f[2]: int(f[0], 16) for f in (l.split() for l in nm.splitlines()) if len(f) == 3}
    KS = sym["KSTATE"]

    # ---- the card: the project's own .work files, no samples ---------------------
    proj = OUT / "proj_RETRIG"
    proj.mkdir()
    for f in pdir.iterdir():
        if f.is_file() and f.suffix.lower() == ".work":
            shutil.copy2(f, proj / f.name)
    card = OUT / "card_RETRIG.img"
    r = subprocess.run([str(PY), str(ROOT / "tools/emu/ot_emu/stage_card.py"), str(proj), "OCTABAM", "RETRIG",
                        "--tree", str(OUT / "tree_RETRIG"), "--out", str(card)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"verify_kits_retrig: stage_card failed:\n{r.stdout[-800:]}{r.stderr[-800:]}")

    tp = T_PLAY + a.press_ms
    end = tp + a.after_ms
    scen = []
    for name in ["base", "null"] + press:
        (OUT / f"{name}.script").write_text(script(name, tp, end, inactive))
        dumps = f"{KS:#x},48={OUT / f'{name}_st.bin'};{CUR:#x},3={OUT / f'{name}_cur.bin'}"
        scen.append(f"{OUT / (name + '.txt')} --live-script {OUT / (name + '.script')} --mem-dump {dumps}")
    cmd = [EMU, "--image", image, "--card", card, "--set", "OCTABAM", "--project", "RETRIG", "--load-ms", "90000",
           "--mkii", "--trig-log", "--watch-pc", f"{P_SAVE:#x},{P_WRITE:#x}", "--watch-mem", f"{CUR + 2:#x},1"]
    cmd += [x for sc in scen for x in ("--scenario", sc)] + ["--scenario-jobs", os.environ.get("KITS_JOBS", "3")]
    with open(OUT / "port.txt", "w") as f:
        f.write(" ".join(map(str, cmd)) + "\n"); f.flush()
        rc = subprocess.run(list(map(str, cmd)), cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode
    top = (OUT / "port.txt").read_text(errors="replace")
    if "usage: ot_emu" in top:
        sys.exit("verify_kits_retrig: this ot_emu has no --trig-log: rebuild the port (make emu-cf)")
    if rc:
        sys.exit(f"verify_kits_retrig: ot_emu exit {rc} -- {OUT / 'port.txt'}")

    # ---- reading the runs back ----------------------------------------------------
    fails = 0

    def check(msg, ok):
        nonlocal fails
        print(f"  [{'ok' if ok else 'FAIL'}] {msg}")
        fails += not ok

    runs, st, cur = {}, {}, {}
    for name in ["base", "null"] + press:
        log = OUT / f"{name}.txt"
        if not log.is_file() or not (OUT / f"{name}_st.bin").is_file():
            sys.exit(f"verify_kits_retrig: scenario {name} never completed ({log})")
        runs[name] = parse(log.read_text(errors="replace"))
        d = (OUT / f"{name}_st.bin").read_bytes()
        st[name] = {n: struct.unpack(">I", d[4 * i:4 * i + 4])[0] for i, n in enumerate(STATE)}
        cur[name] = tuple((OUT / f"{name}_cur.bin").read_bytes())
    b = runs["base"]
    if not b["armed"] or b["f0"] is None or b["end_frame"] is None:
        sys.exit(f"verify_kits_retrig: the base log has no trig log or no script start ({OUT / 'base.txt'})")
    f0 = b["f0"]
    fp = f0 + frames_at(tp)
    play = f0 + frames_at(T_PLAY)
    bank, _part, ptn = cur["base"]
    print(f"  playing: bank {chr(65 + bank)} pattern {ptn % 16 + 1} (as saved); the press at frame {fp} "
          f"({a.press_ms:.0f} ms after PLAY), the runs end at frame {b['end_frame']}")

    for name, rn in runs.items():
        check(f"{name}: no halt, READY {st[name]['READY']}, script start at frame {rn['f0']}",
              not rn["halted"] and st[name]["READY"] == 1 and rn["f0"] == f0)

    after = lambda rn, frm: [t[:3] for t in rn["trigs"] if t[0] >= frm]
    seen = after(b, play)
    check(f"base: {len(seen)} START write(s) after PLAY (the instrument sees the pattern play)", len(seen) > 0)
    if not seen:
        print("    the playing pattern posts no START here: a pattern with trigs on an audio track is needed, "
              "or the remix moved the frame builder's trig path")
    same = after(runs["null"], f0) == after(b, f0)
    check("null: its START writes equal base's from the script start (the port repeats itself; "
          "otherwise every comparison below is inconclusive)", same)
    if not same:
        print("verify_kits_retrig: FAIL (inconclusive: two identical forks differ)")
        return 1

    def at_ms(frm):
        return (frm - fp) / FRAME_HZ * 1000

    for name in press:
        rn = runs[name]
        sw = next((f for f, v in rn["ptn"] if f >= fp and v != ptn), None)
        mine, theirs = collections.Counter(after(rn, fp)), collections.Counter(after(b, fp))
        extra = sorted((mine - theirs).elements())
        lost = sorted((theirs - mine).elements())
        before = [("extra", x) for x in extra if sw is None or x[0] < sw - 1] + \
                 [("lost", x) for x in lost if sw is None or x[0] < sw - 1]
        later = [("extra", x) for x in extra if sw is not None and x[0] >= sw - 1] + \
                [("lost", x) for x in lost if sw is not None and x[0] >= sw - 1]
        ran = {n: rn["pcs"][addr] - b["pcs"][addr] for n, addr in (("Part Save", P_SAVE), ("pattern write", P_WRITE))}
        print(f"  {name}: ran beyond base: {', '.join(f'{n} x{v}' for n, v in ran.items())}; "
              f"KITS staged {st[name]['STAGED'] - st['base']['STAGED']:+d}, dirty {st[name]['KDIRTY']}; "
              f"pattern switch {'at frame %d (%+.0f ms)' % (sw, at_ms(sw)) if sw is not None else 'none by the end'}")
        if name == "fright" and not ran["pattern write"]:
            print("    no pattern write: no empty pattern after the playing one in this bank? (KITS shows NO EMPTY PATTERN)")
        if name == "inactive" and ptn % 16 + 1 in inactive:
            print(f"    pattern {ptn % 16 + 1} plays: --inactive must name two others")
        for kind, (frm, trk, byte) in (before + later)[:12]:
            print(f"    {kind:5s} START track {trk} byte {byte:#04x} at frame {frm} ({at_ms(frm):+.1f} ms from the press)"
                  f"{'  [at/after the switch]' if (kind, (frm, trk, byte)) in later else ''}")
        check(f"{name}: no START base lacks, none lost, between the press and the switch "
              f"({len([k for k, _ in before if k == 'extra'])} extra, {len([k for k, _ in before if k == 'lost'])} lost; "
              f"{len(later)} difference(s) at or after the switch, reported only)", not before)

    print(f"verify_kits_retrig: {'FAIL' if fails else 'ok'} ({fails} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
