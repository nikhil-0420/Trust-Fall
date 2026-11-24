import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv()

import band_rest

def analyze():
    a_key = os.getenv("BAND_AGENT_A_KEY")
    client = band_rest.RestClient(api_key=a_key)

    old_room_id = os.getenv("BAND_ROOM_ID", "2259e40a-1833-49f4-b647-596ac09f99ea")
    fresh_room_id = "df5f87eb-6507-4b62-8587-3346a332c018"

    for name, r_id in [("OLD ROOM", old_room_id), ("FRESH ROOM", fresh_room_id)]:
        print(f"\n=================== {name}: {r_id} ===================")
        
        # Participants
        try:
            p_resp = client.agent_api_participants.list_agent_chat_participants(r_id)
            parts = p_resp.data or []
            print(f"Total Participants: {len(parts)}")
            for p in parts:
                p_id = getattr(p, "participant_id", None) or getattr(p, "id", None)
                p_role = getattr(p, "role", None)
                p_handle = getattr(p, "handle", None)
                print(f"  - id: {p_id}, role: {p_role}, handle: {p_handle}")
        except Exception as e:
            print(f"Error listing participants: {e}")

        # Messages by sender
        sender_counts = Counter()
        all_msgs = []
        cursor = None
        while True:
            try:
                resp = client.agent_api_messages.list_agent_messages(r_id, limit=100, cursor=cursor, sort_order="desc")
                batch = resp.data or []
                all_msgs.extend(batch)
                for m in batch:
                    sender = getattr(m, "sender_id", None) or getattr(m, "sender", "unknown")
                    sender_counts[str(sender)] += 1
                if not resp.metadata or not resp.metadata.has_more or not batch:
                    break
                cursor = resp.metadata.next_cursor
            except Exception as e:
                print(f"Error paging messages: {e}")
                break

        print(f"Total messages fetched: {len(all_msgs)}")
        print("Messages by sender:")
        for s, count in sender_counts.most_common():
            print(f"  - sender {s}: {count} messages")

        if name == "FRESH ROOM":
            print("\nMessages in Fresh Room (oldest to newest):")
            for i, m in enumerate(reversed(all_msgs)):
                m_id = getattr(m, "id", None)
                sender = getattr(m, "sender_id", None) or getattr(m, "sender", "unknown")
                content = getattr(m, "content", "")
                mentions = getattr(m, "mentions", None)
                print(f"  [{i+1}] sender={sender} | id={m_id}")
                print(f"       mentions={mentions}")
                print(f"       content={content[:120]}")

if __name__ == "__main__":
    analyze()
