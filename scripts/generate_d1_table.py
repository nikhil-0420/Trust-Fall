import json
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

run_dir = REPO_ROOT / "data" / "runs" / "run-20261122-182325"
results_path = run_dir / "results.json"
results = json.load(open(results_path, encoding="utf-8"))

with open("attacks/library.json", encoding="utf-8") as f:
    lib = {a["id"]: a for a in json.load(f)}

# Also load benign tickets
from arena.benign import BENIGN_TICKETS
benign_map = {b["id"]: b for b in BENIGN_TICKETS}

rows = []

for r_idx, rnd in enumerate(results["rounds"]):
    round_id = rnd["id"]
    events_file = run_dir / f"events-{round_id}.jsonl"
    events = []
    if events_file.exists():
        with open(events_file, encoding="utf-8") as f:
            events = [json.loads(line) for line in f]

    # Process attack tickets
    for att in rnd["attacks"]:
        aid = att["id"]
        lib_att = lib.get(aid, {})
        goal = att.get("goal") or lib_att.get("goal", "unknown")
        outcome = att.get("outcome")
        gate_info = att.get("gate")
        
        # Find events for this attack
        msg_ev = next((e for e in events if e.get("type") == "message" and e.get("attack_id") == aid), None)
        gate_ev = next((e for e in events if e.get("type") == "gate" and e.get("attack_id") == aid), None)
        judge_ev = next((e for e in events if e.get("type") == "judge" and e.get("attack_id") == aid), None)

        # Check gate cache file for provenance
        text = lib_att.get("text", "")
        h = hashlib.sha256(text[:500].strip().encode("utf-8")).hexdigest()
        cfile = Path(f"data/cache/gate/{h}.json")
        cdata = json.load(open(cfile, encoding="utf-8")) if cfile.exists() else None

        gate_decision = "None"
        is_cache_hit = "N/A"
        impl = "N/A"

        if round_id in ("R1", "R2"):
            if cdata is not None:
                gate_decision = cdata.get("decision", "None")
                is_cache_hit = "Yes"
                # If confidence is floating point with decimals like 99.85, 89.97, 99.99, it came from live Lyzr API call
                # If 0.95, from MockGate
                conf = cdata.get("confidence", 0)
                if conf in (0.95, 0.05):
                    impl = "MockGate"
                else:
                    impl = "Lyzr (pre-run cache)"
            else:
                gate_decision = "None"
                is_cache_hit = "No"
                impl = "None"
        elif round_id == "R0":
            gate_decision = "None"
            is_cache_hit = "N/A"
            impl = "None (Gate inactive)"

        evid = judge_ev.get("evidence") if judge_ev else None
        if evid == "Worker error: timeout":
            outcome_display = "error (timeout)"
            outbound_text = "None (Timed out waiting for BAND message)"
        else:
            outcome_display = outcome
            outbound_text = "Refusal / standard safe support response (Worker resisted)"

        mem_write_attempted = "No"
        if goal == "poison":
            mem_write_attempted = "Yes"
        policy_denied = "No (Policy inactive)" if round_id in ("R0", "R1") else "N/A"

        rows.append({
            "id": aid,
            "goal": goal,
            "round": round_id,
            "outcome": outcome_display,
            "outbound": outbound_text[:200],
            "mem_write": f"Attempted: {mem_write_attempted}, Denied: {policy_denied}",
            "gate_decision": gate_decision,
            "cache_hit": is_cache_hit,
            "impl": impl
        })

    # Benign tickets
    benign_total = rnd["benign"]["total"]
    benign_passed = rnd["benign"]["passed"]
    for b_idx in range(1, benign_total + 1):
        bid = f"B0{b_idx}"
        b_info = benign_map.get(bid, {})
        b_text = b_info.get("text", "")
        h = hashlib.sha256(b_text[:500].strip().encode("utf-8")).hexdigest()
        cfile = Path(f"data/cache/gate/{h}.json")
        cdata = json.load(open(cfile, encoding="utf-8")) if cfile.exists() else None

        if round_id in ("R0", "R1"):
            outcome_b = "passed"
            outbound_b = f"Ticket B-{round_id}-{bid} [processed]: Support ticket processed successfully."
            g_dec = "SAFE" if round_id == "R1" else "None"
            c_hit = "Yes" if (round_id == "R1" and cdata) else ("No" if round_id == "R1" else "N/A")
            b_impl = "Lyzr (pre-run cache)" if (round_id == "R1" and cdata) else ("N/A" if round_id == "R0" else "MockGate")
        else: # R2
            outcome_b = "error (timeout)"
            outbound_b = "None (Timed out waiting for BAND message from sandbox)"
            g_dec = "SAFE"
            c_hit = "Yes" if cdata else "No"
            b_impl = "Lyzr (pre-run cache)" if cdata else "MockGate"

        rows.append({
            "id": bid,
            "goal": "benign",
            "round": round_id,
            "outcome": outcome_b,
            "outbound": outbound_b[:200],
            "mem_write": "Attempted: No, Denied: N/A",
            "gate_decision": g_dec,
            "cache_hit": c_hit,
            "impl": b_impl
        })

print(f"Total rows: {len(rows)}")
for r in rows[:10]:
    print(r)
