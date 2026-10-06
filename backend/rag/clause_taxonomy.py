"""
Canonical clause-type taxonomy.

The clause dataset (lawgorithm_train.jsonl) labels each clause with its
original section heading -- 179k distinct free-text values like
"non-competition", "non-compete", "covenant not to compete",
"restrictive covenants". That's far too fine-grained (and too
US-securities-heavy) to be useful directly, so every raw heading is
mapped onto one of the canonical types below, or "other".

Each type carries:
  - domain:        employment | rental | general
  - statute_query: a natural-language search hint for the Indian
                   statute corpus. This is ONLY a search query handed
                   to the agent ("look for restraint-of-trade law") --
                   never a legal claim, never citable.
  - risk_prone:    clause types where Indian contracts commonly carry
                   one-sided or legally questionable terms. Used as a
                   hint in the prompt, not to set risk_level directly.

Rules are matched in order, first match wins, so specific patterns
(e.g. "termination for cause") must come before general ones
("termination").
"""

import re
from dataclasses import dataclass

OTHER = "other"


@dataclass(frozen=True)
class ClauseType:
    name: str
    label: str
    domain: str
    statute_query: str
    risk_prone: bool = False


CLAUSE_TYPES: dict[str, ClauseType] = {
    t.name: t
    for t in [
        # --- employment ---
        ClauseType("non_compete", "Non-compete", "employment",
                   "agreement in restraint of trade lawful profession void post-employment non-compete", True),
        ClauseType("non_solicitation", "Non-solicitation", "employment",
                   "restraint of trade non-solicitation of employees or customers after employment", True),
        ClauseType("confidentiality", "Confidentiality", "general",
                   "confidential information obligations breach of contract damages"),
        ClauseType("intellectual_property", "Intellectual property / inventions", "employment",
                   "ownership of work created during employment copyright assignment"),
        ClauseType("non_disparagement", "Non-disparagement", "employment",
                   "restriction on statements about employer after termination", True),
        ClauseType("salary_compensation", "Salary & compensation", "employment",
                   "payment of wages timely payment deductions from wages"),
        ClauseType("bonus_incentive", "Bonus & incentives", "employment",
                   "payment of bonus eligibility employee"),
        ClauseType("equity_awards", "Stock / equity awards", "employment",
                   "employee stock option vesting forfeiture"),
        ClauseType("benefits_leave", "Benefits & leave", "employment",
                   "leave entitlement gratuity provident fund employee benefits"),
        ClauseType("duties_position", "Position, duties & working hours", "employment",
                   "working hours duties of employee standing orders"),
        ClauseType("probation", "Probation", "employment",
                   "probation period confirmation of employment termination during probation"),
        ClauseType("termination_for_cause", "Termination for cause / misconduct", "employment",
                   "dismissal for misconduct standing orders inquiry termination", True),
        ClauseType("termination_notice", "Termination & notice period", "general",
                   "notice period termination of contract retrenchment compensation", True),
        ClauseType("severance", "Severance", "employment",
                   "retrenchment compensation gratuity on termination of employment"),
        ClauseType("clawback_forfeiture", "Clawback / forfeiture", "employment",
                   "forfeiture of wages penalty deduction recovery from employee", True),
        ClauseType("expense_reimbursement", "Expense reimbursement", "employment",
                   "reimbursement of expenses incurred by employee"),
        ClauseType("return_of_property", "Return of property", "employment",
                   "return of employer property on termination"),
        ClauseType("outside_activities", "Exclusivity / outside activities", "employment",
                   "exclusive service restriction on other employment during term", True),
        ClauseType("tax_withholding", "Tax withholding", "general",
                   "tax deduction at source on salary withholding"),
        # --- rental / property ---
        ClauseType("rent_payment", "Rent & payment", "rental",
                   "payment of rent due date revision of rent tenant obligations"),
        ClauseType("security_deposit", "Security deposit", "rental",
                   "security deposit limit refund tenant tenancy", True),
        ClauseType("lease_term_renewal", "Lease term & renewal", "rental",
                   "duration of tenancy renewal registration of lease", False),
        ClauseType("use_of_premises", "Use of premises", "rental",
                   "tenant use of premises restrictions purpose"),
        ClauseType("maintenance_repairs", "Maintenance & repairs", "rental",
                   "landlord tenant repairs maintenance responsibilities"),
        ClauseType("utilities", "Utilities & charges", "rental",
                   "electricity water charges essential supply tenant"),
        ClauseType("subletting", "Assignment / subletting", "rental",
                   "tenant sub-letting without consent of landlord", True),
        ClauseType("alterations", "Alterations", "rental",
                   "tenant structural alterations without landlord consent"),
        ClauseType("landlord_access", "Landlord entry / access", "rental",
                   "landlord entry into premises notice to tenant", True),
        ClauseType("surrender_holding_over", "Surrender / holding over", "rental",
                   "tenant holding over after expiry compensation vacate premises", True),
        ClauseType("eviction_default", "Eviction / landlord remedies", "rental",
                   "eviction of tenant grounds recovery of possession", True),
        ClauseType("late_payment_interest", "Late fees & interest", "general",
                   "interest on delayed payment penalty for late payment", True),
        # --- general contract ---
        ClauseType("governing_law", "Governing law", "general",
                   "governing law of contract jurisdiction"),
        ClauseType("dispute_resolution", "Arbitration / dispute resolution", "general",
                   "arbitration agreement dispute resolution", True),
        ClauseType("jurisdiction_venue", "Jurisdiction & venue", "general",
                   "agreement restricting legal proceedings jurisdiction of courts", True),
        ClauseType("jury_waiver", "Jury trial waiver", "general",
                   "waiver of right to legal proceedings"),
        ClauseType("indemnification", "Indemnification", "general",
                   "contract of indemnity rights of indemnity holder", True),
        ClauseType("limitation_of_liability", "Limitation of liability", "general",
                   "limitation of liability compensation for loss caused by breach", True),
        ClauseType("liquidated_damages_penalty", "Liquidated damages / penalty", "general",
                   "compensation for breach of contract where penalty stipulated", True),
        ClauseType("force_majeure", "Force majeure", "general",
                   "frustration of contract impossibility of performance"),
        ClauseType("release_waiver_of_claims", "Release / waiver of claims", "general",
                   "release of claims waiver of statutory rights", True),
        ClauseType("assignment", "Assignment", "general",
                   "assignment of contract rights and obligations"),
        ClauseType("amendment", "Amendment", "general",
                   "modification of contract by agreement"),
        ClauseType("waiver", "Waiver", "general",
                   "waiver of performance of promise"),
        ClauseType("notices", "Notices", "general",
                   "service of notice under contract"),
        ClauseType("severability", "Severability", "general",
                   "agreement void in part enforceability of remainder"),
        ClauseType("entire_agreement", "Entire agreement", "general",
                   "entire agreement prior oral agreements"),
        ClauseType("boilerplate", "Boilerplate (counterparts, headings, definitions)", "general",
                   "execution of contract interpretation"),
        ClauseType("representations_warranties", "Representations & warranties", "general",
                   "misrepresentation consent free consent"),
        ClauseType("insurance", "Insurance", "general",
                   "insurance obligations"),
        ClauseType("term_duration", "Term / duration", "general",
                   "duration of contract term"),
        ClauseType(OTHER, "Other", "general", ""),
    ]
}


def _p(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


# (compiled pattern, canonical type) -- ORDER MATTERS, first match wins.
LABEL_RULES: list[tuple[re.Pattern, str]] = [
    # Lending / securities headings that would otherwise be caught by
    # generic words below ("rent" in "different", "notice" in "notice of
    # borrowing", "interest" in "security interest").
    (_p(r"lend|borrow|loan|letter of credit|swing line|collateral|security interest|lien|"
        r"securities|warrant|note\b|notes\b|prepayment|swap|indebtedness|libor|sofr|"
        r"administrative agent|investment company|stockholder|shareholder|dividend|"
        r"registration rights|purchaser|accredited|offering|gaap|financial statements|"
        r"erisa|patriot act|ofac|sanctions|anti-corruption|money laundering|409a|fatca|principal|"
        r"saturdays|certificates for reimbursement|reviewer|labor disputes|calculation dispute|"
        r"exclusive remed|non-?exclusivity|press release|release of (guarantor|document|collateral)|"
        r"deposit account|direct deposit|delegation of duties|disposition"), OTHER),
    (_p(r"non[- ]?compet|not to compete|covenant against competition|competitive activit"), "non_compete"),
    (_p(r"non[- ]?solicit|no[- ]?solicit|no hire|no-hire|non[- ]?hire|solicitation of (employees|customers)"),
     "non_solicitation"),
    (_p(r"non[- ]?disparag"), "non_disparagement"),
    (_p(r"restrictive covenant"), "non_compete"),
    (_p(r"confidential|non[- ]?disclosure|proprietary information|trade secret"), "confidentiality"),
    (_p(r"intellectual property|invention|work (made )?for hire|work product|patent|copyright"),
     "intellectual_property"),
    (_p(r"clawback|claw-back|recoup|forfeit"), "clawback_forfeiture"),
    (_p(r"severance|separation pay|termination (payment|benefit)s?"), "severance"),
    (_p(r"probation"), "probation"),
    (_p(r"(?<!without )\bcause\b|misconduct|gross negligence"), "termination_for_cause"),
    (_p(r"notice period|garden leave|resignation|termination|terminat|notice of termination|"
        r"without cause|good reason|at[- ]will|separation from service"), "termination_notice"),
    (_p(r"restricted stock|stock option|\bvest|performance (share|unit)|equity award|"
        r"equity compensation|\boption\b|exercise price|\brsu"), "equity_awards"),
    (_p(r"\bbonus|incentive"), "bonus_incentive"),
    (_p(r"salary|\bwages?\b|compensation|remuneration|\bpay\b"), "salary_compensation"),
    (_p(r"benefit of (this |the )?agreement|beneficiar"), "assignment"),
    (_p(r"vacation|leave of absence|sick leave|paid leave|holiday|\bbenefits?\b|retirement|"
        r"pension|gratuity|provident"), "benefits_leave"),
    (_p(r"\bposition\b|^duties|duties and|of duties|nature of duties|working hours|hours of work|"
        r"place of (work|employment)|responsibilities|\btitle and"), "duties_position"),
    (_p(r"outside (activities|employment|business)|^other activities$|exclusive (service|employment)|"
        r"exclusivity|moonlight|conflicts? of interest|full time and attention"), "outside_activities"),
    (_p(r"reimburse|business expenses|travel expenses"), "expense_reimbursement"),
    (_p(r"return of (company )?(property|materials|documents)"), "return_of_property"),
    (_p(r"withholding|tax(es)? withh"), "tax_withholding"),
    # rental -- word-boundary "rent" so "different"/"current" don't match
    (_p(r"security deposit|^deposits?$|tenant.{0,20}deposit"), "security_deposit"),
    (_p(r"\bsubl[eo]t|sub-?lease|assignment (and|or) sublet|subletting"), "subletting"),
    (_p(r"holding over|holdover|surrender of (the )?premises|surrender|yield up|vacat"),
     "surrender_holding_over"),
    (_p(r"\brent\b|\brental\b|base rent|additional rent|rent escalation"), "rent_payment"),
    (_p(r"use of (the )?premises|permitted use|\buse\b$"), "use_of_premises"),
    (_p(r"repair|maintenance of (the )?premises|upkeep"), "maintenance_repairs"),
    (_p(r"utilit|electricity|water charges"), "utilities"),
    (_p(r"alteration|improvements"), "alterations"),
    (_p(r"landlord'?s? (right of )?(entry|access)|access to (the )?premises|right of entry|inspection of premises"),
     "landlord_access"),
    (_p(r"eviction|re-?entry|landlord'?s? remedies|tenant'?s? default"), "eviction_default"),
    (_p(r"renewal|extension of (the )?(lease|term)|lease term|term of lease|option to extend"),
     "lease_term_renewal"),
    (_p(r"late (fee|charge|payment)|default interest|interest on (late|overdue)"),
     "late_payment_interest"),
    # general
    (_p(r"jury"), "jury_waiver"),
    (_p(r"arbitra|dispute|mediat"), "dispute_resolution"),
    (_p(r"governing law|choice of law|^applicable law|law governing"), "governing_law"),
    (_p(r"jurisdiction|venue|forum|service of process"), "jurisdiction_venue"),
    (_p(r"indemn|hold harmless"), "indemnification"),
    (_p(r"limitation (of|on) liabilit|consequential damages|exculpat"), "limitation_of_liability"),
    (_p(r"liquidated damages|penalt"), "liquidated_damages_penalty"),
    (_p(r"force majeure|act of god"), "force_majeure"),
    (_p(r"release|waiver of claims|covenant not to sue"), "release_waiver_of_claims"),
    (_p(r"assign|successors"), "assignment"),
    (_p(r"amend|modification"), "amendment"),
    (_p(r"waiver|no waiver|failure.*not waiver"), "waiver"),
    (_p(r"notice"), "notices"),
    (_p(r"severab|partial invalidity|savings clause"), "severability"),
    (_p(r"entire agreement|integration|complete agreement|prior agreements"), "entire_agreement"),
    (_p(r"counterpart|heading|caption|definition|defined terms|interpretation|construction|"
        r"gender|titles|recitals|further assurances|survival|binding effect|effective date"),
     "boilerplate"),
    (_p(r"representation|warrant"), "representations_warranties"),
    (_p(r"insurance"), "insurance"),
    (_p(r"^term$|term of (agreement|employment)|duration"), "term_duration"),
]


def normalize_label(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().lower().rstrip(".:;"))


def canonical_type(raw_label: str) -> str:
    """Maps a raw section-heading label onto a CLAUSE_TYPES key (or "other")."""
    label = normalize_label(raw_label)
    if not label:
        return OTHER
    for pattern, type_name in LABEL_RULES:
        if pattern.search(label):
            return type_name
    return OTHER


def get_clause_type(name: str | None) -> ClauseType | None:
    return CLAUSE_TYPES.get(name) if name else None
