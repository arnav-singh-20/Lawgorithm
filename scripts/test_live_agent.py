"""
Live test suite for Lawgorithm ReAct Agent against real Gemini LLM API.
Phase A (Step 2) & Phase B verification.
"""

import json
import logging
import sys
from backend.agent.agent import run_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TEST_CASES = [
    {
        "name": "Non-compete Clause (Employment)",
        "clause_id": "test_non_compete",
        "clause_title": "Non-Compete and Restraint of Trade",
        "text": (
            "The Employee covenants that for a period of two (2) years following the termination "
            "of their employment with the Company for any reason, the Employee shall not directly "
            "or indirectly engage in, work for, or provide services to any business competing with "
            "the Company anywhere within the territory of India."
        ),
        "expected_risk": "red",
        "expected_keywords": ["Section 27", "restraint of trade", "void", "Indian Contract Act"],
    },
    {
        "name": "Lock-in Clause (Rental)",
        "clause_id": "test_lock_in",
        "clause_title": "Mandatory Lock-in Period",
        "text": (
            "The Tenant agrees to a mandatory lock-in period of 24 months from the Commencement Date. "
            "If the Tenant terminates the tenancy prior to the expiry of the lock-in period, the Tenant "
            "shall remain liable to pay the full monthly rent for the entire unexpired duration of the 24 months."
        ),
        "expected_risk": "amber",
        "expected_keywords": ["lock-in", "liquidated damages", "penalty", "Section 74"],
    },
    {
        "name": "Penalty Clause (Employment)",
        "clause_id": "test_penalty",
        "clause_title": "Liquidated Damages and Penalty for Policy Breach",
        "text": (
            "In the event of any minor breach of internal company policy by the Employee, the Employee "
            "shall immediately forfeit all accrued salary, bonuses, and gratuity, and shall pay a mandatory "
            "penalty of INR 5,00,000 as liquidated damages to the Employer without requiring proof of actual loss."
        ),
        "expected_risk": "red",
        "expected_keywords": ["Section 74", "penalty", "reasonable compensation", "Contract Act"],
    },
    {
        "name": "Termination Clause (Standard Notice)",
        "clause_id": "test_termination",
        "clause_title": "Termination on Notice",
        "text": (
            "Either party may terminate this agreement at any time, with or without cause, by providing "
            "thirty (30) days prior written notice to the other party or by paying thirty (30) days salary in lieu thereof."
        ),
        "expected_risk": "green", # or amber depending on interpretation, standard mutual notice
        "expected_keywords": ["notice", "termination"],
    },
    {
        "name": "Rental Security Deposit Clause (Rental)",
        "clause_id": "test_rental_deposit",
        "clause_title": "Security Deposit and Maintenance",
        "text": (
            "The Tenant shall pay a refundable security deposit equivalent to two (2) months' rent upon execution "
            "of this agreement. The Landlord shall refund the entire deposit within 30 days of vacation of premises, "
            "subject to deductions for any unpaid rent or physical damage beyond normal wear and tear."
        ),
        "expected_risk": "green",
        "expected_keywords": ["security deposit", "refund", "Model Tenancy Act", "deductions"],
    },
    {
        "name": "Informational Working Hours (No Legal Issue)",
        "clause_id": "test_working_hours",
        "clause_title": "Standard Working Hours",
        "text": (
            "The regular working hours for all employees shall be from 9:30 AM to 6:00 PM, Monday through Friday, "
            "with a one-hour lunch break daily."
        ),
        "expected_risk": "green",
        "expected_keywords": ["working hours", "standard"],
    },
]


def run_live_tests():
    print("=" * 80)
    print("RUNNING REAL LIVE GEMINI LLM AGENT TEST")
    print("=" * 80)

    results = []

    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] Testing: {case['name']}")
        print(f"Clause: {case['text'][:120]}...")

        try:
            res = run_agent(
                clause_text=case["text"],
                clause_id=case["clause_id"],
                clause_title=case["clause_title"],
            )

            print("\n--- AGENT RESULT ---")
            print(f"Risk Level: {res.get('risk_level')}")
            print(f"Confidence: {res.get('confidence')}")
            print(f"Grounding Score: {res.get('grounding_score')}")
            print(f"Citation Valid: {res.get('citation_valid')}")
            print(f"Status: {res.get('status')}")
            print(f"Verification Status: {res.get('verification_status')}")
            print(f"Retrieved Source IDs: {res.get('retrieved_source_ids')}")
            print(f"Number of Claims: {len(res.get('claims', []))}")
            print(f"Plain Explanation: {res.get('plain_explanation')}")
            print(f"Legal Assessment: {res.get('legal_assessment')}")

            results.append({
                "case": case["name"],
                "success": "error" not in res,
                "result": res,
            })
        except Exception as e:
            print(f"FAILED with exception: {e}")
            logging.exception("Error running case %s", case["name"])
            results.append({
                "case": case["name"],
                "success": False,
                "error": str(e),
            })

    print("\n" + "=" * 80)
    print("SUMMARY OF LIVE AGENT RUNS")
    print("=" * 80)
    all_passed = True
    for r in results:
        status_str = "PASSED" if r["success"] else "FAILED"
        if not r["success"]:
            all_passed = False
        print(f"- {r['case']}: {status_str}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_live_tests())
