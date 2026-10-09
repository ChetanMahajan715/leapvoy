"""Fake-skill check: the AI's proof sentences may only name tools, projects and numbers that are in the resume.

Bullet labels are not checked: they deliberately repeat the job post's wording ("MLOps and Deployment").
"""

import re

# common tools/tech written as ordinary words (CamelCase / ACRONYM / numbers are caught by pattern)
VOCAB = {
    "python", "java", "javascript", "typescript", "golang", "rust", "scala", "kotlin", "swift", "php", "ruby",
    "react", "angular", "vue", "node", "express", "django", "flask", "spring", "streamlit", "gradio",
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "airflow", "kafka", "spark", "hadoop", "databricks",
    "snowflake", "bigquery", "redshift", "azure", "gcp", "lambda", "sagemaker", "bedrock", "vertex",
    "mlflow", "kubeflow", "langchain", "langgraph", "llamaindex", "autogen", "crewai", "pinecone", "weaviate",
    "milvus", "qdrant", "chroma", "faiss", "redis", "mongodb", "postgresql", "postgres", "mysql", "cassandra",
    "elasticsearch", "tableau", "excel", "keras", "pytorch", "tensorflow", "jax", "xgboost", "lightgbm", "catboost",
    "opencv", "yolo", "bert", "gpt", "llama", "mistral", "gemini", "claude", "whisper", "nginx", "linux", "git",
    "github", "gitlab", "jira", "figma", "selenium", "pandas", "numpy", "matplotlib", "seaborn", "nltk", "spacy",
}
ALLOW = {"i", "ai", "ml"}
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?%?")
WORD = re.compile(r"[A-Za-z][\w+#./-]*[\w+#]|[A-Za-z]")


def _looks_like_a_name(tok: str) -> bool:
    return (
        tok.lower() in VOCAB
        or bool(re.search(r"[a-z][A-Z]|[A-Z]{2,}[a-z]", tok))  # LangChain, FastAPI, MLflow, ResumeGPT
        or bool(re.fullmatch(r"[A-Z][A-Z0-9/&]+", tok))  # AWS, EC2, RAG, CI/CD
    )


def _in(term: str, resume_lower: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", resume_lower))


# a bullet label is a skill or requirement, never something the post asks the applicant to DO
_INSTRUCTION = re.compile(
    r"\b(send|share|apply|applying|mail|email|e-mail|cv|resume|subject|contact|deadline|dm|forward|whatsapp|"
    r"call|reach out|refer|referral|form|link|portal|submit|mention|attach|interested|eligible|batch|"
    r"office|onsite|on-site|hybrid|remote|wfh|days?|week|weekly|month|months|duration|stipend|salary|ctc|lpa|"
    r"shift|timing|timings|notice|joining|join|location|relocat\w*|years?)\b", re.I)
_STOP = set("""a an the and or of in on at to for with by from as into over across using used use via per is are was
were be been being this that these those it its my i me we our you your their them which who what when where how
also both each all any more most other such than then so very can could would should will built build building
developed develop designed design created create made make implemented working worked work hands-on experience
strong solid real end-to-end end through""".split())


_GENERIC = _STOP | set("""ai ml applications application systems system development developer engineering engineer
skills skill knowledge understanding real world real-world good tools tool solutions solution based hands
problem-solving problem solving ownership mindset communication teamwork learning fast quick""".split())


def unbacked_labels(fit_bullets: list[dict], resume_text: str) -> list[str]:
    """Labels that name nothing the resume shows ("AI coding tools", "Problem-Solving and Ownership"): at least one
    real word of the label must be in the resume. Generic words (AI, applications, skills...) don't count."""
    resume_lower = resume_text.lower()
    bad = []
    for b in fit_bullets:
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9+#./-]*[a-z0-9+#]|[a-z0-9]", b["label"].lower())
                 if w not in _GENERIC and len(w) > 1]
        if not any(_in(w, resume_lower) or _stem_in(w, resume_lower) for w in words):
            bad.append(b["label"])
    return bad


def _stem_in(word: str, resume_lower: str) -> bool:
    """'deployment' matches 'deployed', 'pipelines' matches 'pipeline': same stem, any ending."""
    stem = re.sub(r"(ments?|ings?|ions?|ers?|ed|es|s)$", "", word)
    return len(stem) >= 4 and bool(re.search(rf"(?<![a-z0-9]){re.escape(stem)}[a-z]*", resume_lower))


def instruction_labels(fit_bullets: list[dict]) -> list[str]:
    """Labels that are instructions from the post ("Send resume", "Apply via form"), not skills."""
    return [b["label"] for b in fit_bullets if _INSTRUCTION.search(b["label"])]


def ungrounded_proofs(fit_bullets: list[dict], resume_text: str, min_share: float = 0.7) -> list[str]:
    """Proofs whose wording mostly isn't in the resume (an invented description, even with real tool names): at least
    `min_share` of a proof's content words must appear in the resume. Returns their labels."""
    resume_lower = resume_text.lower()
    bad = []
    for b in fit_bullets:
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9+#.-]*[a-z0-9+#]|[a-z0-9]", b["proof"].lower())
                 if len(w) > 2 and w not in _STOP]
        if words and sum(_in(w, resume_lower) or _in(w.rstrip("s"), resume_lower) for w in words) / len(words) < min_share:
            bad.append(b["label"])
    return bad


_HEADING = {"education", "certifications", "experience", "projects", "technical skills", "summary"}


def _project_sections(resume_text: str) -> dict[str, str]:
    """Resume project blocks, keyed by the project's first word: a header line "Name: ... | tools" and the lines
    under it until the next header or section heading. Empty for resumes written another way."""
    sections: dict[str, str] = {}
    key = None
    for line in resume_text.splitlines():
        if " | " in line:
            key = re.split(r"[:\s]", line.strip(), maxsplit=1)[0].lower()
            if not key.isalnum():  # the title / contact lines ("AI/ML Engineer | ...", "linkedin.com/... |")
                key = None
                continue
            sections[key] = line
        elif line.strip().lower() in _HEADING:
            key = None
        elif key:
            sections[key] += "\n" + line
    return sections


def misattributed(fit_bullets: list[dict], resume_text: str) -> list[str]:
    """A proof that names one project but uses a tool or number the resume lists only under ANOTHER project
    (e.g. "Leapvoy ... on AWS EC2" when EC2 belongs to BankAssist). Returns those labels."""
    sections = _project_sections(resume_text)
    bad = []
    for b in fit_bullets:
        proof = b["proof"].lower()
        named = {k for k in sections if re.search(rf"(?<![a-z0-9]){re.escape(k)}", proof)}
        if not named:
            continue
        mine = "\n".join(sections[k] for k in named).lower()
        others = "\n".join(v for k, v in sections.items() if k not in named).lower()
        for m in [*NUMBER.finditer(b["proof"]), *WORD.finditer(b["proof"])]:
            tok = m.group(0).rstrip(".,/-")
            if (tok[0].isdigit() or _looks_like_a_name(tok)) and tok.lower() not in ALLOW \
                    and _in(tok, others) and not _in(tok, mine):
                bad.append(b["label"])
                break
    return bad


def unsupported_claims(
    fit_bullets: list[dict], closing_line: str, resume_text: str, profile_text: str = "", opening_line: str = ""
) -> list[str]:
    """Terms in the AI-written opening/proofs/closing that neither the resume nor the profile contains (empty = OK).
    The opening line counts: "The focus on X maps closely to my background" claims X."""
    text = "\n".join([opening_line, *(b["proof"] for b in fit_bullets), closing_line])
    resume_lower = f"{resume_text}\n{profile_text}".lower()
    found: list[str] = []
    for m in sorted([*NUMBER.finditer(text), *WORD.finditer(text)], key=lambda m: m.start()):
        tok = m.group(0).rstrip(".,/-")
        is_number = tok[0].isdigit()
        if (is_number or _looks_like_a_name(tok)) and tok.lower() not in ALLOW and not _in(tok, resume_lower):
            if tok not in found:
                found.append(tok)
    return found
