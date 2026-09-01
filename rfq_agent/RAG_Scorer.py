import os
import json
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_mistralai import MistralAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
load_dotenv()
api_key=os.getenv("MISTRAL_API_KEY")
client=ChatMistralAI(model="ministral-8b-latest",api_key=api_key)

# ---------------------------------------------------------
# Cross-platform paths (Windows local / Linux on Render)
# ---------------------------------------------------------

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

POLICY_PDF = os.environ.get(
    "POLICY_PDF",
    os.path.join(BASE_DIR, "procurement_policy.pdf")
)

CHROMA_DIR = os.environ.get(
    "CHROMA_DIR",
    os.path.join(BASE_DIR, "Chroma_policy")
)


def get_embeddings() -> MistralAIEmbeddings:
    """
    Embeddings via the Mistral API.

    Previously this used HuggingFaceEmbeddings (all-MiniLM-L6-v2),
    which pulls in torch + transformers (~1 GB) and will not fit
    in Render's free tier. The API call has no local model weights.

    Note: mistral-embed returns 1024-dim vectors vs MiniLM's 384,
    so any Chroma DB built with the old embeddings must be deleted
    and rebuilt once.
    """
    return MistralAIEmbeddings(
        model="mistral-embed",
        api_key=api_key
    )

#upload the files to chroma
def uploadToChroma() -> Chroma:
    """
    Loads the procurement policy PDF, creates chunks,
    generates embeddings and stores them in Chroma.

    Metadata is added to each chunk so that we can
    filter policy documents during retrieval.
    """

    Folder_dir = CHROMA_DIR

    embediddings = get_embeddings()

    # ---------------------------------------------------------
    # If Chroma DB already exists, load it
    # ---------------------------------------------------------

    if os.path.exists(Folder_dir):

        print("Loading existing Chroma policy database...")

        return Chroma(
            embedding_function=embediddings,
            persist_directory=Folder_dir
        )

    # ---------------------------------------------------------
    # Load procurement policy
    # ---------------------------------------------------------

    print("Creating Chroma policy database...")

    loader = PyMuPDFLoader(
        POLICY_PDF
    )

    pages = loader.load()

    # ---------------------------------------------------------
    # Chunk the policy
    # ---------------------------------------------------------

    splitters = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=80
    )

    chunks = splitters.split_documents(pages)

    # ---------------------------------------------------------
    # Add metadata
    # ---------------------------------------------------------

    for chunk in chunks:

        chunk.metadata["source"] = "procurement_policy"

        chunk.metadata["document_no"] = "PROC-POL-003"

        chunk.metadata["version"] = "3.2"

    # ---------------------------------------------------------
    # Store in Chroma
    # ---------------------------------------------------------

    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embediddings,
        persist_directory=Folder_dir
    )

    return vector_store

def policy_context(
    vector_store: Chroma,
    query: str,
    k: int = 6
) -> str:
    """
    Hybrid retrieval using:

    1. BM25 lexical search
    2. Chroma vector semantic search

    Results are combined using EnsembleRetriever.
    """

    # ---------------------------------------------------------
    # Load policy again for BM25
    # ---------------------------------------------------------

    loader = PyMuPDFLoader(
        POLICY_PDF
    )

    pages = loader.load()

    # ---------------------------------------------------------
    # Same chunking strategy used for Chroma
    # ---------------------------------------------------------

    splitters = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=80
    )

    chunks = splitters.split_documents(pages)

    # ---------------------------------------------------------
    # Add metadata to BM25 documents
    # ---------------------------------------------------------

    for chunk in chunks:

        chunk.metadata["source"] = "procurement_policy"

        chunk.metadata["document_no"] = "PROC-POL-003"

        chunk.metadata["version"] = "3.2"

    # ---------------------------------------------------------
    # 1. BM25 Retriever
    # ---------------------------------------------------------

    bm25_retriever = BM25Retriever.from_documents(
        chunks
    )

    bm25_retriever.k = k

    # ---------------------------------------------------------
    # 2. Vector / Semantic Retriever
    # ---------------------------------------------------------

    vector_retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": k,
            "filter": {
                "source": "procurement_policy"
            }
        }
    )

    # ---------------------------------------------------------
    # 3. Hybrid Retriever
    #
    # 40% BM25
    # 60% semantic/vector
    # ---------------------------------------------------------

    hybrid_retriever = EnsembleRetriever(
        retrievers=[
            bm25_retriever,
            vector_retriever
        ],
        weights=[
            0.4,
            0.6
        ]
    )

    # ---------------------------------------------------------
    # Retrieve documents
    # ---------------------------------------------------------

    result = hybrid_retriever.invoke(query)

    # ---------------------------------------------------------
    # Remove duplicate chunks
    # ---------------------------------------------------------

    unique_chunks = []

    seen = set()

    for doc in result:

        content = doc.page_content.strip()

        if content not in seen:

            seen.add(content)

            unique_chunks.append(doc)

    # ---------------------------------------------------------
    # Build context for LLM
    # ---------------------------------------------------------

    context_parts = []

    for doc in unique_chunks[:k]:

        context_parts.append(
            doc.page_content
        )

    return "\n\n".join(context_parts)

def score_vendor(
    vendor_name: str,
    context: str,
    fields: dict,
    all_landed_cost: dict
) -> dict:
    """
    Scores the vendor using the procurement policy.

    Python performs deterministic calculations.
    Mistral is used only for reasoning and summary.

    Policy weights:
        Price      = 40%
        Delivery   = 25%
        Payment    = 20%
        Quality    = 10%
        Penalty     = 5%
    """

    print(f"   {vendor_name}...")

    # =========================================================
    # 1. FIND LOWEST LANDED COST
    # =========================================================

    valid_costs = {
        k: v
        for k, v in all_landed_cost.items()
        if v is not None and v > 0
    }

    lowest_lc = (
        min(valid_costs.values())
        if valid_costs
        else 0
    )

    this_lc = (
        fields.get("landed_cost")
        or 0
    )

    # =========================================================
    # 2. PRICE SCORE
    #
    # Policy:
    #
    # Score =
    # Lowest Landed Cost / Vendor Landed Cost × 100
    #
    # =========================================================

    if this_lc > 0 and lowest_lc > 0:

        price_raw = (
            lowest_lc / this_lc
        ) * 100

        # Don't allow score above 100
        price_raw = min(
            price_raw,
            100
        )

    else:

        price_raw = 0

    price_raw = round(
        price_raw,
        2
    )

    price_weighted = round(
        price_raw * 0.40,
        2
    )

    # =========================================================
    # 3. DELIVERY SCORE
    #
    # Policy:
    #
    # 0-10  = 100
    # 11-14 = 80
    # 15-21 = 60
    # >21   = 30
    #
    # =========================================================

    delivery_days = (
        fields.get("delivery_days")
    )

    if delivery_days is None:

        delivery_raw = 0

    elif delivery_days <= 10:

        delivery_raw = 100

    elif delivery_days <= 14:

        delivery_raw = 80

    elif delivery_days <= 21:

        delivery_raw = 60

    else:

        delivery_raw = 30

    delivery_weighted = round(
        delivery_raw * 0.25,
        2
    )

    # =========================================================
    # 4. PAYMENT SCORE
    #
    # Policy:
    #
    # 60+ days = 100
    # 45 days  = 80
    # 30 days  = 60
    # Advance <=25% = 30
    # Advance >25% = 10
    # 100% advance = 0
    #
    # =========================================================

    advance_percentage = (
        fields.get("advance_percentage")
        or 0
    )

    credit_days = (
        fields.get("credit_days")
        or 0
    )

    if credit_days >= 60:

        payment_raw = 100

    elif credit_days == 45:

        payment_raw = 80

    elif credit_days == 30:

        payment_raw = 60

    elif advance_percentage >= 100:

        payment_raw = 0

    elif advance_percentage > 25:

        payment_raw = 10

    elif advance_percentage > 0:

        payment_raw = 30

    else:

        payment_raw = 0

    payment_weighted = round(
        payment_raw * 0.20,
        2
    )

    # =========================================================
    # 5. QUALITY SCORE
    #
    # Policy:
    #
    # ISO 9001 + BIS + NABL = 100
    # ISO 9001 + BIS        = 80
    # ISO 9001 only         = 60
    # Certification process = 20
    # No certifications     = 0
    #
    # =========================================================

    certifications = (
        fields.get("certifications")
        or []
    )

    certification_text = " ".join(
        str(cert).upper()
        for cert in certifications
    )

    has_iso = (
        "ISO 9001" in certification_text
    )

    has_bis = (
        "BIS" in certification_text
    )

    has_nabl = (
        "NABL" in certification_text
    )

    if (
        has_iso
        and has_bis
        and has_nabl
    ):

        quality_raw = 100

    elif (
        has_iso
        and has_bis
    ):

        quality_raw = 80

    elif has_iso:

        quality_raw = 60

    elif (
        "IN PROCESS" in certification_text
        or "IN-PROCESS" in certification_text
    ):

        quality_raw = 20

    else:

        quality_raw = 0

    quality_weighted = round(
        quality_raw * 0.10,
        2
    )

    # =========================================================
    # 6. PENALTY SCORE
    #
    # Policy:
    #
    # Penalty clause with % = 100
    # Buyer PO terms          = 50
    # No penalty clause       = 0
    #
    # =========================================================

    penalty_clause = (
        fields.get("penalty_clause")
    )

    if not penalty_clause:

        penalty_raw = 0

    else:

        penalty_text = (
            str(penalty_clause)
            .lower()
        )

        if "%" in penalty_text:

            penalty_raw = 100

        elif (
            "buyer" in penalty_text
            and "po" in penalty_text
        ):

            penalty_raw = 50

        else:

            penalty_raw = 0

    penalty_weighted = round(
        penalty_raw * 0.05,
        2
    )

    # =========================================================
    # 7. TOTAL SCORE
    # =========================================================

    total_score = round(
        price_weighted
        + delivery_weighted
        + payment_weighted
        + quality_weighted
        + penalty_weighted,
        2
    )

    # =========================================================
    # 8. RED FLAGS
    #
    # Policy mandatory disqualification:
    #
    # - Expired quote
    # - 100% advance
    # - No GSTIN
    # - No quality certifications
    # - Price entirely subject to market
    #
    # =========================================================

    red_flags = []

    # No GSTIN
    if not fields.get("gstin"):

        red_flags.append(
            "No GSTIN or GST invoice unavailable"
        )

    # 100% advance
    if advance_percentage >= 100:

        red_flags.append(
            "100% advance payment required"
        )

    # No certifications
    if not certifications:

        red_flags.append(
            "No quality certifications of any kind"
        )

    # Price subject to market
    price_basis = str(
        fields.get("price_basis") or ""
    ).lower()

    special_conditions = str(
        fields.get("special_conditions") or ""
    ).lower()

    price_text = (
        price_basis
        + " "
        + special_conditions
    )

    if (
        "market" in price_text
        and "dispatch" in price_text
    ):

        red_flags.append(
            "Price entirely subject to market at dispatch"
        )

    # =========================================================
    # 9. AMBER FLAGS
    # =========================================================

    amber_flags = []

    # Advance >25%
    if (
        advance_percentage > 25
        and advance_percentage < 100
    ):

        amber_flags.append(
            "Advance payment required above 25%"
        )

    # Quote validity <10 days
    quote_validity = (
        fields.get("quote_validity_days")
    )

    if (
        quote_validity is not None
        and quote_validity < 10
    ):

        amber_flags.append(
            "Quote validity less than 10 days remaining"
        )

    # No penalty clause
    if not penalty_clause:

        amber_flags.append(
            "No penalty clause mentioned"
        )

    # Warranty <6 months
    warranty = (
        fields.get("warranty_months")
    )

    if (
        warranty is not None
        and warranty < 6
    ):

        amber_flags.append(
            "Warranty less than 6 months"
        )

    # Price index revision >3%
    if (
        "index revision" in price_text
        and "3%" in price_text
    ):

        amber_flags.append(
            "Price subject to index revision > 3%"
        )

    # =========================================================
    # 10. DETERMINE RANK CATEGORY
    # =========================================================

    if red_flags:

        rank_category = "Avoid"

        status = "DISQUALIFIED"

    elif total_score >= 80:

        rank_category = "Recommended"

        status = "ELIGIBLE"

    elif total_score >= 65:

        rank_category = "Consider"

        status = "ELIGIBLE"

    elif total_score >= 50:

        rank_category = "Caution"

        status = "ELIGIBLE"

    else:

        rank_category = "Avoid"

        status = "ELIGIBLE"

    # =========================================================
    # 11. ASK MISTRAL ONLY FOR REASONING
    # =========================================================

    prompt = f"""
You are a procurement analyst.

The vendor's numerical score has already been calculated
using the company's procurement policy.

DO NOT change or recalculate any score.

Use the policy context and vendor data to provide concise
reasoning for each criterion.

PROCUREMENT POLICY CONTEXT:
{context}

VENDOR:
{vendor_name}

VENDOR DATA:
{json.dumps(fields, indent=2)}

CALCULATED SCORES:

Price:
Raw Score = {price_raw}
Weighted Score = {price_weighted}

Delivery:
Raw Score = {delivery_raw}
Weighted Score = {delivery_weighted}

Payment:
Raw Score = {payment_raw}
Weighted Score = {payment_weighted}

Quality:
Raw Score = {quality_raw}
Weighted Score = {quality_weighted}

Penalty:
Raw Score = {penalty_raw}
Weighted Score = {penalty_weighted}

TOTAL SCORE:
{total_score}

RED FLAGS:
{red_flags}

AMBER FLAGS:
{amber_flags}

Return ONLY valid JSON:

{{
    "price_reasoning": "one concise sentence",
    "delivery_reasoning": "one concise sentence",
    "payment_reasoning": "one concise sentence",
    "quality_reasoning": "one concise sentence",
    "penalty_reasoning": "one concise sentence",
    "one_line_summary": "one concise overall assessment"
}}
"""

    response = client.invoke(prompt)

    raw = response.content.strip()

    # =========================================================
    # 12. PARSE LLM REASONING
    # =========================================================

    try:

        clean = raw

        if "```" in clean:

            clean = clean.split("```")[1]

            if clean.strip().startswith("json"):

                clean = clean.strip()[4:]

        reasoning = json.loads(
            clean.strip()
        )

    except Exception:

        reasoning = {
            "price_reasoning":
                "Price score calculated from landed cost.",
            "delivery_reasoning":
                "Delivery score calculated from policy lead-time bands.",
            "payment_reasoning":
                "Payment score calculated from credit and advance terms.",
            "quality_reasoning":
                "Quality score calculated from available certifications.",
            "penalty_reasoning":
                "Penalty score calculated from the vendor penalty clause.",
            "one_line_summary":
                f"Vendor evaluated with a total score of {total_score}."
        }

    # =========================================================
    # 13. FINAL RESULT
    # =========================================================

    result = {
        "vendor_name": vendor_name,

        "status": status,

        "criteria_scores": {

            "price": {
                "raw_score": price_raw,
                "weighted_score": price_weighted,
                "reasoning": reasoning.get(
                    "price_reasoning",
                    ""
                )
            },

            "delivery": {
                "raw_score": delivery_raw,
                "weighted_score": delivery_weighted,
                "reasoning": reasoning.get(
                    "delivery_reasoning",
                    ""
                )
            },

            "payment": {
                "raw_score": payment_raw,
                "weighted_score": payment_weighted,
                "reasoning": reasoning.get(
                    "payment_reasoning",
                    ""
                )
            },

            "quality": {
                "raw_score": quality_raw,
                "weighted_score": quality_weighted,
                "reasoning": reasoning.get(
                    "quality_reasoning",
                    ""
                )
            },

            "penalty": {
                "raw_score": penalty_raw,
                "weighted_score": penalty_weighted,
                "reasoning": reasoning.get(
                    "penalty_reasoning",
                    ""
                )
            }
        },

        "landed_cost": this_lc,

        "lowest_landed_cost": lowest_lc,

        "total_score": total_score,

        "rank_category": rank_category,

        "red_flags": red_flags,

        "amber_flags": amber_flags,

        "one_line_summary": reasoning.get(
            "one_line_summary",
            f"Vendor evaluated with a total score of {total_score}."
        )
    }

    return result
def rank_vendors(all_scores: dict) -> list:
    """
    Sorts vendors by total_score descending.
    Returns ranked list with position numbers.
    """
    ranked = sorted(
        all_scores.items(),
        key=lambda x: x[1].get("total_score", 0),
        reverse=True
    )
    result = []
    for position, (vendor_name, score_data) in enumerate(ranked, 1):
        score_data["rank"] = position
        result.append(score_data)
    return result

def run_rag_agent(Extracted_quotes : dict) ->dict:
    """
    load the document and get the vector database
    """
    chromaVectorStore = uploadToChroma()
    ResultContext = policy_context(vector_store = chromaVectorStore, query=(
            "vendor evaluation criteria scoring weights price delivery "
            "payment terms quality certifications penalty clause landed cost "
            "disqualification flags red amber"
        ), k =8)
    all_landed = {
        v: data.get("landed_cost", 0)
        for v, data in Extracted_quotes.items()
        if data.get("landed_cost")
    }
    print("all landed cost has been completed")
    AllScores = {}
    for vendor_name, fields in Extracted_quotes.items():
        ListOfScore = score_vendor(vendor_name = vendor_name , context = ResultContext,fields = fields ,all_landed_cost = all_landed)
        AllScores[vendor_name] = ListOfScore
    return AllScores    

def DisplayScore(score : dict):
    "give the score and we will  be displaying the score"
    Result_score = rank_vendors(score)
    return Result_score


def run_scoring_pipeline():
    """
    Run the complete scoring pipeline.
    Only call this after extracted_quotes.json has been created.
    """
    if not os.path.exists("extracted_quotes.json"):
        print("❌ extracted_quotes.json not found — run chunk2 first")
        return None

    with open("extracted_quotes.json") as f:
        extracted_quotes = json.load(f)

    # run scoring
    all_scores = run_rag_agent(extracted_quotes)
    ranked = DisplayScore(all_scores)

    # save for Chunk 4
    with open("vendor_scores.json", "w") as f:
        json.dump(all_scores, f, indent=2, default=str)

    return all_scores


# IMPORTANT: This code only runs if RAG_Scorer.py is executed directly, not when imported
if __name__ == "__main__":
    all_scores = run_scoring_pipeline()
    if all_scores:
        print("✓ Scoring complete. Results saved to vendor_scores.json")




    





    


    
