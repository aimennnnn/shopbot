"""Deterministic safety guard. It refuses, without calling the model at all
(zero tokens): prompt injection, fishing for other users' data, price
tampering, and clearly off-topic requests. Subtler cases still reach the
agent, whose system prompt carries the same rules."""
import re

INJECTION_PATTERNS = [
    r"ignore (all |any |the |your )*(previous|prior|above|earlier|system)[\w ]{0,20}(instructions?|prompts?|rules?)",
    r"(disregard|forget|override|bypass) (all |any |the |your )*(previous |prior |above |system )?(instructions?|prompts?|rules?|guidelines?)",
    r"(reveal|show|print|repeat|output|tell me|what is|what are|give me) (me )?(your |the )(system |hidden |initial |original |secret )?(prompt|instructions?)",
    r"system prompt",
    r"\b(developer|dan|god|admin|debug|jailbreak) mode\b",
    r"\bjailbreak\b",
    r"you are (now|no longer) ",
    r"(act|behave|respond) as (if you are |an? )?(unrestricted|uncensored|different)",
    r"pretend (to be|you are|you're) (?!interested)",
    r"new (system )?instructions?:",
    r"</?(system|instructions?)>",
    r"\[(system|inst)\]",
    r"(other|another|all|every) (users?|customers?|people)('s|s')? (orders?|data|details|address|info|chats?|messages?|history|memory)",
    r"(orders?|data|details|address|chats?|messages?|history|memory) (of|for|from|belonging to) (the |a |any |an |some )?(user|customer|another|other)",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.IGNORECASE)

REFUSAL = (
    "Sorry, I can't help with that. I'm this shop's assistant, so I can only help "
    "you browse products and manage your own orders."
)

# Clearly off-topic requests. Kept narrow on purpose: anything not matched here
# still goes to the agent, whose prompt also refuses off-topic requests.
OFF_TOPIC_PATTERNS = [
    r"\b(python|javascript|java|c\+\+|html|css|sql|php)\b.{0,30}\b(code|function|script|program|query|class)\b",
    r"\bwrite (me |us )?(a |an |some )?(code|function|program|script|essay|poem|story|song|speech|cover letter|resume)\b",
    r"\b(solve|calculate|integrate|differentiate)\b.{0,40}\b(equation|integral|derivative|math|maths|physics|chemistry)\b",
    r"\b(my|the|this) (homework|assignment|thesis|exam)\b",
    r"\b(capital|president|prime minister|population|currency) of\b",
    r"\b(weather|temperature|forecast) (in|at|for|today|tomorrow)\b",
    r"\bwho (won|is winning|will win)\b",
    r"\btell me a joke\b",
    r"\btranslate\b.{0,60}\b(to|into) (urdu|english|french|arabic|hindi|spanish|german|chinese)\b",
    r"\b(stock market|bitcoin|crypto|election|football|cricket) (price|news|score|result|prediction)s?\b",
]
_OFF_TOPIC = re.compile("|".join(f"(?:{p})" for p in OFF_TOPIC_PATTERNS), re.IGNORECASE)

OFF_TOPIC_REPLY = (
    "I can only help with this shop: finding products, delivery and returns, and your orders. "
    "What are you shopping for today?"
)

# Attempts to change prices or invent discounts. No tool can do this anyway;
# answering here just saves the model call.
TAMPER_PATTERNS = [
    r"\b(change|set|update|reduce|lower|drop|make|edit|override)\b.{0,25}\bprice\b.{0,20}\b(to|as|=|at)\b",
    r"\b(100|9\d) ?(%|percent) (off|discount)\b",
    r"\b(give|apply|create|generate|make) (me |us )?(a |an |the )?(\d+ ?(%|percent) )?(discount|coupon|promo) code\b",
    r"\b(for|at) (rs\.? ?[01]\b|zero rupees)",
    r"^(?!.*\b(deliver\w*|shipp?\w*|wrap\w*|charge\w*|note)\b).*\b(for free|free of cost)\b",
    r"\bmark (it|this|the order) as paid\b",
]
_TAMPER = re.compile("|".join(f"(?:{p})" for p in TAMPER_PATTERNS), re.IGNORECASE)

TAMPER_REPLY = (
    "I can't change prices or create discounts. Prices are set by the seller. "
    "I'm happy to help you find something within your budget."
)


def is_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


def check(text: str) -> str | None:
    """Returns the canned refusal for a message the guard blocks, or None to let it through."""
    if _INJECTION.search(text):
        return REFUSAL
    if _TAMPER.search(text):
        return TAMPER_REPLY
    if _OFF_TOPIC.search(text):
        return OFF_TOPIC_REPLY
    return None
