"""Cheap first line of defence. Obvious prompt injection is refused here
without calling the model at all (zero tokens). Subtler cases and off-topic
requests are handled by the rules in the agent's system prompt."""
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


def is_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))
