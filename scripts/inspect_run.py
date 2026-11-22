import json

for r in [0, 1, 2]:
    fn = f"data/runs/run-20261122-182325/events-R{r}.jsonl"
    with open(fn, "r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f]
    print(f"\n=================== Round {r}: {len(events)} events ===================")
    for e in events:
        etype = e.get("type")
        aid = e.get("attack_id")
        text = e.get("text")
        outc = e.get("outcome")
        dec = e.get("decision")
        fr = e.get("from")
        to = e.get("to")
        print(f"[{e.get('seq')}] type={etype} aid={aid} from={fr} to={to} dec={dec} blocked={e.get('blocked')} cached={e.get('cached')} outc={outc} evid={e.get('evidence')} text={repr(text)[:80] if text else None}")
