# Leapvoy: Default Email Template (FINAL · v1)

> Approved 29 Sep 2026 · based on Chetan's 3 real sample emails
> Default for every user who hasn't added their own template

---

## 1. Template
```
Subject: Application for {role} - {full_name}{subject_extras}

Dear {hr_name_or_team},

I am writing to apply for the {role} role at {company}. {opening_line}

Why I am a strong fit:

{fit_bullets}

{closing_line}

GitHub: {github_url}
LinkedIn: {linkedin_url}

I have attached my resume and look forward to hearing from you.

Best regards,
{full_name}
{phone}
```
Code version: `docs/templates/default_email.j2` (Jinja2, tested)

---

## 2. Placeholders

**Fixed: from profile (never changed by AI)** → `docs/templates/profile.seed.json`
| Placeholder | Value |
|---|---|
| `{full_name}` | Chetan Mahajan |
| `{phone}` | 9000000000 |
| `{github_url}` | https://github.com/ChetanMahajan715 |
| `{linkedin_url}` | https://www.linkedin.com/in/chetanmahajan715/ |

**From the job post**
| Placeholder | Rule |
|---|---|
| `{role}` | Exact role name from post |
| `{company}` | Exact company name from post (no double full stop if it ends in "Inc.") |
| `{hr_name_or_team}` | HR first name if known, else **Hiring Team** |
| `{subject_extras}` | ` \| {City} \| Immediate Joiner` only when job city = home city or post asks for immediate joiners; else empty |
| Subject override | If the post asks for a specific subject / Job ID → use that exactly |

**Written by AI (resume facts only)**
| Placeholder | Rule |
|---|---|
| `{opening_line}` | 1 sentence: "The focus on {top 3–4 post skills} maps closely to my background." + ", and I am based in {city} and available to join immediately" when true |
| `{fit_bullets}` | 3–5 bullets · `- {Post requirement}: {proof from resume}` · same order as post · post's own words as labels |
| `{closing_line}` | "I am a {education}, {availability}, and {location_phrase}." |
| `{location_phrase}` | same city → "based in {city}" · other city → "open to relocating to {city}" · remote → "comfortable working remotely" |

---

## 3. AI writing rules
- Only facts from the resume → no invented skills, tools, numbers
- Auto-check: any skill/tool not in resume → reject + regenerate
- Strongest proof first: BankAssist · LexIQ · LangGraph multi-agent project · Vcity Soft Solutions internship · Chest X-Ray DenseNet121 (97.8%) · AWS (EC2, CI/CD, S3, CloudWatch; Cloud Practitioner, re/Start)
- Use the post's wording for bullet labels
- 150–220 words total
- Plain text · no emojis · no bold · no HTML
- Avoid vague claims ("production-grade", "expert")
- Temperature ~0.3

---

## 4. Fit check shown before the email (job card)
| Requirement | Your fit | Note |
|---|---|---|
| e.g. Python | Strong | Core skill |
| e.g. MLOps | Moderate | AWS CI/CD, EC2 |

- **Verdict:** TOP PRIORITY · STRONG MATCH · APPLY · SKIP
- **Flags:** relocation needed · low stipend · experience gap · location
- **Send to:** HR email(s) found in post

---

## 5. Examples (3 real posts)

### A. Aptino, Inc., Pune (same city, immediate joiner)
```
Subject: Application for AI Engineer (Fresher) - Chetan Mahajan | Pune | Immediate Joiner

Dear Aditi,

I am writing to apply for the AI Engineer (Fresher) role at Aptino, Inc. The focus on GenAI, Agentic AI, LLMs, and MLOps maps closely to my background, and I am based in Pune and available to join immediately.

Why I am a strong fit:

- GenAI and Agentic AI: Built BankAssist, a full-stack RAG banking chatbot, and LexIQ, a legal research assistant, using LangChain, FAISS, ChromaDB, Groq LLaMA 3.3, and Hugging Face Transformers. Also built a multi-agent chatbot using LangGraph for automated document and PPT generation.
- LLMs and AI Frameworks: Hands-on experience with LangChain, LangGraph, Hugging Face, Groq API, FAISS, and ChromaDB across multiple projects.
- Python and AI/ML: Core language across all projects and my internship at Vcity Soft Solutions, including ML pipelines on real-world healthcare and EV battery datasets.
- MLOps and Deployment: Deployed AI applications on AWS EC2 with CI/CD pipelines, S3 integration, and CloudWatch monitoring. AWS Certified Cloud Practitioner and AWS re/Start Graduate.

I am a 2026 batch BCA (Cloud Computing) graduate based in Pune, immediately available, and ready to join at the earliest.

GitHub: https://github.com/ChetanMahajan715
LinkedIn: https://www.linkedin.com/in/chetanmahajan715/

I have attached my resume and look forward to hearing from you.

Best regards,
Chetan Mahajan
9000000000
```
Verdict: **TOP PRIORITY** · Send to: hr@aptino.example

### B. Wentrite Technologies, Chennai (relocation, no HR name)
```
Subject: Application for AI Agent Developer Intern - Chetan Mahajan

Dear Hiring Team,

I am writing to apply for the AI Agent Developer Intern role at Wentrite Technologies Pvt Ltd. The focus on AI agents, LLMs, prompt engineering, and API integrations maps closely to my background.

Why I am a strong fit:

- AI Agents and Agentic Workflows: Built a multi-agent chatbot using LangGraph for automated document and PPT generation, with agents handling planning, generation, and formatting tasks end-to-end.
- LLMs and Prompt Engineering: Designed and optimized prompts for RAG-based systems including BankAssist (banking chatbot) and LexIQ (legal research assistant) using Groq LLaMA 3.3, Hugging Face Transformers, and LangChain.
- API Integrations: Built and integrated REST APIs using FastAPI and Flask, with hands-on JSON handling and external service integrations.
- AI-Powered Automation: Developed end-to-end ML pipelines during my internship at Vcity Soft Solutions, automating data processing and model inference on real-world datasets.
- Debugging and Testing: Hands-on experience debugging LLM agent responses, retrieval pipelines, and API workflows across multiple projects.

I am a 2026 batch BCA (Cloud Computing) graduate, immediately available, and open to relocating to Chennai.

GitHub: https://github.com/ChetanMahajan715
LinkedIn: https://www.linkedin.com/in/chetanmahajan715/

I have attached my resume and look forward to hearing from you.

Best regards,
Chetan Mahajan
9000000000
```
Verdict: **STRONG MATCH** · Flag: Chennai, relocation needed · Send to: hr@wentrite.example

### C. SmartBridge, Noida (internship, HR name known)
```
Subject: Application for AI ML Intern - Chetan Mahajan

Dear Sowmya,

I am writing to apply for the AI ML Intern role at SmartBridge. The focus on Python, AI/ML, and GenAI technologies maps closely to my background.

Why I am a strong fit:

- Python and AI/ML: Built BankAssist, a full-stack RAG banking chatbot, and LexIQ, a legal research assistant, using LangChain, FAISS, ChromaDB, Groq LLaMA 3.3, and Hugging Face Transformers, both deployed end-to-end.
- GenAI and LLM Applications: Hands-on experience building LLM-powered applications, multi-agent systems using LangGraph, and agentic AI workflows.
- ML Pipelines: Built end-to-end ML pipelines during my internship at Vcity Soft Solutions using Python, PyTorch, Scikit-learn, and TensorFlow on real-world healthcare and EV battery datasets.
- Analytical and Problem-Solving Skills: Developed a Chest X-Ray classifier using DenseNet121 achieving 97.8% accuracy.
- Communication: Strong written and spoken English communication skills with experience presenting technical projects.

I am a 2026 batch BCA (Cloud Computing) graduate, immediately available, and open to relocating to Noida.

GitHub: https://github.com/ChetanMahajan715
LinkedIn: https://www.linkedin.com/in/chetanmahajan715/

I have attached my resume and look forward to hearing from you.

Best regards,
Chetan Mahajan
9000000000
```
Verdict: **APPLY** · Flags: Noida, relocation needed; ₹15,000 stipend is low · Send to: hr@smartbridge.example

> Use these 3 as few-shot style examples and as test cases for the renderer.

---

## 6. Flexibility
- This = **default template** (v1), seeded on first run
- Users add own templates → Settings → Templates (same placeholders, live preview on a real job, set default)
- Per sender ID / per channel template choice
- Change from chat, e.g.:
  - "make my template shorter"
  - "add my portfolio link after LinkedIn"
  - "use 'Hi' instead of 'Dear'"
  - "create a template for Data Scientist jobs"
  - "update my LinkedIn link to …"
- Chat shows before / after preview → **Save** → new version
- All versions kept → restore any time
- Profile values editable in Settings → Profile or via chat (seeded from `profile.seed.json`, which stays private)
- Warn if resume PDF links ≠ profile links
