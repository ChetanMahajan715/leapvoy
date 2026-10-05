from app.mailer.guard import unsupported_claims

RESUME = (
    "Built BankAssist, a RAG chatbot with LangChain, FAISS and Groq LLaMA 3.3 on FastAPI; deployed on AWS EC2 with "
    "CI/CD. Chest X-ray classifier with DenseNet121, 97.8% validation accuracy. Python, PyTorch, SQL, Git. "
    "Internship: up to 7% improvement over baseline. 850+ indexed documents. 2026 batch BCA graduate."
)


def bullets(*proofs):
    return [{"label": "Requirement", "proof": p} for p in proofs]


def test_claims_backed_by_resume_pass():
    assert unsupported_claims(
        bullets("Built BankAssist, a RAG chatbot with LangChain and FAISS on FastAPI, deployed on AWS EC2.",
                "DenseNet121 classifier reaching 97.8% validation accuracy; 850+ indexed documents."),
        "I am a 2026 batch BCA graduate, immediately available.",
        RESUME,
    ) == []


def test_invented_tools_are_caught():
    out = unsupported_claims(bullets("Deployed models with Kubernetes and Docker, tracked with MLflow."), "", RESUME)
    assert out == ["Kubernetes", "Docker", "MLflow"]


def test_invented_numbers_are_caught():
    assert unsupported_claims(bullets("Improved accuracy by 12% and cut latency 40%."), "", RESUME) == ["12%", "40%"]


def test_invented_project_names_are_caught():
    assert unsupported_claims(bullets("Built ResumeGPT, an agent for job search."), "", RESUME) == ["ResumeGPT"]


def test_labels_use_post_wording_and_are_not_checked():
    b = [{"label": "Kubernetes and MLOps", "proof": "Deployed AI apps on AWS EC2 with CI/CD."}]
    assert unsupported_claims(b, "", RESUME) == []


def test_closing_line_is_checked_too():
    assert unsupported_claims([], "I am a 2025 batch B.Tech graduate.", RESUME) == ["2025"]


def test_profile_facts_count_as_supported():
    closing = "I am a 2026 batch BCA (Cloud Computing) graduate, immediately available."
    resume = "Bachelor of Computer Applications in Cloud Computing, 2023 – 2026"
    assert unsupported_claims([], closing, resume) == ["BCA"]
    assert unsupported_claims([], closing, resume, profile_text="2026 batch BCA (Cloud Computing) graduate") == []


def test_opening_line_claims_are_checked_too():
    out = unsupported_claims([], "", RESUME, opening_line="The focus on Python, SQL and .NET maps closely to my background.")
    assert out == ["NET"]
