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
