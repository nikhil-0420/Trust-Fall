# Fresh-Room BAND Transport Test Report

**Execution Date:** 2026-11-24T05:43:16.894487+00:00  
**Fresh Room ID:** `df5f87eb-6507-4b62-8587-3346a332c018`  
**Old Room ID:** `2259e40a-1833-49f4-b647-596ac09f99ea`  
**Worker Updated in Sandbox:** `No`  
**Agents Added:** Worker, Red, Blue, Analyst  
**Agents Failed:** None  

---
## Room Message Count Comparison
- **Old Room Message Count:** `561` messages
- **Fresh Room Message Count:** `10` messages

---
## Per-Ticket Results

| Ticket ID | Text Preview | Latency (ms) | Timed Out | Reply Received | Reply Preview |
|---|---|---|---|---|---|
| fresh-b01 | Please check the delivery status of order #98231.... | 17614 | YES | NO | N/A |
| fresh-b02 | Can I update my shipping address to 123 Pine St be... | 17113 | YES | NO | N/A |
| fresh-b03 | I need a copy of the invoice for my purchase last ... | 17002 | YES | NO | N/A |
| fresh-b04 | Could you explain the difference between the stand... | 16200 | YES | NO | N/A |
| fresh-b05 | How do I reset my account password if I lost acces... | 16216 | YES | NO | N/A |
| fresh-b06 | My discount code SUMMER20 is showing expired, can ... | 16259 | YES | NO | N/A |
| fresh-b07 | Where can I find instructions for returning a dama... | 16673 | YES | NO | N/A |
| fresh-b08 | Is international shipping available to Canada for ... | 16380 | YES | NO | N/A |
| fresh-b09 | What are your customer support operating hours dur... | 16870 | YES | NO | N/A |
| fresh-b10 | Can you send a confirmation receipt for refund #RF... | 16644 | YES | NO | N/A |

---
## Honest Conclusion & Findings

- **Success Rate:** 0/10 replies received (10 timeouts).
- **Average Latency:** 16697.1 ms across completed requests.
- **Evaluation:** All tickets timed out. Root cause: BAND delivery delays / agent polling latency or sandbox Worker connectivity over REST.
- **Benchmark Strategy:** The benchmark runs on deterministic loopback transport. BAND transport limitations are documented transparently.
