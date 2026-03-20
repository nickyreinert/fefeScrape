#!./.venv/bin/python3

INSTRUCTION_TEXT = "Write a short German blog comment in a dry, ironic, satirical tone."
SYSTEM_TEXT = "You write short German blog comments in German with dry irony and satire."


def normalize_whitespace(value):
    if not value:
        return ""

    return " ".join(str(value).split())


def build_response_prompt(topic, context="", url=""):
    topic = normalize_whitespace(topic)
    context = normalize_whitespace(context)
    url = normalize_whitespace(url)

    lines = [
        "### Instruction",
        INSTRUCTION_TEXT,
        "",
        "### Input",
        "Topic: {}".format(topic),
    ]

    if context:
        lines.append("Context: {}".format(context))

    if url:
        lines.append("URL: {}".format(url))

    lines.extend([
        "",
        "### Response",
    ])
    return "\n".join(lines)


def build_messages(example, include_target_comment=True):
    topic = example.get("topic_final") or example.get("topic", "")
    context = example.get("context_final") or example.get("context", "")
    url = example.get("url", "")

    messages = [
        {"role": "system", "content": SYSTEM_TEXT},
        {
            "role": "user",
            "content": build_response_prompt(topic, context, url),
        },
    ]

    if include_target_comment:
        messages.append(
            {
                "role": "assistant",
                "content": normalize_whitespace(example["target_comment"]),
            }
        )

    return messages