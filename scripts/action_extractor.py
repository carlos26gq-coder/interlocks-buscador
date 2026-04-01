import re

ACTION_VERBS = [
    "verify", "check", "inspect", "ensure", "adjust",
    "replace", "remove", "install", "reset", "calibrate",
    "confirm", "set", "measure", "disconnect", "reconnect"
]

def extract_action(text: str, keyword: str):
    text_clean = text.replace("\n", " ")
    sentences = re.split(r'(?<=[.!?])\s+', text_clean)

    keyword = keyword.lower()

    for sentence in sentences:
        s = sentence.lower()
        if keyword in s:
            for verb in ACTION_VERBS:
                if verb in s:
                    return sentence.strip()

    return None
