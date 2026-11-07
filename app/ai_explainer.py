
import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


def explain_finding(finding: dict) -> dict[str, str]:
    api_key = os.getenv("GEMINI_API_KEY")

    fallback = finding.get(
        "explanation",
        "AI explanation is unavailable. Review the diagnostic evidence.",
    )

    if not api_key:
        return {
            "source": "rule-based",
            "explanation": fallback,
        }

    prompt = f"""
You are KubeSage, an expert Kubernetes troubleshooting assistant.

Explain this diagnostic finding for a DevOps engineer.
Use only the supplied evidence. Do not invent cluster facts.

Include:
1. Likely cause
2. Potential impact
3. Safe troubleshooting steps

Do not recommend destructive actions without a warning.
Keep the response concise and practical.

Diagnostic finding:
{json.dumps(finding, indent=2)}
"""

    try:
        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
        )

        if response.text:
            return {
                "source": "gemini",
                "explanation": response.text.strip(),
            }

        return {
            "source": "rule-based",
            "explanation": fallback,
        }

    except Exception as exc:
        print(f"Gemini explanation error: {type(exc).__name__}: {exc}")

        return {
            "source": "rule-based",
            "explanation": fallback,
        }
