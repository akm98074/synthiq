"""
Shared pytest fixtures for Phase 2 ingestion tests.
"""
import pytest


@pytest.fixture
def short_text() -> str:
    return "This is a short document. It has two sentences."


@pytest.fixture
def multi_paragraph_text() -> str:
    paragraphs = [
        "The Federal Reserve raised interest rates by 25 basis points in March 2024.",
        "Goldman Sachs revised its GDP forecast for the United States downward to 1.8%.",
        "Inflation remains above the Fed's 2% target despite recent cooling in CPI data.",
        "European Central Bank President Christine Lagarde signaled a pause in rate hikes.",
        "Emerging markets including Brazil and India showed resilience amid global headwinds.",
    ]
    return "\n\n".join(paragraphs)


@pytest.fixture
def long_text() -> str:
    """A single long paragraph exceeding TARGET_CHARS."""
    return (
        "Artificial intelligence is transforming every sector of the global economy. "
        "From healthcare to finance, education to manufacturing, AI-powered systems are "
        "automating repetitive tasks, augmenting human decision-making, and uncovering "
        "patterns in data that would be invisible to human analysts. Large language models "
        "like GPT-4 and Claude are being deployed in customer service, legal research, "
        "medical diagnosis, and software development. Computer vision systems can now "
        "outperform radiologists in detecting certain cancers from medical imaging. "
        "Recommendation engines drive billions in e-commerce revenue annually. "
        "Autonomous vehicles promise to reshape urban planning and logistics. "
        "Meanwhile, the regulatory landscape is evolving rapidly as governments in the EU, "
        "United States, and China grapple with how to govern these powerful technologies. "
        "The EU AI Act establishes risk-based tiers of regulation. The US Executive Order "
        "on AI safety requires frontier model developers to share safety evaluations with "
        "the government. China's regulations focus on algorithmic recommendation systems "
        "and deepfake content. Academic researchers are sounding alarms about job "
        "displacement, algorithmic bias, and the concentration of AI capabilities in a "
        "handful of large technology corporations. OpenAI, Anthropic, Google DeepMind, "
        "and Meta AI command most of the frontier model research talent. Startup ecosystems "
        "in San Francisco, London, and Tel Aviv are racing to build applications on top of "
        "these foundation models. Venture capital investment in AI reached $50 billion "
        "globally in 2023, with enterprise AI SaaS companies capturing a growing share. "
        "The next decade will likely determine whether AI delivers broadly shared prosperity "
        "or concentrates gains among a narrow set of shareholders and geographies."
    ) * 3  # Repeat to exceed 2000-char target
