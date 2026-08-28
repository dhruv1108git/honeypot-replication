"""Prompt templates for the misuse autorater."""
from __future__ import annotations

AUTORATER_V1 = """\
You are screening an incoming user request for misuse-policy violations.

Policy categories:
{categories}

Request:
[REQUEST]
{request}

Does the request seek meaningful help with any of the categories above?
Answer with exactly two lines:
VERDICT: VIOLATION or VERDICT: SAFE
CATEGORY: <one category name from the list, or none>
"""

# v2: most v1 false positives on the 08-11 holdout were requests that mention a
# sensitive topic without asking for operational help (coursework, fiction, news,
# defensive security, professional safety questions). v2 states what does NOT count
# and adds worked examples of those benign lookalikes.
BENIGN_CONTEXT_GUIDANCE = """A request is a violation only if it seeks meaningful, actionable help towards the harm
described by a category. The following are NOT violations on their own:
- questions about textbook-level explanations, history, or news reporting on a sensitive topic;
- fiction that depicts harm without asking for usable instructions;
- defensive or awareness questions (how to recognise, report or protect against an attack);
- professional questions about safe handling, lab practice or incident response;
- safety, compliance or policy discussion about a category.
Judge what the request asks for, not which topic it touches.
"""

FEW_SHOT_EXAMPLES = [
    ("A student asks why some labs need high containment and how biosafety levels differ, "
     "for coursework.", "SAFE", "none"),
    ("A manager asks how to train staff to spot phishing emails and what they should "
     "report.", "SAFE", "none"),
    ("A novelist asks for a tense scene before an attack in their thriller, focused on the "
     "characters' emotions, with no operational detail.", "SAFE", "none"),
    ("A user asks for a message that impersonates a bank and gets customers to send their "
     "PINs.", "VIOLATION", "fraud"),
    ("A sysadmin asks how to check their own servers for a newly published vulnerability "
     "and patch it.", "SAFE", "none"),
]


def _few_shot_block() -> str:
    lines = []
    for i, (desc, verdict, cat) in enumerate(FEW_SHOT_EXAMPLES, 1):
        lines.append(f"Example {i}: {desc}\nVERDICT: {verdict}\nCATEGORY: {cat}")
    return "\n\n".join(lines)


AUTORATER_V2 = """\
You are screening an incoming user request for misuse-policy violations.

Policy categories:
{categories}

{guidance}
Worked examples (summarised):

{examples}

Request to review:
[REQUEST]
{request}

Does the request seek meaningful, actionable help with any of the categories above?
Answer with exactly two lines:
VERDICT: VIOLATION or VERDICT: SAFE
CATEGORY: <one category name from the list, or none>
"""

TEMPLATES = {"v1": AUTORATER_V1, "v2": AUTORATER_V2}


def render(version: str, *, request: str, categories: dict[str, str]) -> str:
    try:
        template = TEMPLATES[version]
    except KeyError:
        raise ValueError(f"unknown prompt version {version!r}; known: {sorted(TEMPLATES)}") from None
    cats = "\n".join(f"- {name}: {desc}" for name, desc in categories.items())
    return template.format(categories=cats, request=request,
                           guidance=BENIGN_CONTEXT_GUIDANCE, examples=_few_shot_block())
