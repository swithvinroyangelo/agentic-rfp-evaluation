"""Build the four fictional supplier proposal PDFs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fpdf import FPDF

REQUIRED_SECTIONS = (
    "Executive summary and understanding of the requirement",
    "Proposed solution and implementation approach",
    "Timeline, team structure and milestones",
    "Price table with assumptions",
    "Security, compliance and risk controls",
    "Support model, relevant experience and references",
)

PROPOSAL_FILENAMES = (
    "apex_systems.pdf",
    "brightpath_tech.pdf",
    "nexaworks.pdf",
    "orbit_digital.pdf",
)

_CREATED_AT = datetime(2026, 1, 15, 9, 0, 0)
_REQUEST = (
    "This fictional proposal responds to the classroom procurement for a "
    "municipal records platform. Every organization, price, and reference below is invented."
)

# Bodies are short on purpose so each file stays within 2 to 4 pages.
_PROPOSALS: dict[str, dict[str, list[str]]] = {
    "apex_systems.pdf": {
        "supplier": "Apex Systems",
        "sections": {
            "Executive summary and understanding of the requirement": [
                _REQUEST,
                "Apex Systems understands the buyer needs a reliable records platform with clear integrations and audit history.",
                "Apex technical design uses a documented integration hub.",
                "Apex fixed price is 480000 fictional units.",
                "Apex delivery schedule is a moderate 16 weeks.",
            ],
            "Proposed solution and implementation approach": [
                "The proposed design is a modular hub, an API gateway, and separate workers for search and storage.",
                "Interfaces are described for the fictional clerk portal and the fictional archive store.",
                "Scalability is addressed with horizontal workers. No live customer system is described.",
            ],
            "Timeline, team structure and milestones": [
                "The schedule is moderate: design in weeks 1 to 4, build in weeks 5 to 12, and trial in weeks 13 to 16.",
                "The fictional team is one lead architect, two engineers, and one part-time tester.",
                "Milestones are design sign-off, integration demo, and trial readiness.",
            ],
            "Price table with assumptions": [
                "Discovery 60000. Build 300000. Trial support 120000. Total 480000 fictional units.",
                "Assumptions: one environment, weekday workshops, and no data migration from a real agency.",
                "This is the highest price among the four fictional bids.",
            ],
            "Security, compliance and risk controls": [
                "Apex security controls are described in detail.",
                "Proposed controls are encryption in transit, role-based access, and an audit log.",
                "No real certification is claimed.",
                "The main risk is the moderate schedule slipping if workshop decisions are late.",
            ],
            "Support model, relevant experience and references": [
                "Support is weekday hours with a fictional on-call rota after go-live.",
                "Experience is two invented projects for the fictional Cedar Archive and the fictional Lake Office.",
                "References are those two invented offices. They are not real organizations.",
            ],
        },
    },
    "brightpath_tech.pdf": {
        "supplier": "BrightPath Tech",
        "sections": {
            "Executive summary and understanding of the requirement": [
                _REQUEST,
                "BrightPath Tech offers a small team and a short calendar for a basic records site.",
                "BrightPath fixed price is 190000 fictional units.",
                "BrightPath timeline is a fast 8 weeks.",
            ],
            "Proposed solution and implementation approach": [
                "The approach is a single hosted application with a simple upload form and keyword search.",
                "Integration is limited to one fictional export file. A broader hub is not designed here.",
            ],
            "Timeline, team structure and milestones": [
                "Week 1 is setup, weeks 2 to 6 are build, and weeks 7 to 8 are a short trial.",
                "The fictional team is two generalists. There is no separate security specialist.",
                "The only milestone called out is a trial login.",
            ],
            "Price table with assumptions": [
                "Build 150000. Short trial 40000. Total 190000 fictional units.",
                "Assumptions: no migration, no custom reports, and remote workshops only.",
                "This is the lowest price among the four fictional bids.",
            ],
            "Security, compliance and risk controls": [
                "BrightPath compliance detail is limited.",
                "The proposal says access will use passwords. It does not describe audit, privacy review, or control evidence.",
                "No real certification is claimed.",
                "Detailed compliance evidence is not included.",
            ],
            "Support model, relevant experience and references": [
                "BrightPath relevant experience is limited.",
                "The only invented example is a two-week workshop for the fictional Mill Club.",
                "No additional references are offered. The Mill Club is not a real organization.",
            ],
        },
    },
    "nexaworks.pdf": {
        "supplier": "NexaWorks",
        "sections": {
            "Executive summary and understanding of the requirement": [
                _REQUEST,
                "NexaWorks submits a balanced design, a careful plan, and a staffed support model.",
                "NexaWorks balanced price is 320000 fictional units.",
            ],
            "Proposed solution and implementation approach": [
                "The solution uses a documented portal, a records store, and one integration adapter.",
                "The approach is balanced: enough design to start, with room to adjust during the plan.",
            ],
            "Timeline, team structure and milestones": [
                "NexaWorks implementation plan is the most detailed.",
                "Weeks 1 to 2 discovery, 3 to 4 design, 5 to 10 build, 11 to 12 rehearsal, and 13 to 14 trial.",
                "Roles are a delivery lead, a planner, two engineers, a tester, and a support lead.",
                "Each milestone has an owner, an exit check, and a listed risk response.",
            ],
            "Price table with assumptions": [
                "Discovery 40000. Build 200000. Rehearsal 40000. Support setup 40000. Total 320000 fictional units.",
                "Assumptions: two environments and weekly steering meetings. Prices are fictional.",
            ],
            "Security, compliance and risk controls": [
                "Controls cover access roles, backup, and a privacy note.",
                "No real certification is claimed.",
                "Risks include late content samples and are paired with a fallback task in the plan.",
            ],
            "Support model, relevant experience and references": [
                "NexaWorks support model has a named escalation path.",
                "The path is service desk, support lead, then delivery lead, on fictional weekdays and a limited weekend rota.",
                "Experience is one invented records project for the fictional Westbend Registry. That registry is not real.",
            ],
        },
    },
    "orbit_digital.pdf": {
        "supplier": "Orbit Digital",
        "sections": {
            "Executive summary and understanding of the requirement": [
                _REQUEST,
                "Orbit Digital emphasizes prior fictional work and a medium commercial offer.",
                "Orbit medium price is 340000 fictional units.",
            ],
            "Proposed solution and implementation approach": [
                "Orbit integration plan stays vague pending discovery.",
                "The text says the platform will connect to buyer systems later. It does not name interfaces, data fields, or an integration pattern.",
                "The rest of the solution is a standard records screen and search box.",
            ],
            "Timeline, team structure and milestones": [
                "The schedule is 14 weeks: familiarization, build, and a trial.",
                "The fictional team is a manager and three engineers who have worked together on invented projects.",
            ],
            "Price table with assumptions": [
                "Familiarization 50000. Build 220000. Trial 70000. Total 340000 fictional units.",
                "The price sits between the lowest and highest fictional bids.",
                "Assumptions: scope stays at the screens described and integration detail is deferred.",
            ],
            "Security, compliance and risk controls": [
                "Controls mentioned are login accounts and nightly backup.",
                "No real certification is claimed.",
                "The integration risk is left open because the integration plan is not specific.",
            ],
            "Support model, relevant experience and references": [
                "Orbit cites three fictional references.",
                "They are the fictional North Station Archive, the fictional Red Lantern Office, and the fictional Glasshouse Museum.",
                "None of those organizations is real. Support is a named fictional account manager on weekdays.",
            ],
        },
    },
}


def generate_sample_proposals(output_dir: Path | str) -> list[Path]:
    """Write the four fictional PDFs. Running this again overwrites them with the same content."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename in PROPOSAL_FILENAMES:
        proposal = _PROPOSALS[filename]
        path = destination / filename
        _write_proposal(path, proposal["supplier"], proposal["sections"])
        written.append(path)
    return written


def _write_proposal(path: Path, supplier_name: str, sections: dict[str, list[str]]) -> None:
    pdf = FPDF(format="A4")
    pdf.set_creation_date(_CREATED_AT)
    pdf.set_title(f"Fictional proposal from {supplier_name}")
    pdf.set_author("Fictional classroom supplier")
    pdf.set_creator("agentic-rfp-evaluation")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    groups = (
        REQUIRED_SECTIONS[:2],
        REQUIRED_SECTIONS[2:4],
        REQUIRED_SECTIONS[4:],
    )
    for index, headings in enumerate(groups):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        if index == 0:
            pdf.multi_cell(0, 8, f"{supplier_name} fictional proposal")
            pdf.ln(2)
            pdf.set_font("Helvetica", "I", 10)
            pdf.multi_cell(0, 5, "Fictional classroom proposal. Not a real bid.")
            pdf.ln(3)
        for heading in headings:
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 7, heading)
            pdf.ln(1)
            pdf.set_font("Helvetica", "", 11)
            for paragraph in sections[heading]:
                pdf.multi_cell(0, 6, paragraph)
                pdf.ln(1)
            pdf.ln(2)
    pdf.output(path)
