"""
Retrieval-augmented generation over NAWASA's FAQ set, backed by Pinecone.

The old app kept FAQS as a hardcoded Python list and did a dumb substring
search (search_faqs()). This replaces that with real semantic search:
each FAQ is embedded with a Gemini embedding model and upserted into a
Pinecone serverless index; at query time the customer's message (or the
agent's own reformulated query) is embedded and matched against it.

Falls back gracefully to local keyword search if PINECONE_API_KEY /
GEMINI_API_KEY aren't set yet, so the rest of the app still runs during
local setup before secrets are configured.
"""
from __future__ import annotations

import logging

from . import config

logger = logging.getLogger("aquaassist.rag")

# ---------------------------------------------------------------------------
# Official NAWASA FAQs (nawasa.gd/nawasa-faqs, customer-facing subset) —
# same source content as the original app, now the seed corpus for Pinecone.
# ---------------------------------------------------------------------------
FAQS = [
    {"id": "faq-001", "category": "New Connections", "q": "How do I apply for a new connection?",
     "a": "Fill out the application for a new service connection. Review the Requirements for Private Water Service and the Terms and Conditions for Water Service on nawasa.gd."},
    {"id": "faq-002", "category": "New Connections", "q": "What is the cost of a new connection?",
     "a": "Connection to half-inch main: $75. Three-quarter-inch main: $125. One-inch main: $175. 1.25/1.5/2-inch main: $420. Four-inch main: $1000. Plus variable costs (transportation, pipes & fittings, VAT) — an estimate is prepared to determine the total."},
    {"id": "faq-003", "category": "New Connections", "q": "How long does it take NAWASA to install a new service?",
     "a": "Per the customer service charter, a new service should be installed within 10 working days after payment of the connection fee."},
    {"id": "faq-004", "category": "New Connections", "q": "I don't own the property, can I still get a connection in my name?",
     "a": "Yes, with written permission from the property owner plus the owner's ID. A security deposit is also required: $240 (Domestic), $340 (Commercial), or $2,000 (Projects) — refundable if you later become the owner or the service is permanently terminated."},
    {"id": "faq-005", "category": "Billing", "q": "How may I change my account name or billing/mailing address?",
     "a": "To change the account name, fill out the application for change of name and provide one of: Title Deed/Conveyance, Death Certificate, Letter from Lawyer, Will, or Court Judgement. To change the mailing address, fill out the Change of Mailing Address Form. A valid picture ID is required for all account changes."},
    {"id": "faq-006", "category": "Billing", "q": "I've been paying my bills, why does my bill show arrears?",
     "a": "Your current bill may have already been issued prior to processing your previous payment."},
    {"id": "faq-007", "category": "Billing", "q": "How are estimated bills calculated?",
     "a": "Estimated bills use an average of your last three months' consumption."},
    {"id": "faq-008", "category": "Water Usage & Leaks", "q": "My water consumption is unusually high, what could be the problem?",
     "a": "High consumption can come from estimated bills, leaks, unsecured taps, or a faulty meter. To check for a leak: turn off all taps and watch the meter dial — if it's still turning, there's a leak. If not, contact Customer Services."},
    {"id": "faq-009", "category": "Disconnection", "q": "Under what circumstances does NAWASA disconnect service?",
     "a": "At the customer's request, for non-payment of arrears, for wastage/abuse, or for illegal tampering of meters and fittings."},
    {"id": "faq-010", "category": "Disconnection", "q": "How do I request a disconnection?",
     "a": "Request in writing or in person using a 'Request for Disconnection' form. Only the account owner or an authorized person (with documentation) can request this, and valid ID is required."},
    {"id": "faq-011", "category": "Disconnection", "q": "What is the minimum balance for disconnection?",
     "a": "A customer can be disconnected once arrears reach at least $50.00 and are at least 30 days overdue."},
    {"id": "faq-012", "category": "Disconnection", "q": "After paying the reconnection fee, how long until reconnection?",
     "a": "Reconnection is not guaranteed within 48 hours after payment of the reconnection fee."},
    {"id": "faq-013", "category": "General", "q": "What does NAWASA mean?",
     "a": "National Water & Sewerage Authority."},
    {"id": "faq-014", "category": "General", "q": "Where is NAWASA's main office?",
     "a": "The main office is on the Carenage, St. George's, with sub-offices in Gouyave, Grenville, Sauteurs, St. David's, and Grand Anse."},
]

_pc_client = None
_index = None
_embeddings = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        _embeddings = GoogleGenerativeAIEmbeddings(
            model=config.GEMINI_EMBED_MODEL, google_api_key=config.GEMINI_API_KEY
        )
    return _embeddings


def _get_index():
    """Lazily connects to Pinecone and returns the FAQ index, creating it
    (serverless, cosine, 768-dim) if it doesn't exist yet."""
    global _pc_client, _index
    if _index is not None:
        return _index
    if not config.PINECONE_API_KEY:
        return None
    from pinecone import Pinecone, ServerlessSpec

    _pc_client = Pinecone(api_key=config.PINECONE_API_KEY)
    existing = [i["name"] for i in _pc_client.list_indexes()]
    if config.PINECONE_INDEX not in existing:
        _pc_client.create_index(
            name=config.PINECONE_INDEX,
            dimension=config.PINECONE_EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud=config.PINECONE_CLOUD, region=config.PINECONE_REGION),
        )
    _index = _pc_client.Index(config.PINECONE_INDEX)
    return _index


def seed_faqs(force: bool = False):
    """Embeds every FAQ and upserts it into Pinecone. Safe to call on every
    startup — upserts are idempotent on `id`, so re-running just overwrites
    with the same vectors unless `force` bypasses the empty-index check."""
    index = _get_index()
    if index is None:
        logger.warning("PINECONE_API_KEY not set — skipping FAQ seeding, will use keyword fallback.")
        return
    stats = index.describe_index_stats()
    if stats.get("total_vector_count", 0) > 0 and not force:
        return
    embeddings = _get_embeddings()
    texts = [f"{f['q']}\n{f['a']}" for f in FAQS]
    vectors = embeddings.embed_documents(texts)
    payload = [
        {
            "id": f["id"],
            "values": vec,
            "metadata": {"question": f["q"], "answer": f["a"], "category": f["category"]},
        }
        for f, vec in zip(FAQS, vectors)
    ]
    index.upsert(vectors=payload)
    logger.info("Seeded %d FAQs into Pinecone index '%s'.", len(payload), config.PINECONE_INDEX)


def search_faqs(query: str, top_k: int = 4) -> list[dict]:
    """Semantic search over the FAQ knowledge base. Falls back to a plain
    substring search over the local FAQS list if Pinecone/Gemini aren't
    configured, so the app degrades gracefully rather than failing."""
    index = _get_index()
    if index is not None and config.GEMINI_API_KEY:
        try:
            embeddings = _get_embeddings()
            query_vec = embeddings.embed_query(query)
            result = index.query(vector=query_vec, top_k=top_k, include_metadata=True)
            return [
                {
                    "question": m["metadata"]["question"],
                    "answer": m["metadata"]["answer"],
                    "category": m["metadata"]["category"],
                    "score": m["score"],
                }
                for m in result.get("matches", [])
            ]
        except Exception:
            logger.exception("Pinecone query failed, falling back to keyword search.")

    q = query.lower()
    return [
        {"question": f["q"], "answer": f["a"], "category": f["category"], "score": None}
        for f in FAQS
        if q in f["q"].lower() or q in f["a"].lower() or q in f["category"].lower()
    ][:top_k]


def list_all_faqs() -> list[dict]:
    return [{"question": f["q"], "answer": f["a"], "category": f["category"]} for f in FAQS]
